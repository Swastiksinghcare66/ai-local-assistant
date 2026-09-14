# SIA1 USB CDC protocol

All integer fields are little-endian.

## Header

```c
struct Header {
    uint32_t magic;       // 0x31414953 = "SIA1"
    uint8_t  version;     // 1
    uint8_t  type;
    uint16_t flags;
    uint32_t sequence;
    uint32_t timestamp_ms;
    uint32_t payload_size;
    uint32_t crc32;
};
```

CRC32 is computed over:
1. header with `crc32=0`
2. payload bytes

Maximum payload: 16384 bytes.

## Host -> device

- 0x01 HostHello
- 0x02 SetRoute: `uint8 route` (0 BT, 1 SIA)
- 0x03 Ping
- 0x04 GetStats
- 0x10 TtsStart: `{uint32 sample_rate, uint16 channels, uint16 bits}`
- 0x11 TtsPcm: PCM16 mono
- 0x12 TtsEnd
- 0x20 MicStart
- 0x21 MicStop

## Device -> host

- 0x81 DeviceHello
- 0x82 RouteAck
- 0x83 Pong
- 0x84 Stats
- 0x90 TtsReady
- 0x91 TtsDone
- 0xA0 MicPcm
- 0xA1 VadEvent
- 0xFF Error

## Full-duplex audio contract

- 16000 Hz
- mono
- signed PCM16 little endian
- TTS PCM sent by host is the exact far-end reference used by AEC.
