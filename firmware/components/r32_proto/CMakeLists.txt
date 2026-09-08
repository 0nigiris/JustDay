idf_component_register(
    SRCS "r32_proto.c"
    INCLUDE_DIRS "include"
    REQUIRES json esp_wifi esp_system esp_app_format r32_gpio r32_guard r32_wol r32_wifi r32_config r32_button
)
