from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ResolvedTurn:
    original_text: str
    resolved_text: str
    dialogue_act: str
    confidence: float
    should_resolve: bool


class DialogueResolver:
    """
    Lightweight deterministic resolver for short conversational replies.

    Important:
    - It does NOT modify stored conversation history.
    - It only clarifies the model-facing meaning of short replies.
    - It intentionally resolves only high-confidence cases.
    """

    YES_WORDS = {
        "yes",
        "yeah",
        "yep",
        "yup",
        "correct",
        "right",
        "exactly",
        "sure",
    }

    NO_WORDS = {
        "no",
        "nope",
        "nah",
    }

    SOFT_NO = {
        "not really",
        "not much",
        "not anymore",
        "not exactly",
    }

    CLOSURES = {
        "lets talk later",
        "let's talk later",
        "talk later",
        "later",
        "good night",
        "goodnight",
        "leave it",
        "forget it",
        "not now",
        "maybe later",
        "we'll talk later",
        "we will talk later",
    }

    FIRST_REFS = {
        "first",
        "first one",
        "the first",
        "the first one",
        "option one",
        "option 1",
    }

    SECOND_REFS = {
        "second",
        "second one",
        "the second",
        "the second one",
        "option two",
        "option 2",
    }

    def _normalize(self, text: str) -> str:
        text = text.lower().strip()
        text = text.replace("’", "'")
        text = re.sub(r"[^\w\s']", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _clean_option(self, text: str) -> str:
        text = text.strip(" ?.,!")
        text = re.sub(
            r"^(would you rather|do you want to|should we|is it|was it)\s+",
            "",
            text,
            flags=re.I,
        )

        text = re.sub(
            r"\b(first|instead|mainly|mostly)$",
            "",
            text,
            flags=re.I,
        ).strip()

        return text

    def _split_choice_question(
        self,
        question: str,
    ) -> tuple[str, str] | None:

        q = question.strip()

        if " or " not in q.lower():
            return None

        parts = re.split(
            r"\s+or\s+",
            q,
            maxsplit=1,
            flags=re.I,
        )

        if len(parts) != 2:
            return None

        left = self._clean_option(parts[0])
        right = self._clean_option(parts[1])

        if not left or not right:
            return None

        return left, right

    def _resolve_choice_reference(
        self,
        question: str,
        answer: str,
    ) -> ResolvedTurn | None:

        options = self._split_choice_question(question)

        if not options:
            return None

        first, second = options
        normalized = self._normalize(answer)

        if normalized in self.FIRST_REFS:
            return ResolvedTurn(
                original_text=answer,
                resolved_text=(
                    f"The user chooses the first option: {first}."
                ),
                dialogue_act="choice_first",
                confidence=0.98,
                should_resolve=True,
            )

        if normalized in self.SECOND_REFS:
            return ResolvedTurn(
                original_text=answer,
                resolved_text=(
                    f"The user chooses the second option: {second}."
                ),
                dialogue_act="choice_second",
                confidence=0.98,
                should_resolve=True,
            )

        # Handle replies such as:
        # "Mostly chunking."
        # "Voice quality."
        # "Probably TTS."
        answer_tokens = {
            token
            for token in normalized.split()
            if len(token) >= 3
            and token not in {
                "mostly",
                "probably",
                "mainly",
                "really",
                "the",
                "one",
            }
        }

        first_norm = self._normalize(first)
        second_norm = self._normalize(second)

        first_score = sum(
            1
            for token in answer_tokens
            if token in first_norm
        )

        second_score = sum(
            1
            for token in answer_tokens
            if token in second_norm
        )

        if first_score > second_score and first_score > 0:
            return ResolvedTurn(
                original_text=answer,
                resolved_text=(
                    f"The user's answer is that it was mainly {first}."
                ),
                dialogue_act="choice_content_first",
                confidence=0.94,
                should_resolve=True,
            )

        if second_score > first_score and second_score > 0:
            return ResolvedTurn(
                original_text=answer,
                resolved_text=(
                    f"The user's answer is that it was mainly {second}."
                ),
                dialogue_act="choice_content_second",
                confidence=0.94,
                should_resolve=True,
            )

        return None

    def _resolve_yes_no(
        self,
        question: str,
        answer: str,
    ) -> ResolvedTurn | None:

        normalized = self._normalize(answer)

        question_normalized = self._normalize(question)

        yes = normalized in self.YES_WORDS
        no = normalized in self.NO_WORDS
        soft_no = normalized in self.SOFT_NO

        if not (yes or no or soft_no):
            return None

        auxiliaries = (
            "is ",
            "are ",
            "was ",
            "were ",
            "do ",
            "does ",
            "did ",
            "can ",
            "could ",
            "will ",
            "would ",
            "has ",
            "have ",
            "had ",
            "should ",
        )

        if not question_normalized.startswith(auxiliaries):
            return None

        if yes:
            resolved = (
                "The user answers yes to Sara's previous question: "
                f'"{question}"'
            )

            act = "yes"

        elif soft_no:
            resolved = (
                "The user indicates that the answer to Sara's previous "
                f'question is mostly no: "{question}"'
            )

            act = "soft_no"

        else:
            resolved = (
                "The user answers no to Sara's previous question: "
                f'"{question}"'
            )

            act = "no"

        return ResolvedTurn(
            original_text=answer,
            resolved_text=resolved,
            dialogue_act=act,
            confidence=0.95,
            should_resolve=True,
        )

    def resolve(
        self,
        previous_assistant: str,
        current_user: str,
    ) -> ResolvedTurn:

        original = current_user.strip()

        normalized = self._normalize(original)

        if not previous_assistant.strip():
            return ResolvedTurn(
                original_text=original,
                resolved_text=original,
                dialogue_act="normal",
                confidence=1.0,
                should_resolve=False,
            )

        # Explicit closure must remain natural and untouched.
        if normalized in self.CLOSURES:
            return ResolvedTurn(
                original_text=original,
                resolved_text=original,
                dialogue_act="closure",
                confidence=1.0,
                should_resolve=False,
            )

        # Avoid rewriting long, self-contained turns.
        if len(original.split()) > 10:
            return ResolvedTurn(
                original_text=original,
                resolved_text=original,
                dialogue_act="normal",
                confidence=1.0,
                should_resolve=False,
            )

        choice = self._resolve_choice_reference(
            previous_assistant,
            original,
        )

        if choice:
            return choice

        yes_no = self._resolve_yes_no(
            previous_assistant,
            original,
        )

        if yes_no:
            return yes_no

        return ResolvedTurn(
            original_text=original,
            resolved_text=original,
            dialogue_act="unresolved_short_reply",
            confidence=0.0,
            should_resolve=False,
        )
