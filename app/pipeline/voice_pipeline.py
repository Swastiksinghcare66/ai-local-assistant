from __future__ import annotations

import asyncio
import contextlib
import io
import re
import threading
import time
import os

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.audio.cosyvoice_client import CosyVoicePersistentClient
from app.audio.piper_client import PiperTTSClient
from app.audio.language_router import LanguageRouter
from app.audio.hinglish_normalizer import HinglishNormalizer
from app.audio.stt import ParakeetSTT
from app.audio.multilingual_stt import MultilingualSTT
from app.audio.wake_listener import WakeCapture
from app.audio.sia_hardware import SIAHardware
from app.audio.sia_audio_source import SIAHardwareListener
from app.audio.sia_playback import SIAAudioPlayer
from app.config import (
    ASSISTANT_NAME,
    LLM_MODEL,
    PREFERRED_CONVERSATION_LANGUAGE,
    FOLLOW_USER_LANGUAGE,
    HINGLISH_TTS_ENABLED,
    PIPER_ENABLED,
    PIPER_MODEL_PATH,
    PIPER_CONFIG_PATH,
    PIPER_TARGET_SAMPLE_RATE,
    PIPER_MAX_GAIN,
    PIPER_TARGET_PEAK,
    PIPER_PACKET_MS,
    PIPER_USE_CUDA,
    PIPER_TARGET_RMS,
    PIPER_GAIN_SMOOTHING,
    PIPER_DSP_ENABLED,
    PIPER_PROSODY_ENABLED,
    MULTILINGUAL_STT_ENABLED,
    MULTILINGUAL_STT_MODEL_DIR,
    MULTILINGUAL_STT_DEVICE,
    MULTILINGUAL_STT_COMPUTE_TYPE,
    MULTILINGUAL_STT_CPU_THREADS,
    MULTILINGUAL_STT_NUM_WORKERS,
    MULTILINGUAL_STT_BEAM_SIZE,
    MULTILINGUAL_STT_INITIAL_PROMPT,
    MULTILINGUAL_STT_FALLBACK_TO_PARAKEET,
)
from app.llm_client import chat_stream, warmup
from app.prompt_builder import AdaptiveState, PromptBuilder
from app.pipeline.text_chunker import (
    HybridSpeechChunker,
    is_speakable_phrase as chunk_is_speakable_phrase,
    normalize_for_speech,
)

FLOW_STEPS = 3

# ============================================================
# SENTENCE-LEVEL TTS STREAMING
# ============================================================

_COMMON_ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.",
    "vs.", "etc.", "e.g.", "i.e.", "a.m.", "p.m.",
    "fig.", "eq.", "no.",
}

_CLOSERS = "\"'â€â€™)]}"


def is_speakable_phrase(text: str) -> bool:
    return chunk_is_speakable_phrase(text)


class SemanticPhraseBuffer:
    """
    Backward-compatible class name with strict sentence-stream behavior.

    Periods are confirmed conservatively so technical strings such as 3.14,
    qwen3:1.7b, app.py, example.com, U.S., and inline code are not split.
    """

    def __init__(self):
        self.buffer = ""

    @staticmethod
    def _clean(text: str) -> str:
        return " ".join(str(text).strip().split())

    @staticmethod
    def _last_token(text: str) -> str:
        text = text.rstrip()
        if not text:
            return ""
        return text.split()[-1].lower()

    def _inside_backticks(self, index: int) -> bool:
        prefix = self.buffer[:index]

        if prefix.count("```") % 2 == 1:
            return True

        return prefix.replace("```", "").count("`") % 2 == 1

    @staticmethod
    def _looks_like_acronym(token: str) -> bool:
        return bool(
            re.fullmatch(
                r"(?:[A-Za-z]\.){2,}",
                token,
            )
        )

    def _period_is_boundary(self, index: int) -> bool:
        if self._inside_backticks(index):
            return False

        if (
            index + 1 < len(self.buffer)
            and self.buffer[index + 1] == "."
        ):
            return False

        if (
            index > 0
            and index + 1 < len(self.buffer)
            and self.buffer[index - 1].isdigit()
            and self.buffer[index + 1].isdigit()
        ):
            return False

        token = self._last_token(
            self.buffer[: index + 1]
        )

        if token in _COMMON_ABBREVIATIONS:
            return False

        if self._looks_like_acronym(token):
            return False

        stem = token[:-1]
        if len(stem) == 1 and stem.isalpha():
            return False

        if index + 1 < len(self.buffer):
            nxt = self.buffer[index + 1]

            if nxt.isalnum() or nxt in "_-/\\":
                return False

            if nxt.isspace() or nxt in _CLOSERS:
                return True

            return False

        # Wait for one more streamed character before accepting a period.
        # This avoids false boundaries when a decimal/version is split across
        # LLM chunks.
        return False

    def _find_sentence_boundary(self) -> Optional[int]:
        index = 0

        while index < len(self.buffer):
            char = self.buffer[index]

            if char not in ".!?":
                index += 1
                continue

            if self._inside_backticks(index):
                index += 1
                continue

            if char == "." and not self._period_is_boundary(index):
                index += 1
                continue

            end = index + 1

            while (
                end < len(self.buffer)
                and self.buffer[end] in ".!?"
            ):
                end += 1

            while (
                end < len(self.buffer)
                and self.buffer[end] in _CLOSERS
            ):
                end += 1

            return end

        return None

    def feed(self, text: str) -> list[str]:
        if not text:
            return []

        self.buffer += text
        sentences: list[str] = []

        while True:
            boundary = self._find_sentence_boundary()

            if boundary is None:
                break

            sentence = self._clean(
                self.buffer[:boundary]
            )

            self.buffer = (
                self.buffer[boundary:]
                .lstrip()
            )

            if is_speakable_phrase(sentence):
                sentences.append(sentence)

        return sentences

    def flush(self) -> list[str]:
        tail = self._clean(self.buffer)
        self.buffer = ""

        return (
            [tail]
            if is_speakable_phrase(tail)
            else []
        )


@dataclass
class _ProducerFailure:
    error: BaseException


_PRODUCER_DONE = object()


class ConversationState(str, Enum):
    STANDBY = "standby"
    WAKE_ACK = "wake_ack"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    ACTIVE_WAIT = "active_wait"
    OFFLINE = "offline"


@dataclass
class VoiceTiming:
    speech_end: Optional[float] = None
    capture_end: Optional[float] = None
    stt_start: Optional[float] = None
    stt_end: Optional[float] = None
    llm_start: Optional[float] = None
    llm_first_text: Optional[float] = None
    llm_end: Optional[float] = None
    first_tts_text: Optional[float] = None
    first_audio: Optional[float] = None
    playback_end: Optional[float] = None

    @staticmethod
    def _ms(a, b):
        if a is None or b is None:
            return None
        return max(0.0, (b - a) * 1000.0)

    def metrics(self) -> dict:
        return {
            "endpoint_ms": self._ms(
                self.speech_end,
                self.capture_end,
            ),
            "stt_ms": self._ms(
                self.stt_start,
                self.stt_end,
            ),
            "llm_ttft_ms": self._ms(
                self.llm_start,
                self.llm_first_text,
            ),
            "chunk_wait_ms": self._ms(
                self.llm_first_text,
                self.first_tts_text,
            ),
            "tts_ttfa_ms": self._ms(
                self.first_tts_text,
                self.first_audio,
            ),
            "speech_to_audio_ms": self._ms(
                self.speech_end,
                self.first_audio,
            ),
        }

    def print_report(self):
        metrics = self.metrics()

        parts = []
        for key, value in metrics.items():
            if value is not None:
                parts.append(f"{key}={value:.1f}")

        if parts:
            print("[LATENCY] " + "ms ".join(parts) + "ms")


@dataclass
class VoiceTurnResult:
    transcript: str
    response: str
    timing: VoiceTiming
    state: AdaptiveState


class VoicePipeline:
    """
    Sara / SIA hardware-integrated voice pipeline:

    INMP441
    -> ESP32-S3 AFE (AEC + NS + VAD)
    -> SIA USB protocol
    -> SIAHardwareListener
    -> Parakeet
    -> adaptive PromptBuilder
    -> Qwen streaming
    -> low-latency hybrid phrases
    -> persistent CosyVoice 24 kHz
    -> SIAAudioPlayer 24 kHz -> 16 kHz
    -> ESP32-S3
    -> MAX98357A
    -> speaker.
    """

    def __init__(
        self,
        model_name: str = LLM_MODEL,
        history_limit: int = 8,
        flow_steps: int = FLOW_STEPS,
    ):
        self.model_name = model_name
        self.history_limit = max(
            2,
            int(history_limit),
        )

        self.flow_steps = int(
            flow_steps
        )

        self.prompt_builder = PromptBuilder()

        self.history: list[dict] = []

        self.hardware: Optional[
            SIAHardware
        ] = None

        self.hardware_player: Optional[
            SIAAudioPlayer
        ] = None

        self.stt: Optional[
            ParakeetSTT
        ] = None

        # Conversation STT is deliberately separate from wake STT.
        # Parakeet remains the proven SIA wake recognizer; Faster-Whisper
        # handles Hindi/Hinglish/English after wake.
        self.conversation_stt: Optional[
            MultilingualSTT
        ] = None
        self.multilingual_stt_ready = False

        self.wake_listener: Optional[
            SIAHardwareListener
        ] = None

        self.tts: Optional[
            CosyVoicePersistentClient
        ] = None

        self.piper_tts: Optional[
            PiperTTSClient
        ] = None

        self.piper_ready = False

        self.language_router = LanguageRouter(
            default_language=PREFERRED_CONVERSATION_LANGUAGE,
            follow_user_language=FOLLOW_USER_LANGUAGE,
        )

        self.hinglish_normalizer = HinglishNormalizer()

        self.initialized = False

        # Internal listener cycle timeout only. main.py intentionally keeps SIA
        # ACTIVE after idle cycles; only an explicit sleep/standby command returns
        # to wake-word mode.
        self.active_session_timeout = float(
            os.getenv("SARA_ACTIVE_TIMEOUT", "24.0")
        )
        # Barge-in is intentionally disabled in the stable conversational path.
        # While SIA is speaking, the microphone is not opened for interruption
        # detection. STT starts only after TTS/playback completes and the main
        # state machine enters ACTIVE listening again.
        self.barge_in_enabled = False

        # Kept only for API/backward compatibility with older configuration.
        self.barge_confirm_ms = 260
        self.barge_rms_multiplier = 2.40
        self.barge_min_rms = 0.015
        self._pending_barge_capture: Optional[WakeCapture] = None
        self._pending_barge_text: str = ""

        self.conversation_state = ConversationState.STANDBY
        self._state_changed_at = time.perf_counter()

        # Backchannels should not destroy a long answer. These are deliberately
        # short and conservative.
        self._backchannels = {
            "hmm", "hm", "mm", "mhm", "uh huh", "uh-huh",
            "yeah", "yep", "yes", "right", "okay", "ok", "got it",
        }

    def set_state(
        self,
        state: ConversationState | str,
    ):
        try:
            new_state = (
                state
                if isinstance(state, ConversationState)
                else ConversationState(str(state))
            )
        except ValueError:
            return

        if new_state == self.conversation_state:
            return

        old = self.conversation_state
        self.conversation_state = new_state
        self._state_changed_at = time.perf_counter()

        print(
            f"[VOICE STATE] {old.value} -> {new_state.value}"
        )

    @staticmethod
    def _normalize_backchannel_text(text: str) -> str:
        text = re.sub(
            r"[^a-z0-9\s'-]",
            " ",
            str(text or "").lower(),
        )
        return " ".join(text.split()).strip()

    def _is_backchannel(self, text: str) -> bool:
        norm = self._normalize_backchannel_text(text)

        if not norm:
            return True

        if norm in self._backchannels:
            return True

        words = norm.split()

        if (
            len(words) <= 2
            and all(
                word in {
                    "hmm", "hm", "mm", "mhm", "yeah", "yep",
                    "yes", "right", "okay", "ok",
                }
                for word in words
            )
        ):
            return True

        return False

    def _is_probable_self_echo(
        self,
        text: str,
        spoken_sentence: str,
    ) -> bool:
        """Conservatively reject transcripts that are clearly Sara's own TTS."""
        heard = self._normalize_backchannel_text(text)
        spoken = self._normalize_backchannel_text(spoken_sentence)

        if not heard or not spoken:
            return False

        heard_words = heard.split()
        spoken_words = spoken.split()

        # One-word interruptions are too ambiguous to suppress as echo.
        if len(heard_words) < 2:
            return False

        # Strongest signal: STT returned a contiguous fragment of the sentence
        # currently being spoken.
        if len(heard) >= 5 and heard in spoken:
            return True

        # Also catch small AEC/STT distortions where nearly every recognized
        # content word came from the current TTS sentence.  Keep this
        # conservative to avoid swallowing genuine user interruptions.
        spoken_set = set(spoken_words)
        overlap = sum(
            1 for word in heard_words
            if word in spoken_set
        )
        overlap_ratio = overlap / max(1, len(heard_words))

        return (
            2 <= len(heard_words) <= 6
            and overlap_ratio >= 0.85
        )

    async def initialize(self):
        if self.initialized:
            return

        print()
        print("=" * 72)
        print("SARA FINAL VOICE PIPELINE")
        print("=" * 72)

        # ====================================================
        # PARakeet STT
        # ====================================================

        print(
            "[STT] Initializing Parakeet..."
        )

        self.stt = await asyncio.to_thread(
            ParakeetSTT
        )

        # ====================================================
        # MULTILINGUAL HINDI / HINGLISH / ENGLISH STT
        # ====================================================
        # Wake remains on Parakeet. This model is only used to transcribe the
        # actual command/conversation after SIA has been detected.
        if MULTILINGUAL_STT_ENABLED:
            print(
                "[STT] Initializing multilingual conversation recognizer..."
            )
            try:
                self.conversation_stt = await asyncio.to_thread(
                    MultilingualSTT,
                    MULTILINGUAL_STT_MODEL_DIR,
                    device=MULTILINGUAL_STT_DEVICE,
                    compute_type=MULTILINGUAL_STT_COMPUTE_TYPE,
                    cpu_threads=MULTILINGUAL_STT_CPU_THREADS,
                    num_workers=MULTILINGUAL_STT_NUM_WORKERS,
                    beam_size=MULTILINGUAL_STT_BEAM_SIZE,
                    initial_prompt=MULTILINGUAL_STT_INITIAL_PROMPT,
                )
                self.multilingual_stt_ready = True
                print(
                    "[STT] Dual-STT ready: Parakeet=wake, "
                    "Faster-Whisper=conversation"
                )
            except Exception as exc:
                self.conversation_stt = None
                self.multilingual_stt_ready = False
                print(
                    "[MULTILINGUAL STT] unavailable; "
                    f"Parakeet fallback active: {type(exc).__name__}: {exc}"
                )

        # ====================================================
        # ESP32-S3 HARDWARE
        # ====================================================

        sia_port = os.getenv(
            "SIA_PORT",
            "COM10",
        )

        print(
            "[HARDWARE] Connecting "
            f"SIA ESP32-S3 on {sia_port}..."
        )

        self.hardware = SIAHardware(
            port=sia_port,
        )

        device = await asyncio.to_thread(
            self.hardware.connect
        )

        print(
            "[HARDWARE] ESP32-S3 ready "
            f"sample_rate={device.sample_rate} "
            f"features=0x{device.features:08X}"
        )

        # Standby/boot speaker route.
        await asyncio.to_thread(
            self.hardware.set_route_bluetooth
        )

        # ====================================================
        # HARDWARE WAKE / ACTIVE LISTENER
        # ====================================================

        print(
            "[LISTENER] Initializing "
            "ESP32-S3 SIA listener..."
        )

        self.wake_listener = SIAHardwareListener(
            hardware=self.hardware,
            stt=self.stt,
            sample_rate=device.sample_rate,
        )

        # ====================================================
        # COSYVOICE -> ESP32-S3 -> MAX98357A
        # ====================================================

        print(
            "[TTS] Initializing "
            "SIA hardware playback..."
        )

        self.hardware_player = SIAAudioPlayer(
            hardware=self.hardware,
            input_sample_rate=24000,
            output_sample_rate=16000,
            slice_ms=20,
        )

        print(
            "[TTS] Connecting persistent "
            "CosyVoice..."
        )

        self.tts = CosyVoicePersistentClient(
            playback=True,
            player=None,
            default_style="warm_conversational",
            default_flow_steps=self.flow_steps,
        )

        await self.tts.connect()

        ping = await self.tts.ping()

        print(
            f"[TTS] ready "
            f"server={ping.get('server')} "
            f"ping="
            f"{ping.get('latency_ms', 0.0):.1f}ms"
        )

        # ====================================================
        # PIPER HINDI / HINGLISH -> DIRECT 16 kHz SIA HARDWARE
        # ====================================================

        if HINGLISH_TTS_ENABLED and PIPER_ENABLED:
            self.piper_tts = PiperTTSClient(
                model_path=PIPER_MODEL_PATH,
                config_path=PIPER_CONFIG_PATH,
                hardware=self.hardware,
                target_sample_rate=PIPER_TARGET_SAMPLE_RATE,
                use_cuda=PIPER_USE_CUDA,
                packet_ms=PIPER_PACKET_MS,
                target_peak=PIPER_TARGET_PEAK,
                max_gain=PIPER_MAX_GAIN,
                target_rms=PIPER_TARGET_RMS,
                gain_smoothing=PIPER_GAIN_SMOOTHING,
                dsp_enabled=PIPER_DSP_ENABLED,
                prosody_enabled=PIPER_PROSODY_ENABLED,
            )

            try:
                await self.piper_tts.connect()
                self.piper_ready = True
                print(
                    "[LANGUAGE] Hinglish/Hindi Piper direct-16k path ready; "
                    "English remains on CosyVoice."
                )
            except Exception as exc:
                # Do not make SIA unbootable if Piper/model is not installed yet.
                # English/CosyVoice remains fully operational.
                self.piper_ready = False
                print(
                    "[PIPER] Hindi/Hinglish path unavailable; "
                    f"falling back to CosyVoice: {type(exc).__name__}: {exc}"
                )

        # ====================================================
        # QWEN WARMUP
        # ====================================================

        print(
            "[LLM] Warming Qwen after "
            "CosyVoice is resident..."
        )

        try:
            ready = await asyncio.to_thread(
                warmup,
                self.model_name,
            )

        except TypeError:
            ready = await asyncio.to_thread(
                warmup
            )

        if ready is False:
            raise RuntimeError(
                "Qwen warm-up failed."
            )

        self.initialized = True

        print("=" * 72)
        print(
            "SARA FINAL VOICE PIPELINE READY"
        )
        print("=" * 72)

    async def close(self):
        """Close TTS, listener state, and ESP32 hardware cleanly."""

        first_error = None

        if self.piper_tts is not None:
            try:
                await self.piper_tts.close()
            except Exception as exc:
                first_error = exc
            finally:
                self.piper_tts = None
                self.piper_ready = False

        if self.tts is not None:
            try:
                await self.tts.close()
            except Exception as exc:
                first_error = exc
            finally:
                self.tts = None

        self.hardware_player = None

        if self.hardware is not None:
            try:
                await asyncio.to_thread(
                    self.hardware.close
                )
            except Exception as exc:
                if first_error is None:
                    first_error = exc
            finally:
                self.hardware = None

        self.wake_listener = None
        self.conversation_stt = None
        self.multilingual_stt_ready = False
        self.stt = None
        self.initialized = False

        if first_error is not None:
            raise first_error

    # ========================================================
    # AUDIO CAPTURE
    # ========================================================

    def listen(self) -> WakeCapture:
        """
        Hardware standby mode.

        While waiting for SIA:
            speaker route -> Bluetooth/PAM

        After SIA is accepted:
            speaker route -> SIA/MAX98357A
        """

        if (
            self.wake_listener is None
            or self.hardware is None
        ):
            raise RuntimeError(
                "SIA hardware listener "
                "is not initialized."
            )

        # Standby owns no chatbot speaker path.
        self.hardware.set_route_bluetooth()

        capture = (
            self.wake_listener
            .listen_for_command()
        )

        # Wake accepted: move BOTH speaker leads to
        # MAX98357A before command processing/TTS.
        self.hardware.set_route_sia()

        return capture

    def listen_active(
        self,
        timeout_seconds: Optional[float] = None,
    ) -> Optional[WakeCapture]:
        """
        Active conversation mode.

        No wake-word requirement. Returning None means only that this internal
        listening cycle was idle. main.py keeps SIA ACTIVE and starts another
        cycle; only an explicit sleep/standby command returns to standby.
        """
        if (
            self.wake_listener is None
            or self.hardware is None
        ):
            raise RuntimeError(
                "SIA hardware listener is not initialized."
            )

        # Active conversation must keep the speaker connected
        # to MAX98357A. This is normally already true after wake,
        # but keeping it explicit makes direct-active startup safe.
        self.hardware.set_route_sia()

        if timeout_seconds is None:
            timeout_seconds = self.active_session_timeout

        return self.wake_listener.listen_active_command(
            max_wait_seconds=timeout_seconds,
            end_silence_seconds=0.42,
        )

    def pop_barge_in_capture(self) -> Optional[WakeCapture]:
        capture = self._pending_barge_capture
        self._pending_barge_capture = None
        return capture

    def pop_barge_in_text(self) -> str:
        text = self._pending_barge_text
        self._pending_barge_text = ""
        return text

    def play_wake_ack(self):
        """
        No PC-speaker acknowledgement in hardware mode.

        A dedicated ESP32/MAX98357A chime can be added later
        without changing wake detection or the conversation path.
        """
        return

    async def interrupt_speech(self):
        if self.tts is not None and hasattr(self.tts, "interrupt"):
            try:
                await self.tts.interrupt()
            except Exception:
                pass

    # ========================================================
    # STT
    # ========================================================

    @staticmethod
    def _strip_wake_prefix_preserve_unicode(text: str) -> str:
        """Remove the SIA wake prefix without destroying Hindi/Devanagari text."""
        text = str(text or "").strip()
        if not text:
            return ""

        # Faster-Whisper may render SIA in several plausible ways. This list is
        # only used after Parakeet has already confirmed that the utterance was a
        # valid wake event, so it cannot create new wake false positives.
        wake_variants = (
            r"sia",
            r"sya",
            r"siah",
            r"sir",
            r"see\s+ya",
            r"see\s+a",
            r"c\s*i\s*a",
        )
        variants = "|".join(wake_variants)
        greeting = r"(?:(?:hey|hello|hi|ok|okay)\s+)?"

        cleaned = re.sub(
            rf"^\s*{greeting}(?:{variants})(?=\s|[,.!?;:\-]|$)[\s,.!?;:\-]*",
            "",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
        return cleaned.strip()

    def _transcribe_conversation_audio(
        self,
        capture: WakeCapture,
    ) -> str:
        """Use multilingual STT when ready, with safe Parakeet fallback."""
        if (
            self.multilingual_stt_ready
            and self.conversation_stt is not None
        ):
            try:
                text = self.conversation_stt.transcribe(
                    capture.audio,
                    sample_rate=capture.sample_rate,
                ).strip()
                if text:
                    print("[STT ROUTE] multilingual conversation STT")
                    return text
            except Exception as exc:
                print(
                    "[MULTILINGUAL STT ERROR] "
                    f"{type(exc).__name__}: {exc}"
                )
                if not MULTILINGUAL_STT_FALLBACK_TO_PARAKEET:
                    raise

        if self.stt is None:
            raise RuntimeError("Parakeet STT is not initialized.")

        print("[STT ROUTE] Parakeet fallback")

        if (
            self.wake_listener is not None
            and hasattr(self.wake_listener, "_transcribe_silent")
        ):
            return self.wake_listener._transcribe_silent(
                capture.audio
            ).strip()

        return self.stt.transcribe(
            capture.audio,
            sample_rate=capture.sample_rate,
        ).strip()

    def transcribe_capture(
        self,
        capture: WakeCapture,
        timing: Optional[
            VoiceTiming
        ] = None,
        strip_wake_word: bool = True,
    ) -> str:

        if capture is None:
            return ""

        if self.stt is None:
            raise RuntimeError(
                "Parakeet STT is not initialized."
            )

        self.set_state(
            ConversationState.TRANSCRIBING
        )

        if timing is not None:
            timing.speech_end = getattr(
                capture,
                "speech_end",
                None,
            )
            timing.capture_end = getattr(
                capture,
                "capture_end",
                None,
            )
            timing.stt_start = time.perf_counter()

        # Standby wake captures have already been transcribed by
        # Parakeet in the wake listener. Re-transcribing the exact same
        # audio with Faster-Whisper can replace a correct wake command
        # with a hallucination and adds ~2-3 seconds of unnecessary STT.
        #
        # ACTIVE captures have wake_word="" and therefore continue to
        # use multilingual Faster-Whisper normally.
        wake_text = str(
            getattr(capture, "wake_transcript", "")
            or ""
        ).strip()

        has_wake_identity = bool(
            getattr(capture, "wake_word", "")
        )

        if has_wake_identity and wake_text:
            text = wake_text
            print(
                "[STT ROUTE] trusted Parakeet wake transcript "
                "(second STT skipped)"
            )
        else:
            text = self._transcribe_conversation_audio(
                capture
            )

        if timing is not None:
            timing.stt_end = time.perf_counter()

        # Only standby captures actually contain a wake prefix. Active captures
        # have wake_word="", so their first real word is never stripped.
        if (
            strip_wake_word
            and bool(getattr(capture, "wake_word", ""))
        ):
            text = self._strip_wake_prefix_preserve_unicode(
                text
            )

        if text:
            language = self.language_router.observe_user_text(text)
            print(
                "[LANGUAGE] user="
                f"{language.language} "
                f"confidence={language.confidence:.2f} "
                f"reason={language.reason}"
            )

        return text


    def transcribe_private_capture(
        self,
        capture: WakeCapture,
    ) -> str:
        """
        Private shutdown-code STT.

        Output is never printed, logged, stored in history, or sent to the LLM.
        It also uses the same serialized Parakeet path as incremental STT.
        """
        if self.stt is None or capture is None:
            return ""

        sink = io.StringIO()

        with (
            contextlib.redirect_stdout(sink),
            contextlib.redirect_stderr(sink),
        ):
            if (
                self.wake_listener is not None
                and hasattr(
                    self.wake_listener,
                    "_transcribe_silent",
                )
            ):
                return self.wake_listener._transcribe_silent(
                    capture.audio
                ).strip()

            if hasattr(
                self.stt,
                "transcribe_silent",
            ):
                try:
                    return (
                        self.stt
                        .transcribe_silent(
                            capture.audio,
                            sample_rate=capture.sample_rate,
                        )
                        .strip()
                    )
                except TypeError:
                    pass

            return (
                self.stt
                .transcribe(
                    capture.audio,
                    sample_rate=capture.sample_rate,
                )
                .strip()
            )

    # ========================================================
    # SIMPLE TTS
    # ========================================================
    # SIMPLE TTS
    # ========================================================

    async def _speak_sentence(
        self,
        sentence: str,
        style: str,
    ):
        """
        Speak one sentence without opening the microphone.

        Stable turn-taking policy:
            user speech -> STT -> response generation -> TTS/playback
            -> ACTIVE listening -> next STT

        There is deliberately no barge-in monitor here. This prevents Sara's
        own speaker output, room noise, relay clicks, or AEC residuals from
        pausing TTS or launching STT while she is speaking.
        """
        if self.tts is None:
            raise RuntimeError(
                "CosyVoice is not initialized."
            )

        sentence = normalize_for_speech(sentence)

        if not is_speakable_phrase(sentence):
            return None

        self.set_state(
            ConversationState.SPEAKING
        )

        output_language = self.language_router.classify_output(sentence)
        preferred_language = self.language_router.current_language

        use_piper = (
            HINGLISH_TTS_ENABLED
            and self.piper_ready
            and self.piper_tts is not None
            and preferred_language in {"hinglish", "hindi"}
            and output_language.language in {"hinglish", "hindi"}
        )

        if use_piper:
            piper_text = self.hinglish_normalizer.to_piper_text(sentence)
            print(
                "[TTS ROUTER] "
                f"preferred={preferred_language} "
                f"detected={output_language.language} "
                "engine=piper-hi_IN"
            )

            try:
                return await self.piper_tts.speak(
                    piper_text,
                    style=style,
                    flow_steps=self.flow_steps,
                )
            except Exception as exc:
                # Fail open to the proven English/CosyVoice path rather than
                # dropping a spoken answer mid-conversation.
                print(
                    "[PIPER ERROR] "
                    f"{type(exc).__name__}: {exc}; "
                    "falling back to CosyVoice."
                )

        print(
            "[TTS ROUTER] "
            f"preferred={preferred_language} "
            f"detected={output_language.language} "
            "engine=cosyvoice"
        )

        return await self.tts.speak(
            sentence,
            style=style,
            flow_steps=self.flow_steps,
        )

    @staticmethod
    def _report_tts_health(
        result,
        sentence_index: int,
    ):
        if not result:
            return

        server = result.get("server") or {}
        rtf = server.get("rtf")

        if rtf is None:
            return

        try:
            rtf_value = float(rtf)
        except (TypeError, ValueError):
            return

        if rtf_value >= 1.0:
            print(
                f"[TTS GAP RISK] sentence={sentence_index} "
                f"RTF={rtf_value:.3f} >= 1.0; "
                "TTS generation may not stay ahead of playback."
            )

    async def speak_text(
        self,
        text: str,
        style: str = "warm_conversational",
        wait_for_playback: bool = True,
    ):
        """
        Speak existing agent/tool text sentence by sentence.

        app.main uses this method for handled agent commands. Therefore both
        agent responses and general-chat fallback now share the same sentence
        streaming policy.
        """

        if not is_speakable_phrase(text):
            return None

        if self.tts is None:
            raise RuntimeError(
                "CosyVoice is not initialized."
            )

        chunker = HybridSpeechChunker()
        sentences = chunker.feed(str(text))
        sentences.extend(chunker.flush())

        last_result = None

        for index, sentence in enumerate(
            sentences,
            start=1,
        ):
            print(
                f"[TTS:{style}] "
                f"sentence={index} "
                f"{sentence}"
            )

            last_result = await self._speak_sentence(
                sentence,
                style,
            )

            self._report_tts_health(
                last_result,
                index,
            )

            if (
                last_result
                and last_result.get("interrupted")
            ):
                break

        if (
            wait_for_playback
            and self._pending_barge_capture is None
        ):
            await asyncio.to_thread(
                self.tts.wait_for_playback
            )

        return last_result

    # ========================================================
    # HISTORY
    # ========================================================

    def clear_history(self):
        self.history.clear()

    def _trim_history(self):
        if (
            len(self.history)
            > self.history_limit
        ):
            del self.history[
                :-self.history_limit
            ]

    # ========================================================
    # GENERATE + STREAM + SPEAK
    # ========================================================

    async def generate_and_speak(
        self,
        transcript: str,
        timing: Optional[
            VoiceTiming
        ] = None,
    ) -> VoiceTurnResult:

        if self.tts is None:
            raise RuntimeError(
                "CosyVoice is not initialized."
            )

        transcript = str(
            transcript or ""
        ).strip()

        timing = timing or VoiceTiming()

        language = self.language_router.observe_user_text(transcript)

        raw_messages = [
            *self.history,
            {
                "role": "user",
                "content": transcript,
            },
        ]

        state = (
            self.prompt_builder
            .get_state(raw_messages)
        )

        try:
            messages = (
                self.prompt_builder
                .build(
                    raw_messages,
                    state=state,
                )
            )
        except TypeError:
            messages = (
                self.prompt_builder
                .build(raw_messages)
            )

        # Add only a language/output-format directive. PromptBuilder still owns
        # personality, adaptive behavior, context trimming, and safety wording.
        language_instruction = self.language_router.llm_instruction(
            language.language
        )

        if (
            messages
            and isinstance(messages[0], dict)
            and messages[0].get("role") == "system"
        ):
            messages[0]["content"] = (
                str(messages[0].get("content") or "").rstrip()
                + "\n\n"
                + language_instruction
            )

        print(
            "[LANGUAGE] response="
            f"{language.language} "
            f"confidence={language.confidence:.2f} "
            f"reason={language.reason}"
        )

        print()
        print("=" * 72)
        print(ASSISTANT_NAME.upper())
        print("=" * 72)

        print(
            f"[MODE]       "
            f"{state.mode}"
        )

        print(
            f"[EMOTION]    "
            f"{state.primary_emotion} / "
            f"{state.secondary_emotion}"
        )

        print(
            f"[VOICE]      "
            f"{state.voice_style}"
        )

        print(
            f"[SHY]        "
            f"{state.shyness:.2f}"
        )

        print(
            f"[HUMILITY]   "
            f"{getattr(state, 'humility', 0.76):.2f}"
        )

        print(
            f"[ASSERTIVE]  "
            f"{getattr(state, 'assertiveness', 0.58):.2f}"
        )

        print(
            f"[EMPATHY]    "
            f"{getattr(state, 'empathy', 0.56):.2f}"
        )

        print(
            f"[HUMOR]      "
            f"{state.humor_level}"
        )

        print(
            f"[LAUGH OK]   "
            f"{state.laugh_allowed}"
        )

        print()

        sentence_queue: asyncio.Queue = (
            asyncio.Queue()
        )

        loop = asyncio.get_running_loop()
        sentence_buffer = HybridSpeechChunker()
        response_parts: list[str] = []
        abort_generation = threading.Event()

        self.set_state(
            ConversationState.THINKING
        )
        timing.llm_start = time.perf_counter()

        # ====================================================
        # LLM PRODUCER THREAD
        # ====================================================

        def producer():
            try:
                try:
                    stream = chat_stream(
                        messages=messages,
                        model_name=self.model_name,
                    )
                except TypeError:
                    stream = chat_stream(
                        messages=messages
                    )

                for chunk in stream:
                    if abort_generation.is_set():
                        break

                    now = time.perf_counter()

                    if timing.llm_first_text is None:
                        timing.llm_first_text = now

                    print(
                        chunk,
                        end="",
                        flush=True,
                    )

                    response_parts.append(chunk)

                    emitted = sentence_buffer.feed(
                        chunk,
                        now=now,
                    )

                    emitted.extend(
                        sentence_buffer.poll(
                            now=time.perf_counter(),
                        )
                    )

                    for sentence in emitted:
                        loop.call_soon_threadsafe(
                            sentence_queue.put_nowait,
                            (
                                "sentence",
                                sentence,
                                time.perf_counter(),
                            ),
                        )

                for sentence in sentence_buffer.flush():
                    loop.call_soon_threadsafe(
                        sentence_queue.put_nowait,
                        (
                            "sentence",
                            sentence,
                            time.perf_counter(),
                        ),
                    )

            except BaseException as exc:
                loop.call_soon_threadsafe(
                    sentence_queue.put_nowait,
                    (
                        "error",
                        _ProducerFailure(exc),
                    ),
                )

            finally:
                timing.llm_end = time.perf_counter()

                loop.call_soon_threadsafe(
                    sentence_queue.put_nowait,
                    (
                        "done",
                        _PRODUCER_DONE,
                    ),
                )

        thread = threading.Thread(
            target=producer,
            daemon=True,
            name="sara-llm-stream",
        )

        thread.start()

        first_sentence = True
        sentence_index = 0
        producer_failure = None

        # ====================================================
        # TTS CONSUMER
        # ====================================================
        #
        # Do not fire concurrent CosyVoice speak() calls.
        # The persistent client/server serialize inference. The PCM player
        # already queues audio, so generation of sentence N+1 can overlap
        # playback of sentence N without overlapping WebSocket receive loops.

        while True:
            item = await sentence_queue.get()
            kind = item[0]

            if kind == "done":
                break

            if kind == "error":
                producer_failure = item[1]
                continue

            _, sentence, emitted_at = item
            sentence_index += 1

            if first_sentence:
                timing.first_tts_text = emitted_at
                first_sentence = False

            print()
            print(
                f"[TTS:{state.voice_style}] "
                f"sentence={sentence_index} "
                f"{sentence}"
            )

            tts_start = time.perf_counter()

            result = await self._speak_sentence(
                sentence,
                state.voice_style,
            )

            self._report_tts_health(
                result,
                sentence_index,
            )

            if (
                result
                and result.get("interrupted")
            ):
                abort_generation.set()
                break

            if (
                timing.first_audio is None
                and result
                and result.get("client_ttfa_ms") is not None
            ):
                timing.first_audio = (
                    tts_start
                    + result["client_ttfa_ms"] / 1000.0
                )

        await asyncio.to_thread(
            thread.join
        )

        if producer_failure is not None:
            raise RuntimeError(
                "Qwen streaming failed."
            ) from producer_failure.error

        print()

        # Wait only once at the end. This preserves overlap between
        # sentence generation and the existing queued PCM playback.
        if self._pending_barge_capture is None:
            await asyncio.to_thread(
                self.tts.wait_for_playback
            )

        timing.playback_end = time.perf_counter()

        # Single-INMP441 post-playback guard.
        # Prevent speaker tail / room reflections from immediately becoming
        # a new ACTIVE user turn.
        post_tts_guard_ms = float(
            os.getenv("SIA_POST_TTS_GUARD_MS", "300")
        )

        if (
            self._pending_barge_capture is None
            and post_tts_guard_ms > 0
        ):
            await asyncio.sleep(
                post_tts_guard_ms / 1000.0
            )

        response = "".join(
            response_parts
        ).strip()

        self.history.extend(
            [
                {
                    "role": "user",
                    "content": transcript,
                },
                {
                    "role": "assistant",
                    "content": response,
                },
            ]
        )

        self._trim_history()

        timing.print_report()

        if self._pending_barge_capture is None:
            self.set_state(
                ConversationState.ACTIVE_WAIT
            )

        return VoiceTurnResult(
            transcript=transcript,
            response=response,
            timing=timing,
            state=state,
        )

