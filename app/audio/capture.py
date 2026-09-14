"""
Microphone Capture
------------------

Low-latency Windows microphone capture using sounddevice.

Controls:

    Press ENTER to stop recording.

Audio format:

    16 kHz
    mono
    float32

This format can be passed directly to Parakeet STT.
"""

import time
import msvcrt

import numpy as np
import sounddevice as sd

from app.config import (
    AUDIO_INPUT_DEVICE,
    MIC_SAMPLE_RATE,
    MIC_CHANNELS,
)


# ============================================================
# DEVICE LISTING
# ============================================================

def list_input_devices():
    """
    Show all available microphone/input devices.
    """

    devices = sd.query_devices()

    print()
    print("=" * 70)
    print("INPUT DEVICES")
    print("=" * 70)

    for index, device in enumerate(devices):

        if device["max_input_channels"] <= 0:
            continue

        print(
            f"{index:>3} : "
            f"{device['name']} "
            f"(inputs={device['max_input_channels']}, "
            f"default_sr={device['default_samplerate']:.0f})"
        )

    print("=" * 70)
    print()


# ============================================================
# KEYBOARD BUFFER
# ============================================================

def _clear_keyboard_buffer():
    """
    Remove pending key presses before recording starts.

    This avoids the Windows issue where the ENTER used to start
    a command immediately stops recording.
    """

    while msvcrt.kbhit():
        msvcrt.getwch()


# ============================================================
# MANUAL PUSH-TO-TALK RECORDING
# ============================================================

def record_until_enter(
    device=None,
    sample_rate=None,
):
    """
    Record audio until ENTER is pressed.

    Returns:
        numpy.ndarray float32 mono audio
    """

    if device is None:
        device = AUDIO_INPUT_DEVICE

    if sample_rate is None:
        sample_rate = MIC_SAMPLE_RATE

    frames = []

    # --------------------------------------------------------
    # AUDIO CALLBACK
    # --------------------------------------------------------

    def callback(
        indata,
        frame_count,
        time_info,
        status,
    ):

        if status:
            print(
                f"[MIC] {status}"
            )

        frames.append(
            indata.copy()
        )

    # --------------------------------------------------------
    # PREPARE
    # --------------------------------------------------------

    _clear_keyboard_buffer()

    print()
    print("=" * 60)
    print("RECORDING")
    print("=" * 60)
    print("Speak now.")
    print("Press ENTER when finished.")
    print("=" * 60)

    # --------------------------------------------------------
    # STREAM
    # --------------------------------------------------------

    start_time = time.perf_counter()

    with sd.InputStream(
        samplerate=sample_rate,
        channels=MIC_CHANNELS,
        dtype="float32",
        device=device,
        blocksize=512,
        latency="low",
        callback=callback,
    ):

        while True:

            if msvcrt.kbhit():

                key = msvcrt.getwch()

                if key == "\r":

                    # Prevent accidental immediate stop caused
                    # by stale keyboard input.
                    if (
                        time.perf_counter()
                        - start_time
                        >= 0.25
                    ):
                        break

            time.sleep(
                0.005
            )

    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    elapsed = (
        time.perf_counter()
        - start_time
    )

    print(
        f"[MIC] Recording stopped "
        f"duration={elapsed:.2f}s"
    )

    if not frames:

        print(
            "[MIC] No microphone samples received."
        )

        return np.array(
            [],
            dtype=np.float32,
        )

    audio = np.concatenate(
        frames,
        axis=0,
    )

    audio = audio.flatten().astype(
        np.float32,
        copy=False,
    )

    print(
        f"[MIC] Captured "
        f"{len(audio):,} samples"
    )

    return audio


# ============================================================
# FIXED-DURATION RECORDING
# ============================================================

def record_audio(
    duration: float = 5.0,
    device=None,
    sample_rate=None,
):
    """
    Record for a fixed duration.

    Useful for testing and benchmarking.
    """

    if device is None:
        device = AUDIO_INPUT_DEVICE

    if sample_rate is None:
        sample_rate = MIC_SAMPLE_RATE

    sample_count = int(
        duration
        * sample_rate
    )

    print(
        f"[MIC] Recording for "
        f"{duration:.1f}s..."
    )

    audio = sd.rec(
        sample_count,
        samplerate=sample_rate,
        channels=MIC_CHANNELS,
        dtype="float32",
        device=device,
        blocking=True,
    )

    return (
        audio
        .flatten()
        .astype(
            np.float32,
            copy=False,
        )
    )