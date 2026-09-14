"""
Alexa Lite - Full Voice Pipeline Test
-------------------------------------

Pipeline:

Microphone
    ↓
Parakeet STT
    ↓
Qwen3 1.7B streaming
    ↓
Complete-sentence detector
    ↓
Chatterbox Turbo HTTP service
    ↓
24 kHz PCM
    ↓
Speaker

IMPORTANT:
- Chatterbox server must already be running.
- We do NOT use tiny character chunks.
- TTS works sentence-by-sentence for natural prosody.
- TTS generation and audio playback run on background threads.
"""

import queue
import threading
import time

import sounddevice as sd

from app.audio.capture import record_until_enter
from app.audio.stt import ParakeetSTT
from app.audio.chatterbox_client import ChatterboxClient

from app.llm_client import (
    chat_stream,
    warmup,
)

from app.config import (
    LLM_MODEL,
    SYSTEM_RESPONSE_HINT,
)


# ============================================================
# SETTINGS
# ============================================================

SYSTEM_PROMPT = f"""
You are Alexa Lite, a conversational voice assistant.

{SYSTEM_RESPONSE_HINT}

Speak naturally.

For normal questions:
- Prefer one or two short sentences.
- Be direct.
- Do not expose hidden reasoning.
- Do not say that you are checking something unless you actually are.
""".strip()


# ============================================================
# SENTENCE BUFFER
# ============================================================

class SentenceBuffer:
    """
    Converts streamed LLM text into complete natural sentences.

    Unlike the old chunker, this does NOT split at arbitrary
    character counts.

    Example:

        "Hello! How can I help you today?"

    becomes:

        "Hello!"
        "How can I help you today?"

    Each complete sentence is sent to Chatterbox.
    """

    ENDINGS = ".!?"

    def __init__(self):
        self.buffer = ""

    def feed(self, text: str) -> list[str]:

        if not text:
            return []

        self.buffer += text

        sentences = []

        while True:

            position = self._find_sentence_end()

            if position is None:
                break

            sentence = self.buffer[:position].strip()

            self.buffer = (
                self.buffer[position:]
                .lstrip()
            )

            if sentence:
                sentences.append(sentence)

        return sentences

    def _find_sentence_end(self):

        for index, character in enumerate(self.buffer):

            if character not in self.ENDINGS:
                continue

            # Include the punctuation itself.
            return index + 1

        return None

    def flush(self):

        remaining = self.buffer.strip()

        self.buffer = ""

        return remaining if remaining else None


# ============================================================
# SHARED TIMINGS
# ============================================================

class PipelineTiming:

    def __init__(self):

        self.speech_end = None

        self.stt_start = None
        self.stt_end = None

        self.llm_start = None
        self.llm_first_text = None
        self.llm_end = None

        self.first_tts_text = None

        self.tts_first_start = None
        self.tts_first_complete = None

        self.first_audio = None

        self.playback_end = None

        self.lock = threading.Lock()


# ============================================================
# TTS WORKER
# ============================================================

def tts_worker(
    client: ChatterboxClient,
    text_queue: queue.Queue,
    audio_queue: queue.Queue,
    timing: PipelineTiming,
):

    first_request = True

    while True:

        text = text_queue.get()

        if text is None:

            text_queue.task_done()
            break


        print()
        print(
            f"[TTS TEXT] {text}"
        )


        start = time.perf_counter()


        if first_request:

            with timing.lock:

                timing.tts_first_start = start


        try:

            result = client.synthesize(
                text
            )

        except Exception as exc:

            print()
            print(
                f"[TTS ERROR] {exc}"
            )

            text_queue.task_done()

            continue


        end = time.perf_counter()


        if first_request:

            with timing.lock:

                timing.tts_first_complete = end

            first_request = False


        audio_queue.put(
            result
        )


        text_queue.task_done()


    # Tell playback there will be no more audio.
    audio_queue.put(
        None
    )


# ============================================================
# PLAYBACK WORKER
# ============================================================

def playback_worker(
    audio_queue: queue.Queue,
    timing: PipelineTiming,
):

    stream = None

    current_sample_rate = None
    current_channels = None


    try:

        while True:

            result = audio_queue.get()


            if result is None:

                audio_queue.task_done()
                break


            # ------------------------------------------------
            # OPEN / REOPEN STREAM WHEN NEEDED
            # ------------------------------------------------

            if (
                stream is None
                or current_sample_rate != result.sample_rate
                or current_channels != result.channels
            ):

                if stream is not None:

                    try:
                        stream.stop()
                    except Exception:
                        pass

                    stream.close()


                print(
                    f"[AUDIO] Opening output "
                    f"{result.sample_rate}Hz "
                    f"{result.channels}ch"
                )


                stream = sd.RawOutputStream(
                    samplerate=result.sample_rate,
                    channels=result.channels,
                    dtype="int16",
                )


                stream.start()


                current_sample_rate = (
                    result.sample_rate
                )

                current_channels = (
                    result.channels
                )


            # ------------------------------------------------
            # FIRST AUDIO TIMESTAMP
            # ------------------------------------------------

            with timing.lock:

                if timing.first_audio is None:

                    timing.first_audio = (
                        time.perf_counter()
                    )


            # ------------------------------------------------
            # PLAY
            # ------------------------------------------------

            stream.write(
                result.pcm
            )


            audio_queue.task_done()


    finally:

        if stream is not None:

            try:

                stream.stop()

            except Exception:

                pass


            stream.close()


        with timing.lock:

            timing.playback_end = (
                time.perf_counter()
            )


# ============================================================
# LATENCY DISPLAY
# ============================================================

def ms_between(
    end,
    start,
):

    if end is None or start is None:
        return None

    return (
        end - start
    ) * 1000.0


def print_latency(
    timing: PipelineTiming,
):

    print()
    print()
    print("=" * 70)
    print("LATENCY")
    print("=" * 70)


    stt_ms = ms_between(
        timing.stt_end,
        timing.stt_start,
    )


    llm_first_ms = ms_between(
        timing.llm_first_text,
        timing.llm_start,
    )


    llm_total_ms = ms_between(
        timing.llm_end,
        timing.llm_start,
    )


    first_tts_text_ms = ms_between(
        timing.first_tts_text,
        timing.speech_end,
    )


    tts_generation_ms = ms_between(
        timing.tts_first_complete,
        timing.tts_first_start,
    )


    first_audio_ms = ms_between(
        timing.first_audio,
        timing.speech_end,
    )


    playback_end_ms = ms_between(
        timing.playback_end,
        timing.speech_end,
    )


    if stt_ms is not None:

        print(
            f"STT               : "
            f"{stt_ms:.1f} ms"
        )


    if llm_first_ms is not None:

        print(
            f"LLM first text    : "
            f"{llm_first_ms:.1f} ms"
        )


    if llm_total_ms is not None:

        print(
            f"LLM complete      : "
            f"{llm_total_ms:.1f} ms"
        )


    if first_tts_text_ms is not None:

        print(
            f"First sentence    : "
            f"{first_tts_text_ms:.1f} ms "
            f"after speech end"
        )


    if tts_generation_ms is not None:

        print(
            f"First TTS generate: "
            f"{tts_generation_ms:.1f} ms"
        )


    if first_audio_ms is not None:

        print(
            f"FIRST AUDIO       : "
            f"{first_audio_ms:.1f} ms "
            f"after speech end"
        )


    if playback_end_ms is not None:

        print(
            f"Full playback end : "
            f"{playback_end_ms:.1f} ms"
        )


    print("=" * 70)


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("ALEXA LITE - CHATTERBOX FULL VOICE TEST")
    print("=" * 70)


    # ========================================================
    # CHECK CHATTERBOX
    # ========================================================

    print()
    print(
        "[TTS] Checking Chatterbox service..."
    )


    chatterbox = ChatterboxClient()


    try:

        health = chatterbox.health()

    except Exception as exc:

        print()
        print(
            "[ERROR] Chatterbox service is not running."
        )

        print(
            f"[ERROR] {exc}"
        )

        print()
        print(
            "Start this first in .venv_chatterbox:"
        )

        print(
            "python -m services.chatterbox_server"
        )

        return


    print(
        f"[TTS] status={health.get('status')} "
        f"device={health.get('device')} "
        f"rate={health.get('sample_rate')}Hz"
    )


    # ========================================================
    # LOAD STT
    # ========================================================

    print()
    print(
        "[STT] Initializing..."
    )


    stt = ParakeetSTT()


    # ========================================================
    # WARM LLM
    # ========================================================

    print()
    warmup(
        LLM_MODEL
    )


    print()
    print("=" * 70)
    print("READY")
    print("=" * 70)


    # ========================================================
    # RECORD
    # ========================================================

    print()
    print("=" * 70)
    print("RECORDING")
    print("=" * 70)

    print(
        "Speak now."
    )

    print(
        "Press ENTER when finished."
    )

    print("=" * 70)


    audio = record_until_enter()


    timing = PipelineTiming()


    timing.speech_end = (
        time.perf_counter()
    )


    if audio is None or len(audio) == 0:

        print(
            "[MIC] No audio captured."
        )

        return


    # ========================================================
    # STT
    # ========================================================

    print()
    print(
        "[PIPELINE] Transcribing..."
    )


    timing.stt_start = (
        time.perf_counter()
    )


    transcript = stt.transcribe(
        audio
    )


    timing.stt_end = (
        time.perf_counter()
    )


    if not transcript:

        print(
            "[STT] No speech recognized."
        )

        return


    print()
    print(
        f"You: {transcript}"
    )


    # ========================================================
    # QUEUES
    # ========================================================

    text_queue = queue.Queue()

    audio_queue = queue.Queue()


    # ========================================================
    # BACKGROUND WORKERS
    # ========================================================

    tts_thread = threading.Thread(
        target=tts_worker,
        args=(
            chatterbox,
            text_queue,
            audio_queue,
            timing,
        ),
        daemon=True,
    )


    playback_thread = threading.Thread(
        target=playback_worker,
        args=(
            audio_queue,
            timing,
        ),
        daemon=True,
    )


    tts_thread.start()

    playback_thread.start()


    # ========================================================
    # LLM
    # ========================================================

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": transcript,
        },
    ]


    sentence_buffer = (
        SentenceBuffer()
    )


    print()
    print(
        "Alexa: ",
        end="",
        flush=True,
    )


    timing.llm_start = (
        time.perf_counter()
    )


    first_llm_text = True

    first_sentence_sent = False


    for token in chat_stream(
        messages=messages,
        model_name=LLM_MODEL,
    ):

        if first_llm_text:

            timing.llm_first_text = (
                time.perf_counter()
            )

            first_llm_text = False


        print(
            token,
            end="",
            flush=True,
        )


        sentences = (
            sentence_buffer.feed(
                token
            )
        )


        for sentence in sentences:

            if not first_sentence_sent:

                timing.first_tts_text = (
                    time.perf_counter()
                )

                first_sentence_sent = True


            text_queue.put(
                sentence
            )


    timing.llm_end = (
        time.perf_counter()
    )


    # ========================================================
    # FLUSH FINAL NON-PUNCTUATED TEXT
    # ========================================================

    remaining = (
        sentence_buffer.flush()
    )


    if remaining:

        if not first_sentence_sent:

            timing.first_tts_text = (
                time.perf_counter()
            )

            first_sentence_sent = True


        text_queue.put(
            remaining
        )


    print()


    # ========================================================
    # STOP TTS QUEUE
    # ========================================================

    text_queue.put(
        None
    )


    # ========================================================
    # WAIT FOR EVERYTHING
    # ========================================================

    tts_thread.join()

    playback_thread.join()


    # ========================================================
    # RESULTS
    # ========================================================

    print_latency(
        timing
    )


    print()
    print(
        "[PIPELINE] Complete."
    )


if __name__ == "__main__":
    main()