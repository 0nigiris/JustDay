# RMT здесь берётся из компонента driver. В ESP-IDF 5.3+ его выделили в
# отдельный esp_driver_rmt, но плата собирается на 5.2, где такого
# компонента ещё нет и сборка на нём падает.
idf_component_register(
    SRCS "r32_led.c"
    INCLUDE_DIRS "include"
    REQUIRES driver r32_config
)
