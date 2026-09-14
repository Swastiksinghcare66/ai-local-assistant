#pragma once

#include "esp_err.h"

namespace sia {

esp_err_t audio_frontend_init();
esp_err_t audio_frontend_start();

}  // namespace sia
