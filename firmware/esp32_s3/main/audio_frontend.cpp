#include "audio_frontend.h"

#include "audio_io.h"
#include "board_config.h"
#include "diagnostics.h"
#include "sia_protocol.h"
#include "system_state.h"

#include "esp_afe_config.h"
#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "model_path.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include <algorithm>
#include <cstring>

namespace sia {
namespace {

constexpr char kTag[] = "afe";

const esp_afe_sr_iface_t *s_afe = nullptr;
esp_afe_sr_data_t *s_afe_data = nullptr;
srmodel_list_t *s_models = nullptr;

int s_feed_samples = 0;
int s_fetch_samples = 0;

int16_t *s_mic = nullptr;
int16_t *s_ref = nullptr;
int16_t *s_interleaved = nullptr;

void push_reference_frame(const int16_t *frame)
{
    QueueHandle_t q = reference_queue();

    if (xQueueSend(q, frame, 0) != pdTRUE)
    {
        // Drop oldest to keep the reference close to "now".
        int16_t old[board::kAfeFrameSamples];
        (void)xQueueReceive(q, old, 0);

        if (xQueueSend(q, frame, 0) != pdTRUE) {
            diagnostics().reference_drop.fetch_add(1);
        }
    }
}

void speaker_task(void *)
{
    ESP_LOGI(kTag, "Speaker/reference task started");

    int16_t frame[board::kAfeFrameSamples]{};
    const size_t frame_bytes = sizeof(frame);

    while (true)
    {
        memset(frame, 0, sizeof(frame));

        size_t got = 0;

        if (runtime_state().tts_active.load())
        {
            got = xStreamBufferReceive(
                playback_stream(),
                frame,
                frame_bytes,
                pdMS_TO_TICKS(30)
            );

            if (got < frame_bytes) {
                diagnostics().playback_underflow.fetch_add(1);
                memset(
                    reinterpret_cast<uint8_t *>(frame) + got,
                    0,
                    frame_bytes - got
                );
            }
        }

        if (
            audio_write_speaker(
                frame,
                board::kAfeFrameSamples,
                pdMS_TO_TICKS(100)
            ) != ESP_OK
        ) {
            memset(frame, 0, sizeof(frame));
        }

        // The AEC reference is the exact PCM actually sent to the amplifier.
        push_reference_frame(frame);
    }
}

void afe_feed_task(void *)
{
    ESP_LOGI(kTag, "AFE feed task started");

    if (s_feed_samples != board::kAfeFrameSamples) {
        ESP_LOGE(
            kTag,
            "Unexpected AFE feed size=%d; expected=%d",
            s_feed_samples,
            board::kAfeFrameSamples
        );
        vTaskDelete(nullptr);
        return;
    }

    while (true)
    {
        if (
            audio_read_mic(
                s_mic,
                s_feed_samples,
                pdMS_TO_TICKS(100)
            ) != ESP_OK
        ) {
            memset(
                s_mic,
                0,
                s_feed_samples * sizeof(int16_t)
            );
        }

        if (
            xQueueReceive(
                reference_queue(),
                s_ref,
                pdMS_TO_TICKS(40)
            ) != pdTRUE
        ) {
            memset(
                s_ref,
                0,
                s_feed_samples * sizeof(int16_t)
            );
        }

        // "MR" input format: microphone + playback reference,
        // sample-interleaved as required by ESP-SR AFE.
        for (int i = 0; i < s_feed_samples; ++i) {
            s_interleaved[i * 2] = s_mic[i];
            s_interleaved[i * 2 + 1] = s_ref[i];
        }

        s_afe->feed(
            s_afe_data,
            s_interleaved
        );

        diagnostics().afe_feed_frames.fetch_add(1);
    }
}

void afe_fetch_task(void *)
{
    ESP_LOGI(kTag, "AFE fetch task started");

    vad_state_t last_vad = VAD_SILENCE;

    while (true)
    {
        afe_fetch_result_t *res =
            s_afe->fetch(s_afe_data);

        if (!res || res->ret_value == ESP_FAIL) {
            ESP_LOGE(kTag, "AFE fetch failed");
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }

        diagnostics().afe_fetch_frames.fetch_add(1);

        if (res->vad_state != last_vad)
        {
            last_vad = res->vad_state;

            const bool speech =
                res->vad_state == VAD_SPEECH;

            runtime_state().vad_speech.store(speech);

            proto::VadPayload vad{
                static_cast<uint8_t>(speech ? 1 : 0)
            };

            (void)proto::send_packet(
                proto::Type::VadEvent,
                &vad,
                sizeof(vad)
            );
        }

        if (!runtime_state().mic_stream_enabled.load()) {
            continue;
        }

        // get_fetch_chunksize() is the canonical number of PCM samples.
        const size_t bytes =
            static_cast<size_t>(s_fetch_samples) *
            sizeof(int16_t);

        if (
            proto::send_packet(
                proto::Type::MicPcm,
                res->data,
                bytes,
                runtime_state().vad_speech.load() ? 1 : 0
            ) == ESP_OK
        ) {
            diagnostics().mic_packets_sent.fetch_add(1);
        }
    }
}

}  // namespace

esp_err_t audio_frontend_init()
{
    // ESP-SR model list. With WebRTC NS/VAD this remains lightweight,
    // while preserving a compatible path for future WakeNet/NSNet/VADNet.
    s_models = esp_srmodel_init("model");

    afe_config_t *cfg = afe_config_init(
        "MR",
        s_models,
        AFE_TYPE_FD,
        AFE_MODE_LOW_COST
    );

    if (!cfg) {
        ESP_LOGE(kTag, "afe_config_init failed");
        return ESP_FAIL;
    }

    // Full-duplex conversational AEC.
    cfg->aec_init = true;
    cfg->aec_mode = AEC_MODE_FD_LOW_COST;
    cfg->aec_filter_length = 4;

    // Start NORMAL to protect near-end speech.
    // Increase only after ERLE + double-talk testing.
    cfg->aec_nlp_level = AEC_NLP_LEVEL_NORMAL;

    // One microphone: no beamformer/BSS.
    cfg->se_init = false;

    // Industry-stable single-channel suppression baseline.
    cfg->ns_init = true;
    cfg->afe_ns_mode = AFE_NS_MODE_WEBRTC;
    cfg->ns_model_name = nullptr;

    // VAD is used for endpoint/event signalling. Keep playback visible
    // so near-end speech can still be detected during TTS/barge-in.
    cfg->vad_init = true;
    cfg->vad_mode = VAD_MODE_2;
    cfg->vad_model_name = nullptr;
    cfg->vad_min_speech_ms = board::kVadMinSpeechMs;
    cfg->vad_min_noise_ms = board::kVadMinNoiseMs;
    cfg->vad_delay_ms = board::kVadDelayMs;
    cfg->vad_mute_playback = false;
    cfg->vad_enable_channel_trigger = false;

    // WakeNet is intentionally off until a licensed/custom SIA wake model
    // is selected and validated.
    cfg->wakenet_init = false;

    // Avoid double-AGC: PC post-AFE pipeline already has conservative AGC.
    cfg->agc_init = false;

    cfg->memory_alloc_mode = AFE_MEMORY_ALLOC_MORE_PSRAM;
    cfg->afe_linear_gain = 1.0f;
    cfg->fixed_first_channel = true;
    cfg->fixed_output_channel = true;
    cfg->output_playback_channel = false;

    cfg = afe_config_check(cfg);
    afe_config_print(cfg);

    s_afe = esp_afe_handle_from_config(cfg);
    if (!s_afe) {
        afe_config_free(cfg);
        ESP_LOGE(kTag, "esp_afe_handle_from_config failed");
        return ESP_FAIL;
    }

    s_afe_data = s_afe->create_from_config(cfg);
    afe_config_free(cfg);

    if (!s_afe_data) {
        ESP_LOGE(kTag, "AFE create failed");
        return ESP_FAIL;
    }

    s_feed_samples = s_afe->get_feed_chunksize(s_afe_data);
    s_fetch_samples = s_afe->get_fetch_chunksize(s_afe_data);

    if (
        s_feed_samples <= 0 ||
        s_fetch_samples <= 0 ||
        s_feed_samples != board::kAfeFrameSamples
    ) {
        ESP_LOGE(
            kTag,
            "AFE chunk mismatch feed=%d fetch=%d",
            s_feed_samples,
            s_fetch_samples
        );
        return ESP_ERR_INVALID_SIZE;
    }

    s_mic = static_cast<int16_t *>(
        heap_caps_aligned_alloc(
            16,
            s_feed_samples * sizeof(int16_t),
            MALLOC_CAP_8BIT
        )
    );

    s_ref = static_cast<int16_t *>(
        heap_caps_aligned_alloc(
            16,
            s_feed_samples * sizeof(int16_t),
            MALLOC_CAP_8BIT
        )
    );

    s_interleaved = static_cast<int16_t *>(
        heap_caps_aligned_alloc(
            16,
            s_feed_samples * 2 * sizeof(int16_t),
            MALLOC_CAP_8BIT
        )
    );

    if (!s_mic || !s_ref || !s_interleaved) {
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(
        kTag,
        "AFE ready: FD AEC + NS + VAD, feed=%d fetch=%d",
        s_feed_samples,
        s_fetch_samples
    );

    return ESP_OK;
}

esp_err_t audio_frontend_start()
{
    BaseType_t a = xTaskCreatePinnedToCore(
        speaker_task,
        "sia_spk",
        4096,
        nullptr,
        12,
        nullptr,
        0
    );

    BaseType_t b = xTaskCreatePinnedToCore(
        afe_feed_task,
        "sia_afe_feed",
        6144,
        nullptr,
        11,
        nullptr,
        0
    );

    BaseType_t c = xTaskCreatePinnedToCore(
        afe_fetch_task,
        "sia_afe_fetch",
        6144,
        nullptr,
        10,
        nullptr,
        1
    );

    return (
        a == pdPASS &&
        b == pdPASS &&
        c == pdPASS
    ) ? ESP_OK : ESP_ERR_NO_MEM;
}

}  // namespace sia
