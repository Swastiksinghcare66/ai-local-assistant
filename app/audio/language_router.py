from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageDecision:
    language: str
    confidence: float
    reason: str


class LanguageRouter:
    """
    SIA conversation-language router.

    Priority order:
        1. Explicit user language request
        2. Hinglish-primary policy lock (when follow_user_language=False)
        3. Script / lexical detection (when follow_user_language=True)
        4. Current conversation language for short acknowledgements
        5. Configured default language

    Important:
        Hinglish-primary does NOT block explicit language overrides.
        Example:
            "Explain RAG"            -> hinglish
            "Explain RAG in English" -> english
            "हिंदी में बताओ"          -> hindi
    """

    _VALID_LANGUAGES = {"hinglish", "hindi", "english"}

    _SHORT_ACKS = {
        "ok",
        "okay",
        "yes",
        "yeah",
        "yep",
        "yup",
        "no",
        "nope",
        "hmm",
        "hm",
        "right",
        "correct",
        "sure",
        "fine",
        "good",
        "great",
        "thanks",
        "thank you",
        "haan",
        "han",
        "ha",
        "nahi",
        "nah",
        "achha",
        "acha",
        "theek",
        "thik",
    }

    _ROMAN_HINDI_MARKERS = {
        "aap",
        "ab",
        "abhi",
        "acha",
        "achha",
        "aur",
        "bata",
        "batao",
        "batana",
        "bol",
        "bolo",
        "chahiye",
        "dekho",
        "dekh",
        "dekhte",
        "do",
        "hai",
        "hain",
        "ho",
        "hoga",
        "hogi",
        "hua",
        "hui",
        "ka",
        "kar",
        "karo",
        "karenge",
        "karke",
        "ke",
        "ki",
        "kya",
        "kyun",
        "kyu",
        "kaise",
        "kitna",
        "kitni",
        "kitne",
        "ko",
        "le",
        "liye",
        "mera",
        "meri",
        "mere",
        "mein",
        "me",
        "mujhe",
        "nahi",
        "nahin",
        "pe",
        "phir",
        "raha",
        "rahi",
        "rahe",
        "samjha",
        "samjhao",
        "sakta",
        "sakti",
        "se",
        "sirf",
        "thoda",
        "thodi",
        "tum",
        "to",
        "wala",
        "wali",
        "ye",
        "yeh",
    }

    # Explicit requests are intentionally checked BEFORE the Hinglish-primary
    # lock. This is the bug fix for FOLLOW_USER_LANGUAGE=False.
    _ENGLISH_REQUEST_PATTERNS = (
        r"\bin\s+english\b",
        r"\benglish\s+only\b",
        r"\bonly\s+english\b",
        r"\buse\s+english\b",
        r"\bspeak\s+(?:in\s+)?english\b",
        r"\breply\s+(?:in\s+)?english\b",
        r"\banswer\s+(?:in\s+)?english\b",
        r"\brespond\s+(?:in\s+)?english\b",
        r"\benglish\s+(?:me|mein)\b",
        r"\benglish\s+language\b",
        r"\btranslate\s+(?:it\s+)?(?:to|into)\s+english\b",
    )

    _HINGLISH_REQUEST_PATTERNS = (
        r"\bin\s+hinglish\b",
        r"\bhinglish\s+only\b",
        r"\bonly\s+hinglish\b",
        r"\buse\s+hinglish\b",
        r"\bspeak\s+(?:in\s+)?hinglish\b",
        r"\breply\s+(?:in\s+)?hinglish\b",
        r"\banswer\s+(?:in\s+)?hinglish\b",
        r"\brespond\s+(?:in\s+)?hinglish\b",
        r"\bhinglish\s+(?:me|mein)\b",
    )

    _HINDI_REQUEST_PATTERNS = (
        r"\bin\s+hindi\b",
        r"\bhindi\s+only\b",
        r"\bonly\s+hindi\b",
        r"\buse\s+hindi\b",
        r"\bspeak\s+(?:in\s+)?hindi\b",
        r"\breply\s+(?:in\s+)?hindi\b",
        r"\banswer\s+(?:in\s+)?hindi\b",
        r"\brespond\s+(?:in\s+)?hindi\b",
        r"\bhindi\s+(?:me|mein)\b",
        r"\btranslate\s+(?:it\s+)?(?:to|into)\s+hindi\b",
    )

    def __init__(
        self,
        default_language: str = "hinglish",
        follow_user_language: bool = True,
    ):
        default = str(default_language or "hinglish").strip().lower()
        if default not in self._VALID_LANGUAGES:
            default = "hinglish"

        self.default_language = default
        self.follow_user_language = bool(follow_user_language)
        self.current_language = default

    @staticmethod
    def _clean(text: str) -> str:
        value = str(text or "").strip().lower()
        value = value.replace("’", "'")
        value = re.sub(r"\s+", " ", value)
        return value

    @staticmethod
    def _has_devanagari(text: str) -> bool:
        return bool(re.search(r"[\u0900-\u097F]", str(text or "")))

    @staticmethod
    def _has_latin(text: str) -> bool:
        return bool(re.search(r"[A-Za-z]", str(text or "")))

    @classmethod
    def _matches_any(cls, text: str, patterns) -> bool:
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)

    @classmethod
    def _explicit_language_request(cls, text: str) -> LanguageDecision | None:
        clean = cls._clean(text)

        # Natural-script explicit Hindi requests.
        devanagari_hindi_request = (
            "हिंदी में" in clean
            or "हिन्दी में" in clean
            or "हिंदी मे" in clean
            or "हिन्दी मे" in clean
            or "सिर्फ हिंदी" in clean
            or "केवल हिंदी" in clean
        )

        # Natural-script explicit English requests.
        devanagari_english_request = (
            "इंग्लिश में" in clean
            or "अंग्रेजी में" in clean
            or "अंग्रेज़ी में" in clean
            or "इंग्लिश मे" in clean
        )

        if cls._matches_any(clean, cls._ENGLISH_REQUEST_PATTERNS) or devanagari_english_request:
            return LanguageDecision(
                language="english",
                confidence=1.0,
                reason="explicit_english_request",
            )

        if cls._matches_any(clean, cls._HINGLISH_REQUEST_PATTERNS):
            return LanguageDecision(
                language="hinglish",
                confidence=1.0,
                reason="explicit_hinglish_request",
            )

        if cls._matches_any(clean, cls._HINDI_REQUEST_PATTERNS) or devanagari_hindi_request:
            return LanguageDecision(
                language="hindi",
                confidence=1.0,
                reason="explicit_hindi_request",
            )

        return None

    @classmethod
    def _roman_hindi_score(cls, text: str) -> tuple[int, int]:
        clean = cls._clean(text)
        tokens = re.findall(r"[a-z]+", clean)

        if not tokens:
            return 0, 0

        hits = sum(1 for token in tokens if token in cls._ROMAN_HINDI_MARKERS)
        return hits, len(tokens)

    def _classify(
        self,
        text: str,
        *,
        update_state: bool,
    ) -> LanguageDecision:
        clean = self._clean(text)

        if not clean:
            decision = LanguageDecision(
                language=self.current_language or self.default_language,
                confidence=0.55,
                reason="empty_keep_current",
            )
            if update_state:
                self.current_language = decision.language
            return decision

        # ========================================================
        # 1. EXPLICIT OVERRIDE — ALWAYS WINS
        # ========================================================
        explicit = self._explicit_language_request(clean)
        if explicit is not None:
            if update_state:
                self.current_language = explicit.language
            return explicit

        # ========================================================
        # 2. HINGLISH-PRIMARY / FIXED DEFAULT POLICY
        # ========================================================
        #
        # FOLLOW_USER_LANGUAGE=False means:
        #   ordinary English input does not force English output.
        #
        # It does NOT mean explicit requests like "in English" are ignored.
        #
        if not self.follow_user_language:
            decision = LanguageDecision(
                language=self.default_language,
                confidence=0.90,
                reason="preferred_default",
            )
            if update_state:
                self.current_language = decision.language
            return decision

        # ========================================================
        # 3. FOLLOW USER LANGUAGE
        # ========================================================
        has_dev = self._has_devanagari(clean)
        has_latin = self._has_latin(clean)

        if has_dev and has_latin:
            decision = LanguageDecision(
                language="hinglish",
                confidence=0.99,
                reason="mixed_script",
            )
            if update_state:
                self.current_language = decision.language
            return decision

        if has_dev:
            decision = LanguageDecision(
                language="hindi",
                confidence=0.96,
                reason="devanagari",
            )
            if update_state:
                self.current_language = decision.language
            return decision

        # Short conversational continuations keep the current language.
        short_key = re.sub(r"[^a-z\s']", " ", clean)
        short_key = re.sub(r"\s+", " ", short_key).strip()

        if short_key in self._SHORT_ACKS or len(short_key.split()) <= 1:
            decision = LanguageDecision(
                language=self.current_language or self.default_language,
                confidence=0.70,
                reason="short_ack_keep_previous",
            )
            if update_state:
                self.current_language = decision.language
            return decision

        roman_hits, latin_count = self._roman_hindi_score(clean)

        # One strong Hindi marker is enough in short code-switched commands;
        # longer sentences require proportionally more evidence.
        if roman_hits >= 2 or (
            roman_hits >= 1
            and latin_count <= 7
        ):
            decision = LanguageDecision(
                language="hinglish",
                confidence=0.98,
                reason="roman_hinglish_markers",
            )
            if update_state:
                self.current_language = decision.language
            return decision

        if has_latin:
            decision = LanguageDecision(
                language="english",
                confidence=0.88,
                reason="latin_english",
            )
            if update_state:
                self.current_language = decision.language
            return decision

        decision = LanguageDecision(
            language=self.current_language or self.default_language,
            confidence=0.60,
            reason="ambiguous_keep_current",
        )

        if update_state:
            self.current_language = decision.language

        return decision

    def observe_user_text(self, text: str) -> LanguageDecision:
        """Classify user speech and update the active conversation language."""
        return self._classify(
            text,
            update_state=True,
        )

    def classify_output(self, text: str) -> LanguageDecision:
        """
        Classify generated/fixed response text without changing conversation
        state. TTS routing can use this safely.
        """
        return self._classify(
            text,
            update_state=False,
        )

    def force_language(self, language: str) -> None:
        """Optional compatibility helper for callers that set language directly."""
        value = str(language or "").strip().lower()
        if value in self._VALID_LANGUAGES:
            self.current_language = value

    def reset(self) -> None:
        self.current_language = self.default_language

    def llm_instruction(
        self,
        language: str | None = None,
    ) -> str:
        selected = str(
            language
            or self.current_language
            or self.default_language
        ).strip().lower()

        if selected == "english":
            return (
                "LANGUAGE RULE: Reply naturally in English. "
                "Do not switch to Hindi or Hinglish unless the user asks."
            )

        if selected == "hindi":
            return (
                "LANGUAGE RULE: Reply naturally in Hindi using Devanagari. "
                "Keep standard technical names, acronyms, product names, and "
                "widely used English technical terms when translating them "
                "would sound unnatural."
            )

        return (
            "LANGUAGE RULE: Reply in natural Indian Hinglish. "
            "Use conversational Hindi grammar and everyday Hindi naturally, "
            "preferably in Devanagari where appropriate, while keeping common "
            "English technical words, product names, acronyms, and engineering "
            "terms in English. Do not translate standard technical terms into "
            "formal textbook Hindi. Keep the tone concise and conversational. "
            "Example style: 'हाँ, GPU का temperature थोड़ा high है. "
            "पहले cooling check करते हैं.'"
        )
