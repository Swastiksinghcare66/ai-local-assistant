import time

from app.audio.sia_hardware import SIAHardware


def main():
    hw = SIAHardware(
        port="COM10"
    )

    try:
        info = hw.connect()

        print()
        print(
            f"Firmware : 0x{info.firmware_semver:06X}"
        )
        print(
            f"Rate     : {info.sample_rate}"
        )
        print(
            f"Features : 0x{info.features:08X}"
        )

        print()
        print("Testing relay -> SIA")

        hw.set_route_sia()

        time.sleep(2)

        print()
        print("Testing microphone stream")

        hw.start_mic()

        total = 0
        start = time.perf_counter()

        while (
            time.perf_counter() - start
            < 5.0
        ):
            frame = hw.get_mic_frame(
                timeout=1.0
            )

            if frame:
                total += len(frame)

                print(
                    f"\rMic bytes: {total}",
                    end="",
                    flush=True,
                )

        print()

        hw.stop_mic()

        print()
        print("Testing relay -> Bluetooth")

        hw.set_route_bluetooth()

        print()
        print("[TEST] PASS")

    finally:
        hw.close()


if __name__ == "__main__":
    main()