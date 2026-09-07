idf_component_register(
    SRCS "r32_http.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_http_server esp_system r32_proto r32_config
)
