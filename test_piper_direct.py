import time
import wave
import audioop

import numpy as np
import sounddevice as sd

from piper import PiperVoice

from app.audio.sia_hardware import SIAHardware
from app.config import (
    PIPER_MODEL_PATH,
    PIPER_CONFIG_PATH,
)


MODEL = str(PIPER_MODEL_PATH)
CONFIG = str(PIPER_CONFIG_PATH)

TEXT = (
    "हाँ स्वस्तिक, यह पाइपर ऑडियो टेस्ट है। "
    "अगर यह आवाज़ सुनाई दे रही है, तो हिंदी टी टी एस सही काम कर रहा है।"
)


print("=" * 70)
print("PIPER RAW PCM DIAGNOSTIC")
print("=" * 70)

voice = PiperVoice.load(
    MODEL,
    config_path=CONFIG,
    use_cuda=False,
)

pcm_parts = []
sample_rate = None


print()
print("[1] Synthesizing Piper audio...")

start = time.perf_counter()

for chunk in voice.synthesize(TEXT):

    pcm = chunk.audio_int16_bytes

    if not pcm:
        continue

    if sample_rate is None:
        sample_rate = int(
            chunk.sample_rate
        )

    pcm_parts.append(
        bytes(pcm)
    )


elapsed = (
    time.perf_counter()
    - start
)

if not pcm_parts:
    raise RuntimeError(
        "Piper generated zero PCM."
    )


native_pcm = b"".join(
    pcm_parts
)

samples = np.frombuffer(
    native_pcm,
    dtype=np.int16,
)


rms = float(
    np.sqrt(
        np.mean(
            samples.astype(
                np.float64
            ) ** 2
        )
    )
)

peak = int(
    np.max(
        np.abs(
            samples.astype(
                np.int32
            )
        )
    )
)

duration = (
    len(samples)
    / sample_rate
)


print(
    f"Sample rate : {sample_rate}"
)

print(
    f"Duration    : {duration:.2f} s"
)

print(
    f"PCM bytes   : {len(native_pcm)}"
)

print(
    f"RMS         : {rms:.1f}"
)

print(
    f"Peak        : {peak}"
)

print(
    f"Generation  : {elapsed:.2f} s"
)


# ============================================================
# SAVE NATIVE WAV
# ============================================================

wav_path = (
    "test_piper_native.wav"
)

with wave.open(
    wav_path,
    "wb",
) as wf:

    wf.setnchannels(1)

    wf.setsampwidth(2)

    wf.setframerate(
        sample_rate
    )

    wf.writeframes(
        native_pcm
    )


print()
print(
    f"[2] WAV saved: {wav_path}"
)


# ============================================================
# PC SPEAKER TEST
# ============================================================

print()
print(
    "[3] Playing Piper directly on PC..."
)

float_audio = (
    samples.astype(
        np.float32
    )
    / 32768.0
)

sd.play(
    float_audio,
    sample_rate,
)

sd.wait()

print(
    "[3] PC playback finished."
)


# ============================================================
# RESAMPLE DIRECTLY TO ESP FORMAT
# ============================================================

print()
print(
    "[4] Resampling directly to 16 kHz..."
)

pcm16, _ = audioop.ratecv(
    native_pcm,
    2,
    1,
    sample_rate,
    16000,
    None,
)


samples16 = np.frombuffer(
    pcm16,
    dtype=np.int16,
)

peak16 = int(
    np.max(
        np.abs(
            samples16.astype(
                np.int32
            )
        )
    )
)

rms16 = float(
    np.sqrt(
        np.mean(
            samples16.astype(
                np.float64
            ) ** 2
        )
    )
)


print(
    f"16k RMS     : {rms16:.1f}"
)

print(
    f"16k Peak    : {peak16}"
)


# ============================================================
# SAFE GAIN NORMALIZATION
# ============================================================

if peak16 > 0:

    target_peak = 24000

    gain = min(
        4.0,
        target_peak / peak16,
    )

else:

    gain = 1.0


print(
    f"Gain        : {gain:.2f}x"
)

if gain > 1.01:

    pcm16 = audioop.mul(
        pcm16,
        2,
        gain,
    )


# ============================================================
# DIRECT ESP32 PLAYBACK
# ============================================================

print()
print(
    "[5] Sending PCM DIRECTLY to ESP32..."
)

hw = SIAHardware(
    port="COM10"
)

hw.connect(
    timeout=3.0
)

hw.set_route_sia()

hw.tts_start(
    sample_rate=16000,
    channels=1,
    bits_per_sample=16,
)


# 20 ms:
# 16000 samples/sec
# × 0.020 sec
# × 2 bytes
# = 640 bytes

chunk_bytes = 640


for offset in range(
    0,
    len(pcm16),
    chunk_bytes,
):

    chunk = pcm16[
        offset:
        offset + chunk_bytes
    ]

    started = (
        time.perf_counter()
    )

    hw.tts_write(
        chunk,
        chunk_bytes=len(chunk),
    )

    audio_seconds = (
        len(chunk)
        / 2
        / 16000
    )

    elapsed_write = (
        time.perf_counter()
        - started
    )

    remaining = (
        audio_seconds
        - elapsed_write
    )

    if remaining > 0:
        time.sleep(
            remaining
        )


hw.tts_end(
    timeout=8.0
)

print(
    "[5] ESP32 playback finished."
)

hw.set_route_bluetooth()

hw.close()


print()
print("=" * 70)
print("TEST COMPLETE")
print("=" * 70)
