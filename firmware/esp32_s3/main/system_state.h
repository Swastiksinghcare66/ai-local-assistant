#pragma once

#include <atomic>
#include <stdint.h>

namespace sia {

enum class AudioRoute : uint8_t {
    Bluetooth = 0,
    Sia = 1,
};

struct RuntimeState {
    std::atomic<AudioRoute> route{AudioRoute::Bluetooth};
    std::atomic<bool> mic_stream_enabled{false};
    std::atomic<bool> tts_active{false};
    std::atomic<bool> host_connected{false};
    std::atomic<bool> vad_speech{false};
};

RuntimeState &runtime_state();

}  // namespace sia
