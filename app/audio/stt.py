"""
Sara - Parakeet Speech-to-Text
------------------------------

Offline Parakeet TDT transcription using sherpa-onnx.

Supports:

- normal transcription with timing logs
- silent transcription for wake-word detection
"""

import time
from pathlib import Path
from typing import Optional

import numpy as np
import sherpa_onnx

from app.config import (
    STT_MODEL_DIR,
    STT_SAMPLE_RATE,
    STT_NUM_THREADS,
    SHOW_INFERENCE_TIME,
)


class ParakeetSTT:

    def __init__(self):

        self.sample_rate = STT_SAMPLE_RATE

        model_dir = Path(
            STT_MODEL_DIR
        )

        encoder = (
            model_dir
            / "encoder.int8.onnx"
        )

        decoder = (
            model_dir
            / "decoder.int8.onnx"
        )

        joiner = (
            model_dir
            / "joiner.int8.onnx"
        )

        tokens = (
            model_dir
            / "tokens.txt"
        )


        required_files = [
            encoder,
            decoder,
            joiner,
            tokens,
        ]


        for path in required_files:

            if not path.exists():

                raise FileNotFoundError(
                    f"Missing STT model file: {path}"
                )


        print(
            "[STT] Loading Parakeet..."
        )


        start = time.perf_counter()


        self.recognizer = (
            sherpa_onnx
            .OfflineRecognizer
            .from_transducer(
                encoder=str(encoder),
                decoder=str(decoder),
                joiner=str(joiner),
                tokens=str(tokens),
                num_threads=STT_NUM_THREADS,
                sample_rate=self.sample_rate,
                feature_dim=128,
                decoding_method="greedy_search",
                provider="cpu",
                model_type="nemo_transducer",
            )
        )


        load_time = (
            time.perf_counter()
            - start
        )


        print(
            f"[STT] Parakeet ready "
            f"load={load_time:.3f}s"
        )


    # ========================================================
    # TRANSCRIBE
    # ========================================================

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: Optional[int] = None,
        silent: bool = False,
    ) -> str:

        if sample_rate is None:
            sample_rate = self.sample_rate


        audio = np.asarray(
            audio,
            dtype=np.float32,
        ).squeeze()


        if audio.size == 0:
            return ""


        start = time.perf_counter()


        stream = (
            self.recognizer
            .create_stream()
        )


        stream.accept_waveform(
            sample_rate,
            audio,
        )


        self.recognizer.decode_stream(
            stream
        )


        text = (
            stream
            .result
            .text
            .strip()
        )


        elapsed = (
            time.perf_counter()
            - start
        )


        if (
            SHOW_INFERENCE_TIME
            and not silent
        ):

            audio_duration = (
                len(audio)
                / sample_rate
            )


            realtime_factor = (
                elapsed
                / audio_duration
                if audio_duration > 0
                else 0.0
            )


            print(
                f"[STT] "
                f"audio={audio_duration:.2f}s "
                f"inference={elapsed:.3f}s "
                f"RTF={realtime_factor:.3f}"
            )


        return text


    # ========================================================
    # WAKE-WORD TRANSCRIPTION
    # ========================================================

    def transcribe_silent(
        self,
        audio: np.ndarray,
        sample_rate: Optional[int] = None,
    ) -> str:

        """
        Convenience method used by the wake-word listener.

        Performs exactly the same recognition but suppresses
        timing/debug output.
        """

        return self.transcribe(
            audio=audio,
            sample_rate=sample_rate,
            silent=True,
        )