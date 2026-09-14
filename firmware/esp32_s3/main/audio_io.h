#pragma once

#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/stream_buffer.h"
#include <stddef.h>
#include <stdint.h>

namespace sia {

esp_err_t audio_io_init();

esp_err_t audio_read_mic(
    int16_t *out,
    size_t sample_count,
    TickType_t timeout
);

esp_err_t audio_write_speaker(
    const int16_t *mono,
    size_t sample_count,
    TickType_t timeout
);

StreamBufferHandle_t playback_stream();
QueueHandle_t reference_queue();

void audio_zero_output();

}  // namespace sia
