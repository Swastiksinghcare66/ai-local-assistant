import time

from app.audio.sia_hardware import SIAHardware


hw = SIAHardware(port="COM10")

try:
    print("Connecting...")
    hw.connect(timeout=3.0)

    print()
    print("====================================")
    print("1. BLUETOOTH MODE - wait 4 seconds")
    print("====================================")
    hw.set_route_bluetooth()
    time.sleep(4)

    print()
    print("====================================")
    print("2. SIA MODE - BOTH RELAYS SHOULD CLICK")
    print("====================================")
    hw.set_route_sia()
    time.sleep(5)

    print()
    print("====================================")
    print("3. BLUETOOTH - BOTH SHOULD CLICK BACK")
    print("====================================")
    hw.set_route_bluetooth()
    time.sleep(5)

    print()
    print("====================================")
    print("4. SIA - BOTH SHOULD CLICK AGAIN")
    print("====================================")
    hw.set_route_sia()
    time.sleep(5)

    print()
    print("====================================")
    print("5. BLUETOOTH - FINAL")
    print("====================================")
    hw.set_route_bluetooth()
    time.sleep(3)

finally:
    hw.close()
    print("Finished.")