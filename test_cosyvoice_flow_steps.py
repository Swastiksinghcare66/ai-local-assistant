import asyncio
import json
import statistics
import time
import wave
from pathlib import Path

import websockets


SERVER_URL = "ws://127.0.0.1:5051/tts"

TEXT = (
    "Hello Swastik. I'm Sara. "
    "I am testing my speech generation latency."
)

STYLE = "warm_conversational"

FLOW_STEPS = [10, 8, 6, 5]

# Two baseline calls first because the freshly loaded
# TensorRT/vLLM stack has substantial cold-start behavior.
WARMUP_RUNS = 2

# Number of measured requests for each Flow setting.
RUNS_PER_SETTING = 3

OUTPUT_DIR = Path("flow_step_tests")
OUTPUT_DIR.mkdir(exist_ok=True)


async def synthesize(flow_steps):
    """
    Send one CosyVoice request and collect:
      - client TTFA
      - server timing report
      - PCM audio
    """

    pcm_chunks = []

    async with websockets.connect(
        SERVER_URL,
        max_size=None,
        open_timeout=10,
    ) as ws:

        request = {
            "text": TEXT,
            "style": STYLE,
            "mode": "stream",
            "flow_steps": flow_steps,
        }

        start = time.perf_counter()

        await ws.send(
            json.dumps(request)
        )

        first_audio_time = None
        report = None

        while True:

            message = await ws.recv()

            if isinstance(message, bytes):

                if first_audio_time is None:
                    first_audio_time = (
                        time.perf_counter()
                    )

                pcm_chunks.append(message)

                continue

            data = json.loads(message)

            message_type = data.get("type")

            if message_type == "start":

                actual_steps = data.get(
                    "flow_steps"
                )

                if actual_steps != flow_steps:
                    raise RuntimeError(
                        "Server requested Flow steps mismatch: "
                        f"requested={flow_steps}, "
                        f"server={actual_steps}"
                    )

            elif message_type == "end":

                report = data
                break

            elif message_type == "error":

                raise RuntimeError(
                    data.get(
                        "message",
                        "Unknown server error",
                    )
                )

    client_ttfa_ms = None

    if first_audio_time is not None:

        client_ttfa_ms = (
            first_audio_time
            - start
        ) * 1000.0

    pcm = b"".join(
        pcm_chunks
    )

    return {
        "client_ttfa_ms":
            client_ttfa_ms,

        "report":
            report,

        "pcm":
            pcm,
    }


def save_wav(
    filename,
    pcm,
    sample_rate=24000,
):

    with wave.open(
        str(filename),
        "wb",
    ) as wav_file:

        wav_file.setnchannels(1)

        wav_file.setsampwidth(2)

        wav_file.setframerate(
            sample_rate
        )

        wav_file.writeframes(
            pcm
        )


def average(values):

    values = [
        value
        for value in values
        if value is not None
    ]

    if not values:
        return None

    return statistics.mean(
        values
    )


def fmt(value):

    if value is None:
        return "N/A"

    return f"{value:.1f}"


async def main():

    print()
    print("=" * 80)
    print("SARA COSYVOICE FLOW-STEP A/B BENCHMARK")
    print("=" * 80)

    print(
        "Text:",
        TEXT,
    )

    print(
        "Style:",
        STYLE,
    )

    print(
        "Flow settings:",
        FLOW_STEPS,
    )

    print()


    # ========================================================
    # WARM-UP
    # ========================================================

    print("=" * 80)
    print("WARM-UP")
    print("=" * 80)

    for run in range(
        1,
        WARMUP_RUNS + 1,
    ):

        print(
            f"Warm-up {run}/"
            f"{WARMUP_RUNS}..."
        )

        result = await synthesize(
            10
        )

        report = result[
            "report"
        ]

        print(
            f"  Client TTFA : "
            f"{fmt(result['client_ttfa_ms'])} ms"
        )

        print(
            f"  Model TTFA  : "
            f"{fmt(report.get('model_ttfa_ms'))} ms"
        )

        print()

        await asyncio.sleep(
            1.0
        )


    # ========================================================
    # MEASUREMENTS
    # ========================================================

    all_results = {}

    for steps in FLOW_STEPS:

        print()
        print("=" * 80)

        print(
            f"TESTING {steps} FLOW STEPS"
        )

        print("=" * 80)

        runs = []

        for run_number in range(
            1,
            RUNS_PER_SETTING + 1,
        ):

            result = await synthesize(
                steps
            )

            report = result[
                "report"
            ]

            stage = (
                report.get(
                    "stage_profile"
                )
                or {}
            )

            token = (
                report.get(
                    "token_profile"
                )
                or {}
            )

            run_data = {
                "client_ttfa":
                    result[
                        "client_ttfa_ms"
                    ],

                "model_ttfa":
                    report.get(
                        "model_ttfa_ms"
                    ),

                "total":
                    report.get(
                        "generation_time"
                    ),

                "rtf":
                    report.get(
                        "rtf"
                    ),

                "flow":
                    stage.get(
                        "first_flow_ms"
                    ),

                "hift":
                    stage.get(
                        "first_hift_ms"
                    ),

                "token28":
                    token.get(
                        "token28_from_request_ms"
                    ),

                "token28_to_audio":
                    token.get(
                        "token28_to_first_audio_ms"
                    ),
            }

            runs.append(
                run_data
            )

            print()
            print(
                f"Run {run_number}:"
            )

            print(
                f"  Client TTFA       : "
                f"{fmt(run_data['client_ttfa'])} ms"
            )

            print(
                f"  Model TTFA        : "
                f"{fmt(run_data['model_ttfa'])} ms"
            )

            print(
                f"  Token 28          : "
                f"{fmt(run_data['token28'])} ms"
            )

            print(
                f"  Flow              : "
                f"{fmt(run_data['flow'])} ms"
            )

            print(
                f"  HiFT              : "
                f"{fmt(run_data['hift'])} ms"
            )

            print(
                f"  Token28 -> audio  : "
                f"{fmt(run_data['token28_to_audio'])} ms"
            )

            print(
                f"  Total generation  : "
                f"{run_data['total']} s"
            )

            print(
                f"  RTF               : "
                f"{run_data['rtf']}"
            )


            # Save the final measured run for quality comparison.
            if (
                run_number
                == RUNS_PER_SETTING
            ):

                filename = (
                    OUTPUT_DIR
                    / f"sara_flow_{steps}_steps.wav"
                )

                save_wav(
                    filename,
                    result["pcm"],
                )

                print(
                    f"  Saved audio       : "
                    f"{filename}"
                )


            await asyncio.sleep(
                1.0
            )

        all_results[
            steps
        ] = runs


    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print()
    print()
    print("=" * 96)
    print("FINAL FLOW-STEP COMPARISON")
    print("=" * 96)

    print(
        f"{'Steps':>5} | "
        f"{'Client TTFA':>12} | "
        f"{'Model TTFA':>11} | "
        f"{'Token28':>9} | "
        f"{'Flow':>9} | "
        f"{'HiFT':>8} | "
        f"{'Total':>8} | "
        f"{'RTF':>6}"
    )

    print("-" * 96)

    for steps in FLOW_STEPS:

        runs = (
            all_results[
                steps
            ]
        )

        client_ttfa = average(
            [
                r["client_ttfa"]
                for r in runs
            ]
        )

        model_ttfa = average(
            [
                r["model_ttfa"]
                for r in runs
            ]
        )

        token28 = average(
            [
                r["token28"]
                for r in runs
            ]
        )

        flow = average(
            [
                r["flow"]
                for r in runs
            ]
        )

        hift = average(
            [
                r["hift"]
                for r in runs
            ]
        )

        total = average(
            [
                r["total"]
                for r in runs
            ]
        )

        rtf = average(
            [
                r["rtf"]
                for r in runs
            ]
        )

        print(
            f"{steps:>5} | "
            f"{fmt(client_ttfa):>12} | "
            f"{fmt(model_ttfa):>11} | "
            f"{fmt(token28):>9} | "
            f"{fmt(flow):>9} | "
            f"{fmt(hift):>8} | "
            f"{fmt(total):>8} | "
            f"{fmt(rtf):>6}"
        )


    print()
    print("=" * 96)
    print("AUDIO QUALITY FILES")
    print("=" * 96)

    for steps in FLOW_STEPS:

        filename = (
            OUTPUT_DIR
            / f"sara_flow_{steps}_steps.wav"
        )

        print(
            f"{steps:>2} steps : "
            f"{filename.resolve()}"
        )

    print()
    print(
        "Listen to 10, 8, 6 and 5-step WAV files "
        "and compare voice quality."
    )

    print()
    print("=" * 96)
    print("BENCHMARK COMPLETE")
    print("=" * 96)


if __name__ == "__main__":

    asyncio.run(
        main()
    )