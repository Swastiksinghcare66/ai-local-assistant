#include "audio_frontend.h"
#include "audio_io.h"
#include "board_config.h"
#include "relay_manager.h"
#include "sia_protocol.h"
#include "usb_transport.h"

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_psram.h"
#include "nvs_flash.h"

namespace {
constexpr char kTag[] = "SIA";
}

extern "C" void app_main(void)
{
    ESP_LOGI(kTag, "========================================");
    ESP_LOGI(kTag, "%s", sia::board::kFirmwareName);
    ESP_LOGI(kTag, "version=%s", sia::board::kFirmwareVersion);
    ESP_LOGI(kTag, "========================================");

    esp_err_t nvs = nvs_flash_init();
    if (
        nvs == ESP_ERR_NVS_NO_FREE_PAGES ||
        nvs == ESP_ERR_NVS_NEW_VERSION_FOUND
    ) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    } else {
        ESP_ERROR_CHECK(nvs);
    }

    if (!esp_psram_is_initialized()) {
        ESP_LOGE(
            kTag,
            "PSRAM is not initialized. Refusing to start production audio core."
        );
        abort();
    }

    ESP_LOGI(
        kTag,
        "PSRAM free=%u bytes, heap free=%u bytes",
        static_cast<unsigned>(
            heap_caps_get_free_size(MALLOC_CAP_SPIRAM)
        ),
        static_cast<unsigned>(
            heap_caps_get_free_size(MALLOC_CAP_8BIT)
        )
    );

    ESP_ERROR_CHECK(sia::relay_init_safe());
    ESP_ERROR_CHECK(sia::audio_io_init());
    ESP_ERROR_CHECK(sia::usb::init());
    ESP_ERROR_CHECK(sia::proto::protocol_init());
    ESP_ERROR_CHECK(sia::audio_frontend_init());

    ESP_ERROR_CHECK(sia::proto::protocol_start());
    ESP_ERROR_CHECK(sia::audio_frontend_start());

    ESP_LOGI(kTag, "SIA production audio core READY");
    ESP_LOGI(
        kTag,
        "Audio: 16k full-duplex | AEC(FD_LOW_COST) | NS | VAD"
    );
}
