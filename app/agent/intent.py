
from __future__ import annotations

import json
import re
from typing import Any

from app.llm_client import chat
from .types import IntentDecision, IntentKind


WEB_SERVICES = {
    "youtube": "YouTube",
    "google": "Google",
    "gmail": "Gmail",
    "github": "GitHub",
}

BROWSERS = {
    "edge": "Microsoft Edge",
    "microsoft edge": "Microsoft Edge",
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "firefox": "Firefox",
    "brave": "Brave",
}


INTENT_SYSTEM_PROMPT = r"""
You are Sara's semantic intent router for a Windows PC assistant.

Do NOT answer the user and do NOT claim that an action succeeded.
Return ONLY one valid JSON object:

{
  "kind": "chat" | "question" | "action" | "ambiguous",
  "intent": "canonical_intent",
  "confidence": 0.0,
  "arguments": {},
  "requires_web": false,
  "search_query": null,
  "ambiguous": false,
  "clarification": null,
  "reason": "short reason"
}

Use semantic meaning, not exact wording.

CANONICAL PC ACTIONS AND ARGUMENTS

open_application
  {"application":"Google Chrome"}

open_website
  {"website":"YouTube"}
  optionally {"browser":"Microsoft Edge"}

open_url
  {"url":"https://example.com"}
  optionally {"browser":"Google Chrome"}

browser_search
  {"query":"ESP32 tutorials","browser":"Microsoft Edge"}

web_search
  {"query":"latest NVIDIA news"}

set_volume
  {"percent":35}

media_control
  {"command":"play|pause|next|previous|mute|volume_up|volume_down"}

get_system_status
  {}

get_running_processes
  {}

get_network_status
  {}

create_folder
  {"name":"Sara Test","location":"desktop"}
  OR {"path":"desktop\\Sara Test"}

list_files
  {"path":"desktop"}

search_files
  {"query":"CMOS","path":"documents"}

open_path
  {"path":"desktop\\notes.pdf"}

copy_path
  {"source":"...","destination":"..."}

move_path
  {"source":"...","destination":"..."}

rename_path
  {"path":"...","new_name":"..."}

recycle_path
  {"path":"..."}

create_text_file
  {"path":"desktop\\note.txt","content":"..."}

overwrite_text_file
  {"path":"...","content":"..."}

set_clipboard
  {"text":"..."}

close_application
  {"application":"Notepad"}

install_package
  {"package":"VLC media player"}

uninstall_package
  {"package":"VLC media player"}

restart_pc
  {}

shutdown_pc
  {}

lock_pc
  {}

IMPORTANT:
- Explicit requests to make the PC do something are ACTION, never chat.
- "open YouTube" means open_website.
- "open WhatsApp" or "open ChatGPT" means open_application unless the user
  explicitly asks for the website/web version.
- "search X in Edge" means browser_search.
- Opening a website or browser search does NOT mean requires_web=true.
  That flag is for retrieving information for Sara to answer.
- Current/latest/news/weather/prices/scores/releases or explicit information
  lookup normally require web search.
- Stable knowledge questions can use normal local question/chat handling.
- For destructive/sensitive actions, still return the intended canonical action.
  A separate policy layer decides confirmation or blocking.
- If the target or operation is genuinely unclear, return kind="ambiguous".
- Do not invent arguments not implied by the request.
- Return JSON only.
""".strip()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _guardrail(user_text: str) -> IntentDecision | None:
    original = _clean(user_text)
    if not original:
        return None
    lower = original.lower()

    # Explicit information web search.
    m = re.match(
        r"^(?:search\s+(?:the\s+)?web\s+(?:for\s+)?|"
        r"look\s+up\s+online\s+|search\s+online\s+(?:for\s+)?)(.+)$",
        lower,
        flags=re.I,
    )
    if m and m.group(1).strip():
        q = m.group(1).strip()
        return IntentDecision(
            kind=IntentKind.ACTION,
            intent="web_search",
            confidence=0.99,
            arguments={"query": q},
            requires_web=True,
            search_query=q,
            reason="Explicit web information search.",
        )

    browser_pattern = (
        r"(microsoft\s+edge|edge|google\s+chrome|chrome|firefox|brave)"
    )
    m = re.match(
        rf"^(?:search|find|look\s+up)\s+(.+?)\s+"
        rf"(?:in|on|using|with)\s+{browser_pattern}$",
        lower,
        flags=re.I,
    )
    if m:
        q = m.group(1).strip()
        browser = BROWSERS.get(m.group(2).strip(), m.group(2).strip())
        return IntentDecision(
            kind=IntentKind.ACTION,
            intent="browser_search",
            confidence=0.99,
            arguments={"query": q, "browser": browser},
            requires_web=False,
            reason="Explicit browser search.",
        )

    # Fast deterministic volume routing.
    m = re.match(
        r"^(?:set|change|turn)\s+(?:the\s+)?volume\s+(?:to\s+)?"
        r"(\d{1,3})(?:\s*%|\s+percent)?$",
        lower,
        flags=re.I,
    )
    if m:
        value = max(0, min(100, int(m.group(1))))
        return IntentDecision(
            kind=IntentKind.ACTION,
            intent="set_volume",
            confidence=0.99,
            arguments={"percent": value},
            requires_web=False,
            reason="Explicit volume setting.",
        )

    # Open/launch guardrail is kept narrow to prevent action->chat failures.
    m = re.match(
        r"^(?:please\s+)?(?:open|launch|start|run|visit|go\s+to)\s+(.+?)"
        rf"(?:\s+(?:in|using|with)\s+{browser_pattern})?$",
        lower,
        flags=re.I,
    )
    if m:
        target = m.group(1).strip()
        browser_raw = m.group(2).strip() if m.group(2) else None
        browser = BROWSERS.get(browser_raw, browser_raw) if browser_raw else None

        if target in WEB_SERVICES:
            args = {"website": WEB_SERVICES[target]}
            if browser:
                args["browser"] = browser
            return IntentDecision(
                kind=IntentKind.ACTION,
                intent="open_website",
                confidence=0.99,
                arguments=args,
                requires_web=False,
                reason="Explicit website-open request.",
            )

        if (
            target.startswith("http://")
            or target.startswith("https://")
            or re.search(r"\.[a-z]{2,}(?:/|$)", target, flags=re.I)
        ):
            args = {"url": target}
            if browser:
                args["browser"] = browser
            return IntentDecision(
                kind=IntentKind.ACTION,
                intent="open_url",
                confidence=0.99,
                arguments=args,
                requires_web=False,
                reason="Explicit URL-open request.",
            )

        return IntentDecision(
            kind=IntentKind.ACTION,
            intent="open_application",
            confidence=0.97,
            arguments={"application": target},
            requires_web=False,
            reason="Explicit application-open request.",
        )

    return None


def _extract_json(text: str) -> dict[str, Any]:
    text = str(text or "").strip()

    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except Exception:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("Intent model did not return JSON.")

    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Intent result was not a JSON object.")

    return value


def _kind(value: Any) -> IntentKind:
    try:
        return IntentKind(str(value).strip().lower())
    except Exception:
        return IntentKind.AMBIGUOUS


def _analyse_intent_base(user_text: str) -> IntentDecision:
    guarded = _guardrail(user_text)
    if guarded is not None:
        return guarded

    response, _ = chat(
        [
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]
    )

    try:
        data = _extract_json(response)
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))

        arguments = data.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}

        kind = _kind(data.get("kind", "ambiguous"))
        ambiguous = bool(data.get("ambiguous", False))
        clarification = data.get("clarification")

        if kind == IntentKind.ACTION and confidence < 0.72:
            kind = IntentKind.AMBIGUOUS
            ambiguous = True
            clarification = clarification or (
                "I'm not fully sure what action you want. Can you clarify?"
            )

        return IntentDecision(
            kind=kind,
            intent=str(data.get("intent") or "unknown").strip(),
            confidence=confidence,
            arguments=arguments,
            requires_web=bool(data.get("requires_web", False)),
            search_query=(
                str(data["search_query"]).strip()
                if data.get("search_query")
                else None
            ),
            ambiguous=ambiguous,
            clarification=(
                str(clarification).strip()
                if clarification
                else None
            ),
            reason=(
                str(data["reason"]).strip()
                if data.get("reason")
                else None
            ),
        )
    except Exception as exc:
        return IntentDecision(
            kind=IntentKind.AMBIGUOUS,
            intent="routing_failure",
            confidence=0.0,
            ambiguous=True,
            clarification=(
                "I couldn't confidently understand that request. "
                "Could you say exactly what you want me to do?"
            ),
            reason=str(exc),
        )


# === SARA YOUTUBE INTENT V1 ===

try:

    INTENT_SYSTEM_PROMPT += r"""

Additional PC capability:

play_youtube_video

Use it when the user wants Sara to find and play
a public YouTube video.

Examples:

"play CUDA tutorial on YouTube"

{
  "kind": "action",
  "intent": "play_youtube_video",
  "confidence": 0.99,
  "arguments": {
    "query": "CUDA tutorial"
  },
  "requires_web": false
}

"find and play ESP32 S3 tutorial on YouTube in Edge"

{
  "kind": "action",
  "intent": "play_youtube_video",
  "confidence": 0.99,
  "arguments": {
    "query": "ESP32 S3 tutorial",
    "browser": "Microsoft Edge"
  },
  "requires_web": false
}

This capability is execution, not web_search.
"""

except Exception:
    pass


def _detect_youtube_play_intent(
    user_text,
):

    import re

    original = str(
        user_text
        or ""
    ).strip()

    if not original:
        return None


    browser_pattern = (
        r"(microsoft\s+edge|edge|"
        r"google\s+chrome|chrome|"
        r"firefox|brave)"
    )


    patterns = [

        rf"^(?:please\s+)?"
        rf"(?:find\s+and\s+)?play\s+"
        rf"(.+?)\s+on\s+youtube"
        rf"(?:\s+(?:in|using|with)\s+"
        rf"{browser_pattern})?\s*$",

        rf"^(?:please\s+)?"
        rf"youtube\s+"
        rf"(?:play|find\s+and\s+play)\s+"
        rf"(.+?)"
        rf"(?:\s+(?:in|using|with)\s+"
        rf"{browser_pattern})?\s*$",
    ]


    for pattern in patterns:

        match = re.match(
            pattern,
            original,
            flags=re.I,
        )

        if not match:
            continue

        query = (
            match.group(1)
            .strip()
        )

        browser = (
            match.group(2)
            if
            len(
                match.groups()
            ) >= 2
            else None
        )

        if browser:

            browser = {
                "edge":
                    "Microsoft Edge",
                "microsoft edge":
                    "Microsoft Edge",
                "chrome":
                    "Google Chrome",
                "google chrome":
                    "Google Chrome",
                "firefox":
                    "Firefox",
                "brave":
                    "Brave",
            }.get(
                browser.lower(),
                browser,
            )

        arguments = {
            "query":
                query,
            "index":
                1,
        }

        if browser:
            arguments[
                "browser"
            ] = browser

        return IntentDecision(
            kind=
                IntentKind.ACTION,
            intent=
                "play_youtube_video",
            confidence=
                0.99,
            arguments=
                arguments,
            requires_web=
                False,
            search_query=
                None,
            ambiguous=
                False,
            reason=(
                "User explicitly requested "
                "YouTube video playback."
            ),
        )


    url_match = re.match(
        r"^(?:please\s+)?play\s+"
        r"(https?://(?:www\.)?"
        r"(?:youtube\.com|youtu\.be)/\S+)\s*$",
        original,
        flags=re.I,
    )


    if url_match:

        return IntentDecision(
            kind=
                IntentKind.ACTION,
            intent=
                "play_youtube_video",
            confidence=
                0.99,
            arguments={
                "query":
                    url_match.group(1),
                "index":
                    1,
            },
            requires_web=
                False,
            search_query=
                None,
            ambiguous=
                False,
            reason=(
                "User supplied a YouTube "
                "video URL to play."
            ),
        )


    return None


def analyse_intent(
    user_text,
):

    youtube = (
        _detect_youtube_play_intent(
            user_text
        )
    )

    if youtube is not None:
        return youtube

    return (
        _analyse_intent_base(
            user_text
        )
    )

# === END SARA YOUTUBE INTENT V1 ===
