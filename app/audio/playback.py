"""
Audio Playback
--------------

Low-latency raw PCM playback using sounddevice.

Designed for:

    Piper PCM
        ↓
    PCMPlayer
        ↓
    laptop speaker

Later the exact same PCM stream can instead be sent to the ESP32.
"""

import sounddevice as sd

from app.config import (
    AUDIO_OUTPUT_DEVICE,
)


# ============================================================
# OUTPUT DEVICE LIST
# ============================================================

def list_output_devices():
    """
    Show all available output devices.
    """

    devices = sd.query_devices()

    print()
    print("=" * 70)
    print("OUTPUT DEVICES")
    print("=" * 70)

    for index, device in enumerate(devices):

        if device["max_output_channels"] <= 0:
            continue

        print(
            f"{index:>3} : "
            f"{device['name']} "
            f"(outputs={device['max_output_channels']}, "
            f"default_sr={device['default_samplerate']:.0f})"
        )

    print("=" * 70)
    print()


# ============================================================
# PCM PLAYER
# ============================================================

class PCMPlayer:
    """
    Persistent low-latency PCM output stream.

    The stream remains open while audio is being produced,
    avoiding repeated device initialization.
    """

    def __init__(
        self,
        device=None,
    ):

        if device is None:
            device = AUDIO_OUTPUT_DEVICE

        self.device = device

        self.stream = None

        self.sample_rate = None
        self.channels = None


    # ========================================================
    # OPEN STREAM
    # ========================================================

    def open(
        self,
        sample_rate: int,
        channels: int = 1,
    ):

        # Reuse existing stream when format matches.
        if (
            self.stream is not None
            and self.sample_rate == sample_rate
            and self.channels == channels
        ):
            return

        self.close()

        self.sample_rate = sample_rate
        self.channels = channels

        print(
            f"[AUDIO] Opening output "
            f"{sample_rate}Hz "
            f"{channels}ch"
        )

        self.stream = sd.RawOutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
            device=self.device,
            latency="low",
            blocksize=0,
        )

        self.stream.start()


    # ========================================================
    # WRITE PCM
    # ========================================================

    def write(
        self,
        pcm: bytes,
        sample_rate: int,
        channels: int = 1,
        sample_width: int = 2,
    ):
        """
        Play one raw PCM chunk.

        Piper currently produces signed 16-bit PCM,
        so sample_width must be 2 bytes.
        """

        if not pcm:
            return

        if sample_width != 2:
            raise ValueError(
                "PCMPlayer currently supports only 16-bit PCM."
            )

        self.open(
            sample_rate=sample_rate,
            channels=channels,
        )

        self.stream.write(
            pcm
        )


    # ========================================================
    # PLAY TTS STREAM
    # ========================================================

    def play_stream(
        self,
        audio_chunks,
    ):
        """
        Play AudioChunk objects as soon as they arrive.

        No temporary WAV file is created.
        """

        for chunk in audio_chunks:

            self.write(
                pcm=chunk.pcm,
                sample_rate=chunk.sample_rate,
                channels=chunk.channels,
                sample_width=chunk.sample_width,
            )


    # ========================================================
    # CLOSE
    # ========================================================

    def close(self):

        if self.stream is None:
            return

        try:
            self.stream.stop()

        finally:
            self.stream.close()

        self.stream = None
        self.sample_rate = None
        self.channels = None


    # ========================================================
    # CONTEXT MANAGER
    # ========================================================

    def __enter__(self):
        return self


    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        self.close()