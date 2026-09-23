idf_component_register(
    SRCS "r32_wifi.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_wifi esp_event esp_netif nvs_flash r32_config
)
