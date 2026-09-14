from __future__ import annotations

import asyncio
import hmac
import re
import unicodedata
from datetime import datetime

from app.config import (
    ASSISTANT_NAME,
    DEFAULT_ASSISTANT_MODE,
    MODE_ACTIVE,
    MODE_OFFLINE,
    MODE_STANDBY,
    OFFLINE_PHRASES,
    SHUTDOWN_CANCEL_PHRASES,
    SHUTDOWN_CANCEL_RESPONSE,
    SHUTDOWN_FAILURE_RESPONSE,
    SHUTDOWN_MAX_ATTEMPTS,
    SHUTDOWN_RETRY_RESPONSE,
    SHUTDOWN_SUCCESS_RESPONSE,
    SHUTDOWN_VERIFICATION_CODE,
    SHUTDOWN_VERIFICATION_ENABLED,
    SHUTDOWN_VERIFY_PROMPT,
    STANDBY_PHRASES,
    STARTUP_GREETING_ENABLED,
    STARTUP_INIT_TEXT,
    STARTUP_READY_TEXT,
    STARTUP_SPEECH_ENABLED,
    USER_NAME,
)

from app.pipeline.voice_pipeline import VoicePipeline, VoiceTiming
from app.conversation_clarifier import ConversationClarifier


def normalize_text(text: str) -> str:
    """Unicode-safe command normalization; preserves Hindi vowel marks."""
    text = str(text or "").lower().replace("’", "'").strip()

    kept = []
    for char in text:
        category = unicodedata.category(char)
        if (
            char.isalnum()
            or char.isspace()
            or char == "'"
            or category.startswith("M")  # combining marks, e.g. Devanagari matras
        ):
            kept.append(char)
        else:
            kept.append(" ")

    text = "".join(kept)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def matches_control_phrase(text: str, phrases) -> bool:
    normalized = normalize_text(text)

    if not normalized:
        return False

    for phrase in phrases:
        candidate = normalize_text(phrase)

        if candidate and normalized == candidate:
            return True

    return False


def build_startup_greeting() -> str:
    now = datetime.now()

    if now.hour < 12:
        daypart = "morning"
    elif now.hour < 17:
        daypart = "afternoon"
    else:
        daypart = "evening"

    return f"Good {daypart}, {USER_NAME}. I'm ready."


# ============================================================
# DETERMINISTIC LOCAL FAST INTENTS
# ============================================================
# These never need Qwen or the web. Keeping them here also makes common
# Hinglish commands deterministic even when the general agent router expects
# English phrasing.

_TIME_PATTERNS = (
    r"^what time is it$",
    r"^what(?:'s| is) the time$",
    r"^current time$",
    r"^tell me the time$",
    r"^time kya hai$",
    r"^time kya ho raha hai$",
    r"^abhi time kya hai$",
    r"^abhi kya time hai$",
    r"^kitna time hua$",
    r"^kitne baje hain$",
    r"^kitne baje hai$",
    r"^abhi kitne baje hain$",
    r"^abhi kitne baje hai$",
    r"^टाइम क्या है$",
    r"^टाइम क्या हो रहा है$",
    r"^अभी टाइम क्या है$",
    r"^अभी कितने बजे हैं$",
    r"^कितने बजे हैं$",
    r"^समय क्या है$",
    r"^अभी समय क्या है$",
)

_DATE_PATTERNS = (
    r"^what(?:'s| is) today'?s date$",
    r"^what is the date$",
    r"^current date$",
    r"^today'?s date$",
    r"^aaj date kya hai$",
    r"^aaj ki date kya hai$",
    r"^date kya hai$",
    r"^आज डेट क्या है$",
    r"^आज की डेट क्या है$",
    r"^आज तारीख क्या है$",
)


def _detect_local_fast_intent(text: str) -> str | None:
    normalized = normalize_text(text)
    if not normalized:
        return None

    # Avoid turning educational questions such as "time complexity kya hai"
    # into a clock request. Only the explicit patterns above are accepted.
    if any(re.fullmatch(pattern, normalized) for pattern in _TIME_PATTERNS):
        return "time"

    if any(re.fullmatch(pattern, normalized) for pattern in _DATE_PATTERNS):
        return "date"

    return None


def _conversation_language(pipeline: VoicePipeline) -> str:
    router = getattr(pipeline, "language_router", None)
    language = str(getattr(router, "current_language", "hinglish") or "hinglish").lower()
    return language if language in {"hinglish", "hindi", "english"} else "hinglish"


def _standby_response_for(pipeline: VoicePipeline) -> str:
    language = _conversation_language(pipeline)
    if language == "english":
        return "Okay. Going to standby."
    if language == "hindi":
        return "ठीक है, स्टैंडबाय पर जा रही हूँ।"
    return "Theek hai, standby pe ja rahi hoon."


def _local_fast_response(pipeline: VoicePipeline, intent: str) -> str:
    now = datetime.now()
    language = _conversation_language(pipeline)

    if intent == "time":
        clock = now.strftime("%I:%M %p").lstrip("0")
        if language == "english":
            return f"It's {clock}."
        if language == "hindi":
            return f"अभी समय {clock} है।"
        return f"Abhi time {clock} hai."

    if intent == "date":
        date_text = f"{now.day} {now.strftime('%B %Y')}"
        if language == "english":
            return f"Today is {date_text}."
        if language == "hindi":
            return f"आज {date_text} है।"
        return f"Aaj {date_text} hai."

    raise ValueError(f"Unknown local fast intent: {intent}")


_NUMBER_WORDS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "to": "2",
    "too": "2",
    "three": "3",
    "four": "4",
    "for": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "ate": "8",
    "nine": "9",
}



# ============================================================
# WEB SEARCH CONSENT
# ============================================================

WEB_SEARCH_CONFIRMATION_ENABLED = True
WEB_SEARCH_CONFIRMATION_PROMPT = (
    "That needs a web search. Should I search it? "
    "Say yes to search, or no to skip."
)
WEB_SEARCH_REJECTED_RESPONSE = "Okay, I won't search the web."
WEB_SEARCH_CONFIRMATION_RETRY = "Should I search the web for that? Say yes or no."


class WebSearchConsent:
    """Hold exactly one pending web query until the user approves or rejects it."""

    def __init__(self):
        self.pending_query: str | None = None
        self.retry_count = 0

    @property
    def pending(self) -> bool:
        return bool(self.pending_query)

    def begin(self, query: str) -> None:
        self.pending_query = str(query or "").strip() or None
        self.retry_count = 0

    def clear(self) -> None:
        self.pending_query = None
        self.retry_count = 0

    def consume(self) -> str:
        query = str(self.pending_query or "").strip()
        self.clear()
        return query


_WEB_YES_PHRASES = {
    "yes",
    "yeah",
    "yep",
    "yup",
    "sure",
    "okay",
    "ok",
    "go ahead",
    "please",
    "please do",
    "do it",
    "proceed",
    "search",
    "search it",
    "search it please",
    "yes search",
    "yes search it",
    "yeah search it",
    "okay search",
    "okay search it",
    "ok search",
    "ok search it",
    "search the web",
    "search online",
    "haan",
    "han",
    "haan karo",
    "haan search karo",
    "search kar do",
    "kar do",
    "हाँ",
    "हाँ करो",
    "सर्च कर दो",
}

_WEB_NO_PHRASES = {
    "no",
    "nope",
    "nah",
    "cancel",
    "cancel it",
    "don't",
    "dont",
    "do not",
    "don't search",
    "dont search",
    "do not search",
    "no search",
    "no don't search",
    "no dont search",
    "leave it",
    "skip it",
    "not now",
    "reject",
    "reject it",
    "nahi",
    "nahin",
    "mat karo",
    "search mat karo",
    "nahi search karo",
    "नहीं",
    "मत करो",
    "सर्च मत करो",
}


def _web_consent_answer(text: str) -> str | None:
    """Return 'yes', 'no', or None for an ambiguous confirmation reply."""

    normalized = normalize_text(text)

    if not normalized:
        return None

    if normalized in _WEB_YES_PHRASES:
        return "yes"

    if normalized in _WEB_NO_PHRASES:
        return "no"

    yes_prefixes = (
        "yes ",
        "yeah ",
        "yep ",
        "sure ",
        "go ahead ",
        "please search",
        "search it",
    )

    no_prefixes = (
        "no ",
        "nope ",
        "don't ",
        "dont ",
        "do not ",
        "cancel ",
        "reject ",
    )

    if normalized.startswith(yes_prefixes):
        return "yes"

    if normalized.startswith(no_prefixes):
        return "no"

    return None


def _looks_like_math_query(text: str) -> bool:
    normalized = normalize_text(text)

    if not normalized:
        return False

    math_words = {
        "plus", "minus", "times", "multiplied", "divide", "divided",
        "percent", "percentage", "square", "cube", "root", "calculate",
    }

    tokens = set(normalized.split())

    if tokens & math_words:
        return True

    stripped = re.sub(
        r"^(?:what is|what's|calculate|compute)\s+",
        "",
        normalized,
    )

    return bool(
        stripped
        and re.fullmatch(r"[0-9\s+\-*/().%]+", stripped)
    )


def _is_local_information_query(text: str) -> bool:
    normalized = normalize_text(text)

    if not normalized:
        return False

    if _detect_local_fast_intent(text) is not None:
        return True

    local_patterns = (
        r"\b(?:what|tell me|give me|show me)?\s*(?:is\s+)?(?:the\s+)?(?:current\s+)?time\b",
        r"\bwhat(?:'s| is)?\s+(?:today'?s\s+)?date\b",
        r"\bwhat day is it\b",
        r"\btoday'?s date\b",
        r"\bcurrent date\b",
        r"\bsystem status\b",
        r"\bcomputer status\b",
        r"\bpc status\b",
        r"\bbattery(?: status| level| percentage)?\b",
        r"\b(?:cpu|gpu|ram|memory) (?:usage|utilization|status)\b",
        r"\bnetwork status\b",
        r"\brunning processes\b",
        r"\bwhat(?:'s| is) running\b",
    )

    return any(
        re.search(pattern, normalized)
        for pattern in local_patterns
    )


def _is_computer_action_query(text: str) -> bool:
    normalized = normalize_text(text)

    if not normalized:
        return False

    action_prefixes = (
        "open ",
        "launch ",
        "start ",
        "close ",
        "quit ",
        "exit ",
        "kill ",
        "run ",
        "type ",
        "press ",
        "click ",
        "set volume",
        "increase volume",
        "decrease volume",
        "turn volume",
        "set brightness",
        "increase brightness",
        "decrease brightness",
        "mute ",
        "unmute ",
    )

    return normalized.startswith(action_prefixes)


def _is_casual_or_personal_query(text: str) -> bool:
    normalized = normalize_text(text)

    if not normalized:
        return True

    exact = {
        "hi", "hello", "hey", "hey sia", "good morning",
        "good afternoon", "good evening", "good night",
        "how are you", "how are you today", "what's up", "whats up",
        "who are you", "what are you", "what is your name",
        "tell me a joke", "say something funny", "tell me a story",
        "thank you", "thanks", "thanks a lot", "okay", "ok",
        "i am sad", "i'm sad", "im sad", "i am happy", "i'm happy",
    }

    if normalized in exact:
        return True

    casual_prefixes = (
        "how do you feel",
        "what do you think",
        "do you like",
        "can we talk",
        "let's talk",
        "lets talk",
        "i feel ",
        "i am feeling ",
        "i'm feeling ",
        "im feeling ",
    )

    return normalized.startswith(casual_prefixes)


def requires_web_confirmation(text: str) -> bool:
    """
    Consent preflight for the current unified-router policy.

    route_main_agent() performs retrieval immediately for web_info, so the
    confirmation must happen before that function is called. This preflight
    intentionally covers explicit web requests, current-information requests,
    and ordinary factual questions while excluding local PC data, PC actions,
    math, and casual conversation.
    """

    if not WEB_SEARCH_CONFIRMATION_ENABLED:
        return False

    normalized = normalize_text(text)

    if not normalized:
        return False

    if _is_local_information_query(normalized):
        return False

    if _is_computer_action_query(normalized):
        return False

    if _looks_like_math_query(normalized):
        return False

    if _is_casual_or_personal_query(normalized):
        return False

    explicit_web_markers = (
        "search ",
        "search for ",
        "search the web",
        "web search",
        "google ",
        "look up ",
        "lookup ",
        "find online",
        "find on the internet",
        "browse ",
        "check online",
        "check the web",
        "on the internet",
        "from the internet",
    )

    if (
        normalized.startswith(explicit_web_markers)
        or any(marker in normalized for marker in explicit_web_markers)
    ):
        return True

    current_markers = (
        "latest",
        "current",
        "currently",
        "recent",
        "recently",
        "today",
        "tonight",
        "this week",
        "this month",
        "news",
        "weather",
        "score",
        "price",
        "stock",
        "president",
        "prime minister",
        "ceo",
    )

    if any(
        re.search(rf"\b{re.escape(marker)}\b", normalized)
        for marker in current_markers
    ):
        return True

    factual_prefixes = (
        "who is ",
        "who was ",
        "who are ",
        "what is ",
        "what are ",
        "what was ",
        "where is ",
        "where are ",
        "when is ",
        "when was ",
        "which ",
        "how many ",
        "how much ",
        "how does ",
        "how do ",
        "why does ",
        "why do ",
        "define ",
        "explain ",
        "tell me about ",
        "tell me who ",
        "tell me what ",
        "give me information about ",
    )

    return normalized.startswith(factual_prefixes)

def _private_code_from_transcript(text: str) -> str:
    text = normalize_text(text)
    digit_groups = re.findall(r"\d+", text)

    if digit_groups:
        return "".join(digit_groups)

    output = []

    for token in text.split():
        value = _NUMBER_WORDS.get(token)

        if value is not None:
            output.append(value)

    return "".join(output)


async def verify_shutdown(pipeline: VoicePipeline) -> bool:
    if not SHUTDOWN_VERIFICATION_ENABLED:
        return True

    await pipeline.speak_text(
        SHUTDOWN_VERIFY_PROMPT,
        style="serious",
    )

    expected = str(
        SHUTDOWN_VERIFICATION_CODE
    ).strip()

    for attempt in range(
        1,
        SHUTDOWN_MAX_ATTEMPTS + 1,
    ):
        print(
            "[SECURITY] Waiting for shutdown verification..."
        )

        capture = await asyncio.to_thread(
            pipeline.listen_active
        )

        # Private security path:
        # never print, log, store in history, or send to the LLM.
        raw_private = await asyncio.to_thread(
            pipeline.transcribe_private_capture,
            capture,
        )

        if matches_control_phrase(
            raw_private,
            SHUTDOWN_CANCEL_PHRASES,
        ):
            await pipeline.speak_text(
                SHUTDOWN_CANCEL_RESPONSE,
                style="serious",
            )
            return False

        candidate = _private_code_from_transcript(
            raw_private
        )

        if hmac.compare_digest(
            candidate,
            expected,
        ):
            return True

        remaining = (
            SHUTDOWN_MAX_ATTEMPTS
            - attempt
        )

        if remaining > 0:
            await pipeline.speak_text(
                SHUTDOWN_RETRY_RESPONSE,
                style="serious",
            )

    await pipeline.speak_text(
        SHUTDOWN_FAILURE_RESPONSE,
        style="serious",
    )

    return False


async def process_active_command(
    pipeline: VoicePipeline,
    transcript: str,
    timing: VoiceTiming | None = None,
    clarifier: ConversationClarifier | None = None,
    web_consent: WebSearchConsent | None = None,
    web_approved: bool = False,
) -> str:
    transcript = str(
        transcript or ""
    ).strip()

    if not transcript:
        return MODE_ACTIVE

    # --------------------------------------------------------
    # PENDING WEB CONSENT
    # --------------------------------------------------------
    #
    # A confirmation reply must be consumed before the normal clarifier,
    # otherwise a bare "yes"/"no" can be merged into an unrelated pending
    # clarification. Security/state commands remain authoritative below.
    #

    if web_consent is not None and web_consent.pending:
        answer = _web_consent_answer(transcript)

        if answer == "yes":
            approved_query = web_consent.consume()

            print()
            print("[WEB CONSENT] approved")
            print(f"[WEB CONSENT] query={approved_query!r}")

            if not approved_query:
                return MODE_ACTIVE

            return await process_active_command(
                pipeline,
                approved_query,
                timing=timing,
                clarifier=None,
                web_consent=web_consent,
                web_approved=True,
            )

        if answer == "no":
            rejected_query = web_consent.consume()

            print()
            print("[WEB CONSENT] rejected")
            print(f"[WEB CONSENT] query={rejected_query!r}")

            await pipeline.speak_text(
                WEB_SEARCH_REJECTED_RESPONSE,
                style="warm_conversational",
            )

            return MODE_ACTIVE

        normalized_reply = normalize_text(transcript)

        # Let explicit assistant-state/security commands replace the pending
        # web request instead of trapping the user inside a yes/no prompt.
        if (
            matches_control_phrase(transcript, STANDBY_PHRASES)
            or matches_control_phrase(transcript, OFFLINE_PHRASES)
        ):
            web_consent.clear()

        # A substantive new request replaces the pending web request. Short
        # uncertain replies such as "maybe" are asked again instead.
        elif len(normalized_reply.split()) >= 3:
            print()
            print("[WEB CONSENT] pending search replaced by new request")
            web_consent.clear()

        else:
            web_consent.retry_count += 1

            print()
            print(
                "[WEB CONSENT] ambiguous reply "
                f"{transcript!r}; asking again"
            )

            await pipeline.speak_text(
                WEB_SEARCH_CONFIRMATION_RETRY,
                style="warm_conversational",
            )

            return MODE_ACTIVE

    # --------------------------------------------------------
    # AUTHORITATIVE ASSISTANT STATE COMMANDS
    # --------------------------------------------------------
    # These are evaluated before clarification/LLM routing. SIA stays ACTIVE
    # indefinitely unless one of these explicit commands is spoken.
    if matches_control_phrase(transcript, STANDBY_PHRASES):
        if web_consent is not None:
            web_consent.clear()
        if clarifier is not None and clarifier.pending is not None:
            clarifier.resolve()
        standby_text = _standby_response_for(pipeline)
        print()
        print(f"You: {transcript}")
        print("[STATE COMMAND] explicit sleep/standby")
        await pipeline.speak_text(
            standby_text,
            style="warm_conversational",
        )
        return MODE_STANDBY

    if matches_control_phrase(transcript, OFFLINE_PHRASES):
        if web_consent is not None:
            web_consent.clear()
        if clarifier is not None and clarifier.pending is not None:
            clarifier.resolve()
        print()
        print(f"You: {transcript}")
        verified = await verify_shutdown(pipeline)
        if verified:
            final_text = SHUTDOWN_SUCCESS_RESPONSE.format(user=USER_NAME)
            await pipeline.speak_text(
                final_text,
                style="serious",
            )
            return MODE_OFFLINE
        return MODE_ACTIVE

    # --------------------------------------------------------
    # ZERO-LLM LOCAL FAST PATH
    # --------------------------------------------------------
    local_fast_intent = _detect_local_fast_intent(transcript)
    if local_fast_intent is not None:
        if clarifier is not None and clarifier.pending is not None:
            clarifier.resolve()
        response = _local_fast_response(
            pipeline,
            local_fast_intent,
        )
        print()
        print(f"You: {transcript}")
        print(
            "[LOCAL FAST] "
            f"intent={local_fast_intent} response={response!r}"
        )
        await pipeline.speak_text(
            response,
            style="warm_conversational",
        )
        return MODE_ACTIVE

    # Low-latency clarification layer.
    # Clear queries go straight through with no extra LLM classifier call.
    if clarifier is not None:
        if clarifier.pending is not None:
            transcript = clarifier.merge_answer(
                transcript
            )
            clarifier.resolve()
        else:
            decision = clarifier.evaluate(
                transcript
            )

            if decision.action in {
                "clarify",
                "ask_for_evidence",
                "confirm_assumption",
            }:
                clarifier.begin(
                    transcript,
                    decision.question,
                )

                print(
                    f"[CLARIFIER] action={decision.action} "
                    f"reason={decision.reason} "
                    f"confidence={decision.confidence:.2f}"
                )

                await pipeline.speak_text(
                    decision.question,
                    style="warm_conversational",
                )

                return MODE_ACTIVE

    print()
    print(
        f"You: {transcript}"
    )

    # --------------------------------------------------------
    # WEB SEARCH CONFIRMATION GATE
    # --------------------------------------------------------
    # route_main_agent() starts web retrieval immediately for web_info.
    # Never call it for a web-bound query until the user has approved.

    if (
        not web_approved
        and web_consent is not None
        and requires_web_confirmation(transcript)
    ):
        web_consent.begin(transcript)

        print()
        print("[WEB CONSENT] required")
        print(f"[WEB CONSENT] pending query={transcript!r}")

        await pipeline.speak_text(
            WEB_SEARCH_CONFIRMATION_PROMPT,
            style="warm_conversational",
        )

        return MODE_ACTIVE

    # === SARA PRODUCTION AGENT ROUTER V3 ===
    #
    # Security/state commands above remain authoritative.
    #
    # All other user input first goes through the capability
    # router. Normal conversation falls through unchanged to
    # the existing adaptive Qwen + CosyVoice pipeline.
    #

    agent_result = None

    try:
        from app.agent.main_bridge import route_main_agent

        agent_result = await asyncio.to_thread(
            route_main_agent,
            transcript,
        )

    except Exception as agent_exc:

        print(
            "[PRODUCTION AGENT ERROR] "
            f"{type(agent_exc).__name__}: "
            f"{agent_exc}"
        )

        # Fail open only to normal conversation.
        # Never claim that an action succeeded.
        agent_result = None


    if (
        agent_result is not None
        and agent_result.handled
    ):

        print()

        print(
            "[AGENT RESULT] "
            f"state={agent_result.state} "
            f"intent={agent_result.intent}"
        )

        print(
            f"{ASSISTANT_NAME}: "
            f"{agent_result.text}"
        )


        agent_state = str(
            agent_result.state or ""
        ).lower()


        if agent_state in {
            "failed",
            "unsupported",
            "needs_consent",
            "needs_clarification",
        }:
            voice_style = "serious"

        elif agent_result.intent in {
            "get_system_status",
            "get_running_processes",
            "get_network_status",
        }:
            voice_style = "calm_confident"

        else:
            voice_style = "warm_conversational"


        await pipeline.speak_text(
            agent_result.text,
            style=voice_style,
        )

        return MODE_ACTIVE


    # --------------------------------------------------------
    # NORMAL CONVERSATION FALLBACK
    # --------------------------------------------------------
    #
    # Existing:
    #   adaptive mode
    #   personality
    #   Qwen streaming
    #   CosyVoice
    #   conversation behaviour
    #
    # remain untouched.
    #

    timing = timing or VoiceTiming()

    await pipeline.generate_and_speak(
        transcript=transcript,
        timing=timing,
    )

    return MODE_ACTIVE


async def main_async():
    print()
    print("=" * 72)
    print("SARA")
    print("=" * 72)

    pipeline = VoicePipeline()
    clarifier = ConversationClarifier(
        max_followups=2
    )
    web_consent = WebSearchConsent()

    try:
        # Pipeline intentionally connects CosyVoice BEFORE Qwen warmup.
        await pipeline.initialize()

        # ========================================================
        # SARA SIGNATURE STARTUP EXPERIENCE
        # ========================================================

        if STARTUP_GREETING_ENABLED:

            from app.audio.startup_experience import (
                build_dynamic_startup_greeting,
                play_startup_soundscape,
            )

            greeting = (
                build_dynamic_startup_greeting(
                    USER_NAME
                )
            )

            print()
            print(
                f"[STARTUP EXPERIENCE] {greeting}"
            )

            # Start the time-aware Sara signature tune.
            play_startup_soundscape()

            # Give the musical motif a short lead-in.
            await asyncio.sleep(
                0.68
            )

            # Startup greeting is intentionally energetic.
            await pipeline.speak_text(
                greeting,
                style="energetic_friendly",
                wait_for_playback=True,
            )

        mode = DEFAULT_ASSISTANT_MODE

        print()
        print("=" * 72)
        print(
            f"SARA MODE: {mode.upper()}"
        )
        print("=" * 72)

        while mode != MODE_OFFLINE:

            if mode == MODE_STANDBY:
                pipeline.set_state("standby")
                print()
                print(
                    "[STATE] STANDBY"
                )

                capture = await asyncio.to_thread(
                    pipeline.listen
                )

                if capture is None:
                    continue

                timing = VoiceTiming()

                transcript = await asyncio.to_thread(
                    pipeline.transcribe_capture,
                    capture,
                    timing,
                    True,
                )

                mode = MODE_ACTIVE

                print(
                    "[STATE] ACTIVE"
                )

                if transcript:
                    mode = await process_active_command(
                        pipeline,
                        transcript,
                        timing,
                        clarifier,
                        web_consent,
                    )

                continue

            if mode == MODE_ACTIVE:
                print()
                print(
                    "[STATE] ACTIVE - listening"
                )

                pipeline.set_state("active_wait")

                # A real barge-in may already have been transcribed during
                # backchannel classification. Reuse that text to avoid a second
                # STT inference.
                capture = pipeline.pop_barge_in_capture()
                pending_text = pipeline.pop_barge_in_text()

                timing = VoiceTiming()

                if capture is None:
                    pipeline.set_state("listening")
                    capture = await asyncio.to_thread(
                        pipeline.listen_active,
                        pipeline.active_session_timeout,
                    )

                # Internal listen cycle timed out with no speech. This is NOT
                # a sleep event. SIA remains ACTIVE forever until the user says
                # an explicit sleep/standby command.
                if capture is None:
                    print(
                        "[STATE] ACTIVE idle cycle -> ACTIVE "
                        "(wake word still not required)"
                    )
                    pipeline.set_state("active_wait")
                    continue

                if pending_text:
                    timing.speech_end = getattr(
                        capture,
                        "speech_end",
                        None,
                    )
                    timing.capture_end = getattr(
                        capture,
                        "capture_end",
                        None,
                    )
                    transcript = pending_text
                else:
                    transcript = await asyncio.to_thread(
                        pipeline.transcribe_capture,
                        capture,
                        timing,
                        True,
                    )

                mode = await process_active_command(
                    pipeline,
                    transcript,
                    timing,
                    clarifier,
                    web_consent,
                )

                continue

            print(
                f"[STATE ERROR] Unknown mode: {mode}"
            )

            pipeline.set_state("standby")
            mode = MODE_STANDBY

    finally:
        print()
        print(
            "[SARA] Closing..."
        )

        await pipeline.close()

        print()
        print("=" * 72)
        print("SARA OFFLINE")
        print("=" * 72)


def main():
    try:
        asyncio.run(
            main_async()
        )
    except KeyboardInterrupt:
        print()
        print(
            "[SARA] Interrupted from keyboard."
        )


if __name__ == "__main__":
    main()
