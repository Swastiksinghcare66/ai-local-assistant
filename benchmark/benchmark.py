import time
import csv
import statistics
from pathlib import Path

from app.llm_client import chat
from app.session import Session
from app.context_manager import ContextManager
from app.prompt_builder import PromptBuilder


# --------------------------------------------------
# Configuration
# --------------------------------------------------

PROMPT_FILE = Path(__file__).parent / "prompts.txt"

RESULTS_DIR = Path(__file__).parent / "results"

RESULTS_FILE = RESULTS_DIR / "benchmark_results.csv"

SUMMARY_FILE = RESULTS_DIR / "benchmark_summary.txt"


# --------------------------------------------------
# Load prompts
# --------------------------------------------------

def load_prompts():

    with open(PROMPT_FILE, "r", encoding="utf-8") as file:

        prompts = [
            line.strip()
            for line in file
            if line.strip()
        ]

    return prompts


# --------------------------------------------------
# Calculate percentile
# --------------------------------------------------

def percentile(values, percent):

    if not values:
        return 0

    values = sorted(values)

    index = (len(values) - 1) * percent

    lower = int(index)
    upper = min(lower + 1, len(values) - 1)

    weight = index - lower

    return (
        values[lower] * (1 - weight)
        + values[upper] * weight
    )


# --------------------------------------------------
# Model warm-up
# --------------------------------------------------

def warmup_model():

    print()
    print("=" * 60)
    print("Model Warm-Up")
    print("=" * 60)

    print("Initializing model...")

    start = time.perf_counter()

    try:

        # Forces Ollama/model initialization.
        # Response is intentionally discarded.
        chat("Respond only with READY.")

        cold_start_time = time.perf_counter() - start

        print(
            f"Model ready in "
            f"{cold_start_time:.3f} seconds"
        )

        return cold_start_time

    except Exception as e:

        print(f"Model warm-up failed: {e}")

        return None


# --------------------------------------------------
# Run benchmark
# --------------------------------------------------

def run_benchmark():

    prompts = load_prompts()

    if not prompts:
        print("No prompts found.")
        return

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------
    # Warm up model BEFORE benchmark
    # --------------------------------------------------

    cold_start_time = warmup_model()

    if cold_start_time is None:
        print("Benchmark aborted.")
        return

    # --------------------------------------------------
    # Initialize ConAI components
    # --------------------------------------------------

    session = Session()

    context_manager = ContextManager()

    prompt_builder = PromptBuilder()

    results = []

    print()
    print("=" * 60)
    print("ConAI Steady-State Benchmark")
    print("=" * 60)

    print(f"Prompts loaded: {len(prompts)}")
    print("Warm-up excluded from benchmark.")
    print()

    # --------------------------------------------------
    # Benchmark loop
    # --------------------------------------------------

    for index, user in enumerate(prompts, start=1):

        print(
            f"[{index}/{len(prompts)}] "
            f"{user}"
        )

        try:

            # ------------------------------------------
            # Entire pipeline timer
            # ------------------------------------------

            total_start = time.perf_counter()

            # ------------------------------------------
            # Add user message
            # ------------------------------------------

            session.conversation.add_user(user)

            # ------------------------------------------
            # Context generation
            # ------------------------------------------

            context_start = time.perf_counter()

            context = context_manager.get_context(
                session.conversation.get_messages()
            )

            context_time = (
                time.perf_counter()
                - context_start
            )

            # ------------------------------------------
            # Prompt construction
            # ------------------------------------------

            prompt_start = time.perf_counter()

            prompt = prompt_builder.build(context)

            prompt_time = (
                time.perf_counter()
                - prompt_start
            )

            # ------------------------------------------
            # LLM inference
            # ------------------------------------------

            llm_start = time.perf_counter()

            answer, inference_time = chat(prompt)

            llm_time = (
                time.perf_counter()
                - llm_start
            )

            # ------------------------------------------
            # Save assistant response
            # ------------------------------------------

            session.conversation.add_assistant(answer)

            # ------------------------------------------
            # Total end-to-end time
            # ------------------------------------------

            total_time = (
                time.perf_counter()
                - total_start
            )

            # ------------------------------------------
            # Store result
            # ------------------------------------------

            result = {

                "prompt_id": index,

                "prompt": user,

                "success": True,

                "context_time": context_time,

                "prompt_time": prompt_time,

                "llm_time": llm_time,

                "inference_time": inference_time,

                "total_time": total_time,

                "response_length": len(answer),

                "context_size": len(context),
            }

            results.append(result)

            print(
                f"    Total: {total_time:.3f}s | "
                f"LLM: {llm_time:.3f}s | "
                f"Context: {context_time:.6f}s | "
                f"Context size: {len(context)}"
            )

        except Exception as e:

            print(f"    ERROR: {e}")

            results.append({

                "prompt_id": index,

                "prompt": user,

                "success": False,

                "context_time": "",

                "prompt_time": "",

                "llm_time": "",

                "inference_time": "",

                "total_time": "",

                "response_length": "",

                "context_size": "",
            })


    # --------------------------------------------------
    # Save raw CSV
    # --------------------------------------------------

    with open(
        RESULTS_FILE,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        fieldnames = [

            "prompt_id",

            "prompt",

            "success",

            "context_time",

            "prompt_time",

            "llm_time",

            "inference_time",

            "total_time",

            "response_length",

            "context_size",
        ]

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()

        writer.writerows(results)


    # --------------------------------------------------
    # Extract successful results
    # --------------------------------------------------

    successful_results = [

        result
        for result in results
        if result["success"] is True
    ]

    failed_count = (
        len(results)
        - len(successful_results)
    )

    if not successful_results:

        print(
            "\nNo successful benchmark results."
        )

        return


    # --------------------------------------------------
    # Extract latency values
    # --------------------------------------------------

    total_times = [

        result["total_time"]
        for result in successful_results
    ]

    llm_times = [

        result["llm_time"]
        for result in successful_results
    ]

    context_times = [

        result["context_time"]
        for result in successful_results
    ]

    prompt_times = [

        result["prompt_time"]
        for result in successful_results
    ]


    # --------------------------------------------------
    # Statistics
    # --------------------------------------------------

    average_latency = statistics.mean(
        total_times
    )

    median_latency = statistics.median(
        total_times
    )

    minimum_latency = min(
        total_times
    )

    maximum_latency = max(
        total_times
    )

    p95_latency = percentile(
        total_times,
        0.95
    )

    average_llm_time = statistics.mean(
        llm_times
    )

    average_context_time = statistics.mean(
        context_times
    )

    average_prompt_time = statistics.mean(
        prompt_times
    )


    # --------------------------------------------------
    # Final report
    # --------------------------------------------------

    report = f"""
============================================================
ConAI Benchmark Report
============================================================

BOOT PERFORMANCE
------------------------------------------------------------
Cold-start model initialization : {cold_start_time:.3f} seconds


STEADY-STATE BENCHMARK
------------------------------------------------------------
Total prompts                  : {len(prompts)}
Successful                     : {len(successful_results)}
Failed                         : {failed_count}


LATENCY
------------------------------------------------------------
Average latency                : {average_latency:.3f} seconds
Median latency                 : {median_latency:.3f} seconds
P95 latency                    : {p95_latency:.3f} seconds
Minimum latency                : {minimum_latency:.3f} seconds
Maximum latency                : {maximum_latency:.3f} seconds


COMPONENT PERFORMANCE
------------------------------------------------------------
Average LLM time               : {average_llm_time:.3f} seconds
Average context processing     : {average_context_time:.6f} seconds
Average prompt building        : {average_prompt_time:.6f} seconds


FILES
------------------------------------------------------------
Raw results                    : {RESULTS_FILE}
Summary                        : {SUMMARY_FILE}

============================================================
"""

    print(report)


    # --------------------------------------------------
    # Save report
    # --------------------------------------------------

    with open(
        SUMMARY_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(report)


if __name__ == "__main__":
    run_benchmark()