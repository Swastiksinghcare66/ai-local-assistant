"""
Chatterbox Turbo GPU Benchmark
------------------------------

Measures:

- model loading time
- GPU VRAM usage
- warm generation time
- synthesis latency
- generated audio duration
- realtime factor

IMPORTANT:

Chatterbox Turbo's standard generate() API returns the complete
waveform, so generation time is effectively time-to-first-audio
for this basic implementation.
"""

import time

import torch
import torchaudio

from chatterbox.tts_turbo import ChatterboxTurboTTS


DEVICE = "cuda"

TEST_TEXTS = [
    "Hello, I am Alexa Lite.",
    "Hello! How can I help you today?",
    (
        "I'm doing well. I'm ready to answer your questions "
        "or just have a conversation."
    ),
]


# ============================================================
# GPU MEMORY
# ============================================================

def gpu_memory_mb():

    allocated = (
        torch.cuda.memory_allocated()
        / 1024
        / 1024
    )

    reserved = (
        torch.cuda.memory_reserved()
        / 1024
        / 1024
    )

    peak = (
        torch.cuda.max_memory_allocated()
        / 1024
        / 1024
    )

    return allocated, reserved, peak


# ============================================================
# SYNTH TEST
# ============================================================

def test_synthesis(
    model,
    text,
    index,
):

    torch.cuda.reset_peak_memory_stats()

    torch.cuda.synchronize()

    start = time.perf_counter()

    wav = model.generate(
        text,
    )

    torch.cuda.synchronize()

    end = time.perf_counter()

    synthesis_time = (
        end - start
    )

    # Chatterbox waveform shape normally:
    #
    # [1, samples]
    #
    sample_count = (
        wav.shape[-1]
    )

    audio_duration = (
        sample_count
        / model.sr
    )

    if audio_duration > 0:

        realtime_factor = (
            synthesis_time
            / audio_duration
        )

    else:

        realtime_factor = 0.0


    allocated, reserved, peak = (
        gpu_memory_mb()
    )


    print()
    print("=" * 70)
    print(f"TEST {index}")
    print("=" * 70)

    print(
        f"TEXT       : {text}"
    )

    print(
        f"GENERATE   : "
        f"{synthesis_time * 1000:.1f} ms"
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
        f"SAMPLE RATE: "
        f"{model.sr} Hz"
    )

    print(
        f"GPU alloc  : "
        f"{allocated:.0f} MB"
    )

    print(
        f"GPU reserve: "
        f"{reserved:.0f} MB"
    )

    print(
        f"GPU peak   : "
        f"{peak:.0f} MB"
    )


    # Save only the first real test so you can listen to quality.

    if index == 1:

        output = (
            "D:/Alexa_lite/Alexa_lite/"
            "chatterbox_turbo_test.wav"
        )

        torchaudio.save(
            output,
            wav.cpu(),
            model.sr,
        )

        print(
            f"Saved      : {output}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("CHATTERBOX TURBO - RTX GPU BENCHMARK")
    print("=" * 70)

    print(
        f"Torch       : "
        f"{torch.__version__}"
    )

    print(
        f"CUDA        : "
        f"{torch.cuda.is_available()}"
    )

    print(
        f"GPU         : "
        f"{torch.cuda.get_device_name(0)}"
    )


    # ========================================================
    # LOAD MODEL
    # ========================================================

    print()
    print("[TTS] Loading Chatterbox Turbo...")

    torch.cuda.empty_cache()

    torch.cuda.reset_peak_memory_stats()

    load_start = time.perf_counter()

    model = (
        ChatterboxTurboTTS
        .from_pretrained(
            device=DEVICE,
        )
    )

    torch.cuda.synchronize()

    load_time = (
        time.perf_counter()
        - load_start
    )


    allocated, reserved, peak = (
        gpu_memory_mb()
    )


    print()
    print(
        f"[TTS] Model load     : "
        f"{load_time:.2f} s"
    )

    print(
        f"[TTS] GPU allocated  : "
        f"{allocated:.0f} MB"
    )

    print(
        f"[TTS] GPU reserved   : "
        f"{reserved:.0f} MB"
    )

    print(
        f"[TTS] GPU peak load  : "
        f"{peak:.0f} MB"
    )


    # ========================================================
    # WARMUP
    # ========================================================

    print()
    print("[TTS] Warmup...")

    torch.cuda.synchronize()

    warm_start = time.perf_counter()

    _ = model.generate(
        "Hello."
    )

    torch.cuda.synchronize()

    warm_time = (
        time.perf_counter()
        - warm_start
    )

    print(
        f"[TTS] Warmup complete: "
        f"{warm_time * 1000:.1f} ms"
    )


    # ========================================================
    # TESTS
    # ========================================================

    for index, text in enumerate(
        TEST_TEXTS,
        start=1,
    ):

        test_synthesis(
            model=model,
            text=text,
            index=index,
        )


    print()
    print("=" * 70)
    print("BENCHMARK COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()