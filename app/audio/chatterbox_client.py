"""
Chatterbox Turbo Client
-----------------------

Runs inside Alexa Lite's normal .venv.

The actual Chatterbox model runs in the separate
.venv_chatterbox process at:

    http://127.0.0.1:5050

This avoids dependency conflicts while keeping the TTS model
loaded permanently on the GPU.
"""

import io
import json
import time
import wave
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np


# ============================================================
# DEFAULT SETTINGS
# ============================================================

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5050
DEFAULT_TIMEOUT = 30.0


# ============================================================
# AUDIO RESULT
# ============================================================

@dataclass
class ChatterboxAudio:
    pcm: bytes
    sample_rate: int
    channels: int
    sample_width: int
    duration: float
    generation_ms: float


# ============================================================
# CLIENT
# ============================================================

class ChatterboxClient:

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout

        self.base_url = (
            f"http://{self.host}:{self.port}"
        )


    # ========================================================
    # HEALTH
    # ========================================================

    def health(self) -> dict:

        url = (
            f"{self.base_url}/health"
        )

        try:

            with urlopen(
                url,
                timeout=self.timeout,
            ) as response:

                raw = response.read()

        except URLError as exc:

            raise RuntimeError(
                "Chatterbox service is not reachable. "
                "Make sure services.chatterbox_server is running."
            ) from exc


        return json.loads(
            raw.decode("utf-8")
        )


    # ========================================================
    # SYNTHESIZE
    # ========================================================

    def synthesize(
        self,
        text: str,
    ) -> ChatterboxAudio:

        text = text.strip()

        if not text:

            raise ValueError(
                "TTS text cannot be empty."
            )


        url = (
            f"{self.base_url}/synthesize"
        )


        body = json.dumps(
            {
                "text": text,
            }
        ).encode("utf-8")


        request = Request(
            url=url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "audio/wav",
            },
        )


        request_start = (
            time.perf_counter()
        )


        try:

            with urlopen(
                request,
                timeout=self.timeout,
            ) as response:

                wav_bytes = (
                    response.read()
                )

                generation_header = (
                    response.headers.get(
                        "X-TTS-Generation-MS"
                    )
                )


        except HTTPError as exc:

            error_body = (
                exc.read()
                .decode(
                    "utf-8",
                    errors="replace",
                )
            )

            raise RuntimeError(
                f"Chatterbox HTTP error "
                f"{exc.code}: {error_body}"
            ) from exc


        except URLError as exc:

            raise RuntimeError(
                "Chatterbox service is not reachable. "
                "Make sure the TTS server is running."
            ) from exc


        total_request_time = (
            time.perf_counter()
            - request_start
        )


        # ----------------------------------------------------
        # DECODE WAV
        # ----------------------------------------------------

        with wave.open(
            io.BytesIO(wav_bytes),
            "rb",
        ) as wav_file:

            channels = (
                wav_file.getnchannels()
            )

            sample_width = (
                wav_file.getsampwidth()
            )

            sample_rate = (
                wav_file.getframerate()
            )

            frame_count = (
                wav_file.getnframes()
            )

            pcm = (
                wav_file.readframes(
                    frame_count
                )
            )


        duration = (
            frame_count
            / sample_rate
            if sample_rate > 0
            else 0.0
        )


        if generation_header:

            try:

                generation_ms = float(
                    generation_header
                )

            except ValueError:

                generation_ms = (
                    total_request_time
                    * 1000.0
                )

        else:

            generation_ms = (
                total_request_time
                * 1000.0
            )


        print(
            f"[CHATTERBOX CLIENT] "
            f"generation={generation_ms:.1f}ms "
            f"request={total_request_time * 1000:.1f}ms "
            f"audio={duration:.2f}s "
            f"rate={sample_rate}Hz"
        )


        return ChatterboxAudio(
            pcm=pcm,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
            duration=duration,
            generation_ms=generation_ms,
        )


    # ========================================================
    # FLOAT32 CONVERSION
    # ========================================================

    def synthesize_float32(
        self,
        text: str,
    ) -> tuple[np.ndarray, int]:

        result = self.synthesize(
            text
        )


        if result.sample_width != 2:

            raise RuntimeError(
                f"Expected 16-bit PCM, "
                f"got sample width "
                f"{result.sample_width} bytes."
            )


        audio = np.frombuffer(
            result.pcm,
            dtype=np.int16,
        ).astype(
            np.float32
        )


        audio /= 32768.0


        if result.channels > 1:

            audio = audio.reshape(
                -1,
                result.channels,
            )


        return (
            audio,
            result.sample_rate,
        )


# ============================================================
# MANUAL TEST
# ============================================================

if __name__ == "__main__":

    client = ChatterboxClient()


    print()
    print("=" * 60)
    print("CHATTERBOX CLIENT TEST")
    print("=" * 60)


    print()
    print("[TEST] Checking service...")


    info = client.health()


    print(
        f"[TEST] status={info.get('status')}"
    )

    print(
        f"[TEST] model={info.get('model')}"
    )

    print(
        f"[TEST] device={info.get('device')}"
    )

    print(
        f"[TEST] sample_rate="
        f"{info.get('sample_rate')}"
    )


    print()
    print("[TEST] Synthesizing...")


    result = client.synthesize(
        "Hello! I am Alexa Lite. How can I help you today?"
    )


    print()
    print(
        f"[TEST] PCM bytes: "
        f"{len(result.pcm)}"
    )

    print(
        f"[TEST] Duration : "
        f"{result.duration:.2f}s"
    )

    print(
        f"[TEST] Rate     : "
        f"{result.sample_rate}Hz"
    )

    print(
        f"[TEST] Channels : "
        f"{result.channels}"
    )

    print()
    print("=" * 60)
    print("CLIENT TEST COMPLETE")
    print("=" * 60)