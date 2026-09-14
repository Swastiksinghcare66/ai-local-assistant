from __future__ import annotations

import audioop
import os
import queue
import threading
import time

from app.audio.sia_hardware import SIAHardware
from app.audio.voice_output_dsp import VoiceOutputDSP


class SIAAudioPlayer:
    """
    Playback backend used by CosyVoicePersistentClient.

    Input:
        PCM16 mono at 24 kHz from CosyVoice.

    Output:
        PCM16 mono at 16 kHz through the SIA USB protocol:
            TtsStart -> TtsPcm... -> TtsEnd

    The public interface intentionally matches PCMAudioPlayer:
        start()
        play()
        wait()
        pause()
        resume()
        interrupt()
        stop()

    This keeps the existing VoicePipeline / barge-in code unchanged.
    """

    def __init__(
        self,
        hardware: SIAHardware,
        input_sample_rate: int = 24000,
        output_sample_rate: int = 16000,
        slice_ms: int = 20,
    ):
        self.hardware = hardware

        self.input_sample_rate = int(
            input_sample_rate
        )

        self.output_sample_rate = int(
            output_sample_rate
        )

        self.slice_ms = max(
            10,
            int(slice_ms),
        )

        # PCM16 mono => 2 bytes per sample.
        self._output_slice_bytes = max(
            2,
            int(
                self.output_sample_rate
                * 2
                * self.slice_ms
                / 1000.0
            ),
        )

        self.audio_queue = queue.Queue()

        self.thread: threading.Thread | None = None
        self.running = False

        # Generation invalidation gives fast hard interruption.
        self._generation = 0
        self._generation_lock = threading.Lock()

        # Soft pause preserves queued audio while a possible
        # barge-in is classified.
        self._pause_event = threading.Event()
        self._pause_event.set()

        # Protect TTS session operations against worker/interrupt races.
        self._session_lock = threading.RLock()

        self._tts_active = False

        # Streaming state for audioop.ratecv().
        self._resample_state = None

        dsp_enabled = str(
            os.getenv("SIA_VOICE_DSP", "1")
        ).strip().lower() not in {
            "0", "false", "off", "no"
        }

        dsp_preset = os.getenv(
            "SIA_VOICE_DSP_PRESET",
            "warm_clear",
        )

        self.voice_dsp = VoiceOutputDSP(
            sample_rate=self.output_sample_rate,
            enabled=dsp_enabled,
            preset=dsp_preset,
        )

    # ========================================================
    # GENERATION
    # ========================================================

    def _get_generation(self) -> int:
        with self._generation_lock:
            return self._generation

    # ========================================================
    # START / STOP
    # ========================================================

    def start(self):
        if self.running:
            return

        if not self.hardware.connected:
            raise RuntimeError(
                "SIA hardware must be connected before "
                "starting hardware playback."
            )

        self.running = True

        self.thread = threading.Thread(
            target=self._worker,
            daemon=True,
            name="sia-hardware-pcm-player",
        )

        self.thread.start()

        print(
            "[SIA AUDIO] Hardware PCM player ready "
            "24k -> 16k"
        )

        if self.voice_dsp.enabled:
            print(
                "[VOICE DSP] enabled "
                + self.voice_dsp.describe()
            )
        else:
            print("[VOICE DSP] bypassed")

    def stop(
        self,
        drain: bool = False,
    ):
        if not self.running:
            return

        if drain:
            self.wait()
        else:
            self.interrupt()

        self.running = False
        self._pause_event.set()

        self.audio_queue.put(None)

        if self.thread is not None:
            self.thread.join(
                timeout=5.0
            )

        self.thread = None

        print(
            "[SIA AUDIO] Hardware player stopped"
        )

    # ========================================================
    # ESP32 TTS SESSION
    # ========================================================

    def _ensure_tts_started(self):
        with self._session_lock:
            if self._tts_active:
                return

            # Both speaker leads are switched by firmware to
            # the MAX98357A/SIA route.
            self.hardware.set_route_sia()

            # A new logical playback stream must begin with
            # a fresh streaming-resampler/DSP state.
            self._resample_state = None
            self.voice_dsp.reset()

            self.hardware.tts_start(
                sample_rate=self.output_sample_rate,
                channels=1,
                bits_per_sample=16,
            )

            self._tts_active = True

            print(
                "[SIA AUDIO] ESP playback session started"
            )

    def _finish_tts_session(
        self,
        timeout: float = 8.0,
    ):
        with self._session_lock:
            if not self._tts_active:
                return

            try:
                self.hardware.tts_end(
                    timeout=timeout
                )
            finally:
                self._tts_active = False
                self._resample_state = None

            print(
                "[SIA AUDIO] ESP playback session finished"
            )

    # ========================================================
    # RESAMPLING
    # ========================================================

    def _resample_24k_to_16k(
        self,
        pcm24: bytes,
    ) -> bytes:
        if not pcm24:
            return b""

        # Keep complete int16 samples only.
        if len(pcm24) & 1:
            pcm24 = pcm24[:-1]

        if not pcm24:
            return b""

        pcm16, self._resample_state = audioop.ratecv(
            pcm24,
            2,  # sample width: int16
            1,  # mono
            self.input_sample_rate,
            self.output_sample_rate,
            self._resample_state,
        )

        return pcm16

    # ========================================================
    # WORKER
    # ========================================================

    def _worker(self):
        try:
            while self.running:
                item = self.audio_queue.get()

                try:
                    if item is None:
                        break

                    generation, pcm24 = item

                    if (
                        generation
                        != self._get_generation()
                    ):
                        continue

                    if not pcm24:
                        continue

                    self._ensure_tts_started()

                    pcm16 = (
                        self._resample_24k_to_16k(
                            pcm24
                        )
                    )

                    if not pcm16:
                        continue

                    pcm16 = self.voice_dsp.process(
                        pcm16
                    )

                    if not pcm16:
                        continue

                    # Pace the USB stream close to real time.
                    #
                    # This prevents seconds of audio from being
                    # buffered inside the ESP32 and keeps pause /
                    # barge-in response bounded by roughly one
                    # slice plus USB/protocol latency.
                    for offset in range(
                        0,
                        len(pcm16),
                        self._output_slice_bytes,
                    ):
                        if (
                            not self.running
                            or generation
                            != self._get_generation()
                        ):
                            break

                        while (
                            self.running
                            and generation
                            == self._get_generation()
                            and not self._pause_event.wait(
                                timeout=0.01
                            )
                        ):
                            pass

                        if (
                            not self.running
                            or generation
                            != self._get_generation()
                        ):
                            break

                        chunk = pcm16[
                            offset:
                            offset
                            + self._output_slice_bytes
                        ]

                        if not chunk:
                            continue

                        started = time.perf_counter()

                        with self._session_lock:
                            if (
                                generation
                                != self._get_generation()
                            ):
                                break

                            if not self._tts_active:
                                break

                            self.hardware.tts_write(
                                chunk,
                                chunk_bytes=len(chunk),
                            )

                        audio_seconds = (
                            len(chunk)
                            / 2
                            / self.output_sample_rate
                        )

                        elapsed = (
                            time.perf_counter()
                            - started
                        )

                        remaining = (
                            audio_seconds
                            - elapsed
                        )

                        if remaining > 0:
                            time.sleep(
                                remaining
                            )

                finally:
                    self.audio_queue.task_done()

        except Exception as exc:
            print(
                "[SIA AUDIO ERROR]",
                repr(exc),
            )

        finally:
            try:
                self._finish_tts_session(
                    timeout=2.0
                )
            except Exception:
                pass

    # ========================================================
    # PLAYER API
    # ========================================================

    def play(
        self,
        pcm: bytes,
    ):
        if not pcm:
            return

        if not self.running:
            self.start()

        self.audio_queue.put(
            (
                self._get_generation(),
                bytes(pcm),
            )
        )

    def wait(self):
        """
        Wait until all queued CosyVoice PCM has been physically
        forwarded at real-time pace, then close the ESP stream
        and wait for firmware TtsDone.
        """
        self.audio_queue.join()

        self._finish_tts_session()

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def interrupt(self):
        """
        Hard interruption:
            - invalidate current generation
            - release a soft pause
            - drop queued host PCM
            - end current ESP32 TTS stream
        """
        with self._generation_lock:
            self._generation += 1

        self._pause_event.set()

        while True:
            try:
                self.audio_queue.get_nowait()

            except queue.Empty:
                break

            else:
                self.audio_queue.task_done()

        try:
            self._finish_tts_session(
                timeout=2.0
            )

        except Exception as exc:
            print(
                "[SIA AUDIO] interrupt cleanup:",
                repr(exc),
            )
