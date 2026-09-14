"""
Sara adaptive conversation-state engine.

Goals:
- no second LLM call
- current-turn dominance
- mixed-emotion support
- conversational-act detection
- topic/mood shift recovery
- anti-repetition guidance
- backward compatibility with get_mode() and build()
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import re
from typing import Iterable

from app.prompts import SYSTEM_PROMPT, ADAPTIVE_PROMPTS


@dataclass
class AdaptiveState:
    mode: str = "default"
    primary_emotion: str = "neutral"
    secondary_emotion: str = "neutral"
    confidence: float = 0.0
    valence: float = 0.0
    arousal: float = 0.25

    sadness: float = 0.0
    anxiety: float = 0.0
    anger: float = 0.0
    frustration: float = 0.0
    excitement: float = 0.0
    relief: float = 0.0
    fatigue: float = 0.0
    affection: float = 0.0
    embarrassment: float = 0.0
    playfulness: float = 0.0

    seriousness: float = 0.2
    shyness: float = 0.32
    energy: float = 0.35
    directness: float = 0.55
    humor_level: int = 0
    laugh_allowed: bool = False

    technical_intent: bool = False
    debugging_intent: bool = False
    teaching_intent: bool = False
    decision_intent: bool = False
    advice_request: bool = False
    venting: bool = False
    question: bool = False
    greeting: bool = False
    gratitude: bool = False
    compliment: bool = False
    teasing: bool = False
    joke: bool = False
    celebration: bool = False
    disagreement: bool = False
    correction: bool = False
    apology: bool = False
    affectionate: bool = False
    topic_shift: bool = False

    response_strategy: str = "answer_naturally"
    voice_style: str = "warm_conversational"

    def to_dict(self):
        return asdict(self)


class PromptBuilder:
    # ------------------------------------------------------------------
    # Lexical cues. Boundary-aware matching is used everywhere so "ai"
    # never matches "drained".
    # ------------------------------------------------------------------

    TECHNICAL_TERMS = {
        "code", "python", "cpp", "c++", "java", "javascript", "function",
        "class", "compiler", "compile", "runtime", "exception", "traceback",
        "error", "bug", "api", "server", "client", "websocket", "fastapi",
        "ollama", "ai", "machine learning", "ml", "llm", "model",
        "inference", "token", "context", "embedding", "rag", "transformer",
        "qwen", "cosyvoice", "parakeet", "tts", "stt", "vllm", "tensorrt",
        "cuda", "gpu", "cpu", "vram", "latency", "ttfa", "rtf", "esp32",
        "esp32-s3", "arduino", "microcontroller", "sensor", "relay", "gpio",
        "uart", "spi", "i2c", "i2s", "pwm", "mosfet", "nmos", "pmos",
        "cmos", "transistor", "amplifier", "voltage", "current", "resistance",
        "impedance", "modulation", "demodulation", "fsk", "psk", "bpsk",
        "qam", "antenna", "filter", "microwave", "awr", "signal",
        "frequency", "bandwidth", "equation", "formula", "calculate",
        "calculation", "algorithm", "throughput", "circuit", "schematic",
        "linux", "wsl", "windows", "firmware", "hardware", "software",
    }

    DEBUG_TERMS = {
        "error", "exception", "traceback", "failed", "failure", "not working",
        "doesn't work", "does not work", "won't work", "wont work", "crash",
        "crashed", "lag", "lagging", "stutter", "stuttering", "slow", "issue",
        "problem", "fix", "debug", "wrong output", "unexpected", "not responding",
        "keeps failing", "still failing", "still not working", "broke", "broken",
    }

    TEACHING_TERMS = {
        "teach me", "explain", "explain from basics", "help me understand",
        "how does", "how do", "what is", "why does", "why do", "concept",
        "understand", "learn", "step by step", "from basics", "eli5",
    }

    DECISION_TERMS = {
        "which is better", "which one", "which should", "what should i choose",
        "what should i use", "should i use", "should i choose", "recommend",
        "recommendation", "best option", "better option", "compare", "comparison",
        "worth it", "go with", "pick one", "choose between",
    }

    CONCISE_TERMS = {
        "short answer", "briefly", "in short", "just answer", "only answer",
        "one line", "one sentence", "concise", "quick answer", "just tell me",
    }

    DETAILED_TERMS = {
        "in detail", "detailed", "complete explanation", "explain everything",
        "deep explanation", "full explanation", "complete calculation", "all details",
        "thoroughly", "everything including", "complete derivation",
    }

    SERIOUS_TERMS = {
        "serious", "seriously", "important", "urgent", "emergency", "critical",
        "danger", "dangerous", "security", "shutdown", "power down",
    }

    SADNESS_CUES = {
        "sad", "upset", "feeling low", "feel low", "feeling down", "feel down",
        "disappointed", "discouraged", "heartbroken", "miserable", "depressed",
        "i failed", "failed my", "i lost", "rejected", "didn't get selected",
        "did not get selected", "nothing is going right", "bad day", "rough day",
        "awful day", "terrible day", "feel terrible", "feeling terrible",
    }

    ANXIETY_CUES = {
        "anxious", "anxiety", "worried", "worry", "nervous", "panicking", "panic",
        "scared", "afraid", "stressed", "stress", "overwhelmed", "can't stop thinking",
        "cannot stop thinking", "what if", "tense",
    }

    ANGER_CUES = {
        "angry", "furious", "pissed", "hate this", "i hate", "mad at", "rage",
        "screw this", "fuck this", "fucking", "bullshit",
    }

    FRUSTRATION_CUES = {
        "annoying", "annoyed", "frustrating", "frustrated", "driving me crazy",
        "fed up", "damn", "shit", "why isn't", "why is this not", "still not working",
        "again not working", "still failing", "keeps failing", "keeps breaking",
        "why the hell", "this is stupid", "this is useless",
    }

    FATIGUE_CUES = {
        "tired", "exhausted", "drained", "sleepy", "burned out", "burnt out",
        "no energy", "long day", "mentally exhausted", "worn out", "done for today",
    }

    EXCITEMENT_CUES = {
        "excited", "amazing", "awesome", "holy shit", "no way", "let's go",
        "lets go", "yes!", "finally", "it worked", "it works", "got selected",
        "i won", "we won", "passed", "nailed it", "great news", "good news",
        "perfect!", "woo", "yay",
    }

    RELIEF_CUES = {
        "relieved", "thank god", "finally worked", "finally fixed", "at last",
        "glad that's over", "glad thats over", "what a relief",
    }

    AFFECTION_CUES = {
        "love you", "i like you", "miss you", "sweet", "cute", "adorable",
        "you mean a lot", "my sara", "dear sara",
    }

    EMBARRASSMENT_CUES = {
        "embarrassed", "awkward", "that was embarrassing", "i feel stupid",
        "i look stupid", "cringe", "oops", "my bad",
    }

    PLAYFUL_CUES = {
        "lol", "lmao", "haha", "hehe", "😂", "🤣", ":)", ";)", "just kidding",
        "jk", "teasing", "kidding", "funny", "joke",
    }

    GREETING_TERMS = {
        "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
        "good night", "what's up", "whats up", "yo",
    }

    GRATITUDE_TERMS = {
        "thanks", "thank you", "thx", "appreciate it", "appreciate that",
    }

    COMPLIMENT_TERMS = {
        "you're smart", "you are smart", "nice voice", "beautiful voice",
        "you did well", "good job", "well done", "you're good", "you are good",
        "i like your voice", "you're amazing", "you are amazing", "you're cute",
        "you are cute", "you're sweet", "you are sweet",
    }

    ADVICE_TERMS = {
        "what should i do", "what do i do", "tell me what to do", "help me decide",
        "give me advice", "any advice", "how should i handle", "what now",
        "how do i fix", "how can i fix", "what can i do",
    }

    DISAGREEMENT_TERMS = {
        "i disagree", "that's wrong", "thats wrong", "no that's wrong", "no thats wrong",
        "not true", "you're wrong", "you are wrong", "i don't agree", "i dont agree",
    }

    CORRECTION_TERMS = {
        "i meant", "no i mean", "correction", "actually i said", "not that",
        "that's not what i asked", "thats not what i asked", "you misunderstood",
    }

    APOLOGY_TERMS = {
        "sorry", "my bad", "i apologize", "apologies",
    }

    TOPIC_SHIFT_MARKERS = {
        "anyway", "anyways", "by the way", "btw", "moving on", "forget that",
        "leave that", "different question", "another question", "new question",
    }

    # Phrases that became repetitive in prior runs. They are not forbidden
    # absolutely, but the prompt strongly discourages them unless necessary.
    STOCK_SUPPORT_PHRASES = (
        "i'm here for you",
        "im here for you",
        "you're not alone",
        "youre not alone",
        "don't hesitate to reach out",
        "dont hesitate to reach out",
        "you're doing your best",
        "youre doing your best",
        "take care",
        "i'm here with you",
        "im here with you",
    )

    # Recent-user weighting: older context can tint emotion, but current input
    # wins decisively. This is intentionally asymmetric.
    USER_WEIGHTS = (0.08, 0.22, 1.00)

    def __init__(self):
        self.last_state = AdaptiveState()

    # ------------------------------------------------------------------
    # Text helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(text: str) -> str:
        text = str(text or "").lower().replace("’", "'")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _term_matches(text: str, term: str) -> bool:
        term = str(term or "").lower().strip()
        if not term:
            return False
        # Emoji/non-word cues are best handled as simple substring matches.
        if not any(ch.isalnum() for ch in term):
            return term in text
        escaped = re.escape(term)
        if term[0].isalnum():
            escaped = r"(?<!\w)" + escaped
        if term[-1].isalnum():
            escaped = escaped + r"(?!\w)"
        return re.search(escaped, text, flags=re.IGNORECASE) is not None

    @classmethod
    def _contains_any(cls, text: str, terms: Iterable[str]) -> bool:
        return any(cls._term_matches(text, term) for term in terms)

    @staticmethod
    def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _words(text: str) -> set[str]:
        stop = {
            "a", "an", "the", "is", "are", "am", "i", "you", "it", "this", "that",
            "to", "of", "and", "or", "in", "on", "for", "my", "your", "me", "we",
            "be", "do", "does", "did", "was", "were", "have", "has", "had",
        }
        words = set(re.findall(r"[a-z0-9+#-]+", text.lower()))
        return {w for w in words if len(w) > 2 and w not in stop}

    @classmethod
    def _lexical_overlap(cls, a: str, b: str) -> float:
        wa, wb = cls._words(a), cls._words(b)
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / max(1, len(wa | wb))

    @classmethod
    def _is_personal_emotional_disclosure(cls, text: str) -> bool:
        """Distinguish 'I am sad' from 'why do sad songs sound good?'."""
        norm = cls._normalize(text)
        first_person = re.search(
            r"\b(i|i'm|im|i've|ive|me|my|myself|i feel|i felt|feeling)\b",
            norm,
        ) is not None
        self_event = cls._contains_any(norm, {
            "bad day", "rough day", "awful day", "terrible day", "long day",
            "failed my", "i failed", "i lost", "got rejected", "rejected me",
            "didn't get selected", "did not get selected", "nothing is going right",
            "can't take this", "cannot take this", "had enough","it's not good", "its not good", "i'm done", "im done", "i give up", "im giving up"
        })
        return bool(first_person or self_event)

    @staticmethod
    def _get_messages(messages, role=None):
        out = []
        for message in messages or []:
            if not isinstance(message, dict):
                continue
            msg_role = message.get("role")
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            if role is not None and msg_role != role:
                continue
            out.append((msg_role, content))
        return out

    def _latest_user_text(self, messages) -> str:
        for role, content in reversed(self._get_messages(messages)):
            if role == "user":
                return content
        return ""

    def _recent_user_texts(self, messages, limit=3) -> list[str]:
        return [content for role, content in self._get_messages(messages, "user")][-limit:]

    def _recent_assistant_texts(self, messages, limit=3) -> list[str]:
        return [content for role, content in self._get_messages(messages, "assistant")][-limit:]

    # ------------------------------------------------------------------
    # Emotion scoring
    # ------------------------------------------------------------------

    def _score_cues(self, user_texts: list[str], cues: set[str]) -> float:
        selected = user_texts[-3:]
        weights = self.USER_WEIGHTS[-len(selected):]
        score = 0.0
        for text, weight in zip(selected, weights):
            norm = self._normalize(text)
            matches = sum(1 for cue in cues if self._term_matches(norm, cue))
            if matches:
                score += weight * min(1.0, 0.55 + 0.22 * (matches - 1))
        return self._clamp(score)

    def _detect_topic_shift(self, messages, current_text: str, current_technical: bool,
                            current_positive: bool, current_negative: bool) -> bool:
        users = self._recent_user_texts(messages, 3)
        if len(users) < 2:
            return False
        previous = self._normalize(users[-2])
        current = self._normalize(current_text)
        if self._contains_any(current, self.TOPIC_SHIFT_MARKERS):
            return True
        previous_technical = self._contains_any(previous, self.TECHNICAL_TERMS)
        previous_negative = any(
            self._contains_any(previous, cues)
            for cues in (self.SADNESS_CUES, self.ANXIETY_CUES, self.ANGER_CUES,
                         self.FRUSTRATION_CUES, self.FATIGUE_CUES)
        )
        previous_positive = self._contains_any(previous, self.EXCITEMENT_CUES | self.RELIEF_CUES)

        # Strong domain or valence change.
        if current_technical != previous_technical and (current_technical or previous_technical):
            return True
        if current_positive and previous_negative:
            return True
        if current_negative and previous_positive:
            return True

        # Very short conversational resets should not inherit emotional tone.
        if current in self.GRATITUDE_TERMS or current in self.GREETING_TERMS:
            return True

        if current in {
            "who are you", "what are you", "what's your name", "whats your name",
            "tell me your name", "what can you do",
        }:
            return True

        overlap = self._lexical_overlap(previous, current)
        if len(current.split()) >= 4 and overlap < 0.04 and (
            current_technical or previous_technical
        ):
            return True
        return False

    # ------------------------------------------------------------------
    # State inference
    # ------------------------------------------------------------------

    def analyze(self, messages) -> AdaptiveState:
        latest_raw = self._latest_user_text(messages)
        text = self._normalize(latest_raw)
        users = self._recent_user_texts(messages, 3)

        if not text:
            state = AdaptiveState()
            self.last_state = state
            return state

        state = AdaptiveState()

        # Intent / conversational acts use the CURRENT turn first.
        state.technical_intent = self._contains_any(text, self.TECHNICAL_TERMS)
        state.debugging_intent = self._contains_any(text, self.DEBUG_TERMS)
        state.teaching_intent = self._contains_any(text, self.TEACHING_TERMS)
        state.decision_intent = self._contains_any(text, self.DECISION_TERMS)
        state.advice_request = self._contains_any(text, self.ADVICE_TERMS)
        state.question = "?" in latest_raw or bool(re.match(
            r"^(what|why|how|when|where|who|which|can|could|should|would|do|does|did|is|are|am)\b",
            text,
        ))
        state.greeting = text in self.GREETING_TERMS or (
            len(text.split()) <= 4 and self._contains_any(text, self.GREETING_TERMS)
        )
        state.gratitude = self._contains_any(text, self.GRATITUDE_TERMS)
        state.compliment = self._contains_any(text, self.COMPLIMENT_TERMS)
        state.disagreement = self._contains_any(text, self.DISAGREEMENT_TERMS)
        state.correction = self._contains_any(text, self.CORRECTION_TERMS)
        state.apology = self._contains_any(text, self.APOLOGY_TERMS)
        state.affectionate = self._contains_any(text, self.AFFECTION_CUES)
        state.joke = self._contains_any(text, {"joke", "funny", "just kidding", "jk"})
        state.teasing = self._contains_any(text, {"tease", "teasing", "just kidding", "jk"})

        # Emotion scores. Older turns only tint the state.
        state.sadness = self._score_cues(users, self.SADNESS_CUES)
        state.anxiety = self._score_cues(users, self.ANXIETY_CUES)
        state.anger = self._score_cues(users, self.ANGER_CUES)
        state.frustration = self._score_cues(users, self.FRUSTRATION_CUES)
        state.fatigue = self._score_cues(users, self.FATIGUE_CUES)
        state.excitement = self._score_cues(users, self.EXCITEMENT_CUES)
        state.relief = self._score_cues(users, self.RELIEF_CUES)
        state.affection = self._score_cues(users, self.AFFECTION_CUES)
        state.embarrassment = self._score_cues(users, self.EMBARRASSMENT_CUES)
        state.playfulness = self._score_cues(users, self.PLAYFUL_CUES)

        current_negative = any(
            self._contains_any(text, cues)
            for cues in (self.SADNESS_CUES, self.ANXIETY_CUES, self.ANGER_CUES,
                         self.FRUSTRATION_CUES, self.FATIGUE_CUES)
        )
        current_positive = self._contains_any(text, self.EXCITEMENT_CUES | self.RELIEF_CUES)
        personal_negative = bool(
            current_negative
            and self._is_personal_emotional_disclosure(text)
        )

        # Conceptual questions can contain emotion words without expressing the
        # user's own emotion (for example: "why do sad songs sound good?").
        if (state.teaching_intent or state.question) and not personal_negative:
            state.sadness = 0.0
            state.anxiety = 0.0
            state.anger = 0.0
            state.frustration = 0.0
            state.fatigue = 0.0
            current_negative = False

        state.topic_shift = self._detect_topic_shift(
            messages, latest_raw, state.technical_intent, current_positive, current_negative
        )

        # When the latest turn clearly resets the topic/mood, old emotion should
        # be almost irrelevant. Re-score from current text only.
        if state.topic_shift:
            one = [latest_raw]
            state.sadness = self._score_cues(one, self.SADNESS_CUES)
            state.anxiety = self._score_cues(one, self.ANXIETY_CUES)
            state.anger = self._score_cues(one, self.ANGER_CUES)
            state.frustration = self._score_cues(one, self.FRUSTRATION_CUES)
            state.fatigue = self._score_cues(one, self.FATIGUE_CUES)
            state.excitement = self._score_cues(one, self.EXCITEMENT_CUES)
            state.relief = self._score_cues(one, self.RELIEF_CUES)
            state.affection = self._score_cues(one, self.AFFECTION_CUES)
            state.embarrassment = self._score_cues(one, self.EMBARRASSMENT_CUES)
            state.playfulness = self._score_cues(one, self.PLAYFUL_CUES)

        personal_negative = bool(
            current_negative
            and self._is_personal_emotional_disclosure(text)
        )

        # Personal venting: negative affect without an explicit question/request.
        state.venting = (
            personal_negative
            and not state.advice_request
            and not state.question
            and not state.technical_intent
        )

        # Celebration is stronger than mere positivity.
        state.celebration = (
            state.excitement >= 0.55
            and self._contains_any(text, {
                "it worked", "finally", "got selected", "i won", "we won", "passed",
                "nailed it", "great news", "good news", "yes!", "let's go", "lets go",
            })
        )

        # Valence / arousal.
        negative = max(state.sadness, state.anxiety, state.anger, state.frustration)
        positive = max(state.excitement, state.relief, state.affection, state.playfulness)
        state.valence = max(-1.0, min(1.0, positive - negative))
        state.arousal = self._clamp(max(
            0.18,
            state.anxiety * 0.85,
            state.anger,
            state.frustration * 0.82,
            state.excitement,
            state.playfulness * 0.72,
            state.sadness * 0.42,
            state.fatigue * 0.18,
        ))

        emotions = {
            "sadness": state.sadness,
            "anxiety": state.anxiety,
            "anger": state.anger,
            "frustration": state.frustration,
            "excitement": state.excitement,
            "relief": state.relief,
            "fatigue": state.fatigue,
            "affection": state.affection,
            "embarrassment": state.embarrassment,
            "playfulness": state.playfulness,
        }
        ranked = sorted(emotions.items(), key=lambda item: item[1], reverse=True)
        state.primary_emotion = ranked[0][0] if ranked[0][1] >= 0.28 else "neutral"
        state.secondary_emotion = ranked[1][0] if ranked[1][1] >= 0.30 else "neutral"
        state.confidence = self._clamp(ranked[0][1])

        # Mode priority is driven by the current act, not old emotion.
        if state.technical_intent and (
            self._contains_any(text, self.FRUSTRATION_CUES | self.ANGER_CUES)
        ):
            state.mode = "frustrated_technical"
        elif state.technical_intent and state.debugging_intent:
            state.mode = "debugging"
        elif self._contains_any(text, self.DETAILED_TERMS):
            state.mode = "detailed"
        elif self._contains_any(text, self.CONCISE_TERMS):
            state.mode = "concise"
        elif state.decision_intent:
            state.mode = "decision"
        elif state.teaching_intent:
            state.mode = "teaching"
        elif state.technical_intent:
            state.mode = "technical"
        elif self._contains_any(text, self.SERIOUS_TERMS):
            state.mode = "serious"
        elif state.celebration and state.excitement >= 0.70:
            # Mixed states such as "I'm exhausted but it finally worked" should
            # follow the current victory while still preserving fatigue as nuance.
            state.mode = "positive"
        elif personal_negative:
            state.mode = "emotional_support"
        elif state.celebration or current_positive:
            state.mode = "positive"
        elif state.greeting or state.gratitude or state.compliment or state.affectionate:
            state.mode = "casual"
        else:
            state.mode = "default"

        # Seriousness, energy, directness, shyness.
        state.seriousness = 0.22
        if state.mode == "serious":
            state.seriousness = 0.95
        elif max(state.sadness, state.anxiety, state.anger) >= 0.65:
            state.seriousness = 0.78
        elif state.mode in {"technical", "debugging", "frustrated_technical", "decision"}:
            state.seriousness = 0.52

        state.energy = self._clamp(0.33 + state.excitement * 0.55 + state.playfulness * 0.25
                                   - state.fatigue * 0.30 - state.sadness * 0.18)
        state.directness = 0.56
        if state.mode in {"debugging", "frustrated_technical", "technical", "decision", "concise"}:
            state.directness = 0.86
        elif state.mode == "emotional_support" and not state.advice_request:
            state.directness = 0.44

        state.shyness = 0.32
        if state.compliment:
            state.shyness = 0.72
        elif state.affectionate:
            state.shyness = 0.58
        elif state.mode in {"technical", "debugging", "frustrated_technical", "serious"}:
            state.shyness = 0.08

        # Humor controller.
        if state.seriousness >= 0.72 or max(state.sadness, state.anxiety, state.anger) >= 0.60:
            state.humor_level = 0
        elif state.joke or state.teasing or state.playfulness >= 0.55:
            state.humor_level = 2
        elif state.celebration or state.compliment or state.affectionate:
            state.humor_level = 1
        elif state.mode == "casual":
            state.humor_level = 1
        else:
            state.humor_level = 0
        state.laugh_allowed = bool(state.humor_level >= 2 and state.seriousness < 0.55)

        state.response_strategy = self._choose_strategy(state, text, messages)
        state.voice_style = self._choose_voice_style(state)

        self.last_state = state
        return state

    def _choose_strategy(self, state: AdaptiveState, text: str, messages) -> str:
        if state.correction:
            return "acknowledge_correction_then_fix"
        if state.disagreement:
            return "address_disagreement_directly"
        if state.gratitude:
            return "brief_natural_acknowledgement"
        if state.compliment:
            return "accept_compliment_with_subtle_shy_wit"
        if state.greeting:
            return "brief_familiar_greeting"
        if state.celebration:
            return "celebrate_specific_event"
        if state.mode == "frustrated_technical":
            return "one_brief_acknowledgement_then_debug"
        if state.mode == "debugging":
            return "diagnose_with_controlled_test"
        if state.mode in {"technical", "teaching", "decision", "detailed", "concise"}:
            return {
                "technical": "answer_then_explain_mechanism",
                "teaching": "intuition_then_mechanism",
                "decision": "criteria_tradeoffs_recommendation",
                "detailed": "structured_deep_explanation",
                "concise": "minimal_direct_answer",
            }[state.mode]
        if state.mode == "emotional_support":
            if state.advice_request:
                return "brief_specific_acknowledgement_then_practical_help"
            if state.venting:
                # Deterministic variety without another model call.
                variants = (
                    "specific_acknowledgement_then_one_gentle_question",
                    "specific_observation_without_forcing_advice",
                    "brief_companionable_response_leave_space",
                )
                seed = hashlib.sha1(text.encode("utf-8", errors="ignore")).digest()[0]
                return variants[seed % len(variants)]
            return "respond_to_specific_emotion_without_canned_reassurance"
        if state.joke or state.teasing:
            return "play_along_with_light_wit"
        if state.question:
            return "answer_question_naturally"
        return "respond_naturally_to_current_turn"

    @staticmethod
    def _choose_voice_style(state: AdaptiveState) -> str:
        if state.mode == "serious" or state.seriousness >= 0.88:
            return "serious"
        if state.mode in {"technical", "debugging", "frustrated_technical", "decision", "detailed"}:
            return "calm_confident"
        if state.mode == "emotional_support":
            return "soft_companion"
        # Energetic is intentionally hard to trigger: true celebration only.
        if state.celebration and state.excitement >= 0.70 and state.valence > 0.15:
            return "energetic_friendly"
        return "warm_conversational"

    # ------------------------------------------------------------------
    # History management and anti-repetition
    # ------------------------------------------------------------------

    def _clean_messages(self, messages, state: AdaptiveState):
        clean = []
        raw = self._get_messages(messages)

        # Remove system messages; PromptBuilder owns the system prompt.
        raw = [(r, c) for r, c in raw if r in {"user", "assistant"}]
        if not raw:
            return []

        # On a strong shift, old assistant emotional wording is more harmful
        # than useful. Keep only enough context to understand a short follow-up.
        if state.topic_shift:
            current = raw[-1]
            prefix = raw[:-1]
            # Keep the immediately previous user message, but drop previous
            # assistant prose so it cannot act as a style template.
            previous_user = next(((r, c) for r, c in reversed(prefix) if r == "user"), None)
            selected = ([previous_user] if previous_user else []) + [current]
        else:
            # Keep a compact rolling conversational window. One or two prior
            # exchanges are enough for pronouns and follow-ups in a voice UI.
            selected = raw[-7:]

        for role, content in selected:
            if role == "assistant" and len(content) > 500:
                content = content[:500].rstrip() + "…"
            elif role == "user" and len(content) > 700:
                content = content[:700].rstrip() + "…"
            clean.append({"role": role, "content": content})
        return clean

    def _anti_repetition_block(self, messages) -> str:
        recent = self._recent_assistant_texts(messages, 3)
        if not recent:
            return ""

        compact = []
        for item in recent:
            item = " ".join(item.split())
            if len(item) > 180:
                item = item[:180].rstrip() + "…"
            compact.append(item)

        lines = [
            "RECENT SARA WORDING — USE FOR CONTINUITY, NOT AS A TEMPLATE:",
        ]
        for idx, item in enumerate(compact, 1):
            lines.append(f"{idx}. {item}")
        lines.extend([
            "Do not repeat the same opening, reassurance, closing, joke pattern,",
            "or sentence structure unless repetition is genuinely necessary.",
            "If the current user turn has moved on, do not carry old emotional",
            "language into the new response.",
        ])
        return "\n".join(lines)

    @staticmethod
    def _state_prompt(state: AdaptiveState) -> str:
        secondary = state.secondary_emotion if state.secondary_emotion != "neutral" else "none"
        return (
            "CURRENT CONVERSATION STATE\n"
            f"- mode: {state.mode}\n"
            f"- primary emotion: {state.primary_emotion}\n"
            f"- secondary emotion: {secondary}\n"
            f"- emotion confidence: {state.confidence:.2f}\n"
            f"- valence: {state.valence:.2f}\n"
            f"- arousal: {state.arousal:.2f}\n"
            f"- seriousness: {state.seriousness:.2f}\n"
            f"- shyness: {state.shyness:.2f}\n"
            f"- energy: {state.energy:.2f}\n"
            f"- directness: {state.directness:.2f}\n"
            f"- humor level: {state.humor_level}/3\n"
            f"- laughter allowed: {state.laugh_allowed}\n"
            f"- advice requested: {state.advice_request}\n"
            f"- venting: {state.venting}\n"
            f"- topic/mood shift: {state.topic_shift}\n"
            f"- response strategy: {state.response_strategy}\n"
            "Treat these as delivery guidance, not facts to state aloud."
        )

    @staticmethod
    def _voice_conversation_block(state: AdaptiveState) -> str:
        """
        Natural voice-first response policy.

        The goal is not to make every answer tiny. The goal is to make the
        first spoken response conversational, with detail expanding only when
        the user asks for it or when the task inherently requires it.
        """
        if state.mode in {
            "detailed",
            "teaching",
            "debugging",
            "frustrated_technical",
        }:
            depth = (
                "Give enough detail to solve the task, but lead with the answer "
                "or diagnosis before expanding."
            )
        elif state.mode in {
            "technical",
            "decision",
        }:
            depth = (
                "Start with the key answer in 1-3 spoken sentences. "
                "Add only the most useful explanation unless the user asks for depth."
            )
        elif state.mode == "emotional_support":
            depth = (
                "Keep the first response human and compact. "
                "Usually 1-3 natural sentences, then leave room for the user."
            )
        else:
            depth = (
                "Default to 1-3 natural spoken sentences. "
                "Expand only when the user asks for more or the task requires it."
            )

        return (
            "VOICE-FIRST CONVERSATION POLICY\n"
            f"{depth}\n"
            "Answer the user's actual question immediately.\n"
            "Do not repeat the user's question before answering.\n"
            "Do not announce structure such as 'Here are the points' unless useful.\n"
            "Prefer natural conversational wording over essay-style prose.\n"
            "Use short complete clauses that can be spoken as soon as they are generated.\n"
            "Avoid long introductions, generic closings, and unnecessary recap.\n"
            "For follow-up questions, assume conversational continuity instead of restating context.\n"
            "When the user asks for code, calculations, a report, or a full explanation, preserve completeness."
        )

    def build(self, messages, state=None):
        if state is None:
            state = self.analyze(messages)
        adaptive = ADAPTIVE_PROMPTS.get(state.mode, ADAPTIVE_PROMPTS["default"])
        recent_block = self._anti_repetition_block(messages)
        final_system = (
            f"{SYSTEM_PROMPT}\n\n"
            f"CURRENT RESPONSE MODE: {state.mode}\n\n"
            f"{adaptive}\n\n"
            f"{self._state_prompt(state)}\n\n"
            f"{self._voice_conversation_block(state)}"
        )
        if recent_block:
            final_system += "\n\n" + recent_block

        # Strong explicit instruction against known boilerplate. The user saw
        # these recur in live tests, so make the constraint concrete.
        if state.mode == "emotional_support" or self._recent_assistant_texts(messages, 2):
            final_system += (
                "\n\nANTI-BOILERPLATE\n"
                "Avoid generic reassurance clichés about always being present, the user "
                "not being alone, inviting them to reach out, generic praise for trying, "
                "or automatic farewell-style closings. Prefer a response specific to the "
                "current message."
            )

        return [
            {"role": "system", "content": final_system},
            *self._clean_messages(messages, state),
        ]

    # ------------------------------------------------------------------
    # Backward-compatible API
    # ------------------------------------------------------------------

    def detect_mode(self, messages):
        return self.analyze(messages).mode

    def get_mode(self, messages):
        return self.detect_mode(messages)

    def get_state(self, messages):
        return self.analyze(messages)

    def get_voice_style(self, state_or_messages):
        if isinstance(state_or_messages, AdaptiveState):
            return state_or_messages.voice_style
        return self.analyze(state_or_messages).voice_style
