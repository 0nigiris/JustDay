idf_component_register(SRCS "r32_guard.c"
                       INCLUDE_DIRS "include"
                       REQUIRES r32_config r32_wifi r32_wol console lwip esp_timer)
