import asyncio
import math
import struct

import websockets


HOST = "0.0.0.0"
PORT = 8765

SAMPLE_RATE = 24000
FREQUENCY = 440.0
DURATION = 5.0

# 20 ms packets
CHUNK_MS = 20
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_MS // 1000

AMPLITUDE = 0.20


async def send_test_tone(websocket):
    print("[ESP32] Connected")

    total_samples = int(SAMPLE_RATE * DURATION)
    position = 0

    print(
        f"[AUDIO] Sending {FREQUENCY:.0f} Hz tone "
        f"for {DURATION:.1f} seconds"
    )

    while position < total_samples:

        count = min(
            CHUNK_SAMPLES,
            total_samples - position
        )

        chunk = bytearray()

        for i in range(count):

            t = (position + i) / SAMPLE_RATE

            value = int(
                32767
                * AMPLITUDE
                * math.sin(
                    2.0
                    * math.pi
                    * FREQUENCY
                    * t
                )
            )

            chunk += struct.pack("<h", value)

        await websocket.send(bytes(chunk))

        position += count

        # Keep stream close to real time
        await asyncio.sleep(
            CHUNK_MS / 1000.0
        )

    print("[AUDIO] Test tone complete")

    # Keep connection alive
    while True:
        await asyncio.sleep(1)


async def main():

    print()
    print("=" * 60)
    print("SARA ESP32 AUDIO SERVER")
    print("=" * 60)
    print(f"Port        : {PORT}")
    print(f"Sample rate : {SAMPLE_RATE} Hz")
    print("PCM         : signed 16-bit little-endian mono")
    print("=" * 60)
    print()
    print("Waiting for ESP32...")

    async with websockets.serve(
        send_test_tone,
        HOST,
        PORT,
        max_size=None
    ):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
