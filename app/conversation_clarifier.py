from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Optional


@dataclass
class PendingClarification:
    original_query: str
    followups: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    attempts: int = 0


@dataclass
class ClarificationDecision:
    action: str
    question: str = ""
    reason: str = ""
    confidence: float = 1.0


class ConversationClarifier:
    """Fast rule-based clarification layer for Sara."""

    def __init__(self, max_followups: int = 2):
        self.max_followups = max(1, int(max_followups))
        self.pending: Optional[PendingClarification] = None

    @staticmethod
    def _clean(text: str) -> str:
        return " ".join(str(text or "").strip().split())

    @staticmethod
    def _words(text: str) -> list[str]:
        return re.findall(r"[a-zA-Z0-9_+'-]+", str(text or "").lower())

    @staticmethod
    def _looks_like_context(text: str) -> bool:
        low = str(text or "").lower()
        markers = [
            "traceback", "exception", "error:", "failed", "failure",
            "latency", "ttfa", "stt", "tts", "qwen", "cosyvoice",
            "parakeet", "wake", "vad", "log", "output", "code",
            "function", "class", "file ", "line ",
        ]
        return any(m in low for m in markers)

    @staticmethod
    def _has_specific_object(text: str) -> bool:
        words = ConversationClarifier._words(text)
        vague = {
            "this", "that", "it", "thing", "issue", "problem",
            "wrong", "bad", "slow", "working", "work", "fix",
            "why", "what", "can", "you", "is", "not", "does",
            "do", "did", "please", "help", "me",
        }
        informative = [w for w in words if w not in vague]
        return len(informative) >= 2

    def evaluate(self, query: str) -> ClarificationDecision:
        query = self._clean(query)

        if not query:
            return ClarificationDecision(
                action="clarify",
                question="What do you want me to help with?",
                reason="empty_query",
                confidence=1.0,
            )

        if self.pending is not None:
            return ClarificationDecision(
                action="answer",
                reason="pending_answer",
                confidence=0.99,
            )

        low = query.lower().rstrip("?.!")
        words = self._words(query)

        vague_exact = {
            "why is it not working",
            "why is this not working",
            "why doesn't it work",
            "why does this not work",
            "what is wrong",
            "what's wrong",
            "fix it",
            "fix this",
            "can you fix it",
            "explain this",
            "help me with this",
            "why is it slow",
            "why is this slow",
            "it's not working",
            "it is not working",
        }

        if low in vague_exact and not self._looks_like_context(query):
            if "slow" in low:
                question = "Which part is slow?"
            elif "explain" in low:
                question = "Which specific part do you want me to explain?"
            else:
                question = "Which component or behavior are you referring to?"

            return ClarificationDecision(
                action="clarify",
                question=question,
                reason="highly_vague_reference",
                confidence=0.99,
            )

        pronoun_heavy = any(w in {"it", "this", "that"} for w in words)
        complaint = any(
            x in low
            for x in [
                "not working", "doesn't work", "does not work",
                "wrong", "slow", "bad response", "bad responses",
                "issue", "problem", "fix",
            ]
        )

        if (
            pronoun_heavy
            and complaint
            and not self._has_specific_object(query)
            and not self._looks_like_context(query)
        ):
            return ClarificationDecision(
                action="clarify",
                question="Which component or behavior is having the problem?",
                reason="missing_target",
                confidence=0.94,
            )

        debug_request = any(
            x in low
            for x in [
                "why did this crash",
                "why is this crashing",
                "debug this error",
                "fix this error",
                "why did it fail",
            ]
        )

        if debug_request and not self._looks_like_context(query):
            return ClarificationDecision(
                action="ask_for_evidence",
                question="Send me the traceback or the relevant console error.",
                reason="missing_debug_evidence",
                confidence=0.97,
            )

        return ClarificationDecision(
            action="answer",
            reason="query_sufficient",
            confidence=0.95,
        )

    def begin(self, original_query: str, question: str):
        self.pending = PendingClarification(
            original_query=self._clean(original_query),
            followups=[self._clean(question)],
            attempts=1,
        )

    def merge_answer(self, answer: str) -> str:
        if self.pending is None:
            return self._clean(answer)

        answer = self._clean(answer)
        self.pending.answers.append(answer)

        return (
            f"Original user query: {self.pending.original_query}\n"
            f"Clarification question: {self.pending.followups[-1]}\n"
            f"User clarification: {answer}\n"
            "Answer the original query using this clarification. "
            "Do not repeat the clarification question unless essential."
        )

    def resolve(self):
        self.pending = None

    def cancel(self):
        self.pending = None
