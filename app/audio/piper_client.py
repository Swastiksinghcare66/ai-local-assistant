from __future__ import annotations

import asyncio
import audioop
import inspect
import math
import threading
import time
from pathlib import Path


class PiperTTSClient:
    """
    Persistent local Hindi/Hinglish Piper client for SIA.

    Audio path:
        Piper native PCM16 mono (~22.05 kHz)
        -> one stateful resample to 16 kHz
        -> light speech dynamics / DC cleanup
        -> paced SIAHardware TtsStart/TtsPcm/TtsEnd
        -> ESP32-S3 -> MAX98357A

    The optional Piper synthesis controls are discovered at runtime. If the
    installed Piper build exposes SynthesisConfig, style-dependent speaking-rate
    and variation controls are used. Otherwise synthesis falls back cleanly to
    the model defaults.
    """

    STYLE_PROFILES = {
        "warm_conversational": {
            "length_scale": 0.97,
            "noise_scale": 0.667,
            "noise_w_scale": 0.80,
            "volume": 1.00,
        },
        "calm_confident": {
            "length_scale": 1.01,
            "noise_scale": 0.62,
            "noise_w_scale": 0.78,
            "volume": 1.00,
        },
        "soft_companion": {
            "length_scale": 1.05,
            "noise_scale": 0.58,
            "noise_w_scale": 0.74,
            "volume": 0.96,
        },
        "serious": {
            "length_scale": 1.03,
            "noise_scale": 0.56,
            "noise_w_scale": 0.72,
            "volume": 0.98,
        },
        "energetic_friendly": {
            "length_scale": 0.93,
            "noise_scale": 0.72,
            "noise_w_scale": 0.86,
            "volume": 1.02,
        },
    }

    def __init__(
        self,
        model_path,
        config_path=None,
        hardware=None,
        player=None,
        target_sample_rate: int = 16000,
        use_cuda: bool = False,
        packet_ms: int = 20,
        target_peak: int = 24000,
        max_gain: float = 2.5,
        target_rms: int = 4300,
        gain_smoothing: float = 0.82,
        dsp_enabled: bool = True,
        prosody_enabled: bool = True,
    ):
        self.model_path = Path(model_path)
        self.config_path = Path(config_path) if config_path else Path(f"{self.model_path}.json")
        self.hardware = hardware
        self.player = player  # compatibility only; Piper uses direct hardware

        self.target_sample_rate = int(target_sample_rate)
        self.use_cuda = bool(use_cuda)
        self.packet_ms = max(10, int(packet_ms))
        self.target_peak = max(1000, min(32000, int(target_peak)))
        self.max_gain = max(1.0, float(max_gain))
        self.target_rms = max(300, int(target_rms))
        self.gain_smoothing = min(0.98, max(0.0, float(gain_smoothing)))
        self.dsp_enabled = bool(dsp_enabled)
        self.prosody_enabled = bool(prosody_enabled)

        self.voice = None
        self._piper_module = None
        self._synthesis_config_cls = None
        self._synthesis_config_param = None

        self._load_lock = asyncio.Lock()
        self._speak_lock = asyncio.Lock()
        self._interrupt_event = threading.Event()
        self._hardware_session_active = False
        self._session_lock = threading.RLock()
        self._smoothed_gain = 1.0

    @property
    def ready(self) -> bool:
        return self.voice is not None

    def _discover_optional_api(self):
        try:
            import piper as piper_module
            self._piper_module = piper_module
            self._synthesis_config_cls = getattr(piper_module, "SynthesisConfig", None)

            try:
                params = inspect.signature(self.voice.synthesize).parameters
            except Exception:
                params = {}

            for candidate in ("syn_config", "synthesis_config", "config"):
                if candidate in params:
                    self._synthesis_config_param = candidate
                    break

            if self._synthesis_config_cls and self._synthesis_config_param:
                print(
                    "[PIPER] Runtime prosody controls available "
                    f"param={self._synthesis_config_param}"
                )
            else:
                print("[PIPER] Using model-default prosody (runtime controls unavailable)")
        except Exception:
            self._synthesis_config_cls = None
            self._synthesis_config_param = None

    def _load_blocking(self):
        if not self.model_path.exists():
            raise FileNotFoundError(f"Piper model not found: {self.model_path}")
        if not self.config_path.exists():
            raise FileNotFoundError(f"Piper config not found: {self.config_path}")

        try:
            from piper import PiperVoice
        except ImportError as exc:
            raise RuntimeError(
                "Piper Python package is not installed. Run: python -m pip install piper-tts"
            ) from exc

        started = time.perf_counter()
        self.voice = PiperVoice.load(
            str(self.model_path),
            config_path=str(self.config_path),
            use_cuda=self.use_cuda,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        native_rate = getattr(getattr(self.voice, "config", None), "sample_rate", None)

        self._discover_optional_api()

        print(
            "[PIPER] Hindi voice ready "
            f"model={self.model_path.name} sample_rate={native_rate} "
            f"load={elapsed_ms:.1f}ms device={'CUDA' if self.use_cuda else 'CPU'}"
        )

    async def connect(self):
        if self.voice is not None:
            return
        async with self._load_lock:
            if self.voice is None:
                await asyncio.to_thread(self._load_blocking)

    def _make_synthesis_config(self, style: str | None):
        if not self.prosody_enabled:
            return None
        if self._synthesis_config_cls is None or self._synthesis_config_param is None:
            return None

        profile = dict(
            self.STYLE_PROFILES.get(
                str(style or "warm_conversational"),
                self.STYLE_PROFILES["warm_conversational"],
            )
        )

        try:
            signature = inspect.signature(self._synthesis_config_cls)
            accepted = set(signature.parameters)
            kwargs = {key: value for key, value in profile.items() if key in accepted}
            return self._synthesis_config_cls(**kwargs)
        except Exception as exc:
            print(f"[PIPER PROSODY] disabled for this run: {type(exc).__name__}: {exc}")
            return None

    def _synthesis_iter(self, text: str, style: str | None):
        syn_config = self._make_synthesis_config(style)
        if syn_config is None or not self._synthesis_config_param:
            return self.voice.synthesize(text)

        kwargs = {self._synthesis_config_param: syn_config}
        try:
            return self.voice.synthesize(text, **kwargs)
        except TypeError:
            # API mismatch should never make speech fail.
            return self.voice.synthesize(text)

    @staticmethod
    def _safe_peak(pcm: bytes) -> int:
        try:
            return int(audioop.max(pcm, 2)) if pcm else 0
        except Exception:
            return 0

    @staticmethod
    def _safe_rms(pcm: bytes) -> int:
        try:
            return int(audioop.rms(pcm, 2)) if pcm else 0
        except Exception:
            return 0

    def _speech_dynamics(self, pcm: bytes, style: str | None) -> tuple[bytes, int, int, float]:
        """Light, smooth speech levelling without per-chunk peak pumping."""
        if not pcm:
            return b"", 0, 0, 1.0

        # Remove tiny DC offsets that waste headroom on small speakers.
        if self.dsp_enabled:
            try:
                dc = int(audioop.avg(pcm, 2))
                if abs(dc) >= 2:
                    pcm = audioop.bias(pcm, 2, -dc)
            except Exception:
                pass

        peak = self._safe_peak(pcm)
        rms = self._safe_rms(pcm)

        if peak <= 0 or rms <= 0:
            return pcm, peak, rms, 1.0

        profile = self.STYLE_PROFILES.get(
            str(style or "warm_conversational"),
            self.STYLE_PROFILES["warm_conversational"],
        )
        style_volume = float(profile.get("volume", 1.0))

        desired = self.target_rms / float(rms)
        peak_limit_gain = self.target_peak / float(max(1, peak))
        desired = min(self.max_gain, desired, peak_limit_gain)
        desired = max(0.70, desired) * style_volume

        # Smooth gain between synthesis chunks so speech level does not pump.
        alpha = self.gain_smoothing
        self._smoothed_gain = alpha * self._smoothed_gain + (1.0 - alpha) * desired
        gain = max(0.65, min(self.max_gain, self._smoothed_gain))

        if abs(gain - 1.0) > 0.01:
            pcm = audioop.mul(pcm, 2, gain)

        # Final hard ceiling only; normally the smooth gain stays below it.
        out_peak = self._safe_peak(pcm)
        if out_peak > self.target_peak:
            limiter_gain = self.target_peak / float(out_peak)
            pcm = audioop.mul(pcm, 2, limiter_gain)
            gain *= limiter_gain

        return pcm, peak, rms, gain

    def _start_hardware_session(self):
        if self.hardware is None:
            raise RuntimeError("Piper direct SIA path requires SIAHardware.")

        with self._session_lock:
            if self._hardware_session_active:
                return
            if not self.hardware.connected:
                raise RuntimeError("SIA hardware is not connected.")

            self.hardware.set_route_sia()
            self.hardware.tts_start(
                sample_rate=self.target_sample_rate,
                channels=1,
                bits_per_sample=16,
            )
            self._hardware_session_active = True
            print(
                "[PIPER AUDIO] ESP direct playback session started "
                f"@ {self.target_sample_rate} Hz"
            )

    def _finish_hardware_session(self, timeout: float = 8.0):
        with self._session_lock:
            if not self._hardware_session_active:
                return
            try:
                self.hardware.tts_end(timeout=timeout)
            finally:
                self._hardware_session_active = False
            print("[PIPER AUDIO] ESP direct playback session finished")

    def _write_realtime(self, pcm16: bytes, packet_bytes: int):
        if not pcm16:
            return 0
        sent = 0
        for offset in range(0, len(pcm16), packet_bytes):
            if self._interrupt_event.is_set():
                break

            packet = pcm16[offset:offset + packet_bytes]
            if len(packet) & 1:
                packet = packet[:-1]
            if not packet:
                continue

            started = time.perf_counter()
            with self._session_lock:
                if not self._hardware_session_active:
                    break
                self.hardware.tts_write(packet, chunk_bytes=len(packet))

            sent += len(packet)
            audio_seconds = len(packet) / 2.0 / self.target_sample_rate
            remaining = audio_seconds - (time.perf_counter() - started)
            if remaining > 0:
                time.sleep(remaining)
        return sent

    def _synthesize_blocking(self, text: str, style: str | None = None) -> dict:
        if self.voice is None:
            raise RuntimeError("Piper voice is not loaded.")

        text = str(text or "").strip()
        if not text:
            return {
                "engine": "piper", "client_ttfa_ms": None,
                "client_total_seconds": 0.0, "packets": 0, "pcm_bytes": 0,
                "server": {"engine": "piper", "rtf": 0.0},
            }
        if self.hardware is None:
            raise RuntimeError("No SIAHardware supplied to PiperTTSClient.")

        self._interrupt_event.clear()
        self._smoothed_gain = 1.0
        request_start = time.perf_counter()
        first_audio_at = None
        native_audio_seconds = 0.0
        packet_count = 0
        pcm_bytes = 0
        resample_state = None
        pending = bytearray()

        packet_bytes = max(
            2,
            int(self.target_sample_rate * 2 * self.packet_ms / 1000.0),
        )

        gains = []
        native_peaks = []
        native_rms_values = []

        try:
            for chunk in self._synthesis_iter(text, style):
                if self._interrupt_event.is_set():
                    break

                pcm = chunk.audio_int16_bytes
                if not pcm:
                    continue

                native_rate = int(chunk.sample_rate)
                sample_width = int(chunk.sample_width)
                channels = int(chunk.sample_channels)
                if sample_width != 2 or channels != 1:
                    raise RuntimeError(
                        "SIA Piper path expects mono PCM16. "
                        f"Got width={sample_width}, channels={channels}."
                    )

                native_audio_seconds += len(pcm) / 2.0 / max(1, native_rate)

                if native_rate != self.target_sample_rate:
                    pcm, resample_state = audioop.ratecv(
                        pcm, 2, 1, native_rate, self.target_sample_rate, resample_state
                    )

                if not pcm:
                    continue

                pcm, peak, rms, gain = self._speech_dynamics(pcm, style)
                native_peaks.append(peak)
                native_rms_values.append(rms)
                gains.append(gain)
                pending.extend(pcm)

                if not self._hardware_session_active:
                    self._start_hardware_session()

                while len(pending) >= packet_bytes:
                    if self._interrupt_event.is_set():
                        break
                    packet = bytes(pending[:packet_bytes])
                    del pending[:packet_bytes]
                    if first_audio_at is None:
                        first_audio_at = time.perf_counter()
                    written = self._write_realtime(packet, packet_bytes)
                    if written:
                        packet_count += 1
                        pcm_bytes += written

            if pending and not self._interrupt_event.is_set():
                if not self._hardware_session_active:
                    self._start_hardware_session()
                if first_audio_at is None:
                    first_audio_at = time.perf_counter()
                written = self._write_realtime(bytes(pending), packet_bytes)
                if written:
                    packet_count += 1
                    pcm_bytes += written
        finally:
            if self._hardware_session_active:
                self._finish_hardware_session(timeout=8.0)

        end = time.perf_counter()
        total_seconds = end - request_start
        ttfa_ms = (
            (first_audio_at - request_start) * 1000.0
            if first_audio_at is not None else None
        )
        rtf = total_seconds / native_audio_seconds if native_audio_seconds > 0 else 0.0
        avg_gain = sum(gains) / len(gains) if gains else 1.0
        max_input_peak = max(native_peaks) if native_peaks else 0
        avg_input_rms = (
            sum(native_rms_values) / len(native_rms_values)
            if native_rms_values else 0.0
        )

        print(
            "[PIPER AUDIO] "
            f"style={style or 'warm_conversational'} "
            f"peak={max_input_peak} rms={avg_input_rms:.0f} "
            f"avg_gain={avg_gain:.2f}x packets={packet_count}"
        )

        return {
            "engine": "piper", "text": text, "client_ttfa_ms": ttfa_ms,
            "client_total_seconds": total_seconds, "packets": packet_count,
            "pcm_bytes": pcm_bytes, "interrupted": self._interrupt_event.is_set(),
            "server": {
                "engine": "piper", "rtf": rtf, "generation_time": total_seconds,
                "audio_seconds": native_audio_seconds, "avg_gain": avg_gain,
                "input_peak": max_input_peak, "input_rms": avg_input_rms,
                "style": style or "warm_conversational",
            },
        }

    async def speak(self, text: str, style=None, flow_steps=None):
        del flow_steps
        await self.connect()
        async with self._speak_lock:
            return await asyncio.to_thread(self._synthesize_blocking, text, style)

    def wait_for_playback(self):
        return

    async def interrupt(self):
        self._interrupt_event.set()
        if self._hardware_session_active:
            try:
                await asyncio.to_thread(self._finish_hardware_session, 2.0)
            except Exception:
                pass

    async def close(self):
        self._interrupt_event.set()
        if self._hardware_session_active:
            try:
                await asyncio.to_thread(self._finish_hardware_session, 2.0)
            except Exception:
                pass
        self.voice = None
