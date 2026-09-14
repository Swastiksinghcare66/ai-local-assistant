from __future__ import annotations

import collections
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.audio.sia_hardware import SIAHardware
from app.audio.wake_listener import WakeCapture

from app.config import (
    WAKE_WORD,
    WAKE_WORD_ALIASES,
    VOICE_COMMAND_WAIT_SECONDS,
    VOICE_MAX_UTTERANCE_SECONDS,
)


# ============================================================
# CONFIG
# ============================================================

@dataclass(slots=True)
class SIAEndpointConfig:
    sample_rate: int = 16000

    # Preserve leading consonants / wake word onset.
    pre_roll_ms: int = 280

    # Standby endpoint.
    end_silence_ms: int = 600

    min_speech_ms: int = 160
    max_utterance_s: float = 12.0

    wait_for_speech_s: float | None = None


# ============================================================
# HARDWARE AUDIO SOURCE
# ============================================================

class SIAAudioSource:
    """
    Converts ESP32 MicPcm packets into float32 mono utterances.

    ESP32 already performs:
        INMP441
        -> AEC
        -> NS
        -> VAD
        -> PCM16

    Therefore this class does not run another denoiser/VAD.
    """

    def __init__(
        self,
        hardware: SIAHardware,
        config: SIAEndpointConfig | None = None,
    ):
        self.hardware = hardware
        self.config = config or SIAEndpointConfig()

    @staticmethod
    def _pcm_rms(pcm: bytes) -> float:
        """Return normalized PCM16 RMS without creating float audio copies."""
        if not pcm:
            return 0.0

        samples = np.frombuffer(pcm, dtype="<i2")
        if samples.size == 0:
            return 0.0

        values = samples.astype(np.float32)
        return float(np.sqrt(np.mean(values * values)) / 32768.0)

    def capture_utterance(
        self,
        *,
        wait_for_speech_s: float | None = None,
        end_silence_ms: int | None = None,
        max_utterance_s: float | None = None,
        stop_event=None,
        on_speech_start=None,
        label: str = "MIC",
        confirm_speech_ms: int = 0,
        threshold_multiplier: float = 0.0,
        min_rms: float = 0.0,
        candidate_release_ms: int = 96,
    ) -> np.ndarray | None:
        """
        Capture one ESP32-AFE utterance.

        ESP32 VAD remains the primary speech detector.  When
        ``confirm_speech_ms`` is non-zero, the host adds a lightweight
        confirmation layer: VAD must remain speech-like long enough and the
        processed PCM must clear an adaptive RMS floor.  This is confirmation,
        not a second VAD/denoiser.
        """
        cfg = self.config

        wait_limit = (
            cfg.wait_for_speech_s
            if wait_for_speech_s is None
            else wait_for_speech_s
        )

        end_ms = (
            cfg.end_silence_ms
            if end_silence_ms is None
            else int(end_silence_ms)
        )

        max_seconds = (
            cfg.max_utterance_s
            if max_utterance_s is None
            else float(max_utterance_s)
        )

        bytes_per_ms = cfg.sample_rate * 2 / 1000.0

        pre_roll_bytes = int(cfg.pre_roll_ms * bytes_per_ms)
        end_silence_bytes = int(end_ms * bytes_per_ms)
        min_speech_bytes = int(cfg.min_speech_ms * bytes_per_ms)
        max_bytes = int(max_seconds * cfg.sample_rate * 2)

        confirm_bytes = max(
            0,
            int(max(0, confirm_speech_ms) * bytes_per_ms),
        )
        candidate_release_bytes = max(
            int(32 * bytes_per_ms),
            int(max(32, candidate_release_ms) * bytes_per_ms),
        )

        pre = collections.deque()
        pre_size = 0
        captured = bytearray()

        speech_bytes = 0
        silence_after_speech = 0
        started = False

        candidate_speech_bytes = 0
        candidate_silence_bytes = 0
        candidate_peak_rms = 0.0
        candidate_rms_sum = 0.0
        candidate_rms_frames = 0

        # Adaptive floor is learned only from AFE frames marked non-speech.
        # A small seed avoids a zero threshold in a perfectly quiet room.
        noise_floor = 0.0025
        noise_alpha = 0.08

        wait_start = time.perf_counter()

        self.hardware.start_mic()

        try:
            while True:
                if (
                    stop_event is not None
                    and stop_event.is_set()
                    and not started
                ):
                    return None

                if (
                    wait_limit is not None
                    and not started
                    and time.perf_counter() - wait_start >= wait_limit
                ):
                    return None

                frame = self.hardware.get_mic_frame(timeout=0.25)
                if frame is None:
                    continue

                pcm = frame.pcm
                speech = frame.speech
                rms = self._pcm_rms(pcm)

                # ----------------------------------------
                # Waiting for confirmed speech
                # ----------------------------------------
                if not started:
                    pre.append(pcm)
                    pre_size += len(pcm)

                    while pre and pre_size > pre_roll_bytes:
                        removed = pre.popleft()
                        pre_size -= len(removed)

                    if not speech:
                        noise_floor = (
                            (1.0 - noise_alpha) * noise_floor
                            + noise_alpha * rms
                        )

                        if candidate_speech_bytes > 0:
                            candidate_silence_bytes += len(pcm)

                            if (
                                candidate_silence_bytes
                                >= candidate_release_bytes
                            ):
                                if label == "BARGE-IN":
                                    gate = max(
                                        float(min_rms),
                                        noise_floor
                                        * float(threshold_multiplier),
                                    )
                                    print(
                                        "[BARGE-IN] Candidate rejected "
                                        f"rms={candidate_peak_rms:.4f} "
                                        f"floor={noise_floor:.4f} "
                                        f"gate={gate:.4f}"
                                    )

                                candidate_speech_bytes = 0
                                candidate_silence_bytes = 0
                                candidate_peak_rms = 0.0
                                candidate_rms_sum = 0.0
                                candidate_rms_frames = 0

                        continue

                    # ESP32 says speech.
                    candidate_speech_bytes += len(pcm)
                    candidate_silence_bytes = 0
                    candidate_peak_rms = max(candidate_peak_rms, rms)
                    candidate_rms_sum += rms
                    candidate_rms_frames += 1

                    # Normal wake/command capture keeps the original immediate
                    # ESP32-VAD behavior unless a confirmation window is asked
                    # for explicitly.
                    if confirm_bytes <= 0:
                        confirmed = True
                        gate = 0.0
                        mean_rms = rms
                    else:
                        gate = max(
                            float(min_rms),
                            noise_floor * float(threshold_multiplier),
                        )
                        mean_rms = (
                            candidate_rms_sum
                            / max(1, candidate_rms_frames)
                        )
                        confirmed = (
                            candidate_speech_bytes >= confirm_bytes
                            and mean_rms >= gate
                        )

                    if not confirmed:
                        continue

                    started = True

                    if label == "BARGE-IN":
                        print(
                            "[BARGE-IN] Confirmed speech "
                            f"mean_rms={mean_rms:.4f} "
                            f"peak_rms={candidate_peak_rms:.4f} "
                            f"floor={noise_floor:.4f} "
                            f"gate={gate:.4f} "
                            f"confirm={confirm_speech_ms}ms"
                        )
                    else:
                        print(
                            f"[{label}] Speech detected "
                            "(ESP32 VAD)"
                        )

                    if on_speech_start is not None:
                        try:
                            on_speech_start()
                        except Exception:
                            pass

                    for block in pre:
                        captured.extend(block)

                    pre.clear()
                    pre_size = 0

                    speech_bytes = max(
                        len(pcm),
                        candidate_speech_bytes,
                    )
                    silence_after_speech = 0
                    continue

                # ----------------------------------------
                # Confirmed speech already active
                # ----------------------------------------
                captured.extend(pcm)

                if speech:
                    speech_bytes += len(pcm)
                    silence_after_speech = 0
                else:
                    silence_after_speech += len(pcm)

                if (
                    speech_bytes >= min_speech_bytes
                    and silence_after_speech >= end_silence_bytes
                ):
                    print(
                        f"[{label}] End of speech "
                        "(ESP32 VAD)"
                    )
                    break

                if len(captured) >= max_bytes:
                    print(
                        f"[{label}] Maximum utterance "
                        "duration reached."
                    )
                    break

        finally:
            self.hardware.stop_mic()

        if not captured:
            return None

        pcm16 = np.frombuffer(bytes(captured), dtype="<i2")
        if pcm16.size == 0:
            return None

        return pcm16.astype(np.float32) / 32768.0


# ============================================================
# HARDWARE WAKE LISTENER
# ============================================================

class SIAHardwareListener:
    """
    Drop-in listener interface for VoicePipeline.

    STANDBY:
        ESP32 AFE/VAD
        -> PCM
        -> Parakeet
        -> SIA wake detection

    ACTIVE:
        ESP32 AFE/VAD
        -> PCM
        -> WakeCapture
    """

    def __init__(
        self,
        hardware: SIAHardware,
        stt,
        sample_rate: int = 16000,
    ):
        self.hardware = hardware
        self.stt = stt
        self.sample_rate = int(
            sample_rate
        )

        aliases = [
            WAKE_WORD,
            *WAKE_WORD_ALIASES,
        ]

        self.wake_aliases: list[str] = []

        for alias in aliases:
            alias = (
                str(alias)
                .strip()
                .lower()
            )

            if (
                alias
                and
                alias not in self.wake_aliases
            ):
                self.wake_aliases.append(
                    alias
                )

        self.source = SIAAudioSource(
            hardware=hardware,
            config=SIAEndpointConfig(
                sample_rate=self.sample_rate,
            ),
        )

        # Compatibility with VoicePipeline.
        self.vad_threshold = 0.0

        # Same STT instance may be used elsewhere.
        self._stt_lock = threading.Lock()

    # ========================================================
    # TEXT HELPERS
    # ========================================================

    @staticmethod
    def normalize_text(
        text: str,
    ) -> str:

        text = (
            str(text or "")
            .strip()
            .lower()
        )

        text = re.sub(
            r"[^a-z0-9\s']",
            " ",
            text,
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        )

        return text.strip()

    def _transcribe_silent(
        self,
        audio: np.ndarray,
    ) -> str:

        with self._stt_lock:

            if hasattr(
                self.stt,
                "transcribe_silent",
            ):
                try:
                    return (
                        self.stt
                        .transcribe_silent(
                            audio,
                            sample_rate=self.sample_rate,
                        )
                        .strip()
                    )

                except TypeError:
                    pass

            return (
                self.stt
                .transcribe(
                    audio,
                    sample_rate=self.sample_rate,
                )
                .strip()
            )

    def find_wake_word(
        self,
        text: str,
    ) -> Optional[str]:

        normalized = self.normalize_text(
            text
        )

        if not normalized:
            return None

        # Match wake word only near beginning.
        prefix = " ".join(
            normalized.split()[:4]
        )

        for alias in self.wake_aliases:

            if re.search(
                r"\b"
                + re.escape(alias)
                + r"\b",
                prefix,
            ):
                return alias

        return None

    def strip_wake_word(
        self,
        text: str,
    ) -> str:

        normalized = self.normalize_text(
            text
        )

        if not normalized:
            return ""

        aliases = "|".join(
            re.escape(alias)
            for alias in sorted(
                self.wake_aliases,
                key=len,
                reverse=True,
            )
        )

        greeting = (
            r"(?:(?:hey|hello|hi|ok|okay)\s+)?"
        )

        cleaned = re.sub(
            rf"^\s*{greeting}"
            rf"(?:{aliases})\b"
            rf"[\s,.:;!?-]*",
            "",
            normalized,
            count=1,
        )

        return cleaned.strip()

    # ========================================================
    # STANDBY
    # ========================================================

    def listen_for_command(
        self,
    ) -> WakeCapture:

        print()
        print("=" * 70)
        print("SIA - HARDWARE STANDBY")
        print("=" * 70)
        print(
            f'Waiting for identity: "{WAKE_WORD}"'
        )
        print(
            "Source: ESP32-S3 / INMP441 / AFE"
        )
        print("=" * 70)

        while True:

            audio = self.source.capture_utterance(
                wait_for_speech_s=None,
                end_silence_ms=600,
                max_utterance_s=VOICE_MAX_UTTERANCE_SECONDS,
                label="WAKE",
            )

            if audio is None or audio.size == 0:
                continue

            duration = (
                len(audio)
                / self.sample_rate
            )

            text = self._transcribe_silent(
                audio
            )

            print(
                f"[WAKE STT] "
                f"{duration:.2f}s -> "
                f"{text!r}"
            )

            if not text:
                continue

            identity = self.find_wake_word(
                text
            )

            if identity is None:
                print("[WAKE] rejected")
                continue

            print()
            print("[IDENTITY] SIA detected.")

            initial_command = (
                self.strip_wake_word(
                    text
                )
            )

            # User said:
            # "SIA what time is it"
            if initial_command:

                print(
                    "[IDENTITY] Initial command: "
                    f"{initial_command}"
                )

                now = time.perf_counter()

                return WakeCapture(
                    audio=audio,
                    sample_rate=self.sample_rate,
                    wake_transcript=text,
                    wake_word=identity,
                    threshold=0.0,
                    speech_end=now,
                    capture_end=now,
                    partial_transcript="",
                )

            # User only said "SIA". Wake is complete immediately. Do NOT
            # wait for a second command inside standby mode and do NOT fall
            # back to wake-word mode if the user pauses. main.py will enter
            # persistent ACTIVE listening, where the wake word is no longer
            # required until an explicit sleep/standby command is spoken.
            print(
                "[IDENTITY] Wake-only accepted -> ACTIVE"
            )

            now = time.perf_counter()

            return WakeCapture(
                audio=audio,
                sample_rate=self.sample_rate,
                wake_transcript=text,
                wake_word=identity,
                threshold=0.0,
                speech_end=now,
                capture_end=now,
                partial_transcript="",
            )

    # ========================================================
    # ACTIVE CONVERSATION
    # ========================================================

    @staticmethod
    def _active_audio_quality(audio: np.ndarray) -> tuple[bool, float, float]:
        """
        Final lightweight sanity check for ACTIVE-mode captures.

        ESP32 AFE/VAD remains the primary detector. This only rejects very
        low-energy captures that commonly come from room noise, relay clicks,
        desk taps, fan bursts, or other false VAD triggers before Parakeet is
        allowed to hallucinate text from them.
        """
        if audio is None or audio.size == 0:
            return False, 0.0, 0.0

        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return False, 0.0, 0.0

        frame_len = 320  # 20 ms @ 16 kHz
        frame_rms = []

        for start in range(0, samples.size, frame_len):
            frame = samples[start:start + frame_len]
            if frame.size < 80:
                continue
            frame_rms.append(
                float(np.sqrt(np.mean(frame * frame) + 1e-12))
            )

        if not frame_rms:
            rms75 = float(np.sqrt(np.mean(samples * samples) + 1e-12))
        else:
            rms75 = float(np.percentile(frame_rms, 75))

        peak = float(np.max(np.abs(samples)))

        min_rms75 = float(os.getenv(
            "SIA_ACTIVE_FINAL_RMS",
            "0.006",
        ))
        min_peak = float(os.getenv(
            "SIA_ACTIVE_FINAL_PEAK",
            "0.025",
        ))

        accepted = rms75 >= min_rms75 and peak >= min_peak
        return accepted, rms75, peak

    def listen_active_command(
        self,
        max_wait_seconds: Optional[float] = None,
        end_silence_seconds: float = 0.42,
    ) -> Optional[WakeCapture]:

        print()
        print(
            "[MIC] Active hardware conversation listening..."
        )

        # ACTIVE mode must be stricter than wake mode because any accepted
        # transcript is routed immediately to agents/LLM. A false capture can
        # otherwise turn random noise into an STT hallucination and trigger an
        # inappropriate conversational response.
        confirm_ms = int(os.getenv(
            "SIA_ACTIVE_CONFIRM_MS",
            "320",
        ))
        rms_multiplier = float(os.getenv(
            "SIA_ACTIVE_RMS_MULTIPLIER",
            "2.60",
        ))
        min_rms = float(os.getenv(
            "SIA_ACTIVE_MIN_RMS",
            "0.014",
        ))

        deadline = (
            None
            if max_wait_seconds is None
            else time.perf_counter() + float(max_wait_seconds)
        )

        while True:
            remaining = None
            if deadline is not None:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    return None

            audio = self.source.capture_utterance(
                wait_for_speech_s=remaining,
                end_silence_ms=int(
                    end_silence_seconds
                    * 1000
                ),
                max_utterance_s=
                VOICE_MAX_UTTERANCE_SECONDS,
                label="MIC",
                confirm_speech_ms=confirm_ms,
                threshold_multiplier=rms_multiplier,
                min_rms=min_rms,
                candidate_release_ms=64,
            )

            if audio is None or audio.size == 0:
                return None

            accepted, rms75, peak = self._active_audio_quality(audio)

            if not accepted:
                print(
                    "[MIC] Noise candidate rejected "
                    f"rms75={rms75:.4f} "
                    f"peak={peak:.4f}"
                )
                # Stay in ACTIVE listening instead of handing noise to STT or
                # forcing the conversation back to standby.
                continue

            duration = (
                len(audio)
                / self.sample_rate
            )

            print(
                f"[MIC] Active command captured "
                f"{duration:.2f}s "
                f"rms75={rms75:.4f} "
                f"peak={peak:.4f}"
            )

            now = time.perf_counter()

            return WakeCapture(
                audio=audio,
                sample_rate=self.sample_rate,
                wake_transcript="",
                wake_word="",
                threshold=0.0,
                speech_end=now,
                capture_end=now,
                partial_transcript="",
            )

    # ========================================================
    # BARGE-IN
    # ========================================================

    def capture_barge_in(
        self,
        stop_event,
        on_speech_start=None,
        *,
        threshold_multiplier: float = 2.40,
        min_rms: float = 0.015,
        end_silence_seconds: float = 0.28,
        confirm_speech_ms: int = 260,
    ) -> Optional[WakeCapture]:
        """
        Full-duplex barge-in with ESP32-VAD + host confirmation.

        The ESP32 AFE/AEC/VAD remains authoritative.  The host only confirms
        that the candidate persists and rises above the current processed-audio
        floor before it tells VoicePipeline to pause Sara.
        """
        audio = self.source.capture_utterance(
            wait_for_speech_s=None,
            end_silence_ms=int(
                end_silence_seconds
                * 1000
            ),
            max_utterance_s=8.0,
            stop_event=stop_event,
            on_speech_start=on_speech_start,
            label="BARGE-IN",
            confirm_speech_ms=int(confirm_speech_ms),
            threshold_multiplier=float(threshold_multiplier),
            min_rms=float(min_rms),
            candidate_release_ms=96,
        )

        if audio is None or audio.size == 0:
            return None

        now = time.perf_counter()

        return WakeCapture(
            audio=audio,
            sample_rate=self.sample_rate,
            wake_transcript="",
            wake_word="",
            threshold=0.0,
            speech_end=now,
            capture_end=now,
            partial_transcript="",
        )
