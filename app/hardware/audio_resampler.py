from __future__ import annotations

import numpy as np

try:
    import soxr
except ImportError as exc:
    raise RuntimeError(
        "SIA hardware audio requires python-soxr. "
        "Install with: python -m pip install soxr"
    ) from exc


class PCM16StreamingResampler:
    """
    Stateful high-quality mono PCM16 streaming resampler.

    SIA product conversation mode:
        CosyVoice: 24 kHz PCM16 mono
        ESP-SR AEC path: 16 kHz PCM16 mono

    SoXR HQ is used instead of independently resampling every websocket
    packet, because packet-wise stateless conversion creates boundary
    discontinuities and can degrade the AEC reference.
    """

    def __init__(
        self,
        input_rate: int = 24000,
        output_rate: int = 16000,
        quality: str = "HQ",
    ):
        self.input_rate = int(input_rate)
        self.output_rate = int(output_rate)
        self.quality = str(quality)
        self._new_stream()

    def _new_stream(self):
        self._stream = soxr.ResampleStream(
            self.input_rate,
            self.output_rate,
            1,
            dtype="int16",
            quality=self.quality,
        )

    def reset(self):
        self._stream.clear()

    def process(self, pcm16_le: bytes, *, last: bool = False) -> bytes:
        if len(pcm16_le) & 1:
            raise ValueError("PCM16 input byte count must be even.")

        samples = np.frombuffer(
            pcm16_le,
            dtype="<i2",
        )

        # soxr accepts an empty array with last=True to flush pending samples.
        output = self._stream.resample_chunk(
            samples,
            last=last,
        )

        if output.size == 0:
            return b""

        return np.asarray(
            output,
            dtype="<i2",
        ).tobytes()
