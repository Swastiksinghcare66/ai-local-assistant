import asyncio
import threading
import time

from app.llm_client import (
    chat_stream,
    warmup,
)

from app.prompt_builder import PromptBuilder

from app.audio.cosyvoice_client import (
    CosyVoicePersistentClient,
)


# ============================================================
# SARA ADAPTIVE VOICE STYLE MAP
# ============================================================

VOICE_STYLE_MAP = {

    # Normal conversation
    "default":
        "warm_conversational",

    "casual":
        "warm_conversational",

    # Emotional / affectionate
    "emotional_support":
        "soft_companion",

    # Happy / excited
    "positive":
        "energetic_friendly",

    # Technical
    "technical":
        "calm_confident",

    "frustrated_technical":
        "calm_confident",

    "debugging":
        "calm_confident",

    # Learning
    "teaching":
        "warm_conversational",

    # Recommendations / decisions
    "decision":
        "calm_confident",

    # Requested response lengths
    "concise":
        "warm_conversational",

    "detailed":
        "calm_confident",

    # Serious conversation
    "serious":
        "serious",
}


DEFAULT_VOICE_STYLE = (
    "warm_conversational"
)


def get_voice_style(mode):
    """Legacy mode-to-style helper kept for compatibility."""

    return VOICE_STYLE_MAP.get(
        mode,
        DEFAULT_VOICE_STYLE,
    )


def is_speakable_phrase(text):
    """Reject empty, punctuation-only, or emoji-only TTS requests."""

    text = str(text or "").strip()

    return bool(
        text
        and
        any(
            ch.isalnum()
            for ch in text
        )
    )


# ============================================================
# COSYVOICE SETTINGS
# ============================================================

FLOW_STEPS = 5


# ============================================================
# SEMANTIC PHRASE BUFFER SETTINGS
# ============================================================

NORMAL_MIN_CHARS = 12

# Normal commas do NOT trigger TTS.
SOFT_SPLIT_CHARS = 150

# Emergency word-boundary split.
HARD_SPLIT_CHARS = 200


# ============================================================
# SEMANTIC PHRASE BUFFER
# ============================================================

class SemanticPhraseBuffer:
    """
    Convert Qwen streaming chunks into natural TTS phrases.

    Priority:

        1. Complete sentence:
               . ! ?

        2. Long sentence:
               , ; :

        3. Emergency word-boundary split.

    This prevents unnatural character-based cuts and keeps
    normal commas inside the same spoken phrase.
    """

    def __init__(self):

        self.buffer = ""


    # --------------------------------------------------------
    # CLEAN TEXT
    # --------------------------------------------------------

    @staticmethod
    def _clean(text):

        return " ".join(
            text.strip().split()
        )


    # --------------------------------------------------------
    # COMPLETE SENTENCE
    # --------------------------------------------------------

    def _find_sentence_boundary(self):

        for index, char in enumerate(
            self.buffer
        ):

            if char not in ".!?":
                continue


            candidate = self._clean(
                self.buffer[
                    :index + 1
                ]
            )


            if (
                len(candidate)
                >= NORMAL_MIN_CHARS
            ):

                return index + 1


        return None


    # --------------------------------------------------------
    # LONG-SENTENCE SOFT SPLIT
    # --------------------------------------------------------

    def _find_soft_boundary(self):

        if (
            len(self.buffer)
            < SOFT_SPLIT_CHARS
        ):

            return None


        search_region = (
            self.buffer[
                :SOFT_SPLIT_CHARS
            ]
        )


        best_position = -1


        for delimiter in (
            ",",
            ";",
            ":",
        ):

            position = (
                search_region.rfind(
                    delimiter
                )
            )


            if (
                position
                > best_position
            ):

                best_position = (
                    position
                )


        if (
            best_position
            >= NORMAL_MIN_CHARS
        ):

            return (
                best_position + 1
            )


        return None


    # --------------------------------------------------------
    # EMERGENCY HARD SPLIT
    # --------------------------------------------------------

    def _find_hard_boundary(self):

        if (
            len(self.buffer)
            < HARD_SPLIT_CHARS
        ):

            return None


        search_region = (
            self.buffer[
                :HARD_SPLIT_CHARS
            ]
        )


        position = (
            search_region.rfind(
                " "
            )
        )


        if (
            position
            >= NORMAL_MIN_CHARS
        ):

            return position


        return HARD_SPLIT_CHARS


    # --------------------------------------------------------
    # FEED STREAM
    # --------------------------------------------------------

    def feed(
        self,
        text,
    ):

        if not text:

            return []


        self.buffer += text


        phrases = []


        while True:

            # Priority 1:
            # proper sentence boundary

            boundary = (
                self._find_sentence_boundary()
            )


            # Priority 2:
            # long sentence punctuation

            if boundary is None:

                boundary = (
                    self._find_soft_boundary()
                )


            # Priority 3:
            # emergency maximum size

            if boundary is None:

                boundary = (
                    self._find_hard_boundary()
                )


            if boundary is None:

                break


            phrase = (
                self._clean(
                    self.buffer[
                        :boundary
                    ]
                )
            )


            self.buffer = (
                self.buffer[
                    boundary:
                ]
            )


            if phrase:

                phrases.append(
                    phrase
                )


        return phrases


    # --------------------------------------------------------
    # FINAL REMAINDER
    # --------------------------------------------------------

    def flush(self):

        phrase = (
            self._clean(
                self.buffer
            )
        )


        self.buffer = ""


        if not phrase:

            return []


        return [phrase]


# ============================================================
# QWEN PRODUCER
# ============================================================

def run_llm_producer(
    messages,
    loop,
    phrase_queue,
    timing,
):
    """
    Run Qwen in a background thread.

    Completed natural phrases are sent to the asynchronous
    CosyVoice consumer while Qwen continues generating.
    """

    phrase_buffer = (
        SemanticPhraseBuffer()
    )


    response_parts = []


    try:

        for chunk in chat_stream(
            messages=messages
        ):

            now = (
                time.perf_counter()
            )


            # =================================================
            # FIRST QWEN TOKEN
            # =================================================

            if (
                timing[
                    "llm_first_token"
                ]
                is None
            ):

                timing[
                    "llm_first_token"
                ] = now


            # =================================================
            # DISPLAY STREAM
            # =================================================

            print(
                chunk,
                end="",
                flush=True,
            )


            response_parts.append(
                chunk
            )


            # =================================================
            # PHRASE EXTRACTION
            # =================================================

            phrases = (
                phrase_buffer.feed(
                    chunk
                )
            )


            for phrase in phrases:

                if not is_speakable_phrase(phrase):
                    continue

                emitted_at = (
                    time.perf_counter()
                )


                if (
                    timing[
                        "first_phrase"
                    ]
                    is None
                ):

                    timing[
                        "first_phrase"
                    ] = emitted_at


                loop.call_soon_threadsafe(
                    phrase_queue.put_nowait,

                    {
                        "text":
                            phrase,

                        "emitted_at":
                            emitted_at,
                    },
                )


        # ====================================================
        # FLUSH REMAINDER
        # ====================================================

        for phrase in (
            phrase_buffer.flush()
        ):

            if not is_speakable_phrase(phrase):
                continue

            emitted_at = (
                time.perf_counter()
            )


            if (
                timing[
                    "first_phrase"
                ]
                is None
            ):

                timing[
                    "first_phrase"
                ] = emitted_at


            loop.call_soon_threadsafe(
                phrase_queue.put_nowait,

                {
                    "text":
                        phrase,

                    "emitted_at":
                        emitted_at,
                },
            )


    finally:

        timing[
            "llm_complete"
        ] = (
            time.perf_counter()
        )


        timing[
            "full_response"
        ] = (
            "".join(
                response_parts
            ).strip()
        )


        # Sentinel:
        # no more Qwen phrases

        loop.call_soon_threadsafe(
            phrase_queue.put_nowait,
            None,
        )


# ============================================================
# SINGLE CONVERSATION TURN
# ============================================================

async def run_turn(
    client,
    prompt_builder,
    user_text,
    history,
):

    turn_start = (
        time.perf_counter()
    )


    # ========================================================
    # RAW CONVERSATION
    # ========================================================

    raw_messages = [

        *history,

        {
            "role":
                "user",

            "content":
                user_text,
        },
    ]


    # ========================================================
    # ADAPTIVE CONVERSATION STATE
    # ========================================================

    state = (
        prompt_builder.get_state(
            raw_messages
        )
    )

    mode = state.mode
    voice_style = state.voice_style


    # ========================================================
    # BUILD FINAL QWEN PROMPT
    # ========================================================

    messages = (
        prompt_builder.build(
            raw_messages,
            state=state,
        )
    )


    print()
    print("=" * 72)
    print("SARA")
    print("=" * 72)

    print(
        f"[ADAPTIVE MODE] "
        f"{mode}"
    )

    print(
        f"[VOICE STYLE]   "
        f"{voice_style}"
    )

    print(
        f"[EMOTION]       "
        f"{state.primary_emotion}"
        f" / {state.secondary_emotion}"
        f" | confidence={state.confidence:.2f}"
    )

    print(
        f"[STRATEGY]      "
        f"{state.response_strategy}"
    )

    print(
        f"[HUMOR]         "
        f"{state.humor_level}/3"
        f" | laugh={state.laugh_allowed}"
        f" | shift={state.topic_shift}"
    )

    print()


    # ========================================================
    # QUEUE + TIMING
    # ========================================================

    phrase_queue = (
        asyncio.Queue()
    )


    timing = {

        "llm_first_token":
            None,

        "first_phrase":
            None,

        "llm_complete":
            None,

        "full_response":
            "",
    }


    loop = (
        asyncio.get_running_loop()
    )


    # ========================================================
    # START QWEN THREAD
    # ========================================================

    producer_thread = (
        threading.Thread(

            target=
                run_llm_producer,

            args=(
                messages,
                loop,
                phrase_queue,
                timing,
            ),

            daemon=True,
        )
    )


    producer_thread.start()


    # ========================================================
    # TTS STATE
    # ========================================================

    phrase_number = 0

    first_audio_absolute = None

    first_tts_ttfa_ms = None

    phrase_metrics = []


    # ========================================================
    # TTS CONSUMER
    # ========================================================

    while True:

        item = (
            await phrase_queue.get()
        )


        if item is None:

            break


        phrase = (
            item["text"]
        )


        emitted_at = (
            item[
                "emitted_at"
            ]
        )


        phrase_number += 1


        print()
        print()


        print(
            f"[TTS phrase "
            f"{phrase_number}] "
            f"[{voice_style}] "
            f"{phrase}"
        )


        # ====================================================
        # QUEUE WAIT
        # ====================================================

        tts_start = (
            time.perf_counter()
        )


        queue_wait_ms = (
            tts_start
            - emitted_at
        ) * 1000.0


        # ====================================================
        # COSYVOICE REQUEST
        # ====================================================

        result = (
            await client.speak(

                phrase,

                style=
                    voice_style,

                flow_steps=
                    FLOW_STEPS,
            )
        )


        server = (
            result.get(
                "server"
            )
            or {}
        )


        client_ttfa_ms = (
            result.get(
                "client_ttfa_ms"
            )
        )


        model_ttfa_ms = (
            server.get(
                "model_ttfa_ms"
            )
        )


        wire_ttfa_ms = (
            server.get(
                "wire_ttfa_ms"
            )
        )


        generation_time = (
            server.get(
                "generation_time"
            )
        )


        rtf = (
            server.get(
                "rtf"
            )
        )


        # ====================================================
        # FIRST AUDIBLE AUDIO
        # ====================================================

        if (
            first_audio_absolute
            is None

            and

            client_ttfa_ms
            is not None
        ):

            first_audio_absolute = (
                tts_start
                +
                (
                    client_ttfa_ms
                    / 1000.0
                )
            )


            first_tts_ttfa_ms = (
                client_ttfa_ms
            )


        # ====================================================
        # STORE METRICS
        # ====================================================

        phrase_metrics.append(
            {
                "phrase_number":
                    phrase_number,

                "text":
                    phrase,

                "style":
                    voice_style,

                "queue_wait_ms":
                    queue_wait_ms,

                "client_ttfa_ms":
                    client_ttfa_ms,

                "model_ttfa_ms":
                    model_ttfa_ms,

                "wire_ttfa_ms":
                    wire_ttfa_ms,

                "generation_time":
                    generation_time,

                "rtf":
                    rtf,
            }
        )


        # ====================================================
        # DISPLAY METRICS
        # ====================================================

        ttfa_display = (
            f"{client_ttfa_ms:.1f}"

            if client_ttfa_ms
            is not None

            else "N/A"
        )


        server_display = (
            f"{model_ttfa_ms}"

            if model_ttfa_ms
            is not None

            else "N/A"
        )


        rtf_display = (
            f"{rtf:.3f}"

            if isinstance(
                rtf,
                (int, float),
            )

            else "N/A"
        )


        print(
            f"[TTS] "
            f"style="
            f"{voice_style} | "
            f"queue wait="
            f"{queue_wait_ms:.1f} ms | "
            f"TTFA="
            f"{ttfa_display} ms | "
            f"server="
            f"{server_display} ms | "
            f"RTF="
            f"{rtf_display}"
        )


        if (
            isinstance(
                rtf,
                (int, float),
            )

            and

            rtf >= 1.0
        ):

            print(
                "[TTS WARNING] "
                "RTF >= 1.0 - "
                "playback starvation "
                "may occur."
            )


    # ========================================================
    # WAIT FOR QWEN THREAD
    # ========================================================

    await asyncio.to_thread(
        producer_thread.join
    )


    pipeline_end = (
        time.perf_counter()
    )


    # ========================================================
    # CALCULATE TIMINGS
    # ========================================================

    llm_ttft_ms = None


    if (
        timing[
            "llm_first_token"
        ]
        is not None
    ):

        llm_ttft_ms = (
            timing[
                "llm_first_token"
            ]
            - turn_start
        ) * 1000.0


    first_phrase_ms = None


    if (
        timing[
            "first_phrase"
        ]
        is not None
    ):

        first_phrase_ms = (
            timing[
                "first_phrase"
            ]
            - turn_start
        ) * 1000.0


    llm_total_ms = None


    if (
        timing[
            "llm_complete"
        ]
        is not None
    ):

        llm_total_ms = (
            timing[
                "llm_complete"
            ]
            - turn_start
        ) * 1000.0


    audible_ttfa_ms = None


    if (
        first_audio_absolute
        is not None
    ):

        audible_ttfa_ms = (
            first_audio_absolute
            - turn_start
        ) * 1000.0


    pipeline_processing_ms = (
        pipeline_end
        - turn_start
    ) * 1000.0


    # ========================================================
    # RTF SUMMARY
    # ========================================================

    valid_rtfs = [

        item["rtf"]

        for item in phrase_metrics

        if isinstance(
            item["rtf"],
            (int, float),
        )
    ]


    average_rtf = None

    maximum_rtf = None


    if valid_rtfs:

        average_rtf = (
            sum(valid_rtfs)
            / len(valid_rtfs)
        )


        maximum_rtf = (
            max(valid_rtfs)
        )


    # ========================================================
    # PIPELINE REPORT
    # ========================================================

    print()
    print()
    print("=" * 72)
    print("PIPELINE TIMING")
    print("=" * 72)


    print(
        f"Adaptive mode          : "
        f"{mode}"
    )


    print(
        f"Voice style            : "
        f"{voice_style}"
    )


    print(
        f"Flow steps             : "
        f"{FLOW_STEPS}"
    )


    if llm_ttft_ms is not None:

        print(
            f"Qwen first token       : "
            f"{llm_ttft_ms:.1f} ms"
        )


    if first_phrase_ms is not None:

        print(
            f"First phrase ready     : "
            f"{first_phrase_ms:.1f} ms"
        )


    if first_tts_ttfa_ms is not None:

        print(
            f"CosyVoice first TTFA   : "
            f"{first_tts_ttfa_ms:.1f} ms"
        )


    if audible_ttfa_ms is not None:

        print(
            f"END-TO-END AUDIBLE TTFA: "
            f"{audible_ttfa_ms:.1f} ms"
        )


    if llm_total_ms is not None:

        print(
            f"Qwen complete          : "
            f"{llm_total_ms:.1f} ms"
        )


    print(
        f"TTS phrases            : "
        f"{phrase_number}"
    )


    if average_rtf is not None:

        print(
            f"Average TTS RTF        : "
            f"{average_rtf:.3f}"
        )


    if maximum_rtf is not None:

        print(
            f"Maximum TTS RTF        : "
            f"{maximum_rtf:.3f}"
        )


    print(
        f"Pipeline processing    : "
        f"{pipeline_processing_ms:.1f} ms"
    )


    print("=" * 72)


    # ========================================================
    # PER-PHRASE REPORT
    # ========================================================

    if phrase_metrics:

        print()
        print("=" * 72)
        print("TTS PHRASE REPORT")
        print("=" * 72)


        for item in phrase_metrics:

            print()


            print(
                f"Phrase "
                f"{item['phrase_number']}:"
            )


            print(
                f"  Style      : "
                f"{item['style']}"
            )


            print(
                f"  Text       : "
                f"{item['text']}"
            )


            print(
                f"  Queue wait : "
                f"{item['queue_wait_ms']:.1f} ms"
            )


            if (
                item[
                    "client_ttfa_ms"
                ]
                is not None
            ):

                print(
                    f"  TTFA       : "
                    f"{item['client_ttfa_ms']:.1f} ms"
                )


            print(
                f"  RTF        : "
                f"{item['rtf']}"
            )


        print()
        print("=" * 72)


    # ========================================================
    # WAIT FOR AUDIO PLAYBACK
    # ========================================================

    print()
    print(
        "[AUDIO] Waiting for playback..."
    )


    await asyncio.to_thread(
        client.wait_for_playback
    )


    # ========================================================
    # UPDATE CONVERSATION HISTORY
    # ========================================================

    response = (
        timing[
            "full_response"
        ]
    )


    history.append(
        {
            "role":
                "user",

            "content":
                user_text,
        }
    )


    history.append(
        {
            "role":
                "assistant",

            "content":
                response,
        }
    )


    # Keep test context manageable.
    if len(history) > 8:

        del history[
            :-8
        ]


    return response


# ============================================================
# MAIN
# ============================================================

async def main():

    print()
    print("=" * 72)
    print(
        "SARA FULL ADAPTIVE "
        "QWEN -> COSYVOICE TEST"
    )
    print("=" * 72)


    print()
    print(
        "Adaptive PromptBuilder : ON"
    )

    print(
        "Adaptive Voice Style   : ON"
    )

    print(
        "Sentence-aware TTS     : ON"
    )

    print(
        "Persistent CosyVoice   : ON"
    )

    print(
        f"Flow steps             : "
        f"{FLOW_STEPS}"
    )


    # ========================================================
    # DISPLAY STYLE MAP
    # ========================================================

    print()
    print(
        "Nominal voice mappings "
        "(conversation state may override):"
    )


    for mode, style in (
        VOICE_STYLE_MAP.items()
    ):

        print(
            f"  "
            f"{mode:<22}"
            f" -> "
            f"{style}"
        )


    # ========================================================
    # PROMPT BUILDER
    # ========================================================

    prompt_builder = (
        PromptBuilder()
    )


    # ========================================================
    # WARM QWEN
    # ========================================================

    print()
    print(
        "[STARTUP] Warming Qwen..."
    )


    qwen_ready = (
        await asyncio.to_thread(
            warmup
        )
    )


    if not qwen_ready:

        print(
            "[ERROR] "
            "Qwen warm-up failed."
        )

        return


    # ========================================================
    # COSYVOICE CLIENT
    # ========================================================

    client = (
        CosyVoicePersistentClient(

            playback=True,

            default_style=
                DEFAULT_VOICE_STYLE,

            default_flow_steps=
                FLOW_STEPS,
        )
    )


    try:

        # ====================================================
        # CONNECT
        # ====================================================

        print()
        print(
            "[STARTUP] "
            "Connecting CosyVoice..."
        )


        await client.connect()


        ping = (
            await client.ping()
        )


        print(
            f"[STARTUP] "
            f"CosyVoice "
            f"{ping['server']} | "
            f"ping="
            f"{ping['latency_ms']:.1f} ms"
        )


        # ====================================================
        # READY
        # ====================================================

        print()
        print("=" * 72)
        print("SARA READY")
        print("=" * 72)


        print(
            "Type a message."
        )


        print(
            "Command: /quit"
        )


        history = []


        # ====================================================
        # CHAT LOOP
        # ====================================================

        while True:

            print()


            user_text = (
                await asyncio.to_thread(
                    input,
                    "You: ",
                )
            )


            user_text = (
                user_text.strip()
            )


            if not user_text:

                continue


            if (
                user_text.lower()
                in {
                    "/quit",
                    "quit",
                    "exit",
                }
            ):

                break


            await run_turn(

                client=
                    client,

                prompt_builder=
                    prompt_builder,

                user_text=
                    user_text,

                history=
                    history,
            )


    finally:

        print()
        print(
            "[SARA] Closing..."
        )


        await client.close()


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print()
        print(
            "[SARA] Stopped."
        )
