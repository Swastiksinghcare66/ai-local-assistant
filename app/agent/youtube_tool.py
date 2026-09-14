from __future__ import annotations

import os
import re
import shutil
import subprocess
import webbrowser

from pathlib import Path
from urllib.parse import (
    parse_qs,
    urlencode,
    urlparse,
    urlunparse,
)

from yt_dlp import YoutubeDL

from .types import ActionResult


BROWSER_CANDIDATES = {
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


def _youtube_url(value: str) -> bool:

    try:
        parsed = urlparse(value)

        host = (
            parsed.netloc
            .lower()
            .removeprefix("www.")
        )

        return host in {
            "youtube.com",
            "m.youtube.com",
            "youtu.be",
            "music.youtube.com",
        }

    except Exception:
        return False


def _autoplay_url(url: str) -> str:

    parsed = urlparse(url)

    query = parse_qs(
        parsed.query
    )

    query["autoplay"] = ["1"]

    encoded = urlencode(
        query,
        doseq=True,
    )

    return urlunparse(
        parsed._replace(
            query=encoded
        )
    )


def _find_browser(
    browser: str,
):

    key = str(
        browser or ""
    ).strip().lower()

    candidates = (
        BROWSER_CANDIDATES.get(
            key
        )
    )

    if not candidates:
        return None

    for candidate in candidates:

        expanded = os.path.expandvars(
            candidate
        )

        if Path(expanded).exists():
            return expanded

        found = shutil.which(
            expanded
        )

        if found:
            return found

    return None


def _open_url(
    url: str,
    browser: str | None,
) -> tuple[bool, str | None]:

    if browser:

        executable = _find_browser(
            browser
        )

        if not executable:

            return (
                False,
                f"I couldn't find {browser} on this PC."
            )

        subprocess.Popen(
            [
                executable,
                url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0,
            ),
        )

        return True, None

    accepted = webbrowser.open(
        url,
        new=2,
    )

    if not accepted:

        return (
            False,
            "Windows did not accept the browser request."
        )

    return True, None


def _resolve_search(
    query: str,
    index: int = 1,
):

    index = max(
        1,
        min(
            int(index),
            5,
        ),
    )

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 12,
    }

    with YoutubeDL(
        options
    ) as ydl:

        result = ydl.extract_info(
            f"ytsearch{index}:{query}",
            download=False,
        )

    entries = (
        result.get("entries")
        or []
    )

    entries = [
        item
        for item in entries
        if item
    ]

    if len(entries) < index:
        return None

    entry = entries[
        index - 1
    ]

    video_id = entry.get(
        "id"
    )

    title = (
        entry.get("title")
        or query
    )

    channel = (
        entry.get("channel")
        or
        entry.get("uploader")
    )

    url = (
        entry.get("webpage_url")
        or
        entry.get("original_url")
    )

    if (
        not url
        and video_id
    ):
        url = (
            "https://www.youtube.com/watch?v="
            +
            video_id
        )

    if not url:
        return None

    return {
        "title": title,
        "channel": channel,
        "url": url,
        "video_id": video_id,
    }


def play_youtube_video(
    query: str,
    browser: str | None = None,
    index: int = 1,
) -> ActionResult:

    query = str(
        query or ""
    ).strip()

    if not query:

        return ActionResult(
            success=False,
            action="play_youtube_video",
            error="No YouTube video or search query was specified.",
            verified=True,
        )

    try:

        if _youtube_url(
            query
        ):

            target = {
                "title": "the requested video",
                "channel": None,
                "url": query,
                "video_id": None,
            }

        else:

            target = _resolve_search(
                query,
                index=index,
            )

            if not target:

                return ActionResult(
                    success=False,
                    action="play_youtube_video",
                    error=(
                        "I couldn't resolve a reliable YouTube "
                        "video for that request."
                    ),
                    verified=True,
                )

        url = _autoplay_url(
            target["url"]
        )

        opened, error = _open_url(
            url,
            browser,
        )

        if not opened:

            return ActionResult(
                success=False,
                action="play_youtube_video",
                error=error,
                verified=True,
            )

        title = target[
            "title"
        ]

        channel = target.get(
            "channel"
        )

        if channel:

            message = (
                f"I opened {title} by {channel} "
                f"on YouTube and requested playback."
            )

        else:

            message = (
                f"I opened {title} on YouTube "
                f"and requested playback."
            )

        return ActionResult(
            success=True,
            action="play_youtube_video",
            message=message,
            verified=False,
            data={
                "title": title,
                "channel": channel,
                "url": url,
                "video_id": target.get(
                    "video_id"
                ),
                "browser": browser,
            },
        )

    except Exception as exc:

        return ActionResult(
            success=False,
            action="play_youtube_video",
            error=(
                f"YouTube playback failed: "
                f"{type(exc).__name__}: {exc}"
            ),
            verified=True,
        )
