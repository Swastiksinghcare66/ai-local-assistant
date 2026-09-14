import asyncio

from app.audio.piper_client import PiperTTSClient
from app.audio.sia_hardware import SIAHardware
from app.audio.sia_playback import SIAAudioPlayer
from app.config import (
    PIPER_MODEL_PATH,
    PIPER_CONFIG_PATH,
)

async def main():

    hw = SIAHardware(
        port="COM10"
    )

    hw.connect(
        timeout=3.0
    )

    hw.set_route_sia()

    player = SIAAudioPlayer(
        hardware=hw,
        input_sample_rate=24000,
        output_sample_rate=16000,
        slice_ms=20,
    )

    player.start()

    piper = PiperTTSClient(
        model_path=PIPER_MODEL_PATH,
        config_path=PIPER_CONFIG_PATH,
        player=player,
        target_sample_rate=24000,
        use_cuda=False,
    )

    await piper.connect()

    text = (
        "हाँ स्वस्तिक, अब मैं हिंदी और हिंग्लिश में भी "
        "बात कर सकती हूँ। जी पी यू, कूडा और रैग जैसे "
        "टेक्निकल वर्ड्स भी बोल सकती हूँ।"
    )

    print()
    print("Speaking:")
    print(text)
    print()

    result = await piper.speak(
        text
    )

    print(
        "TTFA:",
        result.get(
            "client_ttfa_ms"
        ),
        "ms"
    )

    print(
        "RTF:",
        (
            result.get(
                "server"
            )
            or {}
        ).get(
            "rtf"
        )
    )

    await asyncio.to_thread(
        piper.wait_for_playback
    )

    await piper.close()

    player.stop(
        drain=False
    )

    hw.set_route_bluetooth()
    hw.close()

asyncio.run(
    main()
)
