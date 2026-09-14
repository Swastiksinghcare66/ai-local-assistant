"""
Live Microphone -> Parakeet STT Test
-----------------------------------

Flow:

    microphone
        ↓
    16 kHz mono float32
        ↓
    Parakeet
        ↓
    text
"""

import time

from app.audio.capture import (
    record_until_enter,
)
from app.audio.stt import ParakeetSTT
from app.config import (
    AUDIO_INPUT_DEVICE,
    MIC_SAMPLE_RATE,
)


def main():

    print()
    print("=" * 60)
    print("LIVE MICROPHONE -> PARAKEET")
    print("=" * 60)

    print(
        f"Input device : "
        f"{AUDIO_INPUT_DEVICE}"
    )

    print(
        f"Sample rate  : "
        f"{MIC_SAMPLE_RATE} Hz"
    )

    print()

    # --------------------------------------------------------
    # LOAD STT ONCE
    # --------------------------------------------------------

    stt = ParakeetSTT()

    print()
    print("STT ready.")

    # --------------------------------------------------------
    # RECORD
    # --------------------------------------------------------

    audio = record_until_enter()

    if audio.size == 0:

        print()
        print("No audio captured.")
        return

    # --------------------------------------------------------
    # TRANSCRIBE
    # --------------------------------------------------------

    print()
    print("Transcribing...")

    start = time.perf_counter()

    text = stt.transcribe(
        audio,
        MIC_SAMPLE_RATE,
    )

    elapsed = (
        time.perf_counter()
        - start
    )

    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("YOU SAID")
    print("=" * 60)

    print(
        text
        if text
        else "[No speech recognized]"
    )

    print("=" * 60)

    print(
        f"STT total: "
        f"{elapsed * 1000:.1f} ms"
    )


if __name__ == "__main__":
    main()