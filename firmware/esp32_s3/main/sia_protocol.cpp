#include "sia_protocol.h"

#include "audio_io.h"
#include "board_config.h"
#include "diagnostics.h"
#include "relay_manager.h"
#include "system_state.h"
#include "usb_transport.h"

#include "esp_crc.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/stream_buffer.h"
#include "freertos/task.h"

#include <atomic>
#include <cstring>

namespace sia::proto {
namespace {

constexpr char kTag[] = "protocol";

constexpr uint32_t kFeatures =
    (1U << 0) |
    (1U << 1) |
    (1U << 2) |
    (1U << 3) |
    (1U << 4) |
    (1U << 5) |
    (1U << 6);

std::atomic<uint32_t> s_tx_sequence{1};

uint8_t s_payload[
    board::kMaxProtocolPayload
];

SemaphoreHandle_t s_tx_mutex = nullptr;

uint32_t now_ms()
{
    return static_cast<uint32_t>(
        esp_timer_get_time() / 1000ULL
    );
}

bool read_magic()
{
    uint32_t rolling = 0;
    uint8_t byte = 0;

    while (true)
    {
        if (
            usb::read_exact(
                &byte,
                1,
                5000
            ) != 1
        ) {
            return false;
        }

        rolling =
            (rolling >> 8)
            |
            (
                static_cast<uint32_t>(
                    byte
                )
                << 24
            );

        if (rolling == kMagic) {
            return true;
        }
    }
}

void send_error(
    const char *message
)
{
    if (!message) {
        return;
    }

    (void)send_packet(
        Type::Error,
        message,
        strlen(message) + 1
    );
}

void send_stats()
{
    const auto &d = diagnostics();

    StatsPayload p{};
    p.uptime_ms = now_ms();
    p.free_heap =
        heap_caps_get_free_size(
            MALLOC_CAP_8BIT
        );
    p.free_psram =
        heap_caps_get_free_size(
            MALLOC_CAP_SPIRAM
        );
    p.usb_rx_overflow =
        d.usb_rx_overflow.load();
    p.usb_tx_drop =
        d.usb_tx_drop.load();
    p.protocol_crc_error =
        d.protocol_crc_error.load();
    p.protocol_length_error =
        d.protocol_length_error.load();
    p.playback_underflow =
        d.playback_underflow.load();
    p.playback_overflow =
        d.playback_overflow.load();
    p.reference_drop =
        d.reference_drop.load();
    p.mic_i2s_error =
        d.mic_i2s_error.load();
    p.spk_i2s_error =
        d.spk_i2s_error.load();
    p.afe_feed_frames =
        d.afe_feed_frames.load();
    p.afe_fetch_frames =
        d.afe_fetch_frames.load();
    p.mic_packets_sent =
        d.mic_packets_sent.load();

    (void)send_packet(
        Type::Stats,
        &p,
        sizeof(p)
    );
}

void handle_packet(
    Type type,
    const uint8_t *payload,
    size_t payload_size
)
{
    auto &state = runtime_state();

    switch (type)
    {
        case Type::HostHello: {
            state.host_connected.store(true);

            DeviceHelloPayload hello{};
            hello.firmware_semver = 0x020001;
            hello.sample_rate =
                board::kAudioSampleRate;
            hello.features = kFeatures;

            (void)send_packet(
                Type::DeviceHello,
                &hello,
                sizeof(hello)
            );
            break;
        }

        case Type::Ping:
            (void)send_packet(
                Type::Pong,
                nullptr,
                0
            );
            break;

        case Type::GetStats:
            send_stats();
            break;

        case Type::SetRoute: {
            if (
                payload_size
                != sizeof(RoutePayload)
            ) {
                send_error(
                    "bad SetRoute payload"
                );
                break;
            }

            const auto *p =
                reinterpret_cast<
                    const RoutePayload *
                >(payload);

            const AudioRoute route =
                p->route == 1
                ? AudioRoute::Sia
                : AudioRoute::Bluetooth;

            if (state.tts_active.load()) {
                send_error(
                    "route change rejected during TTS"
                );
                break;
            }

            audio_zero_output();

            vTaskDelay(
                pdMS_TO_TICKS(
                    board::
                    kRelayBreakBeforeAudioMs
                )
            );

            if (
                relay_select(route)
                != ESP_OK
            ) {
                send_error(
                    "relay switch failed"
                );
                break;
            }

            RoutePayload ack{
                static_cast<uint8_t>(
                    route
                    == AudioRoute::Sia
                    ? 1
                    : 0
                )
            };

            (void)send_packet(
                Type::RouteAck,
                &ack,
                sizeof(ack)
            );
            break;
        }

        case Type::MicStart:
            state.mic_stream_enabled.store(
                true
            );
            break;

        case Type::MicStop:
            state.mic_stream_enabled.store(
                false
            );
            break;

        case Type::TtsStart: {
            if (
                payload_size
                != sizeof(AudioFormat)
            ) {
                send_error(
                    "bad TtsStart payload"
                );
                break;
            }

            const auto *fmt =
                reinterpret_cast<
                    const AudioFormat *
                >(payload);

            if (
                fmt->sample_rate
                    != board::kAudioSampleRate
                ||
                fmt->channels != 1
                ||
                fmt->bits_per_sample != 16
            ) {
                send_error(
                    "full-duplex path requires "
                    "16kHz mono PCM16"
                );
                break;
            }

            audio_zero_output();

            if (
                relay_current_route()
                != AudioRoute::Sia
            ) {
                vTaskDelay(
                    pdMS_TO_TICKS(
                        board::
                        kRelayBreakBeforeAudioMs
                    )
                );

                if (
                    relay_select(
                        AudioRoute::Sia
                    ) != ESP_OK
                ) {
                    send_error(
                        "relay switch failed"
                    );
                    break;
                }
            }

            xStreamBufferReset(
                playback_stream()
            );

            state.tts_active.store(
                true
            );

            (void)send_packet(
                Type::TtsReady,
                nullptr,
                0
            );
            break;
        }

        case Type::TtsPcm: {
            if (!state.tts_active.load()) {
                send_error(
                    "TTS PCM without TtsStart"
                );
                break;
            }

            if (
                (payload_size & 1U) != 0U
            ) {
                send_error(
                    "unaligned PCM16 payload"
                );
                break;
            }

            const size_t sent =
                xStreamBufferSend(
                    playback_stream(),
                    payload,
                    payload_size,
                    pdMS_TO_TICKS(1000)
                );

            if (sent != payload_size) {
                diagnostics()
                    .playback_overflow
                    .fetch_add(1);

                send_error(
                    "playback buffer overflow"
                );
            }

            break;
        }

        case Type::TtsEnd: {
            if (!state.tts_active.load()) {
                (void)send_packet(
                    Type::TtsDone,
                    nullptr,
                    0
                );
                break;
            }

            const TickType_t deadline =
                xTaskGetTickCount()
                + pdMS_TO_TICKS(5000);

            while (
                xStreamBufferBytesAvailable(
                    playback_stream()
                ) > 0
                &&
                xTaskGetTickCount()
                    < deadline
            ) {
                vTaskDelay(
                    pdMS_TO_TICKS(5)
                );
            }

            // One short guard instead of the previous
            // fixed 50 ms completion penalty.
            vTaskDelay(
                pdMS_TO_TICKS(10)
            );

            state.tts_active.store(false);

            (void)send_packet(
                Type::TtsDone,
                nullptr,
                0
            );
            break;
        }

        default:
            send_error(
                "unsupported packet type"
            );
            break;
    }
}

void protocol_task(void *)
{
    ESP_LOGI(
        kTag,
        "Protocol parser started"
    );

    while (true)
    {
        if (!read_magic()) {
            continue;
        }

        Header header{};
        header.magic = kMagic;

        auto *rest =
            reinterpret_cast<uint8_t *>(
                &header
            )
            + sizeof(header.magic);

        const size_t rest_size =
            sizeof(Header)
            - sizeof(header.magic);

        if (
            usb::read_exact(
                rest,
                rest_size,
                1000
            ) != rest_size
        ) {
            continue;
        }

        if (
            header.version != kVersion
            ||
            header.payload_size
                > board::kMaxProtocolPayload
        ) {
            diagnostics()
                .protocol_length_error
                .fetch_add(1);
            continue;
        }

        if (
            header.payload_size > 0
            &&
            usb::read_exact(
                s_payload,
                header.payload_size,
                2000
            ) != header.payload_size
        ) {
            continue;
        }

        const uint32_t expected =
            crc32(
                header,
                header.payload_size
                    ? s_payload
                    : nullptr,
                header.payload_size
            );

        if (
            expected
            != header.crc32
        ) {
            diagnostics()
                .protocol_crc_error
                .fetch_add(1);
            continue;
        }

        handle_packet(
            static_cast<Type>(
                header.type
            ),
            s_payload,
            header.payload_size
        );
    }
}

}  // namespace

uint32_t crc32(
    const Header &header,
    const uint8_t *payload,
    size_t payload_size
)
{
    Header temp = header;
    temp.crc32 = 0;

    uint32_t crc =
        esp_crc32_le(
            0,
            reinterpret_cast<
                const uint8_t *
            >(&temp),
            sizeof(temp)
        );

    if (
        payload
        && payload_size
    ) {
        crc = esp_crc32_le(
            crc,
            payload,
            payload_size
        );
    }

    return crc;
}

esp_err_t send_packet(
    Type type,
    const void *payload,
    size_t payload_size,
    uint16_t flags
)
{
    if (
        payload_size
        > board::kMaxProtocolPayload
    ) {
        return ESP_ERR_INVALID_SIZE;
    }

    if (!s_tx_mutex) {
        return ESP_ERR_INVALID_STATE;
    }

    if (
        xSemaphoreTake(
            s_tx_mutex,
            pdMS_TO_TICKS(1000)
        ) != pdTRUE
    ) {
        return ESP_ERR_TIMEOUT;
    }

    esp_err_t result = ESP_OK;

    Header header{};
    header.magic = kMagic;
    header.version = kVersion;
    header.type =
        static_cast<uint8_t>(type);
    header.flags = flags;
    header.sequence =
        s_tx_sequence.fetch_add(1);
    header.timestamp_ms = now_ms();
    header.payload_size = payload_size;
    header.crc32 = crc32(
        header,
        static_cast<
            const uint8_t *
        >(payload),
        payload_size
    );

    if (
        usb::write(
            reinterpret_cast<
                const uint8_t *
            >(&header),
            sizeof(header),
            1000
        ) != sizeof(header)
    ) {
        result = ESP_ERR_TIMEOUT;
    }

    if (
        result == ESP_OK
        &&
        payload_size > 0
        &&
        usb::write(
            static_cast<
                const uint8_t *
            >(payload),
            payload_size,
            1000
        ) != payload_size
    ) {
        result = ESP_ERR_TIMEOUT;
    }

    if (
        result == ESP_OK
        &&
        !usb::flush(1000)
    ) {
        result = ESP_ERR_TIMEOUT;
    }

    xSemaphoreGive(
        s_tx_mutex
    );

    return result;
}

esp_err_t protocol_init()
{
    s_tx_mutex =
        xSemaphoreCreateMutex();

    return s_tx_mutex
        ? ESP_OK
        : ESP_ERR_NO_MEM;
}

esp_err_t protocol_start()
{
    BaseType_t ok =
        xTaskCreatePinnedToCore(
            protocol_task,
            "sia_proto",
            8192,
            nullptr,
            8,
            nullptr,
            1
        );

    return (
        ok == pdPASS
        ? ESP_OK
        : ESP_ERR_NO_MEM
    );
}

}  // namespace sia::proto
