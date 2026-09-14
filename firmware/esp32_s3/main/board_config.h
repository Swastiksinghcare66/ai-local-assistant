#pragma once

#include "driver/gpio.h"
#include <stdint.h>

namespace sia::board {

// ---------------- Identity ----------------
inline constexpr const char *kFirmwareName = "SIA ESP32-S3 Voice Core";
inline constexpr const char *kFirmwareVersion = "2.0.1-perf";
inline constexpr uint32_t kProtocolVersion = 1;

// ---------------- Audio ----------------
// Full-duplex AEC requires the microphone and playback reference at 16 kHz.
// CosyVoice's 24 kHz PCM must be resampled to 16 kHz on the PC before
// entering the full-duplex product path.
inline constexpr int kAudioSampleRate = 16000;
inline constexpr int kAfeFrameSamples = 512;   // 32 ms @ 16 kHz
inline constexpr int kPcmBytesPerSample = 2;

// INMP441
inline constexpr gpio_num_t kMicBclk = GPIO_NUM_12;
inline constexpr gpio_num_t kMicWs   = GPIO_NUM_13;
inline constexpr gpio_num_t kMicData = GPIO_NUM_14;

// MAX98357A
inline constexpr gpio_num_t kSpkBclk = GPIO_NUM_6;
inline constexpr gpio_num_t kSpkWs   = GPIO_NUM_5;
inline constexpr gpio_num_t kSpkData = GPIO_NUM_7;

// Active-low dual relay; both channels MUST always switch together.
inline constexpr gpio_num_t kRelayPositive = GPIO_NUM_4;
inline constexpr gpio_num_t kRelayNegative = GPIO_NUM_10;

// ---------------- Buffers ----------------
inline constexpr size_t kPlaybackStreamBytes = 64 * 1024;
inline constexpr size_t kUsbRxStreamBytes = 32 * 1024;
inline constexpr size_t kMaxProtocolPayload = 16 * 1024;
inline constexpr size_t kReferenceQueueFrames = 4;

// ---------------- Relay timing ----------------
inline constexpr int kRelayBreakBeforeAudioMs = 30;
inline constexpr int kRelaySettleMs = 120;

// ---------------- VAD ----------------
inline constexpr int kVadMinSpeechMs = 128;
inline constexpr int kVadMinNoiseMs  = 700;
inline constexpr int kVadDelayMs     = 192;

}  // namespace sia::board
