from __future__ import annotations

import struct
import time
import wave
from pathlib import Path

import serial


PORT = "COM10"
BAUD = 921600

MAGIC = 0x31414953          # "SIA1"
VERSION = 1

HOST_HELLO = 0x01
MIC_START = 0x20
MIC_STOP = 0x21

DEVICE_HELLO = 0x81
MIC_PCM = 0xA0
VAD_EVENT = 0xA1
ERROR = 0xFF

SAMPLE_RATE = 16000
CHANNELS = 1
BITS_PER_SAMPLE = 16

RECORD_SECONDS = 10

OUTPUT = Path("hardware_mic_test.wav")

# Packed firmware Header:
# uint32 magic
# uint8  version
# uint8  type
# uint16 flags
# uint32 sequence
# uint32 timestamp_ms
# uint32 payload_size
# uint32 crc32
HEADER_FMT = "<IBBHIIII"
HEADER_SIZE = struct.calcsize(HEADER_FMT)

sequence = 1


def esp_crc32_le(crc: int, data: bytes) -> int:
    """
    Matches ESP-IDF esp_crc32_le()/esp_rom_crc32_le().
    """

    crc = (~crc) & 0xFFFFFFFF

    for byte in data:
        crc ^= byte

        for _ in range(8):
            if crc & 1:
                crc = (
                    (crc >> 1)
                    ^ 0xEDB88320
                )
            else:
                crc >>= 1

    return (~crc) & 0xFFFFFFFF


def build_packet(
    packet_type: int,
    payload: bytes = b"",
    flags: int = 0,
) -> bytes:

    global sequence

    timestamp_ms = int(
        time.monotonic() * 1000
    ) & 0xFFFFFFFF

    # CRC field must be zero while calculating CRC,
    # exactly like the ESP32 firmware.
    header_zero_crc = struct.pack(
        HEADER_FMT,
        MAGIC,
        VERSION,
        packet_type,
        flags,
        sequence,
        timestamp_ms,
        len(payload),
        0,
    )

    crc = esp_crc32_le(
        0,
        header_zero_crc,
    )

    if payload:
        crc = esp_crc32_le(
            crc,
            payload,
        )

    header = struct.pack(
        HEADER_FMT,
        MAGIC,
        VERSION,
        packet_type,
        flags,
        sequence,
        timestamp_ms,
        len(payload),
        crc,
    )

    sequence += 1

    return header + payload


def read_exact(
    ser: serial.Serial,
    size: int,
) -> bytes:

    data = bytearray()

    while len(data) < size:
        chunk = ser.read(
            size - len(data)
        )

        if not chunk:
            raise TimeoutError(
                f"Timed out after "
                f"{len(data)}/{size} bytes"
            )

        data.extend(chunk)

    return bytes(data)


def find_magic(
    ser: serial.Serial,
):
    """
    Resynchronizes even if USB receives garbage or starts
    in the middle of a packet.
    """

    magic_bytes = struct.pack(
        "<I",
        MAGIC,
    )

    window = bytearray()

    while True:
        byte = ser.read(1)

        if not byte:
            raise TimeoutError(
                "Timed out waiting for SIA magic."
            )

        window.extend(byte)

        if len(window) > 4:
            del window[0]

        if bytes(window) == magic_bytes:
            return


def read_packet(
    ser: serial.Serial,
):

    find_magic(ser)

    remaining = read_exact(
        ser,
        HEADER_SIZE - 4,
    )

    header_bytes = (
        struct.pack("<I", MAGIC)
        + remaining
    )

    (
        magic,
        version,
        packet_type,
        flags,
        seq,
        timestamp_ms,
        payload_size,
        received_crc,
    ) = struct.unpack(
        HEADER_FMT,
        header_bytes,
    )

    payload = (
        read_exact(
            ser,
            payload_size,
        )
        if payload_size
        else b""
    )

    zero_crc_header = struct.pack(
        HEADER_FMT,
        magic,
        version,
        packet_type,
        flags,
        seq,
        timestamp_ms,
        payload_size,
        0,
    )

    expected_crc = esp_crc32_le(
        0,
        zero_crc_header,
    )

    if payload:
        expected_crc = esp_crc32_le(
            expected_crc,
            payload,
        )

    if expected_crc != received_crc:
        raise RuntimeError(
            "CRC mismatch: "
            f"received=0x{received_crc:08X} "
            f"expected=0x{expected_crc:08X}"
        )

    return {
        "type": packet_type,
        "flags": flags,
        "sequence": seq,
        "timestamp_ms": timestamp_ms,
        "payload": payload,
    }


def send_packet(
    ser: serial.Serial,
    packet_type: int,
    payload: bytes = b"",
    flags: int = 0,
):
    packet = build_packet(
        packet_type,
        payload,
        flags,
    )

    ser.write(packet)
    ser.flush()


def main():

    print()
    print("=" * 70)
    print("SIA ESP32-S3 HARDWARE MIC TEST")
    print("=" * 70)

    print(
        f"[USB] Opening {PORT}..."
    )

    with serial.Serial(
        PORT,
        BAUD,
        timeout=3.0,
        write_timeout=3.0,
    ) as ser:

        # Give Windows/TinyUSB a moment after opening.
        time.sleep(0.5)

        # Drop any stale bytes from previous sessions.
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        print(
            "[SIA] Sending HostHello..."
        )

        send_packet(
            ser,
            HOST_HELLO,
        )

        # Wait for DeviceHello.
        while True:

            packet = read_packet(
                ser
            )

            if packet["type"] == DEVICE_HELLO:

                payload = packet["payload"]

                if len(payload) >= 12:
                    (
                        firmware_semver,
                        sample_rate,
                        features,
                    ) = struct.unpack(
                        "<III",
                        payload[:12],
                    )

                    print(
                        "[SIA] DeviceHello"
                    )

                    print(
                        f"[SIA] sample_rate="
                        f"{sample_rate}"
                    )

                    print(
                        f"[SIA] features="
                        f"0x{features:08X}"
                    )

                break

            if packet["type"] == ERROR:
                print(
                    "[ESP ERROR]",
                    packet["payload"],
                )

        print(
            "[MIC] Starting processed PCM stream..."
        )

        send_packet(
            ser,
            MIC_START,
        )

        target_bytes = (
            SAMPLE_RATE
            * CHANNELS
            * (BITS_PER_SAMPLE // 8)
            * RECORD_SECONDS
        )

        pcm = bytearray()

        start = time.perf_counter()

        last_vad = None

        while len(pcm) < target_bytes:

            packet = read_packet(
                ser
            )

            packet_type = packet["type"]

            if packet_type == MIC_PCM:

                pcm.extend(
                    packet["payload"]
                )

                percent = (
                    len(pcm)
                    / target_bytes
                    * 100
                )

                print(
                    f"\r[MIC] "
                    f"{percent:5.1f}% "
                    f"bytes={len(pcm)}",
                    end="",
                    flush=True,
                )

            elif packet_type == VAD_EVENT:

                payload = packet["payload"]

                if payload:

                    vad = bool(
                        payload[0]
                    )

                    if vad != last_vad:

                        last_vad = vad

                        print()

                        print(
                            "[VAD]",
                            "SPEECH"
                            if vad
                            else "SILENCE",
                        )

            elif packet_type == ERROR:

                message = (
                    packet["payload"]
                    .rstrip(b"\x00")
                    .decode(
                        "utf-8",
                        errors="replace",
                    )
                )

                print()

                print(
                    f"[ESP ERROR] {message}"
                )

        print()

        print(
            "[MIC] Sending MicStop..."
        )

        send_packet(
            ser,
            MIC_STOP,
        )

        elapsed = (
            time.perf_counter()
            - start
        )

        pcm = pcm[
            :target_bytes
        ]

    with wave.open(
        str(OUTPUT),
        "wb",
    ) as wav:

        wav.setnchannels(
            CHANNELS
        )

        wav.setsampwidth(
            BITS_PER_SAMPLE // 8
        )

        wav.setframerate(
            SAMPLE_RATE
        )

        wav.writeframes(
            pcm
        )

    print()
    print(
        f"[DONE] Captured "
        f"{len(pcm)} bytes "
        f"in {elapsed:.2f}s"
    )

    print(
        f"[DONE] WAV saved to:"
    )

    print(
        OUTPUT.resolve()
    )


if __name__ == "__main__":
    main()