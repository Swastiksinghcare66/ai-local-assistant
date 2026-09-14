from app.hardware.sia_protocol import (
    PacketDecoder,
    PacketType,
    encode_packet,
)


def test_round_trip():
    wire = encode_packet(
        PacketType.TTS_PCM,
        sequence=42,
        timestamp_ms=123456,
        payload=b"\x01\x02\x03\x04",
        flags=7,
    )

    decoder = PacketDecoder()

    packets = []

    # Deliberately fragment at arbitrary byte boundaries.
    for i in range(0, len(wire), 3):
        packets.extend(
            decoder.feed(wire[i:i + 3])
        )

    assert len(packets) == 1

    p = packets[0]

    assert p.type == PacketType.TTS_PCM
    assert p.sequence == 42
    assert p.timestamp_ms == 123456
    assert p.flags == 7
    assert p.payload == b"\x01\x02\x03\x04"


def test_resync_after_garbage():
    wire = encode_packet(
        PacketType.PING,
        sequence=1,
        timestamp_ms=2,
    )

    decoder = PacketDecoder()
    packets = decoder.feed(b"garbage\x00\x01" + wire)

    assert len(packets) == 1
    assert packets[0].type == PacketType.PING


if __name__ == "__main__":
    test_round_trip()
    test_resync_after_garbage()
    print("PASS")
