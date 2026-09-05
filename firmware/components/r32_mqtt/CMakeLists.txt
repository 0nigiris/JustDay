idf_component_register(
    SRCS "r32_mqtt.c"
    INCLUDE_DIRS "include"
    REQUIRES mqtt esp_system r32_proto r32_config
)
