import asyncio

from app.audio.cosyvoice_client import CosyVoicePersistentClient


STYLES = [
    (
        "warm_conversational",
        "Hey. I'm Sara, and this is my normal conversational voice.",
    ),
    (
        "soft_companion",
        "It's okay. Take your time. We can work through this calmly.",
    ),
    (
        "calm_confident",
        "The system is running correctly, and the next step is straightforward.",
    ),
    (
        "energetic_friendly",
        "Yes! It worked. That was a good result.",
    ),
    (
        "serious",
        "This is important, so I'll keep the explanation clear and precise.",
    ),
]


async def main():
    print("=" * 72)
    print("SARA - ALL COSYVOICE STYLE TEST")
    print("=" * 72)

    client = CosyVoicePersistentClient(
        playback=True,
        default_style="warm_conversational",
        default_flow_steps=5,
    )

    try:
        await client.connect()

        ping = await client.ping()

        print()
        print(f"Server : {ping['server']}")
        print(f"Ping   : {ping['latency_ms']:.1f} ms")
        print()

        for index, (style, text) in enumerate(STYLES, start=1):

            print("=" * 72)
            print(f"STYLE {index}/5 : {style}")
            print("=" * 72)
            print(f"Text: {text}")

            result = await client.speak(
                text,
                style=style,
                flow_steps=5,
            )

            server = result.get("server") or {}

            print(
                f"Client TTFA : "
                f"{result.get('client_ttfa_ms')} ms"
            )

            print(
                f"Server TTFA : "
                f"{server.get('model_ttfa_ms')} ms"
            )

            print(
                f"RTF         : "
                f"{server.get('rtf')}"
            )

            print(
                f"Packets     : "
                f"{result.get('packets')}"
            )

            print()
            print("Waiting for this style to finish playing...")

            await asyncio.to_thread(
                client.wait_for_playback
            )

            print()

        print("=" * 72)
        print("ALL FIVE STYLE REQUESTS COMPLETED")
        print("=" * 72)

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
