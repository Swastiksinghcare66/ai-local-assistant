from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable

MAGIC = 0x31414953  # little-endian bytes -> b"SIA1"
MAGIC_BYTES = b"SIA1"
VERSION = 1
MAX_PAYLOAD = 16 * 1024

_HEADER = struct.Struct("<IBBHIIII")
HEADER_SIZE = _HEADER.size


class PacketType(IntEnum):
    HOST_HELLO = 0x01
    SET_ROUTE = 0x02
    PING = 0x03
    GET_STATS = 0x04

    TTS_START = 0x10
    TTS_PCM = 0x11
    TTS_END = 0x12

    MIC_START = 0x20
    MIC_STOP = 0x21

    DEVICE_HELLO = 0x81
    ROUTE_ACK = 0x82
    PONG = 0x83
    STATS = 0x84

    TTS_READY = 0x90
    TTS_DONE = 0x91

    MIC_PCM = 0xA0
    VAD_EVENT = 0xA1

    ERROR = 0xFF


class Route(IntEnum):
    BLUETOOTH = 0
    SIA = 1


@dataclass(slots=True, frozen=True)
class Packet:
    type: PacketType
    sequence: int
    timestamp_ms: int
    flags: int
    payload: bytes


@dataclass(slots=True)
class DecodeCounters:
    garbage_bytes: int = 0
    bad_version: int = 0
    bad_length: int = 0
    bad_crc: int = 0


def _crc32(data: bytes, previous: int = 0) -> int:
    # Matches esp_crc32_le(0, ...) for the SIA firmware protocol and supports
    # chaining with the previous return value.
    return zlib.crc32(data, previous) & 0xFFFFFFFF


def encode_packet(
    packet_type: PacketType,
    sequence: int,
    timestamp_ms: int,
    payload: bytes = b"",
    flags: int = 0,
) -> bytes:
    payload = bytes(payload)

    if len(payload) > MAX_PAYLOAD:
        raise ValueError(
            f"payload too large: {len(payload)} > {MAX_PAYLOAD}"
        )

    header_zero_crc = _HEADER.pack(
        MAGIC,
        VERSION,
        int(packet_type),
        flags & 0xFFFF,
        sequence & 0xFFFFFFFF,
        timestamp_ms & 0xFFFFFFFF,
        len(payload),
        0,
    )

    crc = _crc32(header_zero_crc)
    if payload:
        crc = _crc32(payload, crc)

    header = _HEADER.pack(
        MAGIC,
        VERSION,
        int(packet_type),
        flags & 0xFFFF,
        sequence & 0xFFFFFFFF,
        timestamp_ms & 0xFFFFFFFF,
        len(payload),
        crc,
    )

    return header + payload


class PacketDecoder:
    """
    Incremental, resynchronizing SIA1 stream decoder.

    Native USB CDC is a byte stream. A single serial read can contain:
      - less than one packet
      - exactly one packet
      - several packets

    This decoder handles all three and can recover after garbage/corruption.
    """

    def __init__(self, max_payload: int = MAX_PAYLOAD):
        self.max_payload = int(max_payload)
        self.buffer = bytearray()
        self.counters = DecodeCounters()

    def feed(self, data: bytes) -> list[Packet]:
        if data:
            self.buffer.extend(data)

        out: list[Packet] = []

        while True:
            if len(self.buffer) < 4:
                break

            pos = self.buffer.find(MAGIC_BYTES)

            if pos < 0:
                # Keep last 3 bytes because they can be prefix of "SIA1".
                drop = max(0, len(self.buffer) - 3)
                if drop:
                    del self.buffer[:drop]
                    self.counters.garbage_bytes += drop
                break

            if pos:
                del self.buffer[:pos]
                self.counters.garbage_bytes += pos

            if len(self.buffer) < HEADER_SIZE:
                break

            (
                magic,
                version,
                raw_type,
                flags,
                sequence,
                timestamp_ms,
                payload_size,
                received_crc,
            ) = _HEADER.unpack_from(self.buffer)

            if magic != MAGIC:
                del self.buffer[0]
                self.counters.garbage_bytes += 1
                continue

            if version != VERSION:
                del self.buffer[0]
                self.counters.bad_version += 1
                continue

            if payload_size > self.max_payload:
                del self.buffer[0]
                self.counters.bad_length += 1
                continue

            total = HEADER_SIZE + payload_size
            if len(self.buffer) < total:
                break

            payload = bytes(self.buffer[HEADER_SIZE:total])

            zero_crc_header = _HEADER.pack(
                magic,
                version,
                raw_type,
                flags,
                sequence,
                timestamp_ms,
                payload_size,
                0,
            )

            expected_crc = _crc32(zero_crc_header)
            if payload:
                expected_crc = _crc32(payload, expected_crc)

            if expected_crc != received_crc:
                # Shift one byte and search for the next magic marker.
                del self.buffer[0]
                self.counters.bad_crc += 1
                continue

            try:
                packet_type = PacketType(raw_type)
            except ValueError:
                # Unknown future packet: consume it, but do not crash current
                # software. Forward compatibility is preferable to deadlock.
                del self.buffer[:total]
                continue

            out.append(
                Packet(
                    type=packet_type,
                    sequence=sequence,
                    timestamp_ms=timestamp_ms,
                    flags=flags,
                    payload=payload,
                )
            )

            del self.buffer[:total]

        return out
