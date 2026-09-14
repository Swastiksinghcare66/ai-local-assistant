import numpy as np

from app.hardware.audio_resampler import PCM16StreamingResampler


def main():
    sr_in = 24000
    sr_out = 16000
    seconds = 1.0

    t = np.arange(
        int(sr_in * seconds),
        dtype=np.float64,
    ) / sr_in

    x = (
        np.sin(2 * np.pi * 1000.0 * t)
        * 12000
    ).astype("<i2")

    raw = x.tobytes()

    r = PCM16StreamingResampler(
        input_rate=sr_in,
        output_rate=sr_out,
    )

    output = bytearray()

    # Simulate irregular CosyVoice websocket chunks.
    offsets = [0, 1300, 4096, 8778, 16000, len(raw)]

    for a, b in zip(offsets, offsets[1:]):
        chunk = raw[a:b]

        # Keep PCM16 framing valid.
        if len(chunk) & 1:
            chunk = chunk[:-1]

        output.extend(r.process(chunk))

    output.extend(r.process(b"", last=True))

    y = np.frombuffer(output, dtype="<i2")

    # SoXR has filter delay/flush behavior, but final duration should be close.
    assert abs(len(y) - sr_out) < 64, len(y)

    print(
        f"PASS input={len(x)} samples "
        f"output={len(y)} samples"
    )


if __name__ == "__main__":
    main()
