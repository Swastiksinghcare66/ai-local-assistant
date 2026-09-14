#include "usb_transport.h"

#include "board_config.h"
#include "diagnostics.h"

#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/stream_buffer.h"
#include "tinyusb.h"
#include "tinyusb_cdc_acm.h"
#include "tinyusb_default_config.h"

namespace sia::usb {
namespace {

constexpr char kTag[] = "usb";
StreamBufferHandle_t s_rx_stream = nullptr;

void cdc_rx_callback(int itf, cdcacm_event_t *event)
{
    (void)event;

    uint8_t temp[1024];

    while (true)
    {
        size_t got = 0;

        if (
            tinyusb_cdcacm_read(
                static_cast<tinyusb_cdcacm_itf_t>(itf),
                temp,
                sizeof(temp),
                &got
            ) != ESP_OK ||
            got == 0
        ) {
            break;
        }

        const size_t pushed = xStreamBufferSend(
            s_rx_stream,
            temp,
            got,
            0
        );

        if (pushed != got) {
            diagnostics().usb_rx_overflow.fetch_add(1);
        }
    }
}

}  // namespace

esp_err_t init()
{
    s_rx_stream = xStreamBufferCreate(
        board::kUsbRxStreamBytes,
        1
    );

    if (!s_rx_stream) {
        return ESP_ERR_NO_MEM;
    }

    const tinyusb_config_t tusb_cfg =
        TINYUSB_DEFAULT_CONFIG();

    ESP_RETURN_ON_ERROR(
        tinyusb_driver_install(&tusb_cfg),
        kTag,
        "tinyusb_driver_install"
    );

    const tinyusb_config_cdcacm_t acm_cfg = {
        .cdc_port = TINYUSB_CDC_ACM_0,
        .callback_rx = cdc_rx_callback,
        .callback_rx_wanted_char = nullptr,
        .callback_line_state_changed = nullptr,
        .callback_line_coding_changed = nullptr,
    };

    ESP_RETURN_ON_ERROR(
        tinyusb_cdcacm_init(&acm_cfg),
        kTag,
        "tinyusb_cdcacm_init"
    );

    ESP_LOGI(kTag, "TinyUSB CDC ready");
    return ESP_OK;
}

esp_err_t start()
{
    return ESP_OK;
}

size_t write(
    const uint8_t *data,
    size_t size,
    uint32_t timeout_ms
)
{
    if (!data || size == 0) {
        return 0;
    }

    size_t total = 0;
    const TickType_t start =
        xTaskGetTickCount();

    const TickType_t timeout =
        pdMS_TO_TICKS(timeout_ms);

    while (total < size)
    {
        const size_t queued =
            tinyusb_cdcacm_write_queue(
                TINYUSB_CDC_ACM_0,
                data + total,
                size - total
            );

        if (queued > 0) {
            total += queued;
            continue;
        }

        // Queue is full: kick one USB transfer, then retry.
        (void)tinyusb_cdcacm_write_flush(
            TINYUSB_CDC_ACM_0,
            0
        );

        if (
            (xTaskGetTickCount() - start)
            >= timeout
        ) {
            diagnostics().usb_tx_drop.fetch_add(1);
            break;
        }

        vTaskDelay(pdMS_TO_TICKS(1));
    }

    return total;
}

bool flush(
    uint32_t timeout_ms
)
{
    return tinyusb_cdcacm_write_flush(
        TINYUSB_CDC_ACM_0,
        pdMS_TO_TICKS(timeout_ms)
    ) == ESP_OK;
}

size_t read_exact(
    uint8_t *data,
    size_t size,
    uint32_t timeout_ms
)
{
    if (!data || size == 0 || !s_rx_stream) {
        return 0;
    }

    size_t total = 0;

    const TickType_t deadline =
        xTaskGetTickCount()
        + pdMS_TO_TICKS(timeout_ms);

    while (total < size)
    {
        const TickType_t now =
            xTaskGetTickCount();

        if (now >= deadline) {
            break;
        }

        const TickType_t wait =
            deadline - now;

        const size_t got =
            xStreamBufferReceive(
                s_rx_stream,
                data + total,
                size - total,
                wait
            );

        if (got == 0) {
            break;
        }

        total += got;
    }

    return total;
}

}  // namespace sia::usb
