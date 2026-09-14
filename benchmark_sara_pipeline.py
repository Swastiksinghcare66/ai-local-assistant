import asyncio
import csv
import json
import statistics
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from app.llm_client import (
    chat_stream,
    warmup,
)

from app.audio.cosyvoice_client import (
    CosyVoicePersistentClient,
)


# ============================================================
# BENCHMARK CONFIGURATION
# ============================================================

BENCHMARK_NAME = "Sara Hybrid Qwen + CosyVoice Benchmark"

RESULT_DIR = Path("benchmark_results")

RESULT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# Delay after playback before next prompt.
# Keeps tests sequential while still representing
# a normal conversation.

BETWEEN_PROMPT_DELAY = 1.0


# ============================================================
# TEST PROMPTS
# ============================================================

PROMPTS = [

    # --------------------------------------------------------
    # 1. VERY SHORT CONVERSATIONAL RESPONSE
    # --------------------------------------------------------

    {
        "id": "P01",
        "category": "very_short",
        "prompt": "Hi. Reply naturally in one short sentence.",
    },


    # --------------------------------------------------------
    # 2. SHORT FACTUAL RESPONSE
    # --------------------------------------------------------

    {
        "id": "P02",
        "category": "short_factual",
        "prompt": (
            "What is an ESP32? "
            "Answer in one short sentence."
        ),
    },


    # --------------------------------------------------------
    # 3. THREE-SENTENCE RESPONSE
    # --------------------------------------------------------

    {
        "id": "P03",
        "category": "medium_explanation",
        "prompt": (
            "Explain artificial intelligence "
            "in exactly three short sentences."
        ),
    },


    # --------------------------------------------------------
    # 4. COMPARISON
    # --------------------------------------------------------

    {
        "id": "P04",
        "category": "comparison",
        "prompt": (
            "Compare Wi-Fi and Bluetooth "
            "in two concise sentences."
        ),
    },


    # --------------------------------------------------------
    # 5. MULTI-SENTENCE TECHNICAL RESPONSE
    # --------------------------------------------------------

    {
        "id": "P05",
        "category": "technical",
        "prompt": (
            "Explain edge AI, including one advantage "
            "and one limitation, in three short sentences."
        ),
    },


    # --------------------------------------------------------
    # 6. NATURAL CONVERSATION
    # --------------------------------------------------------

    {
        "id": "P06",
        "category": "conversation",
        "prompt": (
            "I had a long day today. "
            "Respond naturally and briefly."
        ),
    },


    # --------------------------------------------------------
    # 7. COMMA / CONTINUITY TEST
    # --------------------------------------------------------

    {
        "id": "P07",
        "category": "comma_continuity",
        "prompt": (
            "Explain the Internet of Things in one natural "
            "sentence containing several commas, but keep "
            "the sentence concise."
        ),
    },


    # --------------------------------------------------------
    # 8. LONGER RESPONSE
    # --------------------------------------------------------

    {
        "id": "P08",
        "category": "longer_response",
        "prompt": (
            "Explain how a voice assistant works from "
            "speech input to spoken output in exactly "
            "five short sentences."
        ),
    },
]


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are Sara, a fast natural conversational voice assistant.

Speak naturally as if talking directly to the user.

Rules:
- Be concise unless more detail is requested.
- Prefer short complete sentences.
- Do not use markdown.
- Do not use headings.
- Do not use bullet points.
- Avoid unnecessary filler.
- Do not describe hidden reasoning.
""".strip()


# ============================================================
# PHRASE BUFFER
# ============================================================

# These values intentionally match the current
# streaming experiment closely.

FIRST_MIN_CHARS = 24
FIRST_MAX_CHARS = 70

NEXT_MIN_CHARS = 35
NEXT_MAX_CHARS = 120


class SemanticPhraseBuffer:

    def __init__(self):

        self.buffer = ""

        self.first_phrase = True


    def _limits(self):

        if self.first_phrase:

            return (
                FIRST_MIN_CHARS,
                FIRST_MAX_CHARS,
            )

        return (
            NEXT_MIN_CHARS,
            NEXT_MAX_CHARS,
        )


    @staticmethod
    def _clean(text):

        return " ".join(
            text.strip().split()
        )


    def _find_sentence_boundary(
        self,
        min_chars,
    ):

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

            if len(candidate) >= min_chars:

                return index + 1

        return None


    def _find_forced_boundary(
        self,
        min_chars,
        max_chars,
    ):

        if len(self.buffer) < max_chars:

            return None


        search_region = (
            self.buffer[
                :max_chars
            ]
        )


        # Prefer punctuation when a response becomes long.

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

            if position + 1 >= min_chars:

                return position + 1


        # Otherwise split at a word boundary.

        position = (
            search_region.rfind(
                " "
            )
        )


        if position >= min_chars:

            return position


        return max_chars


    def feed(
        self,
        text,
    ):

        if not text:

            return []


        self.buffer += text

        phrases = []


        while True:

            min_chars, max_chars = (
                self._limits()
            )


            boundary = (
                self._find_sentence_boundary(
                    min_chars
                )
            )


            if boundary is None:

                boundary = (
                    self._find_forced_boundary(
                        min_chars,
                        max_chars,
                    )
                )


            if boundary is None:

                break


            phrase = self._clean(
                self.buffer[
                    :boundary
                ]
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

                self.first_phrase = False


        return phrases


    def flush(self):

        phrase = self._clean(
            self.buffer
        )

        self.buffer = ""


        if not phrase:

            return []


        self.first_phrase = False

        return [phrase]


# ============================================================
# SYSTEM SNAPSHOTS
# ============================================================

def run_command(command):

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
        )

        return result.stdout.strip()

    except Exception as exc:

        return f"ERROR: {exc}"


def get_ollama_snapshot():

    return run_command(
        [
            "ollama",
            "ps",
        ]
    )


def get_gpu_snapshot():

    output = run_command(
        [
            "nvidia-smi",

            "--query-gpu="
            "memory.used,"
            "memory.total,"
            "utilization.gpu,"
            "temperature.gpu,"
            "power.draw",

            "--format=csv,noheader,nounits",
        ]
    )


    if output.startswith("ERROR"):

        return {
            "raw": output
        }


    try:

        parts = [
            x.strip()
            for x in output.split(",")
        ]


        return {
            "memory_used_mb":
                float(parts[0]),

            "memory_total_mb":
                float(parts[1]),

            "gpu_util_percent":
                float(parts[2]),

            "temperature_c":
                float(parts[3]),

            "power_w":
                float(parts[4]),

            "raw":
                output,
        }

    except Exception:

        return {
            "raw":
                output,
        }


# ============================================================
# PERCENTILE
# ============================================================

def percentile(
    values,
    percent,
):

    values = sorted(
        value
        for value in values
        if value is not None
    )


    if not values:

        return None


    if len(values) == 1:

        return values[0]


    position = (
        (len(values) - 1)
        * percent
    )


    lower = int(position)

    upper = min(
        lower + 1,
        len(values) - 1,
    )


    fraction = (
        position
        - lower
    )


    return (
        values[lower]
        * (1 - fraction)
        +
        values[upper]
        * fraction
    )


# ============================================================
# LLM PRODUCER
# ============================================================

def llm_producer(
    messages,
    loop,
    phrase_queue,
    timing,
):

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


            if (
                timing["llm_first_token"]
                is None
            ):

                timing[
                    "llm_first_token"
                ] = now


            response_parts.append(
                chunk
            )


            phrases = (
                phrase_buffer.feed(
                    chunk
                )
            )


            for phrase in phrases:

                emitted_at = (
                    time.perf_counter()
                )


                if (
                    timing["first_phrase"]
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


        # Final unsent text.

        for phrase in (
            phrase_buffer.flush()
        ):

            emitted_at = (
                time.perf_counter()
            )


            if (
                timing["first_phrase"]
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
        ] = "".join(
            response_parts
        ).strip()


        loop.call_soon_threadsafe(
            phrase_queue.put_nowait,
            None,
        )


# ============================================================
# ONE BENCHMARK TURN
# ============================================================

async def benchmark_turn(
    client,
    prompt_entry,
):

    prompt_id = (
        prompt_entry["id"]
    )

    category = (
        prompt_entry["category"]
    )

    user_text = (
        prompt_entry["prompt"]
    )


    print()
    print()
    print("=" * 88)

    print(
        f"{prompt_id} | {category}"
    )

    print("=" * 88)

    print(
        f"PROMPT: {user_text}"
    )

    print("-" * 88)


    gpu_before = (
        get_gpu_snapshot()
    )


    turn_start = (
        time.perf_counter()
    )


    messages = [
        {
            "role":
                "system",

            "content":
                SYSTEM_PROMPT,
        },

        {
            "role":
                "user",

            "content":
                user_text,
        },
    ]


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


    producer = (
        threading.Thread(
            target=llm_producer,

            args=(
                messages,
                loop,
                phrase_queue,
                timing,
            ),

            daemon=True,
        )
    )


    producer.start()


    phrase_results = []

    phrase_number = 0

    first_audio_absolute = None


    # ========================================================
    # CONSUME PHRASES
    # ========================================================

    while True:

        item = (
            await phrase_queue.get()
        )


        if item is None:

            break


        phrase_number += 1

        phrase_text = (
            item["text"]
        )


        phrase_emitted_at = (
            item["emitted_at"]
        )


        tts_start = (
            time.perf_counter()
        )


        queue_wait_ms = (
            tts_start
            - phrase_emitted_at
        ) * 1000.0


        print()

        print(
            f"TTS Phrase {phrase_number}: "
            f"{phrase_text}"
        )


        result = (
            await client.speak(
                phrase_text
            )
        )


        server = (
            result.get("server")
            or {}
        )


        client_ttfa = (
            result.get(
                "client_ttfa_ms"
            )
        )


        model_ttfa = (
            server.get(
                "model_ttfa_ms"
            )
        )


        wire_ttfa = (
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


        audio_duration = (
            server.get(
                "audio_duration"
            )
        )


        packet_count = (
            result.get(
                "packets"
            )
        )


        if (
            first_audio_absolute
            is None
            and
            client_ttfa is not None
        ):

            first_audio_absolute = (
                tts_start
                +
                client_ttfa / 1000.0
            )


        phrase_record = {

            "phrase_number":
                phrase_number,

            "text":
                phrase_text,

            "characters":
                len(phrase_text),

            "queue_wait_ms":
                queue_wait_ms,

            "client_ttfa_ms":
                client_ttfa,

            "model_ttfa_ms":
                model_ttfa,

            "wire_ttfa_ms":
                wire_ttfa,

            "generation_time_s":
                generation_time,

            "audio_duration_s":
                audio_duration,

            "rtf":
                rtf,

            "packets":
                packet_count,

            "stutter_risk":
                (
                    rtf is not None
                    and
                    rtf >= 1.0
                ),
        }


        phrase_results.append(
            phrase_record
        )


        print(
            f"  Queue wait : "
            f"{queue_wait_ms:.1f} ms"
        )

        print(
            f"  Client TTFA: "
            f"{client_ttfa} ms"
        )

        print(
            f"  Model TTFA : "
            f"{model_ttfa} ms"
        )

        print(
            f"  Wire TTFA  : "
            f"{wire_ttfa} ms"
        )

        print(
            f"  RTF        : "
            f"{rtf}"
        )

        print(
            f"  Packets    : "
            f"{packet_count}"
        )


        if (
            rtf is not None
            and
            rtf >= 1.0
        ):

            print(
                "  WARNING    : "
                "RTF >= 1.0, "
                "mid-speech buffer starvation possible."
            )


    await asyncio.to_thread(
        producer.join
    )


    # ========================================================
    # TIMINGS
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


    end_to_end_ms = None

    if first_audio_absolute is not None:

        end_to_end_ms = (
            first_audio_absolute
            - turn_start
        ) * 1000.0


    pipeline_end = (
        time.perf_counter()
    )


    pipeline_processing_ms = (
        pipeline_end
        - turn_start
    ) * 1000.0


    # ========================================================
    # WAIT FOR SPEAKER
    # ========================================================

    await asyncio.to_thread(
        client.wait_for_playback
    )


    turn_complete = (
        time.perf_counter()
    )


    playback_complete_ms = (
        turn_complete
        - turn_start
    ) * 1000.0


    gpu_after = (
        get_gpu_snapshot()
    )


    # ========================================================
    # SUMMARY FOR TURN
    # ========================================================

    phrase_rtfs = [
        x["rtf"]
        for x in phrase_results
        if x["rtf"] is not None
    ]


    phrase_ttfas = [
        x["client_ttfa_ms"]
        for x in phrase_results
        if x["client_ttfa_ms"] is not None
    ]


    max_rtf = (
        max(phrase_rtfs)
        if phrase_rtfs
        else None
    )


    avg_rtf = (
        statistics.mean(
            phrase_rtfs
        )
        if phrase_rtfs
        else None
    )


    avg_tts_ttfa = (
        statistics.mean(
            phrase_ttfas
        )
        if phrase_ttfas
        else None
    )


    stutter_risk = (
        any(
            x["stutter_risk"]
            for x in phrase_results
        )
    )


    turn_result = {

        "id":
            prompt_id,

        "category":
            category,

        "prompt":
            user_text,

        "response":
            timing[
                "full_response"
            ],

        "llm_ttft_ms":
            llm_ttft_ms,

        "first_phrase_ready_ms":
            first_phrase_ms,

        "llm_total_ms":
            llm_total_ms,

        "end_to_end_audible_ttfa_ms":
            end_to_end_ms,

        "pipeline_processing_ms":
            pipeline_processing_ms,

        "playback_complete_ms":
            playback_complete_ms,

        "tts_phrase_count":
            phrase_number,

        "avg_tts_ttfa_ms":
            avg_tts_ttfa,

        "avg_rtf":
            avg_rtf,

        "max_rtf":
            max_rtf,

        "stutter_risk":
            stutter_risk,

        "gpu_before":
            gpu_before,

        "gpu_after":
            gpu_after,

        "phrases":
            phrase_results,
    }


    print()

    print("-" * 88)

    print("TURN SUMMARY")

    print("-" * 88)


    print(
        f"Qwen TTFT              : "
        f"{llm_ttft_ms:.1f} ms"
    )


    print(
        f"First phrase ready     : "
        f"{first_phrase_ms:.1f} ms"
    )


    print(
        f"Qwen total             : "
        f"{llm_total_ms:.1f} ms"
    )


    print(
        f"End-to-end audible     : "
        f"{end_to_end_ms:.1f} ms"
    )


    print(
        f"TTS phrases            : "
        f"{phrase_number}"
    )


    print(
        f"Average TTS TTFA       : "
        f"{avg_tts_ttfa:.1f} ms"
    )


    print(
        f"Average RTF            : "
        f"{avg_rtf:.3f}"
    )


    print(
        f"Maximum RTF            : "
        f"{max_rtf:.3f}"
    )


    print(
        f"Mid-speech stutter risk: "
        f"{'YES' if stutter_risk else 'NO'}"
    )


    print("=" * 88)


    return turn_result


# ============================================================
# NUMBER FORMATTERS
# ============================================================

def fmt(
    value,
    digits=1,
):

    if value is None:

        return "-"

    return f"{value:.{digits}f}"


# ============================================================
# SAVE JSON
# ============================================================

def save_json(
    path,
    data,
):

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False,
        )


# ============================================================
# SAVE CSV
# ============================================================

def save_csv(
    path,
    results,
):

    fieldnames = [

        "id",
        "category",
        "prompt",

        "llm_ttft_ms",
        "first_phrase_ready_ms",
        "llm_total_ms",

        "end_to_end_audible_ttfa_ms",

        "tts_phrase_count",

        "avg_tts_ttfa_ms",

        "avg_rtf",
        "max_rtf",

        "stutter_risk",

        "pipeline_processing_ms",
        "playback_complete_ms",
    ]


    with open(
        path,
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )


        writer.writeheader()


        for result in results:

            writer.writerow(
                {
                    key:
                        result.get(key)

                    for key
                    in fieldnames
                }
            )


# ============================================================
# FINAL REPORT
# ============================================================

def print_final_report(
    results,
    start_gpu,
    end_gpu,
    ollama_state,
):

    print()
    print()
    print("=" * 110)
    print("FINAL SARA BENCHMARK REPORT")
    print("=" * 110)

    print()

    print("OLLAMA STATE")
    print("-" * 110)

    print(
        ollama_state
    )

    print()

    print("GPU AT START")
    print("-" * 110)

    print(
        start_gpu
    )

    print()

    print("GPU AT END")
    print("-" * 110)

    print(
        end_gpu
    )

    print()
    print()


    # ========================================================
    # PER PROMPT TABLE
    # ========================================================

    header = (
        f"{'ID':<5}"
        f"{'TYPE':<21}"
        f"{'LLM TTFT':>11}"
        f"{'PHRASE':>11}"
        f"{'TTS TTFA':>12}"
        f"{'E2E':>11}"
        f"{'RTF AVG':>10}"
        f"{'RTF MAX':>10}"
        f"{'TTS #':>7}"
        f"{'STUTTER':>10}"
    )


    print(header)

    print("-" * len(header))


    for result in results:

        print(
            f"{result['id']:<5}"
            f"{result['category']:<21}"
            f"{fmt(result['llm_ttft_ms']):>11}"
            f"{fmt(result['first_phrase_ready_ms']):>11}"
            f"{fmt(result['avg_tts_ttfa_ms']):>12}"
            f"{fmt(result['end_to_end_audible_ttfa_ms']):>11}"
            f"{fmt(result['avg_rtf'], 3):>10}"
            f"{fmt(result['max_rtf'], 3):>10}"
            f"{result['tts_phrase_count']:>7}"
            f"{('YES' if result['stutter_risk'] else 'NO'):>10}"
        )


    print()


    # ========================================================
    # GLOBAL METRICS
    # ========================================================

    llm_ttft_values = [

        result[
            "llm_ttft_ms"
        ]

        for result in results

        if result[
            "llm_ttft_ms"
        ] is not None
    ]


    first_phrase_values = [

        result[
            "first_phrase_ready_ms"
        ]

        for result in results

        if result[
            "first_phrase_ready_ms"
        ] is not None
    ]


    e2e_values = [

        result[
            "end_to_end_audible_ttfa_ms"
        ]

        for result in results

        if result[
            "end_to_end_audible_ttfa_ms"
        ] is not None
    ]


    all_phrase_ttfa = []

    all_rtfs = []

    all_queue_wait = []


    for result in results:

        for phrase in result[
            "phrases"
        ]:

            if (
                phrase[
                    "client_ttfa_ms"
                ]
                is not None
            ):

                all_phrase_ttfa.append(
                    phrase[
                        "client_ttfa_ms"
                    ]
                )


            if (
                phrase["rtf"]
                is not None
            ):

                all_rtfs.append(
                    phrase["rtf"]
                )


            all_queue_wait.append(
                phrase[
                    "queue_wait_ms"
                ]
            )


    def avg(values):

        if not values:

            return None

        return statistics.mean(
            values
        )


    print("=" * 110)

    print("AGGREGATE METRICS")

    print("=" * 110)


    print(
        f"Prompts tested                 : "
        f"{len(results)}"
    )


    print(
        f"Total TTS phrases              : "
        f"{len(all_rtfs)}"
    )


    print()


    print(
        f"Average Qwen TTFT              : "
        f"{fmt(avg(llm_ttft_values))} ms"
    )


    print(
        f"P95 Qwen TTFT                  : "
        f"{fmt(percentile(llm_ttft_values, 0.95))} ms"
    )


    print(
        f"Average first phrase ready     : "
        f"{fmt(avg(first_phrase_values))} ms"
    )


    print(
        f"Average TTS TTFA               : "
        f"{fmt(avg(all_phrase_ttfa))} ms"
    )


    print(
        f"P95 TTS TTFA                   : "
        f"{fmt(percentile(all_phrase_ttfa, 0.95))} ms"
    )


    print(
        f"Best TTS TTFA                  : "
        f"{fmt(min(all_phrase_ttfa) if all_phrase_ttfa else None)} ms"
    )


    print(
        f"Worst TTS TTFA                 : "
        f"{fmt(max(all_phrase_ttfa) if all_phrase_ttfa else None)} ms"
    )


    print()


    print(
        f"Average end-to-end audible     : "
        f"{fmt(avg(e2e_values))} ms"
    )


    print(
        f"P95 end-to-end audible         : "
        f"{fmt(percentile(e2e_values, 0.95))} ms"
    )


    print()


    print(
        f"Average RTF                    : "
        f"{fmt(avg(all_rtfs), 3)}"
    )


    print(
        f"P95 RTF                        : "
        f"{fmt(percentile(all_rtfs, 0.95), 3)}"
    )


    print(
        f"Maximum RTF                    : "
        f"{fmt(max(all_rtfs) if all_rtfs else None, 3)}"
    )


    print()


    print(
        f"Average phrase queue wait      : "
        f"{fmt(avg(all_queue_wait))} ms"
    )


    print(
        f"Maximum phrase queue wait      : "
        f"{fmt(max(all_queue_wait) if all_queue_wait else None)} ms"
    )


    # ========================================================
    # HEALTH COUNTS
    # ========================================================

    unsafe_rtf = [
        x
        for x in all_rtfs
        if x >= 1.0
    ]


    healthy_rtf = [
        x
        for x in all_rtfs
        if x < 1.0
    ]


    excellent_rtf = [
        x
        for x in all_rtfs
        if x <= 0.7
    ]


    print()
    print("=" * 110)

    print("STREAMING HEALTH")

    print("=" * 110)


    print(
        f"RTF < 1.0 phrases              : "
        f"{len(healthy_rtf)} / "
        f"{len(all_rtfs)}"
    )


    print(
        f"RTF <= 0.7 phrases             : "
        f"{len(excellent_rtf)} / "
        f"{len(all_rtfs)}"
    )


    print(
        f"RTF >= 1.0 phrases             : "
        f"{len(unsafe_rtf)} / "
        f"{len(all_rtfs)}"
    )


    # ========================================================
    # DECISION
    # ========================================================

    average_rtf = (
        avg(all_rtfs)
    )


    p95_rtf = (
        percentile(
            all_rtfs,
            0.95,
        )
    )


    average_e2e = (
        avg(e2e_values)
    )


    print()
    print("=" * 110)

    print("AUTOMATIC ASSESSMENT")

    print("=" * 110)


    if (
        average_rtf is not None
        and
        p95_rtf is not None
    ):

        if (
            average_rtf <= 0.7
            and
            p95_rtf < 1.0
        ):

            print(
                "TTS STREAMING : EXCELLENT"
            )

            print(
                "All or nearly all speech is being "
                "generated comfortably faster than playback."
            )


        elif p95_rtf < 1.0:

            print(
                "TTS STREAMING : GOOD"
            )

            print(
                "Speech generation remains faster "
                "than playback without major starvation risk."
            )


        else:

            print(
                "TTS STREAMING : NOT YET STABLE"
            )

            print(
                "Some phrases have RTF >= 1.0, "
                "so mid-speech pauses remain possible."
            )


    if average_e2e is not None:

        if average_e2e <= 1500:

            print(
                "RESPONSIVENESS : EXCELLENT"
            )

        elif average_e2e <= 2000:

            print(
                "RESPONSIVENESS : GOOD"
            )

        elif average_e2e <= 3000:

            print(
                "RESPONSIVENESS : USABLE"
            )

        else:

            print(
                "RESPONSIVENESS : NEEDS OPTIMIZATION"
            )


    print("=" * 110)


# ============================================================
# MAIN
# ============================================================

async def main():

    benchmark_start_wall = (
        datetime.now()
    )


    timestamp = (
        benchmark_start_wall.strftime(
            "%Y%m%d_%H%M%S"
        )
    )


    json_path = (
        RESULT_DIR
        / f"sara_benchmark_{timestamp}.json"
    )


    csv_path = (
        RESULT_DIR
        / f"sara_benchmark_{timestamp}.csv"
    )


    print()
    print("=" * 88)

    print(BENCHMARK_NAME)

    print("=" * 88)


    print()

    print(
        f"Prompts to execute: "
        f"{len(PROMPTS)}"
    )


    for prompt in PROMPTS:

        print(
            f"{prompt['id']} | "
            f"{prompt['category']:<20} | "
            f"{prompt['prompt']}"
        )


    # ========================================================
    # INITIAL SYSTEM STATE
    # ========================================================

    print()
    print("=" * 88)

    print("INITIAL SYSTEM STATE")

    print("=" * 88)


    ollama_state = (
        get_ollama_snapshot()
    )


    print()
    print("OLLAMA")
    print(ollama_state)


    start_gpu = (
        get_gpu_snapshot()
    )


    print()
    print("GPU")
    print(start_gpu)


    # ========================================================
    # WARM QWEN
    # ========================================================

    print()
    print("=" * 88)

    print("WARMING QWEN")

    print("=" * 88)


    qwen_ready = (
        await asyncio.to_thread(
            warmup
        )
    )


    if not qwen_ready:

        print(
            "ERROR: Qwen warmup failed."
        )

        return


    # ========================================================
    # COSYVOICE CLIENT
    # ========================================================

    client = (
        CosyVoicePersistentClient(

            playback=True,

            default_style=
                "warm_conversational",

            default_flow_steps=
                5,
        )
    )


    results = []


    try:

        print()
        print("=" * 88)

        print("CONNECTING COSYVOICE")

        print("=" * 88)


        await client.connect()


        ping_result = (
            await client.ping()
        )


        print(
            f"Server : "
            f"{ping_result['server']}"
        )


        print(
            f"Ping   : "
            f"{ping_result['latency_ms']:.1f} ms"
        )


        # ====================================================
        # EXECUTE ALL PROMPTS
        # ====================================================

        print()
        print("=" * 88)

        print("STARTING AUTOMATIC BENCHMARK")

        print("=" * 88)


        for index, prompt in enumerate(
            PROMPTS,
            start=1,
        ):

            print(
                f"\nRunning "
                f"{index}/{len(PROMPTS)}..."
            )


            result = (
                await benchmark_turn(
                    client,
                    prompt,
                )
            )


            results.append(
                result
            )


            # Save partial data after every prompt so results
            # survive an accidental interruption.

            partial_data = {

                "benchmark":
                    BENCHMARK_NAME,

                "timestamp":
                    timestamp,

                "completed":
                    len(results),

                "total_prompts":
                    len(PROMPTS),

                "results":
                    results,
            }


            save_json(
                json_path,
                partial_data,
            )


            if (
                index
                < len(PROMPTS)
            ):

                print(
                    f"\nWaiting "
                    f"{BETWEEN_PROMPT_DELAY:.1f}s "
                    f"before next prompt..."
                )


                await asyncio.sleep(
                    BETWEEN_PROMPT_DELAY
                )


    finally:

        await client.close()


    # ========================================================
    # FINAL SYSTEM STATE
    # ========================================================

    end_gpu = (
        get_gpu_snapshot()
    )


    final_ollama_state = (
        get_ollama_snapshot()
    )


    # ========================================================
    # SAVE FINAL DATA
    # ========================================================

    benchmark_end_wall = (
        datetime.now()
    )


    final_data = {

        "benchmark":
            BENCHMARK_NAME,

        "started":
            benchmark_start_wall.isoformat(),

        "finished":
            benchmark_end_wall.isoformat(),

        "prompt_count":
            len(PROMPTS),

        "ollama_start":
            ollama_state,

        "ollama_end":
            final_ollama_state,

        "gpu_start":
            start_gpu,

        "gpu_end":
            end_gpu,

        "results":
            results,
    }


    save_json(
        json_path,
        final_data,
    )


    save_csv(
        csv_path,
        results,
    )


    # ========================================================
    # FINAL REPORT
    # ========================================================

    print_final_report(
        results=
            results,

        start_gpu=
            start_gpu,

        end_gpu=
            end_gpu,

        ollama_state=
            final_ollama_state,
    )


    print()
    print("=" * 110)

    print("RESULT FILES")

    print("=" * 110)


    print(
        f"JSON : "
        f"{json_path.resolve()}"
    )


    print(
        f"CSV  : "
        f"{csv_path.resolve()}"
    )


    print("=" * 110)


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
            "Benchmark interrupted by user."
        )