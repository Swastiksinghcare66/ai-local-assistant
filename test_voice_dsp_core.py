from __future__ import annotations

import math
from array import array

from app.audio.voice_output_dsp import VoiceOutputDSP


SAMPLE_RATE = 16000


def make_test_pcm() -> bytes:
    data = array("h")

    for n in range(SAMPLE_RATE):
        t = n / SAMPLE_RATE

        x = (
            0.24 * math.sin(2.0 * math.pi * 220.0 * t)
            + 0.12 * math.sin(2.0 * math.pi * 280.0 * t)
            + 0.09 * math.sin(2.0 * math.pi * 3200.0 * t)
        )

        value = int(
            max(
                -32768,
                min(
                    32767,
                    round(x * 32767.0),
                ),
            )
        )

        data.append(value)

    return data.tobytes()


pcm = make_test_pcm()

dsp = VoiceOutputDSP(
    sample_rate=SAMPLE_RATE,
    enabled=True,
    preset="warm_clear",
)

processed = dsp.process(pcm)

assert processed
assert len(processed) == len(pcm)

out = array("h")
out.frombytes(processed)

peak = max(abs(int(x)) for x in out)

assert peak <= 32767

print("VOICE DSP CORE TEST: PASS")
print(dsp.describe())
print("bytes:", len(processed))
print("peak:", peak)
