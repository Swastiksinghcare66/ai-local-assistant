idf_component_register(
    SRCS
        "app_main.cpp"
        "audio_io.cpp"
        "audio_frontend.cpp"
        "relay_manager.cpp"
        "sia_protocol.cpp"
        "usb_transport.cpp"
        "system_state.cpp"
        "diagnostics.cpp"
    INCLUDE_DIRS "."
    REQUIRES
        esp_driver_i2s
        esp_timer
        esp_system
        esp_psram
        nvs_flash
)
