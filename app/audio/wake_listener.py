from __future__ import annotations

import re
import time
import threading
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np
import sounddevice as sd

from app.audio.stt import ParakeetSTT

from app.config import (
    AUDIO_INPUT_DEVICE,
    MIC_CHANNELS,
    MIC_SAMPLE_RATE,
    VAD_ENABLED,
    WAKE_MIN_RMS,
    WAKE_WORD,
    WAKE_WORD_ALIASES,
    VOICE_BLOCK_SECONDS,
    VOICE_COMMAND_WAIT_SECONDS,
    VOICE_END_SILENCE_SECONDS,
    VOICE_MAX_UTTERANCE_SECONDS,
    VOICE_MIN_RMS,
    VOICE_NOISE_MULTIPLIER,
)


@dataclass
class WakeCapture:
    audio: np.ndarray
    sample_rate: int
    wake_transcript: str
    wake_word: str
    threshold: float
    speech_end: Optional[float] = None
    capture_end: Optional[float] = None
    partial_transcript: str = ""


class WakeListener:
    """
    PC-only wake listener.

    STANDBY:
        PC mic -> adaptive VAD -> capture complete utterance
        -> Parakeet once -> detect configured wake word
        -> optionally continue listening for command

    ACTIVE:
        PC mic -> adaptive VAD -> capture complete utterance

    This deliberately does NOT use ESP32/SIA.
    """

    def __init__(
        self,
        stt: ParakeetSTT,
        input_device=None,
    ):
        self.stt = stt
        self.sample_rate = MIC_SAMPLE_RATE
        self.channels = MIC_CHANNELS

        self.input_device = (
            AUDIO_INPUT_DEVICE
            if input_device is None
            else input_device
        )

        self.block_seconds = max(
            VOICE_BLOCK_SECONDS,
            0.03,
        )

        self.block_frames = max(
            int(
                self.sample_rate
                * self.block_seconds
            ),
            1,
        )

        # Pre-roll prevents loss of the first phoneme of "Sara".
        self.pre_roll_blocks = max(
            int(
                0.35
                / self.block_seconds
            ),
            1,
        )

        aliases = [
            WAKE_WORD,
            *WAKE_WORD_ALIASES,
        ]

        # Wake aliases come only from config. This avoids accidentally making
        # the assistant name ("Sara") a wake word when the actual wake word is SIA.

        self.wake_aliases: list[str] = []

        for alias in aliases:
            alias = (
                str(alias)
                .strip()
                .lower()
            )

            if (
                alias
                and alias
                not in self.wake_aliases
            ):
                self.wake_aliases.append(
                    alias
                )

        self.noise_floor = 0.0
        self.vad_threshold = VOICE_MIN_RMS

        # Parakeet is shared by wake detection, incremental previews, final STT,
        # and barge-in classification. Serialize calls so partial recognition
        # never races the final transcription.
        self._stt_lock = threading.Lock()

        # Incremental STT is intentionally conservative: one preview at a time.
        # It runs while audio capture continues, so it can improve endpointing
        # without blocking the microphone loop.
        self.incremental_stt_enabled = True
        self.incremental_first_seconds = 0.55
        self.incremental_interval_seconds = 0.62

    @staticmethod
    def rms(
        audio: np.ndarray,
    ) -> float:
        if audio is None:
            return 0.0

        audio = np.asarray(
            audio,
            dtype=np.float32,
        )

        if audio.size == 0:
            return 0.0

        return float(
            np.sqrt(
                np.mean(
                    np.square(audio)
                )
                + 1e-12
            )
        )

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

    def find_wake_word(
        self,
        text: str,
    ) -> Optional[str]:
        normalized = (
            self.normalize_text(text)
        )

        if not normalized:
            return None

        # Only search near the beginning.
        # This reduces accidental triggers from unrelated speech.
        first_words = (
            normalized
            .split()[:4]
        )

        prefix = " ".join(
            first_words
        )

        for alias in self.wake_aliases:
            pattern = (
                r"\b"
                + re.escape(alias)
                + r"\b"
            )

            if re.search(
                pattern,
                prefix,
            ):
                return alias

        return None

    def strip_wake_word(
        self,
        text: str,
    ) -> str:
        normalized = (
            self.normalize_text(text)
        )

        if not normalized:
            return ""

        # Optional greeting before wake word.
        # Examples:
        #   "hey sara what time is it"
        #   "hello sarah"
        greeting = (
            r"(?:(?:hey|hello|hi|ok|okay)\s+)?"
        )

        aliases = "|".join(
            re.escape(a)
            for a in sorted(
                self.wake_aliases,
                key=len,
                reverse=True,
            )
        )

        cleaned = re.sub(
            rf"^\s*{greeting}(?:{aliases})\b[\s,.:;!?-]*",
            "",
            normalized,
            count=1,
        )

        return cleaned.strip()

    def _refresh_threshold(
        self,
    ):
        dynamic_threshold = (
            self.noise_floor
            * VOICE_NOISE_MULTIPLIER
        )

        self.vad_threshold = max(
            VOICE_MIN_RMS,
            dynamic_threshold,
        )

    def _calibrate_noise(
        self,
        stream: sd.InputStream,
        seconds: float = 0.6,
    ):
        print()
        print(
            "[VAD] Measuring room noise..."
        )

        values = []

        block_count = max(
            int(
                seconds
                / self.block_seconds
            ),
            1,
        )

        for _ in range(
            block_count
        ):
            block, overflowed = (
                stream.read(
                    self.block_frames
                )
            )

            if overflowed:
                continue

            block = (
                np.asarray(
                    block,
                    dtype=np.float32,
                )
                .reshape(-1)
            )

            values.append(
                self.rms(block)
            )

        if values:
            self.noise_floor = float(
                np.median(values)
            )
        else:
            self.noise_floor = 0.0

        self._refresh_threshold()

        print(
            f"[VAD] "
            f"noise={self.noise_floor:.5f} "
            f"threshold={self.vad_threshold:.5f}"
        )

    def _update_noise_floor(
        self,
        block_rms: float,
    ):
        if block_rms <= 0:
            return

        quiet_limit = max(
            self.vad_threshold * 0.70,
            VOICE_MIN_RMS,
        )

        if block_rms > quiet_limit:
            return

        if self.noise_floor <= 0:
            self.noise_floor = (
                block_rms
            )
        else:
            self.noise_floor = (
                self.noise_floor
                * 0.98
                + block_rms
                * 0.02
            )

        self._refresh_threshold()

    def _is_speech(
        self,
        block_rms: float,
    ) -> bool:
        if not VAD_ENABLED:
            return True

        return (
            block_rms
            >= self.vad_threshold
        )

    def _open_stream(
        self,
    ):
        return sd.InputStream(
            device=self.input_device,
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            blocksize=self.block_frames,
        )

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

    @staticmethod
    def _looks_semantically_complete(text: str) -> bool:
        text = " ".join(str(text or "").strip().split())
        if not text:
            return False

        low = text.lower()
        words = re.findall(r"[a-z0-9']+", low)

        if not words:
            return False

        if text.rstrip().endswith((".", "?", "!")):
            return True

        # Common unfinished endings. These need a longer acoustic pause.
        unfinished = {
            "and", "or", "but", "because", "so", "if", "when", "while",
            "that", "which", "who", "to", "of", "for", "with", "from",
            "about", "like", "then", "than", "is", "are", "was", "were",
            "can", "could", "would", "should", "will", "do", "does", "did",
        }

        if words[-1] in unfinished:
            return False

        # Very short fragments are often hesitation/backchannel rather than a
        # complete command.
        if len(words) <= 2:
            return False

        return True

    def _semantic_endpoint_delay(
        self,
        partial_text: str,
        fallback_seconds: float,
    ) -> float:
        """
        Software semantic endpointing.

        Complete-looking partial transcript -> aggressive release.
        Incomplete clause -> allow a longer pause.
        No partial transcript -> acoustic fallback.
        """
        partial_text = str(partial_text or "").strip()

        if not partial_text:
            return max(0.28, float(fallback_seconds))

        if self._looks_semantically_complete(partial_text):
            return 0.28

        return max(0.58, float(fallback_seconds))

    def _capture_complete_utterance(
        self,
        stream: sd.InputStream,
        *,
        max_wait_seconds: Optional[float] = None,
        max_utterance_seconds: Optional[float] = None,
        label: str = "WAKE",
        end_silence_seconds: Optional[float] = None,
        semantic_endpoint: bool = False,
    ) -> Optional[tuple[np.ndarray, float, str]]:
        """
        Capture a complete utterance while optionally running incremental
        Parakeet previews in the background.

        Return:
            (audio, last_voiced_timestamp, latest_partial_transcript)
        """
        max_utterance_seconds = (
            VOICE_MAX_UTTERANCE_SECONDS
            if max_utterance_seconds is None
            else max_utterance_seconds
        )

        end_silence_seconds = (
            VOICE_END_SILENCE_SECONDS
            if end_silence_seconds is None
            else max(0.20, float(end_silence_seconds))
        )

        pre_roll = deque(maxlen=self.pre_roll_blocks)
        speech_blocks: list[np.ndarray] = []
        speech_started = False

        wait_start = time.perf_counter()
        speech_start = None
        last_speech_time = None

        partial_state = {
            "text": "",
            "last_launch": 0.0,
            "thread": None,
        }
        partial_lock = threading.Lock()

        def launch_partial(snapshot: np.ndarray):
            def worker():
                try:
                    text = self._transcribe_silent(snapshot)
                except Exception:
                    text = ""

                if text:
                    with partial_lock:
                        partial_state["text"] = text

            thread = threading.Thread(
                target=worker,
                daemon=True,
                name="sara-incremental-stt",
            )

            with partial_lock:
                partial_state["thread"] = thread
                partial_state["last_launch"] = time.perf_counter()

            thread.start()

        while True:
            now = time.perf_counter()

            if (
                not speech_started
                and max_wait_seconds is not None
                and now - wait_start >= max_wait_seconds
            ):
                return None

            block, overflowed = stream.read(self.block_frames)

            if overflowed:
                print("[AUDIO] Input overflow.")

            block = np.asarray(
                block,
                dtype=np.float32,
            ).reshape(-1)

            block_rms = self.rms(block)
            is_speech = self._is_speech(block_rms)

            if not speech_started:
                self._update_noise_floor(block_rms)
                pre_roll.append(block.copy())

                gate = max(
                    VOICE_MIN_RMS,
                    min(
                        WAKE_MIN_RMS,
                        self.vad_threshold,
                    ),
                )

                if VAD_ENABLED and block_rms < gate:
                    continue

                if not is_speech:
                    continue

                speech_started = True
                speech_start = time.perf_counter()
                last_speech_time = speech_start

                speech_blocks.extend(list(pre_roll))
                pre_roll.clear()

                print(
                    f"[{label}] Speech detected "
                    f"rms={block_rms:.5f} "
                    f"threshold={self.vad_threshold:.5f}"
                )
                continue

            speech_blocks.append(block.copy())
            now = time.perf_counter()

            release_threshold = self.vad_threshold * 0.65

            if (
                not VAD_ENABLED
                or block_rms >= release_threshold
            ):
                last_speech_time = now

            # Incremental transcription is active only where semantic endpointing
            # is requested. This avoids wasting inference in indefinite standby.
            if (
                semantic_endpoint
                and self.incremental_stt_enabled
                and speech_start is not None
            ):
                elapsed = now - speech_start

                with partial_lock:
                    thread = partial_state["thread"]
                    last_launch = float(partial_state["last_launch"])

                worker_alive = (
                    thread is not None
                    and thread.is_alive()
                )

                launch_due = (
                    elapsed >= self.incremental_first_seconds
                    and not worker_alive
                    and (
                        last_launch <= 0.0
                        or now - last_launch
                        >= self.incremental_interval_seconds
                    )
                )

                if launch_due:
                    try:
                        snapshot = np.concatenate(
                            speech_blocks
                        ).astype(
                            np.float32,
                            copy=False,
                        )
                        launch_partial(snapshot.copy())
                    except Exception:
                        pass

            if (
                speech_start is not None
                and now - speech_start >= max_utterance_seconds
            ):
                print(
                    f"[{label}] Maximum utterance duration reached."
                )
                break

            if last_speech_time is not None:
                with partial_lock:
                    partial_text = str(
                        partial_state["text"] or ""
                    )

                endpoint_delay = (
                    self._semantic_endpoint_delay(
                        partial_text,
                        end_silence_seconds,
                    )
                    if semantic_endpoint
                    else end_silence_seconds
                )

                if now - last_speech_time >= endpoint_delay:
                    if semantic_endpoint and partial_text:
                        print(
                            f"[ENDPOINT] {endpoint_delay*1000:.0f}ms "
                            f"partial={partial_text!r}"
                        )
                    else:
                        print(f"[{label}] End of speech.")
                    break

        if not speech_blocks:
            return None

        # Do not force a partial worker to finish before returning audio. Final
        # transcription is serialized by _stt_lock and will wait only if needed.
        with partial_lock:
            latest_partial = str(
                partial_state["text"] or ""
            )

        audio = np.concatenate(
            speech_blocks
        ).astype(
            np.float32,
            copy=False,
        )

        return (
            audio,
            float(last_speech_time or time.perf_counter()),
            latest_partial,
        )

    def _play_wake_ack(self):
        """
        Immediate local wake acknowledgement.
        No TTS call, no model call, ~70 ms.
        """
        try:
            sample_rate = 24000
            duration = 0.07
            count = int(sample_rate * duration)
            t = np.arange(count, dtype=np.float32) / sample_rate
            tone = (
                0.055
                * np.sin(2.0 * np.pi * 880.0 * t)
                * np.hanning(count).astype(np.float32)
            )
            sd.play(tone, sample_rate, blocking=True)
        except Exception:
            pass

    def _capture_after_identity(
        self,
        stream: sd.InputStream,
        wake_audio: np.ndarray,
        wake_transcript: str,
        wake_word: str,
    ) -> Optional[WakeCapture]:
        print()
        print(
            "[IDENTITY] SIA detected."
        )

        # Immediate acknowledgement masks wake-processing delay and tells the
        # user exactly when Sara is ready for the command.
        self._play_wake_ack()

        initial_command = (
            self.strip_wake_word(
                wake_transcript
            )
        )

        # If command was already spoken in the same utterance,
        # there is no reason to wait for another utterance.
        if initial_command:
            print(
                f"[IDENTITY] Initial command: "
                f"{initial_command}"
            )

            return WakeCapture(
                audio=wake_audio,
                sample_rate=self.sample_rate,
                wake_transcript=wake_transcript,
                wake_word=wake_word,
                threshold=self.vad_threshold,
                speech_end=time.perf_counter(),
                capture_end=time.perf_counter(),
                partial_transcript="",
            )

        print(
            "[LISTENING] Waiting for command..."
        )

        command_result = self._capture_complete_utterance(
            stream,
            max_wait_seconds=VOICE_COMMAND_WAIT_SECONDS,
            label="COMMAND",
            end_silence_seconds=0.40,
            semantic_endpoint=True,
        )

        if command_result is None:
            print(
                "[IDENTITY] No command heard."
            )
            return None

        command_audio, command_speech_end, command_partial = command_result

        if command_audio.size == 0:
            return None

        # Combine wake utterance + following command.
        # Existing pipeline later transcribes the complete audio and strips
        # the wake word, so compatibility is preserved.
        combined = np.concatenate(
            [
                wake_audio,
                command_audio,
            ]
        ).astype(
            np.float32,
            copy=False,
        )

        return WakeCapture(
            audio=combined,
            sample_rate=self.sample_rate,
            wake_transcript=wake_transcript,
            wake_word=wake_word,
            threshold=self.vad_threshold,
            speech_end=command_speech_end,
            capture_end=time.perf_counter(),
            partial_transcript=command_partial,
        )

    def listen_for_command(
        self,
    ) -> WakeCapture:
        """
        STANDBY MODE.

        Wait indefinitely for a complete speech utterance.
        Transcribe it once.
        If configured wake word is present near the start, wake.
        """

        print()
        print("=" * 70)
        print("SIA - STANDBY")
        print("=" * 70)
        print(
            f'Waiting for identity: "{WAKE_WORD}"'
        )
        print("=" * 70)

        with self._open_stream() as stream:
            self._calibrate_noise(
                stream
            )

            while True:
                wake_result = self._capture_complete_utterance(
                    stream,
                    max_wait_seconds=None,
                    label="WAKE",
                    semantic_endpoint=False,
                )

                if wake_result is None:
                    continue

                wake_audio, wake_speech_end, wake_partial = wake_result

                if wake_audio.size == 0:
                    continue

                duration = (
                    len(wake_audio)
                    / self.sample_rate
                )

                text = (
                    self._transcribe_silent(
                        wake_audio
                    )
                )

                print(
                    f"[WAKE STT] "
                    f"{duration:.2f}s -> "
                    f"{text!r}"
                )

                if not text:
                    continue

                identity = (
                    self.find_wake_word(
                        text
                    )
                )

                if identity is None:
                    print(
                        "[WAKE] rejected"
                    )
                    continue

                result = (
                    self._capture_after_identity(
                        stream=stream,
                        wake_audio=wake_audio,
                        wake_transcript=text,
                        wake_word=identity,
                    )
                )

                if result is not None:
                    return result

                print()
                print(
                    "[IDENTITY] Returning to standby..."
                )

    def listen_active_command(
        self,
        max_wait_seconds: Optional[float] = None,
        end_silence_seconds: float = 0.42,
    ) -> Optional[WakeCapture]:
        """
        ACTIVE MODE.

        No wake word is required. The endpoint is intentionally faster than
        standby so turn-taking feels conversational. When max_wait_seconds is
        supplied, returning None means the active session timed out.
        """
        print()
        print("[MIC] Active conversation listening...")

        with self._open_stream() as stream:
            result = self._capture_complete_utterance(
                stream,
                max_wait_seconds=max_wait_seconds,
                label="MIC",
                end_silence_seconds=end_silence_seconds,
                semantic_endpoint=True,
            )

        if result is None:
            return None

        audio, speech_end, partial_text = result

        if audio.size == 0:
            return None

        duration = len(audio) / self.sample_rate
        print(f"[MIC] Active command captured {duration:.2f}s")

        return WakeCapture(
            audio=audio,
            sample_rate=self.sample_rate,
            wake_transcript="",
            wake_word="",
            threshold=self.vad_threshold,
            speech_end=speech_end,
            capture_end=time.perf_counter(),
            partial_transcript=partial_text,
        )

    def capture_barge_in(
        self,
        stop_event,
        on_speech_start=None,
        *,
        threshold_multiplier: float = 2.15,
        min_rms: float = 0.025,
        end_silence_seconds: float = 0.34,
    ) -> Optional[WakeCapture]:
        """
        Listen while Sara is speaking.

        A deliberately higher threshold is used to reduce false triggers from
        Sara's own loudspeaker audio. Without acoustic echo cancellation this
        can never be perfect; headphones give the cleanest PC-only barge-in.

        stop_event stops the monitor when speech has not started.
        on_speech_start is called immediately when a genuine high-energy onset
        is sustained, allowing playback to be interrupted before the utterance
        has finished.
        """
        trigger_blocks = max(2, int(0.09 / self.block_seconds))
        pre_roll = deque(maxlen=max(2, int(0.24 / self.block_seconds)))
        speech_blocks = []
        started = False
        hot_blocks = 0
        speech_start = None
        last_speech = None

        base_threshold = max(
            self.vad_threshold,
            VOICE_MIN_RMS,
            min_rms,
        )
        trigger_threshold = max(
            min_rms,
            base_threshold * threshold_multiplier,
        )
        release_threshold = max(
            VOICE_MIN_RMS,
            trigger_threshold * 0.42,
        )

        with self._open_stream() as stream:
            while True:
                if stop_event.is_set() and not started:
                    return None

                block, _ = stream.read(self.block_frames)
                block = np.asarray(
                    block,
                    dtype=np.float32,
                ).reshape(-1)

                block_rms = self.rms(block)
                now = time.perf_counter()

                if not started:
                    pre_roll.append(block.copy())

                    if block_rms >= trigger_threshold:
                        hot_blocks += 1
                    else:
                        hot_blocks = max(0, hot_blocks - 1)

                    if hot_blocks < trigger_blocks:
                        continue

                    started = True
                    speech_start = now
                    last_speech = now
                    speech_blocks.extend(list(pre_roll))
                    pre_roll.clear()

                    print(
                        f"[BARGE-IN] detected rms={block_rms:.5f} "
                        f"threshold={trigger_threshold:.5f}"
                    )

                    if on_speech_start is not None:
                        try:
                            on_speech_start()
                        except Exception:
                            pass

                    continue

                speech_blocks.append(block.copy())

                if block_rms >= release_threshold:
                    last_speech = now

                if speech_start is not None and now - speech_start >= 8.0:
                    break

                if (
                    last_speech is not None
                    and now - last_speech >= end_silence_seconds
                ):
                    break

        if not speech_blocks:
            return None

        audio = np.concatenate(speech_blocks).astype(
            np.float32,
            copy=False,
        )

        return WakeCapture(
            audio=audio,
            sample_rate=self.sample_rate,
            wake_transcript="",
            wake_word="",
            threshold=trigger_threshold,
            speech_end=float(last_speech or time.perf_counter()),
            capture_end=time.perf_counter(),
            partial_transcript="",
        )


def main():
    print()
    print("=" * 70)
    print("SIA PC LISTENER TEST")
    print("=" * 70)
    print("PC microphone only. ESP32/SIA is not used.")

    stt = (
        ParakeetSTT()
    )

    listener = (
        WakeListener(
            stt=stt
        )
    )

    try:
        capture = (
            listener
            .listen_for_command()
        )

        transcript = (
            stt.transcribe(
                capture.audio,
                sample_rate=capture.sample_rate,
            )
        )

        command = (
            listener
            .strip_wake_word(
                transcript
            )
        )

        print()
        print("=" * 70)
        print("STANDBY RESULT")
        print("=" * 70)
        print(
            f"Raw    : {transcript}"
        )
        print(
            f"Command: {command}"
        )
        print("=" * 70)

        print()
        print(
            "Sara is now ACTIVE."
        )

        active_capture = (
            listener
            .listen_active_command()
        )

        active_text = (
            stt.transcribe(
                active_capture.audio,
                sample_rate=active_capture.sample_rate,
            )
        )

        print()
        print("=" * 70)
        print("ACTIVE RESULT")
        print("=" * 70)
        print(
            f"Command: {active_text}"
        )
        print("=" * 70)

    except KeyboardInterrupt:
        print()
        print(
            "[SARA] Listener stopped."
        )


if __name__ == "__main__":
    main()
