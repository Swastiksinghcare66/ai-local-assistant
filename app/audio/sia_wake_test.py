from app.audio.sia_hardware import SIAHardware
from app.audio.sia_audio_source import SIAHardwareListener
from app.audio.stt import ParakeetSTT


def main():

    hw = SIAHardware(
        port="COM10"
    )

    try:
        hw.connect()

        stt = ParakeetSTT()

        listener = SIAHardwareListener(
            hardware=hw,
            stt=stt,
        )

        print()
        print("Say:")
        print('    "SIA what time is it"')
        print()

        capture = listener.listen_for_command()

        print()
        print("=" * 70)
        print("HARDWARE WAKE TEST PASSED")
        print("=" * 70)

        print(
            f"Wake STT : "
            f"{capture.wake_transcript}"
        )

        print(
            f"Wake word: "
            f"{capture.wake_word}"
        )

        final_text = stt.transcribe(
            capture.audio,
            sample_rate=capture.sample_rate,
        )

        print(
            f"Final STT: "
            f"{final_text}"
        )

        print("=" * 70)

    finally:
        hw.close()


if __name__ == "__main__":
    main()