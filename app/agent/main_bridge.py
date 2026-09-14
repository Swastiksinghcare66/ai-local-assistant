from __future__ import annotations

import re
from dataclasses import dataclass

from .runtime import SaraAgent

from .knowledge_router import (
    ACTION,
    CASUAL,
    LOCAL_INFO,
    KNOWLEDGE_INFO,
    classify_request,
)

from .local_information import (
    answer_local_information,
)


@dataclass
class MainAgentResult:
    handled: bool
    text: str = ""
    state: str = ""
    intent: str = ""
    confidence: float = 0.0


# ============================================================
# PERSISTENT RUNTIME STATE
# ============================================================

_AGENT = SaraAgent()

_LAST_YOUTUBE_QUERY: str | None = None

_PENDING_WEB_HELP: str | None = None


# ============================================================
# YES / NO
# ============================================================

def _is_yes(text: str) -> bool:

    q = re.sub(
        r"\s+",
        " ",
        text.lower().strip(),
    )

    return bool(
        re.fullmatch(
            r"(yes|yeah|yep|sure|okay|ok|"
            r"do it|search it|search online|"
            r"search the internet|go ahead|"
            r"yes search it|yes please)",
            q,
        )
    )


def _is_no(text: str) -> bool:

    q = re.sub(
        r"\s+",
        " ",
        text.lower().strip(),
    )

    return bool(
        re.fullmatch(
            r"(no|nope|nah|cancel|"
            r"never mind|nevermind|"
            r"don't|do not)",
            q,
        )
    )


# ============================================================
# YOUTUBE CONTEXT
# ============================================================

def _normalize_media_request(
    text: str,
) -> str:

    global _LAST_YOUTUBE_QUERY


    raw = str(
        text or ""
    ).strip()

    q = re.sub(
        r"\s+",
        " ",
        raw.lower(),
    ).strip()


    if _LAST_YOUTUBE_QUERY:

        if re.fullmatch(
            r"(?:please\s+)?"
            r"(?:play|start)\s+"
            r"(?:the\s+|that\s+)?"
            r"(?:song|video|one|it)",
            q,
        ):

            rewritten = (
                f"play {_LAST_YOUTUBE_QUERY} "
                f"on youtube"
            )

            print(
                "[MEDIA CONTEXT] "
                f"{raw!r} -> {rewritten!r}"
            )

            return rewritten


    if (
        "youtube" in q
        and
        re.search(
            r"\b(play|watch|start)\b",
            q,
        )
    ):

        match = re.search(
            r"\b(?:play|watch|start)\b"
            r"\s+"
            r"(?:a\s+(?:song|video)\s+)?"
            r"(.+?)"
            r"\s+"
            r"(?:on|in|using)\s+"
            r"youtube"
            r"(?:\s+music)?"
            r"(?:\s+or\s+youtube)?"
            r"\s*$",
            raw,
            flags=re.I,
        )


        if match:

            query = (
                match.group(1)
                .strip(" ,.-")
            )


            query = re.sub(
                r"^(?:play|watch|start)\s+",
                "",
                query,
                flags=re.I,
            ).strip()


            query = re.sub(
                r"^(?:the\s+)?(?:song|video)\s+",
                "",
                query,
                flags=re.I,
            ).strip()


            if query:

                _LAST_YOUTUBE_QUERY = query

                rewritten = (
                    f"play {query} on youtube"
                )

                if rewritten.lower() != raw.lower():

                    print(
                        "[MEDIA NORMALIZE] "
                        f"{raw!r} -> {rewritten!r}"
                    )

                return rewritten


    return raw


# ============================================================
# SECURITY: DO NOT OFFER WEB HELP FOR BLOCKED/SENSITIVE ACTIONS
# ============================================================

def _sensitive_request(
    text: str,
    intent: str,
) -> bool:

    joined = (
        str(text or "")
        + " "
        + str(intent or "")
    ).lower()


    blocked = (
        "password",
        "credential",
        "cookie",
        "session token",
        "api key",
        "disable defender",
        "disable antivirus",
        "disable firewall",
        "uac bypass",
        "bypass uac",
        "format disk",
        "wipe disk",
        "permanent delete",
        "dump credential",
        "run shell",
        "powershell command",
    )


    return any(
        phrase in joined
        for phrase in blocked
    )


# ============================================================
# AGENT REPLY ADAPTER
# ============================================================

def _adapt_agent_reply(
    reply,
    transcript: str,
) -> MainAgentResult:

    global _PENDING_WEB_HELP


    decision = getattr(
        reply,
        "decision",
        None,
    )


    intent = ""

    confidence = 0.0


    if decision is not None:

        intent = str(
            getattr(
                decision,
                "intent",
                "",
            )
            or ""
        )


        try:

            confidence = float(
                getattr(
                    decision,
                    "confidence",
                    0.0,
                )
                or 0.0
            )

        except Exception:

            confidence = 0.0


        kind = getattr(
            getattr(
                decision,
                "kind",
                None,
            ),
            "value",
            getattr(
                decision,
                "kind",
                "",
            ),
        )


        print(
            "[MAIN INTENT] "
            f"kind={kind} "
            f"intent={intent} "
            f"confidence={confidence:.2f}"
        )


    state_obj = getattr(
        reply,
        "state",
        None,
    )


    state = str(
        getattr(
            state_obj,
            "value",
            state_obj or "",
        )
    ).lower()


    text = str(
        getattr(
            reply,
            "text",
            "",
        )
        or ""
    ).strip()


    normal_chat = bool(
        getattr(
            reply,
            "use_normal_chat",
            False,
        )
    )


    # An ACTION must never silently fall into conversational Qwen.
    if normal_chat:

        _PENDING_WEB_HELP = None

        return MainAgentResult(
            handled=True,
            text=(
                "I don't currently have a local capability "
                "for that action."
            ),
            state="needs_clarification",
            intent=intent or "unsupported_action",
            confidence=confidence,
        )


    # Sensitive blocks remain blocked.
    if (
        state == "unsupported"
        and
        _sensitive_request(
            transcript,
            intent,
        )
    ):

        return MainAgentResult(
            handled=True,
            text=(
                text
                or
                "I can't perform that action."
            ),
            state=state,
            intent=intent,
            confidence=confidence,
        )


    # Unsupported/failed local action:
    # offer background research rather than hallucinating execution.
    if state in {
        "unsupported",
        "failed",
    }:

        _PENDING_WEB_HELP = None

        return MainAgentResult(
            handled=True,
            text=(
                "I can't perform that reliably with my "
                "current local capabilities."
            ),
            state="needs_clarification",
            intent=intent or "unsupported_action",
            confidence=confidence,
        )


    if not text:

        return MainAgentResult(
            handled=False,
            state=state,
            intent=intent,
            confidence=confidence,
        )


    print(
        "[MAIN AGENT] "
        f"state={state} "
        f"intent={intent}"
    )


    return MainAgentResult(
        handled=True,
        text=text,
        state=state,
        intent=intent,
        confidence=confidence,
    )


# ============================================================
# MAIN ROUTER
# ============================================================

def route_main_agent(
    transcript: str,
) -> MainAgentResult:

    global _PENDING_WEB_HELP


    transcript = str(
        transcript or ""
    ).strip()


    if not transcript:

        return MainAgentResult(
            handled=False
        )


    # ========================================================
    # MEDIA NORMALIZATION
    # ========================================================

    routed = _normalize_media_request(
        transcript
    )


    # ========================================================
    # UNIVERSAL CLASSIFICATION
    # ========================================================

    decision = classify_request(
        routed
    )


    print(
        "[UNIFIED ROUTER] "
        f"{decision.kind} | "
        f"{decision.reason}"
    )


    # ========================================================
    # CASUAL CONVERSATION
    # ========================================================

    if decision.kind == CASUAL:

        # Existing PromptBuilder/Qwen/CosyVoice path handles it.
        return MainAgentResult(
            handled=False,
            state="chat",
            intent="casual_chat",
            confidence=1.0,
        )


    # ========================================================
    # LOCAL INFORMATION
    # ========================================================

    if decision.kind == LOCAL_INFO:

        local_answer = (
            answer_local_information(
                routed
            )
        )


        if local_answer:

            return MainAgentResult(
                handled=True,
                text=local_answer,
                state="success",
                intent="local_information",
                confidence=1.0,
            )


        # More complex local facts can still use existing agent tools.
        try:

            reply = _AGENT.handle(
                routed
            )

            return _adapt_agent_reply(
                reply,
                routed,
            )

        except Exception as exc:

            return MainAgentResult(
                handled=True,
                text=(
                    "I couldn't read that information "
                    "from the computer."
                ),
                state="failed",
                intent="local_information",
                confidence=1.0,
            )


    # ========================================================
    # API KNOWLEDGE ROUTING
    # ========================================================

    if decision.kind == KNOWLEDGE_INFO:

        # ----------------------------------------------------
        # CURRENT / LIVE INFORMATION
        # ----------------------------------------------------
        # GPT-5.6 Luna is used for general knowledge, but Sara
        # does not yet have a dedicated live-data/search tool.
        # Do not fabricate current facts.
        if decision.current:
            return MainAgentResult(
                handled=True,
                text=(
                    "I don't have live-data access for that yet."
                ),
                state="unsupported",
                intent="live_information_unavailable",
                confidence=1.0,
            )

        # ----------------------------------------------------
        # GENERAL KNOWLEDGE -> GPT-5.6 LUNA API
        # ----------------------------------------------------
        # handled=False intentionally passes the utterance into
        # the normal conversation pipeline, whose chat_stream()
        # now uses OpenRouter / GPT-5.6 Luna.
        print(
            "[KNOWLEDGE ROUTE] "
            "GPT-5.6 Luna API"
        )

        return MainAgentResult(
            handled=False,
            state="chat",
            intent="general_knowledge",
            confidence=1.0,
        )


    # ========================================================
    # COMPUTER ACTION
    # ========================================================

    try:

        reply = _AGENT.handle(
            routed
        )


    except Exception as exc:

        print(
            "[MAIN AGENT ERROR] "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        _PENDING_WEB_HELP = None

        return MainAgentResult(
            handled=True,
            text=(
                "I couldn't perform that through my "
                "current local capabilities."
            ),
            state="needs_clarification",
            intent="action_error",
            confidence=1.0,
        )


    return _adapt_agent_reply(
        reply,
        routed,
    )


def get_main_agent():
    return _AGENT

