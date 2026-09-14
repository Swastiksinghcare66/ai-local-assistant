#pragma once

#include "esp_err.h"
#include "system_state.h"

namespace sia {

esp_err_t relay_init_safe();
esp_err_t relay_select(AudioRoute route);
AudioRoute relay_current_route();

}  // namespace sia
