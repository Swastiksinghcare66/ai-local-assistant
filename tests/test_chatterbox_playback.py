"""
Chatterbox Turbo Playback Test
------------------------------

Tests:

Alexa main .venv
    ->
Chatterbox HTTP service
    ->
24 kHz PCM
    ->
Windows speaker

Keep the Chatterbox server running in the other PowerShell.
"""

import time

import sounddevice as sd

from app.audio.chatterbox_client import ChatterboxClient


TEST_TEXT = (
    "Hello! I am Alexa Lite. "
    "This is my new conversational voice."
)


def main():

    print()
    print("=" * 70)
    print("CHATTERBOX TURBO PLAYBACK TEST")
    print("=" * 70)

    client = ChatterboxClient()


    # ========================================================
    # CHECK SERVER
    # ========================================================

    print()
    print("[TEST] Checking Chatterbox service...")

    info = client.health()

    print(
        f"[TEST] status      : {info.get('status')}"
    )

    print(
        f"[TEST] model       : {info.get('model')}"
    )

    print(
        f"[TEST] device      : {info.get('device')}"
    )

    print(
        f"[TEST] sample rate : {info.get('sample_rate')}"
    )


    # ========================================================
    # SYNTHESIS
    # ========================================================

    print()
    print(f"[TEST] Text: {TEST_TEXT}")
    print()
    print("[TEST] Generating speech...")


    total_start = time.perf_counter()


    synthesis_start = time.perf_counter()

    result = client.synthesize(
        TEST_TEXT
    )

    synthesis_end = time.perf_counter()


    synthesis_ms = (
        synthesis_end
        - synthesis_start
    ) * 1000.0


    print()
    print(
        f"[TEST] Synthesis complete : "
        f"{synthesis_ms:.1f} ms"
    )

    print(
        f"[TEST] Audio duration     : "
        f"{result.duration:.2f} s"
    )

    print(
        f"[TEST] Sample rate        : "
        f"{result.sample_rate} Hz"
    )

    print(
        f"[TEST] Channels           : "
        f"{result.channels}"
    )

    print(
        f"[TEST] Sample width       : "
        f"{result.sample_width * 8}-bit"
    )


    # ========================================================
    # PLAYBACK
    # ========================================================

    print()
    print("[AUDIO] Playing...")


    playback_start = time.perf_counter()


    stream = sd.RawOutputStream(
        samplerate=result.sample_rate,
        channels=result.channels,
        dtype="int16",
    )


    try:

        stream.start()

        first_audio = time.perf_counter()

        stream.write(
            result.pcm
        )

        stream.stop()


    finally:

        stream.close()


    playback_end = time.perf_counter()


    first_audio_ms = (
        first_audio
        - total_start
    ) * 1000.0


    playback_ms = (
        playback_end
        - playback_start
    ) * 1000.0


    total_ms = (
        playback_end
        - total_start
    ) * 1000.0


    # ========================================================
    # RESULTS
    # ========================================================

    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)

    print(
        f"TTS generation     : "
        f"{result.generation_ms:.1f} ms"
    )

    print(
        f"Client synthesis   : "
        f"{synthesis_ms:.1f} ms"
    )

    print(
        f"FIRST AUDIO        : "
        f"{first_audio_ms:.1f} ms"
    )

    print(
        f"Audio duration     : "
        f"{result.duration:.2f} s"
    )

    print(
        f"Playback duration  : "
        f"{playback_ms:.1f} ms"
    )

    print(
        f"Total test         : "
        f"{total_ms:.1f} ms"
    )

    print("=" * 70)

    print()
    print("[TEST] Playback complete.")


if __name__ == "__main__":
    main()