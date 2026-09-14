#pragma once

#include <atomic>
#include <stdint.h>

namespace sia {

struct DiagnosticCounters {
    std::atomic<uint32_t> usb_rx_overflow{0};
    std::atomic<uint32_t> usb_tx_drop{0};
    std::atomic<uint32_t> protocol_crc_error{0};
    std::atomic<uint32_t> protocol_length_error{0};
    std::atomic<uint32_t> playback_underflow{0};
    std::atomic<uint32_t> playback_overflow{0};
    std::atomic<uint32_t> reference_drop{0};
    std::atomic<uint32_t> mic_i2s_error{0};
    std::atomic<uint32_t> spk_i2s_error{0};
    std::atomic<uint32_t> afe_feed_frames{0};
    std::atomic<uint32_t> afe_fetch_frames{0};
    std::atomic<uint32_t> mic_packets_sent{0};
};

DiagnosticCounters &diagnostics();

}  // namespace sia
