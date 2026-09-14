from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import threading
import time
import winreg

from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppEntry:
    name: str
    kind: str
    target: str


class InstalledApplicationResolver:

    REFRESH_SECONDS = 300

    MIN_SCORE = 0.84
    AMBIGUITY_MARGIN = 0.07

    def __init__(self):
        self._entries: list[AppEntry] = []
        self._last_refresh = 0.0
        self._lock = threading.RLock()


    @staticmethod
    def _normalize(value: str) -> str:

        value = str(
            value or ""
        ).lower().strip()

        value = re.sub(
            r"[\-_.()/\\]+",
            " ",
            value,
        )

        value = re.sub(
            r"\b(application|app)\b$",
            "",
            value,
        )

        value = re.sub(
            r"\s+",
            " ",
            value,
        )

        return value.strip()


    @classmethod
    def _compact(cls, value: str) -> str:

        return re.sub(
            r"[^a-z0-9]+",
            "",
            cls._normalize(value),
        )


    def _add(
        self,
        entries: dict,
        name: str,
        kind: str,
        target: str,
    ):

        name = str(name or "").strip()
        target = str(target or "").strip()

        if not name or not target:
            return

        key = (
            self._normalize(name),
            kind,
            target.lower(),
        )

        entries[key] = AppEntry(
            name=name,
            kind=kind,
            target=target,
        )


    def _scan_start_apps(
        self,
        entries: dict,
    ):

        try:

            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    (
                        "Get-StartApps | "
                        "Select-Object Name,AppID | "
                        "ConvertTo-Json -Compress"
                    ),
                ],
                capture_output=True,
                text=True,
                timeout=8,
                shell=False,
            )

            if result.returncode != 0:
                return

            raw = result.stdout.strip()

            if not raw:
                return

            data = json.loads(raw)

            if isinstance(data, dict):
                data = [data]

            for item in data:

                self._add(
                    entries,
                    item.get("Name", ""),
                    "appid",
                    item.get("AppID", ""),
                )

        except Exception:
            pass


    def _scan_shortcuts(
        self,
        entries: dict,
    ):

        locations = [
            (
                Path(
                    os.environ.get(
                        "APPDATA",
                        "",
                    )
                )
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
            ),
            (
                Path(
                    os.environ.get(
                        "PROGRAMDATA",
                        "",
                    )
                )
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
            ),
            Path.home() / "Desktop",
        ]

        onedrive = os.environ.get(
            "OneDrive"
        )

        if onedrive:
            locations.append(
                Path(onedrive) / "Desktop"
            )

        for root in locations:

            if not root.exists():
                continue

            try:

                for shortcut in root.rglob(
                    "*.lnk"
                ):

                    self._add(
                        entries,
                        shortcut.stem,
                        "shortcut",
                        str(shortcut),
                    )

            except Exception:
                continue


    def _scan_app_paths(
        self,
        entries: dict,
    ):

        base = (
            r"SOFTWARE\Microsoft\Windows"
            r"\CurrentVersion\App Paths"
        )

        roots = (
            winreg.HKEY_CURRENT_USER,
            winreg.HKEY_LOCAL_MACHINE,
        )

        views = (
            0,
            getattr(
                winreg,
                "KEY_WOW64_64KEY",
                0,
            ),
            getattr(
                winreg,
                "KEY_WOW64_32KEY",
                0,
            ),
        )

        for root in roots:

            for view in views:

                try:

                    key = winreg.OpenKey(
                        root,
                        base,
                        0,
                        winreg.KEY_READ | view,
                    )

                except OSError:
                    continue

                try:

                    count = (
                        winreg.QueryInfoKey(
                            key
                        )[0]
                    )

                    for i in range(count):

                        try:

                            child_name = (
                                winreg.EnumKey(
                                    key,
                                    i,
                                )
                            )

                            child = winreg.OpenKey(
                                key,
                                child_name,
                            )

                            value, _ = (
                                winreg.QueryValueEx(
                                    child,
                                    None,
                                )
                            )

                            winreg.CloseKey(
                                child
                            )

                            exe = str(
                                value
                            ).strip('" ')

                            self._add(
                                entries,
                                Path(
                                    child_name
                                ).stem,
                                "exe",
                                exe,
                            )

                        except Exception:
                            continue

                finally:

                    winreg.CloseKey(
                        key
                    )


    def _scan_path(
        self,
        entries: dict,
    ):

        seen = set()

        for folder in os.environ.get(
            "PATH",
            "",
        ).split(os.pathsep):

            folder = folder.strip(
                '" '
            )

            if not folder:
                continue

            lowered = folder.lower()

            if lowered in seen:
                continue

            seen.add(lowered)

            path = Path(folder)

            if not path.is_dir():
                continue

            try:

                for exe in path.glob(
                    "*.exe"
                ):

                    self._add(
                        entries,
                        exe.stem,
                        "exe",
                        str(exe),
                    )

            except Exception:
                continue


    def refresh(
        self,
        force: bool = False,
    ) -> int:

        with self._lock:

            now = time.monotonic()

            if (
                not force
                and
                self._entries
                and
                now - self._last_refresh
                <
                self.REFRESH_SECONDS
            ):
                return len(
                    self._entries
                )

            entries = {}

            self._scan_start_apps(
                entries
            )

            self._scan_shortcuts(
                entries
            )

            self._scan_app_paths(
                entries
            )

            self._scan_path(
                entries
            )

            self._entries = list(
                entries.values()
            )

            self._last_refresh = now

            print(
                "[APP CATALOG] "
                f"{len(self._entries)} "
                "applications discovered"
            )

            return len(
                self._entries
            )


    def _score(
        self,
        query: str,
        entry: AppEntry,
    ) -> float:

        q = self._normalize(
            query
        )

        n = self._normalize(
            entry.name
        )

        qc = self._compact(
            query
        )

        nc = self._compact(
            entry.name
        )

        if not q or not n:
            return 0.0


        # Exact human-readable name
        if q == n:
            return 1.0


        # Handles:
        # "chat gpt" vs "ChatGPT"
        # "power point" vs "PowerPoint"
        if qc and qc == nc:
            return 0.995


        q_words = q.split()
        n_words = n.split()


        # Every requested word exists in app name.
        if (
            q_words
            and
            all(
                word in n_words
                for word in q_words
            )
        ):

            coverage = (
                len(q_words)
                /
                max(
                    1,
                    len(n_words),
                )
            )

            return (
                0.94
                +
                min(
                    0.04,
                    coverage * 0.04,
                )
            )


        # Strong prefix.
        if (
            len(qc) >= 4
            and
            nc.startswith(qc)
        ):
            return 0.93


        # Strong substring, but only when query represents
        # a meaningful portion of the candidate name.
        if (
            len(qc) >= 4
            and
            qc in nc
        ):

            coverage = (
                len(qc)
                /
                max(
                    1,
                    len(nc),
                )
            )

            if coverage >= 0.55:
                return 0.90


        # Typo tolerance only.
        #
        # Deliberately reject weak fuzzy similarity.
        ratio = (
            difflib.SequenceMatcher(
                None,
                qc,
                nc,
            )
            .ratio()
        )

        if ratio >= 0.88:
            return ratio


        return 0.0


    def candidates(
        self,
        query: str,
        limit: int = 8,
    ) -> list[dict]:

        self.refresh(
            force=False
        )

        ranked = []

        for entry in self._entries:

            score = self._score(
                query,
                entry,
            )

            if score <= 0:
                continue

            ranked.append(
                (
                    score,
                    entry,
                )
            )

        kind_priority = {
            "appid": 3,
            "shortcut": 2,
            "exe": 1,
        }

        ranked.sort(
            key=lambda item: (
                item[0],
                kind_priority.get(
                    item[1].kind,
                    0,
                ),
            ),
            reverse=True,
        )


        # Collapse duplicates for the same visible app name.
        output = []
        seen_names = set()

        for score, entry in ranked:

            name_key = self._normalize(
                entry.name
            )

            if name_key in seen_names:
                continue

            seen_names.add(
                name_key
            )

            output.append(
                {
                    "name": entry.name,
                    "kind": entry.kind,
                    "target": entry.target,
                    "score": round(
                        score,
                        4,
                    ),
                    "_entry": entry,
                }
            )

            if len(output) >= limit:
                break


        return output


    def resolve(
        self,
        query: str,
    ) -> tuple[
        AppEntry | None,
        float,
    ]:

        self.refresh(
            force=False
        )

        candidates = self.candidates(
            query,
            limit=5,
        )


        # If unknown, force one fresh catalog scan in case
        # software was installed since startup.
        if not candidates:

            self.refresh(
                force=True
            )

            candidates = self.candidates(
                query,
                limit=5,
            )


        if not candidates:

            return (
                None,
                0.0,
            )


        best = candidates[0]

        best_score = float(
            best["score"]
        )


        if best_score < self.MIN_SCORE:

            return (
                None,
                best_score,
            )


        # Do not choose between similarly plausible app names.
        if len(candidates) > 1:

            second = candidates[1]

            second_score = float(
                second["score"]
            )

            if (
                best["name"].lower()
                !=
                second["name"].lower()
                and
                best_score < 0.98
                and
                (
                    best_score
                    -
                    second_score
                )
                <
                self.AMBIGUITY_MARGIN
            ):

                print(
                    "[APP RESOLVER] "
                    "ambiguous match: "
                    f"{best['name']} "
                    f"({best_score:.2f}) vs "
                    f"{second['name']} "
                    f"({second_score:.2f})"
                )

                return (
                    None,
                    best_score,
                )


        return (
            best["_entry"],
            best_score,
        )


    @staticmethod
    def _launch(
        entry: AppEntry,
    ):

        if entry.kind == "appid":

            subprocess.Popen(
                [
                    "explorer.exe",
                    (
                        "shell:AppsFolder\\"
                        + entry.target
                    ),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            return


        if entry.kind == "shortcut":

            os.startfile(
                entry.target
            )

            return


        if entry.kind == "exe":

            subprocess.Popen(
                [
                    entry.target
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )

            return


        raise RuntimeError(
            "Unknown application type."
        )


    def launch(
        self,
        query: str,
    ) -> dict:

        entry, score = self.resolve(
            query
        )

        if entry is None:

            return {
                "success": False,
                "error": (
                    f"I couldn't confidently find "
                    f"{query} among the installed applications."
                ),
                "score": score,
            }


        try:

            self._launch(
                entry
            )

        except Exception as exc:

            return {
                "success": False,
                "error": (
                    f"Windows identified {entry.name}, "
                    f"but launching it failed: "
                    f"{type(exc).__name__}: {exc}"
                ),
                "score": score,
            }


        return {
            "success": True,
            "name": entry.name,
            "kind": entry.kind,
            "target": entry.target,
            "score": score,
        }


_RESOLVER = InstalledApplicationResolver()


def get_application_resolver():
    return _RESOLVER


def resolve_and_launch_application(
    query: str,
) -> dict:

    return _RESOLVER.launch(
        query
    )
