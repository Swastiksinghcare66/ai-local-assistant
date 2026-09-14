from app.hardware.sia_esp32 import SIAESP32
from app.hardware.sia_protocol import Route


def main():
    with SIAESP32(port="COM10") as hw:
        hello = hw.host_hello()

        print("Firmware:", hello.firmware_version)
        print("Audio rate:", hello.sample_rate)
        print("Features: 0x%08X" % hello.features)

        print("Ping:", f"{hw.ping():.2f} ms")

        route = hw.set_route(Route.SIA)
        print("Route:", route.name)

        stats = hw.get_stats()
        print("Free heap:", stats.free_heap)
        print("Free PSRAM:", stats.free_psram)
        print("AFE feed:", stats.afe_feed_frames)
        print("AFE fetch:", stats.afe_fetch_frames)

        route = hw.set_route(Route.BLUETOOTH)
        print("Route:", route.name)

    print("PASS")


if __name__ == "__main__":
    main()

