#pragma once

#include "esp_err.h"
#include <stddef.h>
#include <stdint.h>

namespace sia::usb {

esp_err_t init();
esp_err_t start();

size_t write(
    const uint8_t *data,
    size_t size,
    uint32_t timeout_ms
);

bool flush(
    uint32_t timeout_ms
);

size_t read_exact(
    uint8_t *data,
    size_t size,
    uint32_t timeout_ms
);

}  // namespace sia::usb
