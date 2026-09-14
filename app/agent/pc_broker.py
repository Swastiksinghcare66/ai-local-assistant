from __future__ import annotations

import ctypes
import json
import os
import random
import re
import shutil
import subprocess
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

import psutil

from .types import ActionResult

AUTO = "auto"
CONFIRM = "confirm"
BLOCK = "block"


@dataclass
class PreparedAction:
    intent: str
    args: dict
    policy: str
    summary: str


class PCCapabilityBroker:
    CONFIRM_TTL = 90.0

    def __init__(self):
        self.pending: tuple[PreparedAction, str, float] | None = None

    # ---------------- paths ----------------

    def _desktop(self) -> Path:
        one = os.environ.get("OneDrive")
        if one:
            p = Path(one) / "Desktop"
            if p.exists():
                return p
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"

    def _downloads(self) -> Path:
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads"

    def _documents(self) -> Path:
        one = os.environ.get("OneDrive")
        if one:
            p = Path(one) / "Documents"
            if p.exists():
                return p
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"

    def _resolve_path(self, value: str | None) -> Path:
        raw = str(value or "").strip().strip('"').strip("'")
        if not raw:
            return self._desktop()

        lower = raw.lower().replace("/", "\\")
        roots = {
            "desktop": self._desktop(),
            "downloads": self._downloads(),
            "documents": self._documents(),
            "home": Path.home(),
            "~": Path.home(),
            "project": Path.cwd(),
        }

        for key, root in roots.items():
            if lower == key:
                return root
            prefix = key + "\\"
            if lower.startswith(prefix):
                rest = raw[len(prefix):].replace("\\", os.sep).replace("/", os.sep)
                return root / rest

        return Path(os.path.expandvars(os.path.expanduser(raw)))

    # ---------------- policy ----------------

    def prepare(self, intent: str, args: dict | None) -> PreparedAction:
        intent = str(intent or "").strip()
        args = dict(args or {})

        aliases = {
            "list_files_on_desktop": "list_files",
            "list_desktop_files": "list_files",
            "show_system_status": "get_system_status",
            "system_status": "get_system_status",
            "delete_path": "recycle_path",
            "delete_file": "recycle_path",
            "delete_folder": "recycle_path",
            "remove_path": "recycle_path",
            "write_clipboard": "set_clipboard",
        }
        intent = aliases.get(intent, intent)

        if intent == "list_files" and not any(k in args for k in ("path", "directory", "folder")):
            args["path"] = "desktop"

        auto = {
            "open_application", "open_website", "open_url", "browser_search",
            "set_volume", "media_control", "get_system_status",
            "get_running_processes", "get_network_status", "create_folder",
            "list_files", "search_files", "open_path", "copy_path",
            "create_text_file", "set_clipboard", "get_current_time",
            "get_current_date",
        }
        confirm = {
            "move_path", "rename_path", "recycle_path", "close_application",
            "overwrite_text_file", "install_package", "uninstall_package",
            "lock_pc", "restart_pc", "shutdown_pc",
        }
        blocked = {
            "shell", "raw_shell", "powershell", "cmd", "registry_edit",
            "disable_defender", "disable_firewall", "uac_bypass",
            "dump_credentials", "read_passwords", "dump_cookies",
            "format_disk", "wipe_disk", "permanent_delete",
        }

        if intent in blocked:
            policy = BLOCK
        elif intent in confirm:
            policy = CONFIRM
        elif intent in auto:
            policy = AUTO
        else:
            policy = BLOCK

        return PreparedAction(
            intent=intent,
            args=args,
            policy=policy,
            summary=self._summary(intent, args),
        )

    def _summary(self, intent: str, args: dict) -> str:
        if intent == "recycle_path":
            return f"move {args.get('path') or args.get('target') or 'the selected item'} to the Recycle Bin"
        if intent == "move_path":
            return f"move {args.get('source')} to {args.get('destination')}"
        if intent == "rename_path":
            return f"rename {args.get('path') or args.get('source')} to {args.get('new_name') or args.get('name')}"
        if intent == "close_application":
            return f"close {args.get('application') or args.get('app') or args.get('target')}"
        if intent == "install_package":
            return f"install {args.get('package') or args.get('name')}"
        if intent == "uninstall_package":
            return f"uninstall {args.get('package') or args.get('name')}"
        if intent == "restart_pc":
            return "restart this PC"
        if intent == "shutdown_pc":
            return "shut down this PC"
        if intent == "lock_pc":
            return "lock this PC"
        if intent == "overwrite_text_file":
            return f"overwrite {args.get('path')}"
        return intent.replace("_", " ")

    # ---------------- confirmation ----------------

    def stage(self, action: PreparedAction) -> str:
        code = f"{random.randint(0, 9999):04d}"
        self.pending = (action, code, time.time() + self.CONFIRM_TTL)
        return code

    def cancel_pending(self):
        self.pending = None

    def has_pending(self) -> bool:
        if self.pending is None:
            return False
        if time.time() > self.pending[2]:
            self.pending = None
            return False
        return True

    def confirm_from_text(self, text: str) -> ActionResult | None:
        if not self.has_pending():
            return None

        m = re.fullmatch(r"\s*confirm\s+([0-9](?:\s*[0-9]){3})\s*", str(text or ""), flags=re.I)
        if not m:
            if re.fullmatch(r"\s*(cancel|no|stop|never mind|nevermind)\s*", str(text or ""), flags=re.I):
                self.pending = None
                return ActionResult(True, "cancel_pending", "Cancelled.", verified=True)
            return ActionResult(False, "confirm_pending", error="The confirmation code did not match. Say confirm followed by the four digits.", verified=True)

        entered = re.sub(r"\s+", "", m.group(1))
        action, code, _ = self.pending
        if entered != code:
            return ActionResult(False, "confirm_pending", error="That confirmation code is incorrect.", verified=True)

        self.pending = None
        return self.execute(action)

    # ---------------- execution ----------------

    def execute(self, action: PreparedAction) -> ActionResult:
        if action.policy == BLOCK:
            return ActionResult(
                False,
                action.intent,
                error="That capability is blocked or is not safely implemented.",
                verified=True,
            )

        handler = getattr(self, f"_do_{action.intent}", None)
        if handler is None:
            return ActionResult(
                False,
                action.intent,
                error=f"I understand the action, but {action.intent} is not implemented yet.",
                verified=True,
            )
        try:
            return handler(action.args)
        except Exception as exc:
            return ActionResult(False, action.intent, error=f"{type(exc).__name__}: {exc}", verified=True)

    # ---------------- applications / browser ----------------

    def _known_exe(self, name: str) -> str | None:
        key = name.lower().strip()
        aliases = {
            "notepad": ["notepad.exe"],
            "calculator": ["calc.exe"],
            "file explorer": ["explorer.exe"],
            "explorer": ["explorer.exe"],
            "chrome": [
                "chrome.exe",
                r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
                r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
                r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
            ],
            "google chrome": [
                "chrome.exe",
                r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
                r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
                r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
            ],
            "edge": [
                "msedge.exe",
                r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
                r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
            ],
            "microsoft edge": [
                "msedge.exe",
                r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
                r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
            ],
            "vscode": [
                "code.exe",
                r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
            ],
            "visual studio code": [
                "code.exe",
                r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
            ],
        }

        for candidate in aliases.get(key, []):
            expanded = os.path.expandvars(candidate)
            if Path(expanded).exists():
                return expanded
            found = shutil.which(expanded)
            if found:
                return found
        return None

    def _start_app_id(self, name: str) -> tuple[str, str] | None:
        fixed = (
            "Get-StartApps | "
            "Select-Object Name,AppID | "
            "ConvertTo-Json -Compress"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", fixed],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return None

        data = json.loads(completed.stdout)
        if isinstance(data, dict):
            data = [data]

        target = name.lower().strip()
        exact = [x for x in data if str(x.get("Name", "")).lower() == target]
        matches = exact or [x for x in data if target in str(x.get("Name", "")).lower()]
        if not matches:
            return None

        row = matches[0]
        return str(row["Name"]), str(row["AppID"])

    def _do_open_application(self, args: dict) -> ActionResult:
        name = str(args.get("application") or args.get("app") or args.get("target") or "").strip()
        if not name:
            return ActionResult(False, "open_application", error="No application was specified.", verified=True)

        exe = self._known_exe(name)
        if exe:
            subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ActionResult(True, "open_application", f"{name} is open.", verified=True)

        start = self._start_app_id(name)
        if start:
            display, appid = start
            subprocess.Popen(
                ["explorer.exe", f"shell:AppsFolder\\{appid}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return ActionResult(True, "open_application", f"{display} is open.", verified=True)

        web_fallback = {
            "whatsapp": "https://web.whatsapp.com/",
            "chatgpt": "https://chatgpt.com/",
        }
        if name.lower() in web_fallback:
            webbrowser.open(web_fallback[name.lower()], new=2)
            return ActionResult(True, "open_application", f"I couldn't find the installed {name} app, so I opened its web version.", verified=True)

        return ActionResult(False, "open_application", error=f"I couldn't find {name} on this PC.", verified=True)

    def _website_url(self, value: str) -> str | None:
        text = value.strip()
        aliases = {
            "youtube": "https://www.youtube.com/",
            "google": "https://www.google.com/",
            "github": "https://github.com/",
            "gmail": "https://mail.google.com/",
            "whatsapp": "https://web.whatsapp.com/",
            "chatgpt": "https://chatgpt.com/",
        }
        if text.lower() in aliases:
            return aliases[text.lower()]
        if text.startswith(("http://", "https://")):
            return text
        if "." in text and " " not in text:
            return "https://" + text
        return None

    def _browser_exe(self, browser: str | None) -> str | None:
        if not browser:
            return None
        return self._known_exe(browser)

    def _do_open_website(self, args: dict) -> ActionResult:
        target = str(args.get("website") or args.get("url") or args.get("target") or "").strip()
        url = self._website_url(target)
        if not url:
            return ActionResult(False, "open_website", error=f"I don't have a reliable URL for {target}.", verified=True)
        browser = args.get("browser")
        exe = self._browser_exe(str(browser)) if browser else None
        if browser and exe:
            subprocess.Popen([exe, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ActionResult(True, "open_website", f"I opened {target} in {browser}.", verified=True)
        webbrowser.open(url, new=2)
        return ActionResult(True, "open_website", f"I opened {target}.", verified=True)

    def _do_open_url(self, args: dict) -> ActionResult:
        return self._do_open_website(args)

    def _do_browser_search(self, args: dict) -> ActionResult:
        query = str(args.get("query") or args.get("target") or "").strip()
        if not query:
            return ActionResult(False, "browser_search", error="No search query was specified.", verified=True)
        url = "https://www.google.com/search?q=" + quote_plus(query)
        browser = str(args.get("browser") or "").strip()
        exe = self._browser_exe(browser) if browser else None
        if browser and exe:
            subprocess.Popen([exe, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ActionResult(True, "browser_search", f"I searched for {query} in {browser}.", verified=True)
        webbrowser.open(url, new=2)
        return ActionResult(True, "browser_search", f"I searched for {query}.", verified=True)

    # ---------------- audio / media ----------------

    def _do_set_volume(self, args: dict) -> ActionResult:
        raw = args.get("percent", args.get("volume", args.get("level")))
        if raw is None:
            return ActionResult(False, "set_volume", error="No volume level was specified.", verified=True)

        if isinstance(raw, str):
            m = re.search(r"-?\d+(?:\.\d+)?", raw)
            if not m:
                return ActionResult(False, "set_volume", error="I couldn't understand the volume level.", verified=True)
            percent = float(m.group(0))
        else:
            percent = float(raw)

        percent = max(0.0, min(100.0, percent))

        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities

        speakers = AudioUtilities.GetSpeakers()
        endpoint = speakers.EndpointVolume
        endpoint.SetMasterVolumeLevelScalar(percent / 100.0, None)
        actual = round(endpoint.GetMasterVolumeLevelScalar() * 100)
        return ActionResult(True, "set_volume", f"Volume is set to {actual} percent.", verified=True, data={"percent": actual})

    def _do_media_control(self, args: dict) -> ActionResult:
        action = str(args.get("action") or args.get("command") or args.get("target") or "").lower().strip()
        keys = {
            "play": "playpause",
            "pause": "playpause",
            "play_pause": "playpause",
            "play pause": "playpause",
            "next": "nexttrack",
            "next track": "nexttrack",
            "previous": "prevtrack",
            "previous track": "prevtrack",
            "mute": "volumemute",
            "volume up": "volumeup",
            "volume down": "volumedown",
        }
        key = keys.get(action)
        if not key:
            return ActionResult(False, "media_control", error=f"Unsupported media action: {action}", verified=True)
        import pyautogui
        pyautogui.press(key)
        return ActionResult(True, "media_control", f"Media command {action} sent.", verified=False)

    # ---------------- system ----------------

    def _do_get_system_status(self, args: dict) -> ActionResult:
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage(str(Path.home().anchor or "C:\\"))
        battery = psutil.sensors_battery()
        cpu = psutil.cpu_percent(interval=0.25)
        parts = [
            f"CPU usage is {cpu:.0f} percent",
            f"memory usage is {vm.percent:.0f} percent",
            f"disk usage is {disk.percent:.0f} percent",
        ]
        data = {
            "cpu_percent": cpu,
            "memory_percent": vm.percent,
            "disk_percent": disk.percent,
        }
        if battery is not None:
            parts.append(f"battery is {battery.percent:.0f} percent")
            data["battery_percent"] = battery.percent
        return ActionResult(True, "get_system_status", ", ".join(parts) + ".", verified=True, data=data)

    def _do_get_running_processes(self, args: dict) -> ActionResult:
        names = []
        for proc in psutil.process_iter(["name"]):
            try:
                name = proc.info.get("name")
                if name:
                    names.append(name)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        unique = sorted(set(names), key=str.lower)
        preview = ", ".join(unique[:20])
        more = max(0, len(unique) - 20)
        msg = f"Running applications and processes include {preview}"
        if more:
            msg += f", plus {more} more"
        return ActionResult(True, "get_running_processes", msg + ".", verified=True, data={"processes": unique})

    def _do_get_network_status(self, args: dict) -> ActionResult:
        stats = psutil.net_if_stats()
        up = [name for name, st in stats.items() if st.isup]
        return ActionResult(True, "get_network_status", f"{len(up)} network interfaces are active: {', '.join(up[:8])}.", verified=True, data={"active_interfaces": up})

    def _do_get_current_time(self, args: dict) -> ActionResult:
        return ActionResult(True, "get_current_time", time.strftime("The current time is %I:%M %p."), verified=True)

    def _do_get_current_date(self, args: dict) -> ActionResult:
        return ActionResult(True, "get_current_date", time.strftime("Today is %A, %d %B %Y."), verified=True)

    # ---------------- files ----------------

    def _do_create_folder(self, args: dict) -> ActionResult:
        if args.get("path"):
            path = self._resolve_path(args["path"])
        else:
            name = str(args.get("name") or args.get("folder") or args.get("folder_name") or "").strip()
            base = self._resolve_path(args.get("location") or "desktop")
            path = base / name
        if not path.name:
            return ActionResult(False, "create_folder", error="No folder name was specified.", verified=True)
        existed = path.exists()
        path.mkdir(parents=True, exist_ok=True)
        return ActionResult(True, "create_folder", f"{'The folder already exists at' if existed else 'Created folder'} {path}.", verified=path.is_dir(), data={"path": str(path)})

    def _do_list_files(self, args: dict) -> ActionResult:
        path = self._resolve_path(args.get("path") or args.get("directory") or args.get("folder") or args.get("location") or "desktop")
        if not path.exists() or not path.is_dir():
            return ActionResult(False, "list_files", error=f"{path} is not an accessible folder.", verified=True)
        items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        names = [p.name + ("/" if p.is_dir() else "") for p in items]
        if not names:
            return ActionResult(True, "list_files", f"{path} is empty.", verified=True, data={"path": str(path), "items": []})
        preview = ", ".join(names[:20])
        more = max(0, len(names) - 20)
        msg = f"In {path}, I found {preview}"
        if more:
            msg += f", plus {more} more items"
        return ActionResult(True, "list_files", msg + ".", verified=True, data={"path": str(path), "items": names})

    def _do_search_files(self, args: dict) -> ActionResult:
        query = str(args.get("query") or args.get("pattern") or args.get("name") or "").lower().strip()
        root = self._resolve_path(args.get("path") or args.get("directory") or "home")
        if not query:
            return ActionResult(False, "search_files", error="No file search query was specified.", verified=True)
        matches = []
        for p in root.rglob("*"):
            if query in p.name.lower():
                matches.append(str(p))
                if len(matches) >= 50:
                    break
        if not matches:
            return ActionResult(True, "search_files", f"I found no files matching {query} under {root}.", verified=True, data={"matches": []})
        return ActionResult(True, "search_files", f"I found {len(matches)} matches. The first ones are " + ", ".join(matches[:8]) + ".", verified=True, data={"matches": matches})

    def _do_open_path(self, args: dict) -> ActionResult:
        path = self._resolve_path(args.get("path") or args.get("target"))
        if not path.exists():
            return ActionResult(False, "open_path", error=f"{path} does not exist.", verified=True)
        os.startfile(str(path))
        return ActionResult(True, "open_path", f"I opened {path}.", verified=True)

    def _do_copy_path(self, args: dict) -> ActionResult:
        src = self._resolve_path(args.get("source") or args.get("path"))
        dst = self._resolve_path(args.get("destination") or args.get("dest"))
        if not src.exists():
            return ActionResult(False, "copy_path", error=f"{src} does not exist.", verified=True)
        if src.is_dir():
            target = dst / src.name if dst.exists() and dst.is_dir() else dst
            if target.exists():
                return ActionResult(False, "copy_path", error=f"{target} already exists. I will not overwrite it automatically.", verified=True)
            shutil.copytree(src, target, dirs_exist_ok=False)
        else:
            target = dst / src.name if dst.exists() and dst.is_dir() else dst
            if target.exists():
                return ActionResult(False, "copy_path", error=f"{target} already exists. I will not overwrite it automatically.", verified=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        return ActionResult(True, "copy_path", f"Copied {src} to {target}.", verified=target.exists(), data={"target": str(target)})

    def _do_move_path(self, args: dict) -> ActionResult:
        src = self._resolve_path(args.get("source") or args.get("path"))
        dst = self._resolve_path(args.get("destination") or args.get("dest"))
        if not src.exists():
            return ActionResult(False, "move_path", error=f"{src} does not exist.", verified=True)
        result = Path(shutil.move(str(src), str(dst)))
        return ActionResult(True, "move_path", f"Moved {src} to {result}.", verified=result.exists())

    def _do_rename_path(self, args: dict) -> ActionResult:
        src = self._resolve_path(args.get("path") or args.get("source"))
        new_name = str(args.get("new_name") or args.get("name") or "").strip()
        if not src.exists():
            return ActionResult(False, "rename_path", error=f"{src} does not exist.", verified=True)
        if not new_name or any(ch in new_name for ch in '<>:"/\\|?*'):
            return ActionResult(False, "rename_path", error="The new name is invalid.", verified=True)
        dst = src.with_name(new_name)
        src.rename(dst)
        return ActionResult(True, "rename_path", f"Renamed it to {dst.name}.", verified=dst.exists())

    def _do_recycle_path(self, args: dict) -> ActionResult:
        from send2trash import send2trash
        path = self._resolve_path(args.get("path") or args.get("target"))
        if not path.exists():
            return ActionResult(False, "recycle_path", error=f"{path} does not exist.", verified=True)
        send2trash(str(path))
        return ActionResult(True, "recycle_path", f"Moved {path.name} to the Recycle Bin.", verified=not path.exists())

    def _do_create_text_file(self, args: dict) -> ActionResult:
        raw_path = args.get("path")
        if raw_path:
            path = self._resolve_path(raw_path)
        else:
            name = str(args.get("name") or args.get("filename") or "").strip()
            base = self._resolve_path(args.get("location") or "desktop")
            path = base / name
        content = str(args.get("content") or args.get("text") or "")
        if path.exists():
            return ActionResult(False, "create_text_file", error=f"{path} already exists. Overwriting requires confirmation.", verified=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return ActionResult(True, "create_text_file", f"Created {path}.", verified=path.exists())

    def _do_overwrite_text_file(self, args: dict) -> ActionResult:
        path = self._resolve_path(args.get("path"))
        content = str(args.get("content") or args.get("text") or "")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return ActionResult(True, "overwrite_text_file", f"Updated {path}.", verified=path.exists())

    def _do_set_clipboard(self, args: dict) -> ActionResult:
        import pyperclip
        text = str(args.get("text") or args.get("content") or "")
        pyperclip.copy(text)
        return ActionResult(True, "set_clipboard", "Copied the requested text to the clipboard.", verified=True)

    # ---------------- consequential system actions ----------------

    def _do_close_application(self, args: dict) -> ActionResult:
        target = str(args.get("application") or args.get("app") or args.get("target") or "").lower().strip()
        if not target:
            return ActionResult(False, "close_application", error="No application was specified.", verified=True)
        killed = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = str(proc.info.get("name") or "")
                if target in name.lower() or name.lower().startswith(target):
                    proc.terminate()
                    killed.append(name)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if not killed:
            return ActionResult(False, "close_application", error=f"I couldn't find a running process matching {target}.", verified=True)
        return ActionResult(True, "close_application", f"Closed {target}.", verified=True, data={"processes": killed})

    def _do_install_package(self, args: dict) -> ActionResult:
        package = str(args.get("package") or args.get("name") or "").strip()
        if not package:
            return ActionResult(False, "install_package", error="No package was specified.", verified=True)
        completed = subprocess.run(
            ["winget", "install", "--id", package, "-e", "--accept-package-agreements", "--accept-source-agreements"],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if completed.returncode != 0:
            return ActionResult(False, "install_package", error=(completed.stderr or completed.stdout or "winget failed")[-600:], verified=True)
        return ActionResult(True, "install_package", f"Installed {package}.", verified=True)

    def _do_uninstall_package(self, args: dict) -> ActionResult:
        package = str(args.get("package") or args.get("name") or "").strip()
        if not package:
            return ActionResult(False, "uninstall_package", error="No package was specified.", verified=True)
        completed = subprocess.run(
            ["winget", "uninstall", "--id", package, "-e"],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if completed.returncode != 0:
            return ActionResult(False, "uninstall_package", error=(completed.stderr or completed.stdout or "winget failed")[-600:], verified=True)
        return ActionResult(True, "uninstall_package", f"Uninstalled {package}.", verified=True)

    def _do_lock_pc(self, args: dict) -> ActionResult:
        ok = ctypes.windll.user32.LockWorkStation()
        return ActionResult(bool(ok), "lock_pc", "PC locked." if ok else None, error=None if ok else "Windows rejected the lock request.", verified=bool(ok))

    def _do_restart_pc(self, args: dict) -> ActionResult:
        subprocess.Popen(["shutdown.exe", "/r", "/t", "5"])
        return ActionResult(True, "restart_pc", "Restart scheduled in five seconds.", verified=True)

    def _do_shutdown_pc(self, args: dict) -> ActionResult:
        subprocess.Popen(["shutdown.exe", "/s", "/t", "5"])
        return ActionResult(True, "shutdown_pc", "Shutdown scheduled in five seconds.", verified=True)



# === SARA YOUTUBE PLAYBACK CAPABILITY V1 ===

_SARA_YOUTUBE_ORIGINAL_PREPARE = (
    PCCapabilityBroker.prepare
)

_SARA_YOUTUBE_ORIGINAL_EXECUTE = (
    PCCapabilityBroker.execute
)


def _sara_prepare_with_youtube(
    self,
    intent,
    args,
):

    if (
        str(intent)
        ==
        "play_youtube_video"
    ):

        args = dict(
            args
            or {}
        )

        query = str(
            args.get("query")
            or
            args.get("video")
            or
            args.get("title")
            or
            args.get("url")
            or ""
        ).strip()

        browser = (
            args.get("browser")
        )

        try:
            index = int(
                args.get(
                    "index",
                    1,
                )
            )
        except Exception:
            index = 1

        return PreparedAction(
            intent=
                "play_youtube_video",
            args={
                "query":
                    query,
                "browser":
                    browser,
                "index":
                    index,
            },
            policy=AUTO,
            summary=(
                f"play {query} on YouTube"
            ),
        )

    return (
        _SARA_YOUTUBE_ORIGINAL_PREPARE(
            self,
            intent,
            args,
        )
    )


def _sara_execute_with_youtube(
    self,
    prepared,
):

    if (
        prepared.intent
        ==
        "play_youtube_video"
    ):

        from .youtube_tool import (
            play_youtube_video,
        )

        return play_youtube_video(
            query=
                prepared.args.get(
                    "query",
                    "",
                ),
            browser=
                prepared.args.get(
                    "browser"
                ),
            index=
                prepared.args.get(
                    "index",
                    1,
                ),
        )

    return (
        _SARA_YOUTUBE_ORIGINAL_EXECUTE(
            self,
            prepared,
        )
    )


PCCapabilityBroker.prepare = (
    _sara_prepare_with_youtube
)

PCCapabilityBroker.execute = (
    _sara_execute_with_youtube
)

# === END SARA YOUTUBE PLAYBACK CAPABILITY V1 ===


# === SARA DYNAMIC APPLICATION RESOLVER V1 ===

_SARA_EXECUTE_BEFORE_DYNAMIC_APPS = (
    PCCapabilityBroker.execute
)


def _sara_execute_with_dynamic_apps(
    self,
    prepared,
):

    if (
        getattr(
            prepared,
            "intent",
            "",
        )
        ==
        "open_application"
    ):

        args = getattr(
            prepared,
            "args",
            {},
        ) or {}


        target = str(
            args.get("target")
            or
            args.get("application")
            or
            args.get("app")
            or
            args.get("name")
            or ""
        ).strip()


        if target:

            try:

                from .app_resolver import (
                    resolve_and_launch_application,
                )

                dynamic = (
                    resolve_and_launch_application(
                        target
                    )
                )


                if dynamic.get(
                    "success"
                ):

                    from .types import (
                        ActionResult
                    )

                    name = (
                        dynamic.get(
                            "name"
                        )
                        or target
                    )


                    return ActionResult(
                        success=True,
                        action=
                            "open_application",
                        message=
                            f"{name} is open.",
                        verified=False,
                        data={
                            "resolver":
                                "dynamic_windows_catalog",
                            "matched_name":
                                name,
                            "match_score":
                                dynamic.get(
                                    "score"
                                ),
                            "kind":
                                dynamic.get(
                                    "kind"
                                ),
                        },
                    )


            except Exception as exc:

                print(
                    "[APP RESOLVER ERROR] "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )


    # Existing broker remains the fallback.
    return (
        _SARA_EXECUTE_BEFORE_DYNAMIC_APPS(
            self,
            prepared,
        )
    )


PCCapabilityBroker.execute = (
    _sara_execute_with_dynamic_apps
)

# === END SARA DYNAMIC APPLICATION RESOLVER V1 ===


# === SARA STRICT DYNAMIC APP GUARD V2 ===

_SARA_EXECUTE_BEFORE_STRICT_APP_GUARD = (
    PCCapabilityBroker.execute
)


def _sara_execute_strict_apps(
    self,
    prepared,
):

    if (
        getattr(
            prepared,
            "intent",
            "",
        )
        ==
        "open_application"
    ):

        args = (
            getattr(
                prepared,
                "args",
                {},
            )
            or {}
        )


        target = str(
            args.get("target")
            or
            args.get("application")
            or
            args.get("app")
            or
            args.get("name")
            or ""
        ).strip()


        from .types import ActionResult

        if not target:

            return ActionResult(
                success=False,
                action="open_application",
                error=(
                    "No application name was supplied."
                ),
                verified=True,
            )


        try:

            from .app_resolver import (
                resolve_and_launch_application,
            )

            result = (
                resolve_and_launch_application(
                    target
                )
            )


        except Exception as exc:

            return ActionResult(
                success=False,
                action="open_application",
                error=(
                    "Application discovery failed: "
                    f"{type(exc).__name__}: {exc}"
                ),
                verified=True,
            )


        if not result.get(
            "success"
        ):

            return ActionResult(
                success=False,
                action="open_application",
                error=(
                    result.get(
                        "error"
                    )
                    or
                    (
                        "I couldn't confidently identify "
                        "that installed application."
                    )
                ),
                verified=True,
                data={
                    "resolver":
                        "strict_dynamic_windows_catalog",
                    "score":
                        result.get(
                            "score"
                        ),
                },
            )


        name = (
            result.get(
                "name"
            )
            or target
        )


        return ActionResult(
            success=True,
            action="open_application",
            message=
                f"{name} is open.",
            verified=False,
            data={
                "resolver":
                    "strict_dynamic_windows_catalog",
                "matched_name":
                    name,
                "match_score":
                    result.get(
                        "score"
                    ),
                "kind":
                    result.get(
                        "kind"
                    ),
            },
        )


    return (
        _SARA_EXECUTE_BEFORE_STRICT_APP_GUARD(
            self,
            prepared,
        )
    )


PCCapabilityBroker.execute = (
    _sara_execute_strict_apps
)

# === END SARA STRICT DYNAMIC APP GUARD V2 ===
