#pragma once

#include "esp_err.h"
#include <stddef.h>
#include <stdint.h>

namespace sia::proto {

inline constexpr uint32_t kMagic = 0x31414953U;
inline constexpr uint8_t kVersion = 1;

enum class Type : uint8_t {
    HostHello       = 0x01,
    SetRoute        = 0x02,
    Ping            = 0x03,
    GetStats        = 0x04,

    TtsStart        = 0x10,
    TtsPcm          = 0x11,
    TtsEnd          = 0x12,

    MicStart        = 0x20,
    MicStop         = 0x21,

    DeviceHello     = 0x81,
    RouteAck        = 0x82,
    Pong            = 0x83,
    Stats           = 0x84,

    TtsReady        = 0x90,
    TtsDone         = 0x91,

    MicPcm          = 0xA0,
    VadEvent        = 0xA1,

    Error           = 0xFF,
};

#pragma pack(push, 1)
struct Header {
    uint32_t magic;
    uint8_t version;
    uint8_t type;
    uint16_t flags;
    uint32_t sequence;
    uint32_t timestamp_ms;
    uint32_t payload_size;
    uint32_t crc32;
};

struct AudioFormat {
    uint32_t sample_rate;
    uint16_t channels;
    uint16_t bits_per_sample;
};

struct RoutePayload {
    uint8_t route;
};

struct VadPayload {
    uint8_t speech;
};

struct StatsPayload {
    uint32_t uptime_ms;
    uint32_t free_heap;
    uint32_t free_psram;
    uint32_t usb_rx_overflow;
    uint32_t usb_tx_drop;
    uint32_t protocol_crc_error;
    uint32_t protocol_length_error;
    uint32_t playback_underflow;
    uint32_t playback_overflow;
    uint32_t reference_drop;
    uint32_t mic_i2s_error;
    uint32_t spk_i2s_error;
    uint32_t afe_feed_frames;
    uint32_t afe_fetch_frames;
    uint32_t mic_packets_sent;
};

struct DeviceHelloPayload {
    uint32_t firmware_semver;
    uint32_t sample_rate;
    uint32_t features;
};
#pragma pack(pop)

uint32_t crc32(
    const Header &header,
    const uint8_t *payload,
    size_t payload_size
);

esp_err_t send_packet(
    Type type,
    const void *payload,
    size_t payload_size,
    uint16_t flags = 0
);

esp_err_t protocol_init();
esp_err_t protocol_start();

}  // namespace sia::proto
