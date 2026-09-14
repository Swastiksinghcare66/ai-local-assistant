from __future__ import annotations

import os
import shutil
import subprocess
import time
import webbrowser

from pathlib import Path
from urllib.parse import (
    quote_plus,
    urlparse,
)

from ..types import ActionResult


APP_ALIASES = {

    "chrome": [
        "chrome",
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    ],

    "google chrome": [
        "chrome",
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    ],

    "edge": [
        "msedge",
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    ],

    "microsoft edge": [
        "msedge",
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    ],

    "notepad": [
        "notepad.exe",
    ],

    "calculator": [
        "calc.exe",
    ],

    "explorer": [
        "explorer.exe",
    ],

    "file explorer": [
        "explorer.exe",
    ],

    "visual studio code": [
        "code",
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
    ],

    "vscode": [
        "code",
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
    ],
}


BROWSER_ALIASES = {

    "microsoft edge":
        APP_ALIASES["microsoft edge"],

    "edge":
        APP_ALIASES["edge"],

    "google chrome":
        APP_ALIASES["google chrome"],

    "chrome":
        APP_ALIASES["chrome"],

    "firefox": [
        "firefox",
        r"%ProgramFiles%\Mozilla Firefox\firefox.exe",
        r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe",
    ],

    "brave": [
        "brave",
        r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
}


WEBSITE_ALIASES = {

    "youtube":
        "https://www.youtube.com/",

    "google":
        "https://www.google.com/",

    "github":
        "https://github.com/",

    "gmail":
        "https://mail.google.com/",
}


def _find_executable(
    candidates,
):

    for candidate in candidates:

        if not candidate:
            continue

        expanded = os.path.expandvars(
            candidate
        )

        if Path(expanded).exists():
            return expanded

        resolved = shutil.which(
            expanded
        )

        if resolved:
            return resolved

    return None


def _spawn(
    executable,
    *args,
):

    subprocess.Popen(
        [
            executable,
            *args,
        ],
        stdout=
            subprocess.DEVNULL,
        stderr=
            subprocess.DEVNULL,
        creationflags=
            getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0,
            ),
    )


def _browser_executable(
    browser,
):

    if not browser:
        return None

    key = str(
        browser
    ).strip().lower()

    candidates = (
        BROWSER_ALIASES.get(
            key
        )
    )

    if not candidates:
        return None

    return _find_executable(
        candidates
    )


def open_application(
    application: str,
) -> ActionResult:

    requested = str(
        application or ""
    ).strip()

    if not requested:

        return ActionResult(
            success=False,
            action=
                "open_application",
            error=
                "No application was specified.",
            verified=True,
        )


    key = requested.lower()


    candidates = (
        APP_ALIASES.get(
            key
        )
    )


    if candidates:

        executable = (
            _find_executable(
                candidates
            )
        )

        if not executable:

            return ActionResult(
                success=False,
                action=
                    "open_application",
                error=(
                    f"I couldn't find "
                    f"{requested} on this PC."
                ),
                verified=True,
            )


        try:

            _spawn(
                executable
            )

            time.sleep(
                0.35
            )

            return ActionResult(
                success=True,
                action=
                    "open_application",
                message=(
                    f"{requested} is open."
                ),
                verified=True,
                data={
                    "executable":
                        executable,
                },
            )

        except Exception as exc:

            return ActionResult(
                success=False,
                action=
                    "open_application",
                error=str(exc),
                verified=True,
            )


    try:

        os.startfile(
            requested
        )

        return ActionResult(
            success=True,
            action=
                "open_application",
            message=(
                f"I opened {requested}."
            ),
            verified=False,
        )

    except Exception:

        return ActionResult(
            success=False,
            action=
                "open_application",
            error=(
                f"I couldn't reliably find "
                f"{requested} on this PC."
            ),
            verified=True,
        )


def _resolve_url(
    target,
):

    target = str(
        target or ""
    ).strip()

    if not target:
        return None


    alias = (
        WEBSITE_ALIASES.get(
            target.lower()
        )
    )

    if alias:
        return alias


    parsed = urlparse(
        target
    )


    if (
        parsed.scheme
        in {
            "http",
            "https",
        }
        and
        parsed.netloc
    ):
        return target


    if (
        "." in target
        and
        " " not in target
    ):
        return (
            "https://"
            +
            target
        )


    return None


def open_website(
    target: str,
    browser: str | None = None,
) -> ActionResult:

    url = _resolve_url(
        target
    )


    if not url:

        return ActionResult(
            success=False,
            action=
                "open_website",
            error=(
                f"I don't have a reliable URL "
                f"for {target}."
            ),
            verified=True,
        )


    try:

        if browser:

            executable = (
                _browser_executable(
                    browser
                )
            )

            if not executable:

                return ActionResult(
                    success=False,
                    action=
                        "open_website",
                    error=(
                        f"I couldn't find "
                        f"{browser} on this PC."
                    ),
                    verified=True,
                )


            _spawn(
                executable,
                url,
            )


            return ActionResult(
                success=True,
                action=
                    "open_website",
                message=(
                    f"I opened {target} "
                    f"in {browser}."
                ),
                verified=True,
                data={
                    "url":
                        url,
                    "browser":
                        browser,
                },
            )


        opened = webbrowser.open(
            url,
            new=2,
        )


        if not opened:

            return ActionResult(
                success=False,
                action=
                    "open_website",
                error=(
                    "Windows did not accept "
                    "the browser request."
                ),
                verified=True,
            )


        return ActionResult(
            success=True,
            action=
                "open_website",
            message=(
                f"I opened {target}."
            ),
            verified=True,
            data={
                "url":
                    url,
            },
        )


    except Exception as exc:

        return ActionResult(
            success=False,
            action=
                "open_website",
            error=str(exc),
            verified=True,
        )


def browser_search(
    query: str,
    browser: str | None = None,
) -> ActionResult:

    query = str(
        query or ""
    ).strip()


    if not query:

        return ActionResult(
            success=False,
            action=
                "browser_search",
            error=
                "No search query was specified.",
            verified=True,
        )


    search_url = (
        "https://www.google.com/search?q="
        +
        quote_plus(
            query
        )
    )


    try:

        if browser:

            executable = (
                _browser_executable(
                    browser
                )
            )


            if not executable:

                return ActionResult(
                    success=False,
                    action=
                        "browser_search",
                    error=(
                        f"I couldn't find "
                        f"{browser} on this PC."
                    ),
                    verified=True,
                )


            _spawn(
                executable,
                search_url,
            )


            return ActionResult(
                success=True,
                action=
                    "browser_search",
                message=(
                    f"I searched for {query} "
                    f"in {browser}."
                ),
                verified=True,
                data={
                    "query":
                        query,
                    "browser":
                        browser,
                    "url":
                        search_url,
                },
            )


        opened = (
            webbrowser.open(
                search_url,
                new=2,
            )
        )


        if not opened:

            return ActionResult(
                success=False,
                action=
                    "browser_search",
                error=(
                    "Windows did not accept "
                    "the browser search request."
                ),
                verified=True,
            )


        return ActionResult(
            success=True,
            action=
                "browser_search",
            message=(
                f"I searched for {query}."
            ),
            verified=True,
            data={
                "query":
                    query,
                "url":
                    search_url,
            },
        )


    except Exception as exc:

        return ActionResult(
            success=False,
            action=
                "browser_search",
            error=str(exc),
            verified=True,
        )
