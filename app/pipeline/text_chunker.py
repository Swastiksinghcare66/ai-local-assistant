from __future__ import annotations

import re
from typing import Optional

_COMMON_ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.",
    "vs.", "etc.", "e.g.", "i.e.", "a.m.", "p.m.",
    "fig.", "eq.", "no.",
}
_CLOSERS = "\"'”’)]}"


def is_speakable_phrase(text: str) -> bool:
    text = str(text or "").strip()
    return bool(text) and any(ch.isalnum() for ch in text)


def normalize_for_speech(text: str) -> str:
    """
    Lightweight speech normalization for TTS.
    It removes formatting noise but deliberately avoids rewriting technical
    values, decimals, model names, file paths, or equations.
    """
    text = str(text or "")
    if not text.strip():
        return ""

    text = re.sub(r"```(?:[a-zA-Z0-9_+-]+)?\s*", "", text)
    text = text.replace("```", "")
    text = re.sub(r"`([^`]+)`", r"\1", text)

    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)

    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*•]\s+", "", text)
    text = re.sub(r"(?m)^\s*\d+\.\s+", "", text)

    text = text.replace("**", "").replace("__", "")
    text = text.replace("~~", "")

    # Speak a few common symbols naturally without damaging code-like tokens.
    text = re.sub(r"\s+&\s+", " and ", text)
    text = re.sub(r"\s+->\s+", " to ", text)
    text = re.sub(r"\s+→\s+", " to ", text)

    text = " ".join(text.split())
    return text.strip()


class HybridSpeechChunker:
    """
    Adaptive clause chunker for conversational TTS.

    Goals:
    - first speakable chunk is released as soon as it is natural
    - dispatch overhead after a natural boundary should stay in the ~0-50 ms class
    - later chunks are larger to protect prosody and reduce TTS overhead
    - technical punctuation is protected

    This does NOT make CosyVoice itself produce audio in 50 ms. It only keeps
    the Python-side chunking/dispatch latency small.
    """

    def __init__(
        self,
        first_target: int = 64,
        normal_target: int = 120,
        hard_max: int = 200,
        first_min: int = 36,
        normal_min: int = 64,
        max_hold_ms: float = 120.0,
    ):
        self.first_target = max(20, int(first_target))
        self.normal_target = max(self.first_target, int(normal_target))
        self.hard_max = max(self.normal_target + 20, int(hard_max))
        self.first_min = max(12, int(first_min))
        self.normal_min = max(self.first_min, int(normal_min))
        self.max_hold_ms = max(20.0, float(max_hold_ms))

        self.buffer = ""
        self.first_chunk_sent = False
        self._buffer_started_at = None

    @staticmethod
    def _clean(text: str) -> str:
        return " ".join(str(text).strip().split())

    @staticmethod
    def _last_token(text: str) -> str:
        text = text.rstrip()
        return text.split()[-1].lower() if text else ""

    @staticmethod
    def _looks_like_acronym(token: str) -> bool:
        return bool(re.fullmatch(r"(?:[A-Za-z]\.){2,}", token))

    def _inside_backticks(self, index: int) -> bool:
        prefix = self.buffer[:index]
        if prefix.count("```") % 2 == 1:
            return True
        return prefix.replace("```", "").count("`") % 2 == 1

    def _period_is_boundary(self, index: int) -> bool:
        if self._inside_backticks(index):
            return False

        if index + 1 < len(self.buffer) and self.buffer[index + 1] == ".":
            return False

        if (
            index > 0
            and index + 1 < len(self.buffer)
            and self.buffer[index - 1].isdigit()
            and self.buffer[index + 1].isdigit()
        ):
            return False

        token = self._last_token(self.buffer[: index + 1])

        if token in _COMMON_ABBREVIATIONS:
            return False

        if self._looks_like_acronym(token):
            return False

        stem = token[:-1]
        if len(stem) == 1 and stem.isalpha():
            return False

        if index + 1 >= len(self.buffer):
            return False

        nxt = self.buffer[index + 1]
        if nxt.isalnum() or nxt in "_-/\\":
            return False

        return nxt.isspace() or nxt in _CLOSERS

    def _sentence_boundary(
        self,
        min_len: int,
        search_limit: int,
    ) -> Optional[int]:
        i = 0
        limit = min(len(self.buffer), search_limit)

        while i < limit:
            ch = self.buffer[i]

            if ch not in ".!?":
                i += 1
                continue

            if self._inside_backticks(i):
                i += 1
                continue

            if ch == "." and not self._period_is_boundary(i):
                i += 1
                continue

            end = i + 1

            while end < len(self.buffer) and self.buffer[end] in ".!?":
                end += 1

            while end < len(self.buffer) and self.buffer[end] in _CLOSERS:
                end += 1

            if end >= min_len:
                return end

            i = end

        return None

    def _elapsed_ms(self, now: float) -> float:
        if self._buffer_started_at is None:
            return 0.0
        return max(0.0, (now - self._buffer_started_at) * 1000.0)

    def _take(self, position: int, now: float) -> str:
        chunk = self._clean(self.buffer[:position])
        self.buffer = self.buffer[position:].lstrip()

        self.first_chunk_sent = True

        if self.buffer:
            self._buffer_started_at = now
        else:
            self._buffer_started_at = None

        return chunk

    def _natural_clause_boundary(
        self,
        minimum: int,
        search_limit: int,
    ) -> Optional[int]:
        area = self.buffer[:search_limit]
        candidates: list[int] = []

        # Strong spoken clause punctuation.
        for punct in [",", ";", ":", "—", "–"]:
            pos = area.rfind(punct)
            if pos + 1 >= minimum:
                candidates.append(pos + 1)

        # Natural linguistic split points. The boundary is before the marker so
        # the next phrase starts cleanly.
        lower = area.lower()
        for marker in [
            " because ",
            " but ",
            " so ",
            " while ",
            " although ",
            " however ",
            " which ",
            " then ",
        ]:
            pos = lower.rfind(marker)
            if pos >= minimum:
                candidates.append(pos)

        return max(candidates) if candidates else None

    def _extract(self, now: float) -> Optional[str]:
        target = (
            self.normal_target
            if self.first_chunk_sent
            else self.first_target
        )
        minimum = (
            self.normal_min
            if self.first_chunk_sent
            else self.first_min
        )

        if len(self.buffer) < minimum:
            return None

        # Full sentence always wins.
        boundary = self._sentence_boundary(
            min_len=minimum,
            search_limit=min(len(self.buffer), target + 48),
        )

        if boundary is not None:
            return self._take(boundary, now)

        # Split at a natural clause only after the nominal target
        # has been reached. This prevents short complete thoughts
        # such as "... while I'm offline." from becoming two TTS calls.
        clause = None

        if len(self.buffer) >= target:
            clause = self._natural_clause_boundary(
                minimum=minimum,
                search_limit=min(len(self.buffer), target + 28),
            )

        if clause is not None:
            return self._take(clause, now)

        elapsed_ms = self._elapsed_ms(now)

        # If enough natural text has accumulated, do not hold it just to hit a
        # fixed character target. This is the low-latency path.
        if (
            len(self.buffer) >= target
            and elapsed_ms >= self.max_hold_ms
        ):
            search_limit = min(len(self.buffer), max(target, minimum + 8))
            split = self.buffer.rfind(" ", 0, search_limit)

            if split >= minimum:
                return self._take(split, now)

        if len(self.buffer) < target:
            return None

        search_limit = min(len(self.buffer), target + 24)
        split = self.buffer.rfind(" ", 0, search_limit)

        if split >= minimum:
            return self._take(split, now)

        if len(self.buffer) >= self.hard_max:
            split = self.buffer.rfind(" ", 0, self.hard_max)
            if split <= 0:
                split = self.hard_max
            return self._take(split, now)

        return None

    def feed(
        self,
        text: str,
        now: Optional[float] = None,
    ) -> list[str]:
        if not text:
            return []

        import time as _time

        now = _time.perf_counter() if now is None else float(now)

        if not self.buffer:
            self._buffer_started_at = now

        self.buffer += text
        output: list[str] = []

        while True:
            chunk = self._extract(now)

            if chunk is None:
                break

            if is_speakable_phrase(chunk):
                output.append(chunk)

        return output

    def poll(
        self,
        now: Optional[float] = None,
    ) -> list[str]:
        """
        Allow the producer loop to release a held natural phrase even when no
        new token arrived for a few milliseconds.
        """
        import time as _time

        now = _time.perf_counter() if now is None else float(now)
        output: list[str] = []

        while True:
            chunk = self._extract(now)

            if chunk is None:
                break

            if is_speakable_phrase(chunk):
                output.append(chunk)

        return output

    def flush(self) -> list[str]:
        tail = self._clean(self.buffer)
        self.buffer = ""
        self._buffer_started_at = None

        return [tail] if is_speakable_phrase(tail) else []

    def reset(self):
        self.buffer = ""
        self.first_chunk_sent = False
        self._buffer_started_at = None
