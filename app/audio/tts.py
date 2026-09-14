"""
Text-to-Speech
--------------

Ultra-low-latency Piper TTS.

The model is loaded once and kept resident.

Flow:

    text
      ↓
    Piper
      ↓
    PCM chunks
      ↓
    playback / ESP32 later
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

from piper.voice import PiperVoice

from app.config import (
    MODELS_DIR,
    TTS_MODEL,
    SHOW_INFERENCE_TIME,
)


# ============================================================
# AUDIO CHUNK
# ============================================================

@dataclass
class AudioChunk:
    """
    Model-independent PCM audio container.
    """

    pcm: bytes
    sample_rate: int
    sample_width: int
    channels: int


# ============================================================
# PIPER TTS
# ============================================================

class PiperTTS:

    def __init__(self):

        model_dir = (
            Path(MODELS_DIR)
            / "piper"
        )

        model_path = (
            model_dir
            / f"{TTS_MODEL}.onnx"
        )

        config_path = (
            model_dir
            / f"{TTS_MODEL}.onnx.json"
        )

        if not model_path.exists():
            raise FileNotFoundError(
                f"Missing Piper model: {model_path}"
            )

        if not config_path.exists():
            raise FileNotFoundError(
                f"Missing Piper config: {config_path}"
            )

        print(
            f"[TTS] Loading Piper: "
            f"{TTS_MODEL}"
        )

        start = time.perf_counter()

        self.voice = PiperVoice.load(
            str(model_path),
            config_path=str(config_path),
            use_cuda=False,
        )

        elapsed = (
            time.perf_counter()
            - start
        )

        print(
            f"[TTS] Piper ready "
            f"load={elapsed:.3f}s"
        )

        self._warmup()


    # ========================================================
    # WARMUP
    # ========================================================

    def _warmup(self):

        start = time.perf_counter()

        for _ in self.voice.synthesize(
            "Hello."
        ):
            pass

        elapsed = (
            time.perf_counter()
            - start
        )

        if SHOW_INFERENCE_TIME:

            print(
                f"[TTS] warmup="
                f"{elapsed * 1000:.1f}ms"
            )


    # ========================================================
    # STREAM
    # ========================================================

    def stream(
        self,
        text: str,
    ) -> Generator[AudioChunk, None, None]:
        """
        Generate PCM audio incrementally.

        Audio is yielded as soon as Piper creates each chunk.
        """

        text = text.strip()

        if not text:
            return

        start = time.perf_counter()

        first_audio_time = None

        total_bytes = 0
        chunks = 0

        for chunk in self.voice.synthesize(
            text
        ):

            now = time.perf_counter()

            if first_audio_time is None:

                first_audio_time = now

                if SHOW_INFERENCE_TIME:

                    first_latency = (
                        first_audio_time
                        - start
                    )

                    print(
                        f"[TTS] first_audio="
                        f"{first_latency * 1000:.1f}ms"
                    )

            pcm = (
                chunk.audio_int16_bytes
            )

            total_bytes += len(pcm)
            chunks += 1

            yield AudioChunk(
                pcm=pcm,
                sample_rate=chunk.sample_rate,
                sample_width=chunk.sample_width,
                channels=chunk.sample_channels,
            )

        total_time = (
            time.perf_counter()
            - start
        )

        if SHOW_INFERENCE_TIME:

            print(
                f"[TTS] complete "
                f"total={total_time * 1000:.1f}ms "
                f"chunks={chunks} "
                f"bytes={total_bytes:,}"
            )


    # ========================================================
    # FULL PCM
    # ========================================================

    def synthesize(
        self,
        text: str,
    ):
        """
        Convenience method for cases where complete PCM is needed.

        The low-latency voice pipeline should normally use stream().
        """

        pcm_parts = []

        sample_rate = None
        sample_width = None
        channels = None

        for chunk in self.stream(
            text
        ):

            pcm_parts.append(
                chunk.pcm
            )

            sample_rate = (
                chunk.sample_rate
            )

            sample_width = (
                chunk.sample_width
            )

            channels = (
                chunk.channels
            )

        return {
            "pcm": b"".join(
                pcm_parts
            ),
            "sample_rate": sample_rate,
            "sample_width": sample_width,
            "channels": channels,
        }