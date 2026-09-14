import time
from pathlib import Path

from piper.voice import PiperVoice


ROOT = Path(__file__).resolve().parents[1]

MODEL_PATH = (
    ROOT
    / "models"
    / "piper"
    / "en_US-lessac-low.onnx"
)

CONFIG_PATH = (
    ROOT
    / "models"
    / "piper"
    / "en_US-lessac-low.onnx.json"
)


TEST_SENTENCES = [
    "Hello, how are you?",
    "I'm doing great. What can I help you with?",
    "The weather looks nice today.",
]


def synthesize_test(voice, text):

    start = time.perf_counter()

    first_audio_time = None

    total_bytes = 0
    sample_rate = None
    sample_width = None
    sample_channels = None

    for chunk in voice.synthesize(text):

        now = time.perf_counter()

        if first_audio_time is None:
            first_audio_time = now

        audio_bytes = chunk.audio_int16_bytes

        total_bytes += len(audio_bytes)

        sample_rate = chunk.sample_rate
        sample_width = chunk.sample_width
        sample_channels = chunk.sample_channels

    end = time.perf_counter()

    total_time = end - start

    if first_audio_time is None:
        first_audio_latency = total_time
    else:
        first_audio_latency = (
            first_audio_time - start
        )

    if (
        sample_rate
        and sample_width
        and sample_channels
    ):
        audio_duration = (
            total_bytes
            / sample_rate
            / sample_width
            / sample_channels
        )
    else:
        audio_duration = 0.0

    if audio_duration > 0:
        realtime_factor = (
            total_time / audio_duration
        )
    else:
        realtime_factor = 0.0

    print()
    print("-" * 60)
    print(f"TEXT       : {text}")
    print(
        f"FIRST AUDIO: "
        f"{first_audio_latency * 1000:.1f} ms"
    )
    print(
        f"SYNTH TOTAL: "
        f"{total_time * 1000:.1f} ms"
    )
    print(
        f"AUDIO LEN  : "
        f"{audio_duration:.2f} s"
    )
    print(
        f"RTF        : "
        f"{realtime_factor:.3f}"
    )
    print(
        f"PCM BYTES  : "
        f"{total_bytes:,}"
    )


def main():

    print()
    print("=" * 60)
    print("PIPER LOW-LATENCY BENCHMARK")
    print("=" * 60)

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            MODEL_PATH
        )

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            CONFIG_PATH
        )

    print()
    print("Loading Piper...")

    load_start = time.perf_counter()

    voice = PiperVoice.load(
        str(MODEL_PATH),
        config_path=str(CONFIG_PATH),
        use_cuda=False,
    )

    load_time = (
        time.perf_counter()
        - load_start
    )

    print(
        f"Model load: "
        f"{load_time:.3f} s"
    )

    # First synthesis can contain one-time initialization cost.
    print()
    print("Warmup...")

    for _ in voice.synthesize("Hello."):
        pass

    print("Warmup complete.")

    for sentence in TEST_SENTENCES:
        synthesize_test(
            voice,
            sentence,
        )


if __name__ == "__main__":
    main()