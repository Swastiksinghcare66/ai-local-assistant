import asyncio
import json
import time

import websockets


SERVER_URL = "ws://127.0.0.1:5051/tts"

TEXT = (
    "Hello Swastik. I'm Sara. "
    "I am testing my real-time speech performance."
)

STYLE = "warm_conversational"
MODE = "stream"

RUNS = 5


async def run_once(run_number):
    request_start = time.perf_counter()

    first_audio_time = None
    packet_count = 0
    total_bytes = 0
    server_report = None

    async with websockets.connect(
        SERVER_URL,
        max_size=None,
        open_timeout=10,
    ) as websocket:

        await websocket.send(
            json.dumps(
                {
                    "text": TEXT,
                    "style": STYLE,
                    "mode": MODE,
                }
            )
        )

        while True:
            message = await websocket.recv()

            if isinstance(message, bytes):
                if first_audio_time is None:
                    first_audio_time = time.perf_counter()

                packet_count += 1
                total_bytes += len(message)
                continue

            data = json.loads(message)

            if data.get("type") == "end":
                server_report = data
                break

            if data.get("type") == "error":
                raise RuntimeError(
                    data.get("message", "Unknown server error")
                )

    end_time = time.perf_counter()

    if first_audio_time is not None:
        client_ttfa_ms = (
            first_audio_time - request_start
        ) * 1000.0
    else:
        client_ttfa_ms = None

    client_total = end_time - request_start

    result = {
        "run": run_number,
        "client_ttfa_ms": client_ttfa_ms,
        "client_total": client_total,
        "packets": packet_count,
        "bytes": total_bytes,
        "server": server_report,
    }

    return result


async def main():
    print("=" * 78)
    print("SARA COSYVOICE — STEADY-STATE STREAM BENCHMARK")
    print("=" * 78)

    print("Server :", SERVER_URL)
    print("Mode   :", MODE)
    print("Style  :", STYLE)
    print("Runs   :", RUNS)
    print()

    results = []

    for run_number in range(1, RUNS + 1):
        print(
            f"Running test {run_number}/{RUNS}...",
            flush=True,
        )

        result = await run_once(run_number)
        results.append(result)

        server = result["server"]

        print(
            f"RUN {run_number} | "
            f"client TTFA={result['client_ttfa_ms']:.1f} ms | "
            f"model TTFA={server.get('model_ttfa_ms')} ms | "
            f"total={server.get('generation_time')} s | "
            f"RTF={server.get('rtf')} | "
            f"packets={server.get('packets')}"
        )

        # Small pause between requests.
        await asyncio.sleep(1.0)

    print()
    print("=" * 78)
    print("FINAL RESULTS")
    print("=" * 78)

    for result in results:
        server = result["server"]

        print(
            f"Run {result['run']}: "
            f"Client TTFA={result['client_ttfa_ms']:.1f} ms | "
            f"Model TTFA={server.get('model_ttfa_ms')} ms | "
            f"Total={server.get('generation_time')} s | "
            f"RTF={server.get('rtf')}"
        )

    # Ignore run 1 when calculating warm steady-state average.
    warm_results = results[1:]

    if warm_results:
        avg_client_ttfa = sum(
            r["client_ttfa_ms"]
            for r in warm_results
        ) / len(warm_results)

        avg_model_ttfa = sum(
            r["server"]["model_ttfa_ms"]
            for r in warm_results
        ) / len(warm_results)

        avg_total = sum(
            r["server"]["generation_time"]
            for r in warm_results
        ) / len(warm_results)

        avg_rtf = sum(
            r["server"]["rtf"]
            for r in warm_results
        ) / len(warm_results)

        print()
        print("-" * 78)
        print("WARM STEADY-STATE AVERAGE — RUNS 2 TO 5")
        print("-" * 78)

        print(
            f"Average client TTFA : "
            f"{avg_client_ttfa:.1f} ms"
        )

        print(
            f"Average model TTFA  : "
            f"{avg_model_ttfa:.1f} ms"
        )

        print(
            f"Average total time  : "
            f"{avg_total:.3f} s"
        )

        print(
            f"Average RTF         : "
            f"{avg_rtf:.3f}"
        )

    print()
    print("=" * 78)
    print("BENCHMARK COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())