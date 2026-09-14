import asyncio
import json
import time

import websockets


SERVER_URL = "ws://127.0.0.1:5051/tts"

TEXT = (
    "Hello Swastik. I'm Sara. "
    "I am testing my speech generation latency."
)

STYLE = "warm_conversational"


async def main():
    print("=" * 72)
    print("SARA COSYVOICE TOKEN LATENCY PROFILE")
    print("=" * 72)

    start = time.perf_counter()

    first_audio = None
    packet_count = 0
    report = None

    async with websockets.connect(
        SERVER_URL,
        max_size=None,
        open_timeout=10,
    ) as ws:

        await ws.send(
            json.dumps(
                {
                    "text": TEXT,
                    "style": STYLE,
                    "mode": "stream",
                }
            )
        )

        print("\nRequest sent.")
        print("Text :", TEXT)
        print("Style:", STYLE)
        print()

        while True:
            message = await ws.recv()

            if isinstance(message, bytes):
                packet_count += 1

                if first_audio is None:
                    first_audio = time.perf_counter()

                    print(
                        "FIRST AUDIO RECEIVED: "
                        f"{(first_audio - start) * 1000:.1f} ms"
                    )

                print(
                    f"Audio packet {packet_count}: "
                    f"{len(message)} bytes"
                )

                continue

            data = json.loads(message)

            if data.get("type") == "start":
                print(
                    f"Stream started: "
                    f"{data.get('sample_rate')} Hz"
                )

            elif data.get("type") == "end":
                report = data
                break

            elif data.get("type") == "error":
                raise RuntimeError(
                    data.get("message")
                )

    print()
    print("=" * 72)
    print("GENERAL TTS TIMINGS")
    print("=" * 72)

    print(
        "Model TTFA             :",
        report.get("model_ttfa_ms"),
        "ms",
    )

    print(
        "PCM ready              :",
        report.get("pcm_ready_ms"),
        "ms",
    )

    print(
        "First send complete    :",
        report.get("wire_ttfa_ms"),
        "ms",
    )

    print(
        "Total generation       :",
        report.get("generation_time"),
        "s",
    )

    print(
        "RTF                    :",
        report.get("rtf"),
    )

    profile = report.get("token_profile")

    print()
    print("=" * 72)
    print("VLLM SPEECH TOKEN PROFILE")
    print("=" * 72)

    if not profile:
        print("No token profile received.")
        return

    print(
        "LLM start from request :",
        profile.get("llm_start_from_request_ms"),
        "ms",
    )

    print(
        "Token 1 from LLM       :",
        profile.get("token1_from_llm_ms"),
        "ms",
    )

    print(
        "Token 10 from LLM      :",
        profile.get("token10_from_llm_ms"),
        "ms",
    )

    print(
        "Token 20 from LLM      :",
        profile.get("token20_from_llm_ms"),
        "ms",
    )

    print(
        "Token 28 from LLM      :",
        profile.get("token28_from_llm_ms"),
        "ms",
    )

    print(
        "Token 28 from request  :",
        profile.get("token28_from_request_ms"),
        "ms",
    )

    print(
        "Token28 -> first audio :",
        profile.get("token28_to_first_audio_ms"),
        "ms",
    )

    print(
        "Generated tokens       :",
        profile.get("token_count"),
    )

    print()
    print("=" * 72)
    print("PROFILE COMPLETE")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())