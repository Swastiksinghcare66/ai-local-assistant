#include "relay_manager.h"

#include "board_config.h"
#include "driver/gpio.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

namespace sia {
namespace {
constexpr char kTag[] = "relay";

inline int level_for(AudioRoute route)
{
    // Module is active-LOW:
    // LOW  -> NO -> MAX98357A/SIA
    // HIGH -> NC -> PAM8403/Bluetooth
    return route == AudioRoute::Sia ? 0 : 1;
}
}  // namespace

esp_err_t relay_init_safe()
{
    gpio_config_t cfg{};
    cfg.pin_bit_mask =
        (1ULL << board::kRelayPositive) |
        (1ULL << board::kRelayNegative);
    cfg.mode = GPIO_MODE_OUTPUT;
    cfg.pull_up_en = GPIO_PULLUP_DISABLE;
    cfg.pull_down_en = GPIO_PULLDOWN_DISABLE;
    cfg.intr_type = GPIO_INTR_DISABLE;

    ESP_RETURN_ON_ERROR(gpio_config(&cfg), kTag, "gpio_config");

    // Safe boot invariant: Bluetooth/PAM path, both poles identical.
    ESP_RETURN_ON_ERROR(
        gpio_set_level(board::kRelayPositive, 1),
        kTag,
        "relay + safe"
    );
    ESP_RETURN_ON_ERROR(
        gpio_set_level(board::kRelayNegative, 1),
        kTag,
        "relay - safe"
    );

    runtime_state().route.store(AudioRoute::Bluetooth);
    ESP_LOGI(kTag, "Safe route: BLUETOOTH/PAM");
    return ESP_OK;
}

esp_err_t relay_select(AudioRoute route)
{
    const int level = level_for(route);

    // Both BTL conductors are switched. Never switch only one relay pole.
    ESP_RETURN_ON_ERROR(
        gpio_set_level(board::kRelayPositive, level),
        kTag,
        "relay +"
    );
    ESP_RETURN_ON_ERROR(
        gpio_set_level(board::kRelayNegative, level),
        kTag,
        "relay -"
    );

    vTaskDelay(pdMS_TO_TICKS(board::kRelaySettleMs));

    runtime_state().route.store(route);

    ESP_LOGI(
        kTag,
        "Route=%s",
        route == AudioRoute::Sia ? "SIA/MAX98357A" : "BLUETOOTH/PAM8403"
    );

    return ESP_OK;
}

AudioRoute relay_current_route()
{
    return runtime_state().route.load();
}

}  // namespace sia

