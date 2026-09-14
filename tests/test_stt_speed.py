import time
import wave
from pathlib import Path

import numpy as np

from app.audio.stt import ParakeetSTT


ROOT = Path(__file__).resolve().parents[1]

TEST_WAV_DIR = (
    ROOT
    / "models"
    / "parakeet"
    / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
    / "test_wavs"
)


def load_wav(path: Path):

    with wave.open(
        str(path),
        "rb",
    ) as wav_file:

        channels = (
            wav_file.getnchannels()
        )

        sample_rate = (
            wav_file.getframerate()
        )

        sample_width = (
            wav_file.getsampwidth()
        )

        frames = wav_file.readframes(
            wav_file.getnframes()
        )

    if sample_width != 2:
        raise ValueError(
            f"Expected 16-bit WAV: {path}"
        )

    audio = np.frombuffer(
        frames,
        dtype=np.int16,
    ).astype(np.float32)

    audio /= 32768.0

    if channels > 1:
        audio = audio.reshape(
            -1,
            channels,
        ).mean(
            axis=1
        )

    return (
        audio,
        sample_rate,
    )


def main():

    print()
    print("=" * 60)
    print("PARAKEET STT BENCHMARK")
    print("=" * 60)

    stt = ParakeetSTT()

    wav_files = sorted(
        TEST_WAV_DIR.glob("*.wav")
    )

    if not wav_files:
        raise FileNotFoundError(
            f"No WAV files found in {TEST_WAV_DIR}"
        )

    print(
        f"[TEST] Found "
        f"{len(wav_files)} WAV file(s)"
    )

    for wav_path in wav_files:

        audio, sample_rate = (
            load_wav(
                wav_path
            )
        )

        print()
        print("-" * 60)
        print(
            f"FILE: {wav_path.name}"
        )

        start = time.perf_counter()

        text = stt.transcribe(
            audio,
            sample_rate,
        )

        total = (
            time.perf_counter()
            - start
        )

        print(
            f"TEXT : {text}"
        )

        print(
            f"TOTAL: "
            f"{total * 1000:.1f} ms"
        )


if __name__ == "__main__":
    main()