idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES nvs_flash console esp_timer esp_system
             r32_config r32_wifi r32_gpio r32_wol r32_proto r32_http r32_mqtt r32_guard
)
