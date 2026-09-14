from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import numpy as np


class MultilingualSTT:
    """
    Local multilingual conversation STT for SIA.

    Wake-word detection stays on the existing Parakeet path. This recognizer is
    used only after SIA is awake (and to re-transcribe the wake utterance when it
    also contains a command), which gives Hindi/Hinglish/English code-switching
    much better coverage without disturbing the proven wake path.

    Backend: faster-whisper / CTranslate2.
    """

    def __init__(
        self,
        model_path: str | Path,
        *,
        device: str = "cpu",
        compute_type: str = "int8",
        cpu_threads: int = 8,
        num_workers: int = 1,
        beam_size: int = 1,
        initial_prompt: str = "",
    ):
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:
            raise RuntimeError(
                "faster-whisper is not installed. Run setup_multilingual_stt.ps1."
            ) from exc

        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Multilingual STT model directory not found: {self.model_path}"
            )

        self.device = str(device)
        self.compute_type = str(compute_type)
        self.cpu_threads = max(1, int(cpu_threads))
        self.num_workers = max(1, int(num_workers))
        self.beam_size = max(1, int(beam_size))
        self.initial_prompt = str(initial_prompt or "").strip()

        started = time.perf_counter()

        self.model = WhisperModel(
            str(self.model_path),
            device=self.device,
            compute_type=self.compute_type,
            cpu_threads=self.cpu_threads,
            num_workers=self.num_workers,
        )

        self.load_seconds = time.perf_counter() - started

        print(
            "[MULTILINGUAL STT] ready "
            f"model={self.model_path.name} "
            f"device={self.device} "
            f"compute={self.compute_type} "
            f"load={self.load_seconds:.2f}s"
        )

    @staticmethod
    def _to_float32(audio: np.ndarray) -> np.ndarray:
        samples = np.asarray(audio)

        if samples.ndim > 1:
            samples = samples.reshape(-1)

        if samples.dtype == np.int16:
            samples = samples.astype(np.float32) / 32768.0
        else:
            samples = samples.astype(np.float32, copy=False)

            # Defensive conversion for float arrays that still contain PCM16-like
            # magnitudes. Normal SIA captures are already in [-1, 1].
            peak = float(np.max(np.abs(samples))) if samples.size else 0.0
            if peak > 2.0:
                samples = samples / 32768.0

        return np.clip(samples, -1.0, 1.0)

    @staticmethod
    def _resample_linear(
        audio: np.ndarray,
        source_rate: int,
        target_rate: int = 16000,
    ) -> np.ndarray:
        source_rate = int(source_rate)
        target_rate = int(target_rate)

        if source_rate == target_rate:
            return audio

        if source_rate <= 0 or target_rate <= 0 or audio.size == 0:
            return audio

        source_n = int(audio.size)
        target_n = max(1, int(round(source_n * target_rate / source_rate)))

        x_old = np.linspace(0.0, 1.0, source_n, endpoint=False)
        x_new = np.linspace(0.0, 1.0, target_n, endpoint=False)

        return np.interp(x_new, x_old, audio).astype(np.float32)

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        sample_rate: int = 16000,
    ) -> str:
        samples = self._to_float32(audio)

        if samples.size == 0:
            return ""

        if int(sample_rate) != 16000:
            samples = self._resample_linear(
                samples,
                int(sample_rate),
                16000,
            )

        started = time.perf_counter()

        kwargs = dict(
            beam_size=self.beam_size,
            language=None,
            task="transcribe",
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
            temperature=0.0,
        )

        if self.initial_prompt:
            kwargs["initial_prompt"] = self.initial_prompt

        segments, info = self.model.transcribe(
            samples,
            **kwargs,
        )

        text = " ".join(
            str(segment.text or "").strip()
            for segment in segments
            if str(segment.text or "").strip()
        ).strip()

        detected_language = getattr(
            info,
            "language",
            None,
        ) or "unknown"

        probability = getattr(
            info,
            "language_probability",
            None,
        )

        # SIA conversation is intentionally English / Hindi / Hinglish.
        # Faster-Whisper can occasionally misclassify short/noisy English
        # utterances as German, French, Spanish, etc.  In that situation
        # retry the SAME audio with English locked instead of forwarding
        # an unrelated-language hallucination to the LLM.
        allowed_languages = {
            "en",
            "hi",
        }

        language_confidence = (
            float(probability)
            if probability is not None
            else 0.0
        )

        # For one-mic conversational audio, short Indian-English/Hinglish
        # commands can occasionally be classified as Hindi with weak
        # confidence. Preserve genuine confident Hindi, but retry uncertain
        # Hindi and unrelated languages as English.
        retry_as_english = (
            detected_language not in allowed_languages
            or (
                detected_language == "hi"
                and language_confidence < 0.65
            )
        )

        if retry_as_english:
            print(
                "[MULTILINGUAL STT] uncertain language "
                f"{detected_language!r} "
                f"p={language_confidence:.2f} "
                "-> retrying as English"
            )

            retry_kwargs = dict(kwargs)
            retry_kwargs["language"] = "en"

            retry_segments, retry_info = self.model.transcribe(
                samples,
                **retry_kwargs,
            )

            retry_text = " ".join(
                str(segment.text or "").strip()
                for segment in retry_segments
                if str(segment.text or "").strip()
            ).strip()

            if retry_text:
                text = retry_text
                info = retry_info
                detected_language = "en"
                probability = getattr(
                    retry_info,
                    "language_probability",
                    None,
                )

                print(
                    "[MULTILINGUAL STT] English retry "
                    f"accepted -> {text!r}"
                )

        elapsed = time.perf_counter() - started

        if probability is None:
            print(
                "[MULTILINGUAL STT] "
                f"lang={detected_language} time={elapsed:.3f}s -> {text!r}"
            )
        else:
            print(
                "[MULTILINGUAL STT] "
                f"lang={detected_language} p={float(probability):.2f} "
                f"time={elapsed:.3f}s -> {text!r}"
            )

        return text

    def transcribe_silent(
        self,
        audio: np.ndarray,
        *,
        sample_rate: int = 16000,
    ) -> str:
        """Compatibility alias. The backend itself is already quiet except for our log."""
        return self.transcribe(audio, sample_rate=sample_rate)
