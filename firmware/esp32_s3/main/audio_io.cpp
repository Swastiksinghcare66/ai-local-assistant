#include "audio_io.h"

#include "board_config.h"
#include "diagnostics.h"

#include "driver/i2s_std.h"
#include "esp_check.h"
#include "esp_log.h"

#include <algorithm>
#include <cstring>

namespace sia {
namespace {

constexpr char kTag[] = "audio_io";

i2s_chan_handle_t s_mic_rx = nullptr;
i2s_chan_handle_t s_spk_tx = nullptr;

StreamBufferHandle_t s_playback_stream = nullptr;
QueueHandle_t s_reference_queue = nullptr;

int32_t s_mic_raw[board::kAfeFrameSamples];
int16_t s_stereo[board::kAfeFrameSamples * 2];

}  // namespace

esp_err_t audio_io_init()
{
    // ---------------- INMP441 RX ----------------
    i2s_chan_config_t rx_chan_cfg =
        I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);

    ESP_RETURN_ON_ERROR(
        i2s_new_channel(&rx_chan_cfg, nullptr, &s_mic_rx),
        kTag,
        "new mic channel"
    );

    i2s_std_config_t rx_std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(board::kAudioSampleRate),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_32BIT,
            I2S_SLOT_MODE_MONO
        ),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = board::kMicBclk,
            .ws = board::kMicWs,
            .dout = I2S_GPIO_UNUSED,
            .din = board::kMicData,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };
    rx_std_cfg.slot_cfg.slot_mask = I2S_STD_SLOT_LEFT;

    ESP_RETURN_ON_ERROR(
        i2s_channel_init_std_mode(s_mic_rx, &rx_std_cfg),
        kTag,
        "init mic std"
    );

    ESP_RETURN_ON_ERROR(
        i2s_channel_enable(s_mic_rx),
        kTag,
        "enable mic"
    );

    // ---------------- MAX98357A TX ----------------
    i2s_chan_config_t tx_chan_cfg =
        I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);

    ESP_RETURN_ON_ERROR(
        i2s_new_channel(&tx_chan_cfg, &s_spk_tx, nullptr),
        kTag,
        "new speaker channel"
    );

    i2s_std_config_t tx_std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(board::kAudioSampleRate),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_16BIT,
            I2S_SLOT_MODE_STEREO
        ),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = board::kSpkBclk,
            .ws = board::kSpkWs,
            .dout = board::kSpkData,
            .din = I2S_GPIO_UNUSED,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };
    tx_std_cfg.slot_cfg.slot_mask = I2S_STD_SLOT_BOTH;

    ESP_RETURN_ON_ERROR(
        i2s_channel_init_std_mode(s_spk_tx, &tx_std_cfg),
        kTag,
        "init speaker std"
    );

    ESP_RETURN_ON_ERROR(
        i2s_channel_enable(s_spk_tx),
        kTag,
        "enable speaker"
    );

    s_playback_stream = xStreamBufferCreate(
        board::kPlaybackStreamBytes,
        board::kAfeFrameSamples * sizeof(int16_t)
    );

    s_reference_queue = xQueueCreate(
        board::kReferenceQueueFrames,
        board::kAfeFrameSamples * sizeof(int16_t)
    );

    if (!s_playback_stream || !s_reference_queue) {
        ESP_LOGE(kTag, "Failed to allocate RT audio buffers");
        return ESP_ERR_NO_MEM;
    }

    audio_zero_output();

    ESP_LOGI(
        kTag,
        "Audio I/O ready: mic=%d Hz, speaker=%d Hz",
        board::kAudioSampleRate,
        board::kAudioSampleRate
    );

    return ESP_OK;
}

esp_err_t audio_read_mic(
    int16_t *out,
    size_t sample_count,
    TickType_t timeout
)
{
    if (!out || sample_count == 0 || sample_count > board::kAfeFrameSamples) {
        return ESP_ERR_INVALID_ARG;
    }

    size_t bytes_read = 0;
    const size_t requested = sample_count * sizeof(int32_t);

    esp_err_t err = i2s_channel_read(
        s_mic_rx,
        s_mic_raw,
        requested,
        &bytes_read,
        timeout
    );

    if (err != ESP_OK || bytes_read != requested) {
        diagnostics().mic_i2s_error.fetch_add(1);
        return err == ESP_OK ? ESP_ERR_INVALID_SIZE : err;
    }

    // This exact conversion matched the validated INMP441 path used earlier:
    // 32-bit I2S slot -> signed PCM16.
    for (size_t i = 0; i < sample_count; ++i) {
        out[i] = static_cast<int16_t>(s_mic_raw[i] >> 16);
    }

    return ESP_OK;
}

esp_err_t audio_write_speaker(
    const int16_t *mono,
    size_t sample_count,
    TickType_t timeout
)
{
    if (!mono || sample_count == 0 || sample_count > board::kAfeFrameSamples) {
        return ESP_ERR_INVALID_ARG;
    }

    for (size_t i = 0; i < sample_count; ++i) {
        s_stereo[i * 2] = mono[i];
        s_stereo[i * 2 + 1] = mono[i];
    }

    size_t bytes_written = 0;
    const size_t requested = sample_count * 2 * sizeof(int16_t);

    esp_err_t err = i2s_channel_write(
        s_spk_tx,
        s_stereo,
        requested,
        &bytes_written,
        timeout
    );

    if (err != ESP_OK || bytes_written != requested) {
        diagnostics().spk_i2s_error.fetch_add(1);
        return err == ESP_OK ? ESP_ERR_INVALID_SIZE : err;
    }

    return ESP_OK;
}

StreamBufferHandle_t playback_stream()
{
    return s_playback_stream;
}

QueueHandle_t reference_queue()
{
    return s_reference_queue;
}

void audio_zero_output()
{
    static const int16_t zeros[board::kAfeFrameSamples] = {};
    if (s_spk_tx) {
        (void)audio_write_speaker(
            zeros,
            board::kAfeFrameSamples,
            pdMS_TO_TICKS(100)
        );
    }
}

}  // namespace sia
