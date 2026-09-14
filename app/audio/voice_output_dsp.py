from __future__ import annotations

import math
from array import array
from dataclasses import dataclass


def _db_to_linear(db: float) -> float:
    return 10.0 ** (float(db) / 20.0)


def _linear_to_db(value: float) -> float:
    value = max(float(value), 1.0e-12)
    return 20.0 * math.log10(value)


class _Biquad:
    def __init__(self, b0, b1, b2, a0, a1, a2):
        if abs(a0) < 1.0e-12:
            raise ValueError("Invalid biquad a0")

        self.b0 = b0 / a0
        self.b1 = b1 / a0
        self.b2 = b2 / a0
        self.a1 = a1 / a0
        self.a2 = a2 / a0

        self.z1 = 0.0
        self.z2 = 0.0

    def reset(self):
        self.z1 = 0.0
        self.z2 = 0.0

    def process_sample(self, x: float) -> float:
        y = self.b0 * x + self.z1

        self.z1 = (
            self.b1 * x
            - self.a1 * y
            + self.z2
        )

        self.z2 = (
            self.b2 * x
            - self.a2 * y
        )

        return y


def _highpass(sample_rate: int, freq: float, q: float = 0.707) -> _Biquad:
    sr = float(sample_rate)
    freq = min(max(10.0, float(freq)), sr * 0.45)

    w0 = 2.0 * math.pi * freq / sr
    c = math.cos(w0)
    s = math.sin(w0)
    alpha = s / (2.0 * q)

    b0 = (1.0 + c) / 2.0
    b1 = -(1.0 + c)
    b2 = (1.0 + c) / 2.0
    a0 = 1.0 + alpha
    a1 = -2.0 * c
    a2 = 1.0 - alpha

    return _Biquad(b0, b1, b2, a0, a1, a2)


def _peaking(
    sample_rate: int,
    freq: float,
    gain_db: float,
    q: float = 1.0,
) -> _Biquad:
    sr = float(sample_rate)
    freq = min(max(20.0, float(freq)), sr * 0.45)

    a = 10.0 ** (float(gain_db) / 40.0)
    w0 = 2.0 * math.pi * freq / sr
    c = math.cos(w0)
    s = math.sin(w0)
    alpha = s / (2.0 * q)

    b0 = 1.0 + alpha * a
    b1 = -2.0 * c
    b2 = 1.0 - alpha * a
    a0 = 1.0 + alpha / a
    a1 = -2.0 * c
    a2 = 1.0 - alpha / a

    return _Biquad(b0, b1, b2, a0, a1, a2)


def _high_shelf(
    sample_rate: int,
    freq: float,
    gain_db: float,
    slope: float = 1.0,
) -> _Biquad:
    sr = float(sample_rate)
    freq = min(max(100.0, float(freq)), sr * 0.44)

    a = 10.0 ** (float(gain_db) / 40.0)
    w0 = 2.0 * math.pi * freq / sr
    c = math.cos(w0)
    s = math.sin(w0)
    slope = max(0.1, float(slope))

    alpha = (
        s
        / 2.0
        * math.sqrt(
            (a + 1.0 / a)
            * (1.0 / slope - 1.0)
            + 2.0
        )
    )

    two_sqrt_a_alpha = (
        2.0
        * math.sqrt(a)
        * alpha
    )

    b0 = a * (
        (a + 1.0)
        + (a - 1.0) * c
        + two_sqrt_a_alpha
    )

    b1 = -2.0 * a * (
        (a - 1.0)
        + (a + 1.0) * c
    )

    b2 = a * (
        (a + 1.0)
        + (a - 1.0) * c
        - two_sqrt_a_alpha
    )

    a0 = (
        (a + 1.0)
        - (a - 1.0) * c
        + two_sqrt_a_alpha
    )

    a1 = 2.0 * (
        (a - 1.0)
        - (a + 1.0) * c
    )

    a2 = (
        (a + 1.0)
        - (a - 1.0) * c
        - two_sqrt_a_alpha
    )

    return _Biquad(b0, b1, b2, a0, a1, a2)


@dataclass(frozen=True)
class VoiceDSPPreset:
    name: str
    highpass_hz: float
    low_mid_hz: float
    low_mid_gain_db: float
    low_mid_q: float
    presence_hz: float
    presence_gain_db: float
    presence_q: float
    air_hz: float
    air_gain_db: float
    compressor_threshold_db: float
    compressor_ratio: float
    compressor_attack_ms: float
    compressor_release_ms: float
    makeup_gain_db: float
    limiter_ceiling_db: float


_PRESETS = {
    "warm_clear": VoiceDSPPreset(
        name="warm_clear",
        highpass_hz=95.0,
        low_mid_hz=280.0,
        low_mid_gain_db=-1.4,
        low_mid_q=0.85,
        presence_hz=3200.0,
        presence_gain_db=1.1,
        presence_q=0.90,
        air_hz=5600.0,
        air_gain_db=0.6,
        compressor_threshold_db=-18.0,
        compressor_ratio=1.70,
        compressor_attack_ms=10.0,
        compressor_release_ms=100.0,
        makeup_gain_db=0.8,
        limiter_ceiling_db=-1.0,
    ),

    "soft": VoiceDSPPreset(
        name="soft",
        highpass_hz=90.0,
        low_mid_hz=260.0,
        low_mid_gain_db=-0.8,
        low_mid_q=0.85,
        presence_hz=2800.0,
        presence_gain_db=0.7,
        presence_q=0.90,
        air_hz=5400.0,
        air_gain_db=0.3,
        compressor_threshold_db=-19.0,
        compressor_ratio=1.55,
        compressor_attack_ms=14.0,
        compressor_release_ms=120.0,
        makeup_gain_db=0.6,
        limiter_ceiling_db=-1.0,
    ),

    "bright": VoiceDSPPreset(
        name="bright",
        highpass_hz=105.0,
        low_mid_hz=300.0,
        low_mid_gain_db=-1.8,
        low_mid_q=0.85,
        presence_hz=3400.0,
        presence_gain_db=1.6,
        presence_q=0.90,
        air_hz=5900.0,
        air_gain_db=0.9,
        compressor_threshold_db=-18.0,
        compressor_ratio=1.75,
        compressor_attack_ms=9.0,
        compressor_release_ms=90.0,
        makeup_gain_db=0.7,
        limiter_ceiling_db=-1.0,
    ),
}


class VoiceOutputDSP:
    """
    Stateful PCM16-mono speaker-output polish for SIA.

    Signal chain:
        high-pass
        -> low-mid cleanup
        -> presence EQ
        -> gentle high shelf
        -> soft compressor
        -> transparent peak limiter
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        *,
        enabled: bool = True,
        preset: str = "warm_clear",
    ):
        self.sample_rate = int(sample_rate)
        self.enabled = bool(enabled)

        preset_key = str(
            preset or "warm_clear"
        ).strip().lower()

        self.preset = _PRESETS.get(
            preset_key,
            _PRESETS["warm_clear"],
        )

        p = self.preset

        self._filters = [
            _highpass(
                self.sample_rate,
                p.highpass_hz,
            ),
            _peaking(
                self.sample_rate,
                p.low_mid_hz,
                p.low_mid_gain_db,
                p.low_mid_q,
            ),
            _peaking(
                self.sample_rate,
                p.presence_hz,
                p.presence_gain_db,
                p.presence_q,
            ),
            _high_shelf(
                self.sample_rate,
                p.air_hz,
                p.air_gain_db,
            ),
        ]

        self._env = 0.0

        attack_s = max(
            0.001,
            p.compressor_attack_ms / 1000.0,
        )

        release_s = max(
            0.005,
            p.compressor_release_ms / 1000.0,
        )

        self._attack_coeff = math.exp(
            -1.0
            / (
                attack_s
                * self.sample_rate
            )
        )

        self._release_coeff = math.exp(
            -1.0
            / (
                release_s
                * self.sample_rate
            )
        )

        self._threshold = _db_to_linear(
            p.compressor_threshold_db
        )

        self._makeup = _db_to_linear(
            p.makeup_gain_db
        )

        self._ceiling = _db_to_linear(
            p.limiter_ceiling_db
        )

    def reset(self):
        for stage in self._filters:
            stage.reset()

        self._env = 0.0

    def describe(self) -> str:
        p = self.preset

        return (
            f"preset={p.name} "
            f"HPF={p.highpass_hz:.0f}Hz "
            f"mud={p.low_mid_gain_db:+.1f}dB@{p.low_mid_hz:.0f}Hz "
            f"presence={p.presence_gain_db:+.1f}dB@{p.presence_hz:.0f}Hz "
            f"air={p.air_gain_db:+.1f}dB@{p.air_hz:.0f}Hz "
            f"comp={p.compressor_ratio:.2f}:1 "
            f"limit={p.limiter_ceiling_db:.1f}dBFS"
        )

    def process(self, pcm16: bytes) -> bytes:
        if not pcm16:
            return b""

        if not self.enabled:
            return pcm16

        if len(pcm16) & 1:
            pcm16 = pcm16[:-1]

        if not pcm16:
            return b""

        samples = array("h")
        samples.frombytes(pcm16)

        p = self.preset
        threshold = self._threshold
        ratio = max(1.0, p.compressor_ratio)
        ceiling = self._ceiling
        makeup = self._makeup

        attack_coeff = self._attack_coeff
        release_coeff = self._release_coeff

        env = self._env
        output = array("h")

        for raw in samples:
            x = float(raw) / 32768.0

            for stage in self._filters:
                x = stage.process_sample(x)

            level = abs(x)

            coeff = (
                attack_coeff
                if level > env
                else release_coeff
            )

            env = (
                coeff * env
                + (1.0 - coeff) * level
            )

            compressor_gain = 1.0

            if env > threshold:
                over_db = _linear_to_db(
                    env / threshold
                )

                reduction_db = (
                    over_db
                    - over_db / ratio
                )

                compressor_gain = (
                    _db_to_linear(
                        -reduction_db
                    )
                )

            y = (
                x
                * compressor_gain
                * makeup
            )

            if y > ceiling:
                y = ceiling
            elif y < -ceiling:
                y = -ceiling

            value = int(
                round(
                    y * 32767.0
                )
            )

            if value > 32767:
                value = 32767
            elif value < -32768:
                value = -32768

            output.append(value)

        self._env = env

        return output.tobytes()
