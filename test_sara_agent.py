import asyncio

from app.audio.cosyvoice_client import (
    CosyVoicePersistentClient,
)
from app.llm_client import warmup
from app.prompt_builder import PromptBuilder

from app.agent import SaraAgent
from app.agent.voice_bridge import agent_turn

from test_qwen_cosyvoice_stream import (
    DEFAULT_VOICE_STYLE,
    FLOW_STEPS,
    run_turn,
)


async def main():
    print()
    print("=" * 72)
    print("SARA AGENT V1")
    print("=" * 72)
    print("Intent understanding : ON")
    print("Capability awareness : ON")
    print("Action verification  : ON")
    print("Web fallback         : ON")
    print("Consent policy       : ON")
    print("Normal TTS pipeline  : PRESERVED")
    print()

    prompt_builder = PromptBuilder()
    agent = SaraAgent()

    print("[STARTUP] Warming Qwen...")

    ready = await asyncio.to_thread(
        warmup
    )

    if not ready:
        print("[ERROR] Qwen warm-up failed.")
        return

    client = CosyVoicePersistentClient(
        playback=True,
        default_style=DEFAULT_VOICE_STYLE,
        default_flow_steps=FLOW_STEPS,
    )

    history = []

    try:
        print("[STARTUP] Connecting CosyVoice...")
        await client.connect()

        ping = await client.ping()

        print(
            f"[STARTUP] CosyVoice {ping['server']} | "
            f"ping={ping['latency_ms']:.1f} ms"
        )

        print()
        print("SARA READY")
        print("Type a message. /quit to stop.")

        while True:
            user_text = (
                await asyncio.to_thread(
                    input,
                    "\nYou: ",
                )
            ).strip()

            if not user_text:
                continue

            if user_text.lower() in {
                "/quit",
                "quit",
                "exit",
            }:
                break

            await agent_turn(
                agent=agent,
                client=client,
                prompt_builder=prompt_builder,
                user_text=user_text,
                history=history,
                normal_run_turn=run_turn,
            )

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
