/* Локальный HTTP-сервер: управление платой из домашней сети.
 *
 * Наружу интернета этот сервер выставлять не нужно: для удалённого
 * доступа существует MQTT с исходящим соединением.
 */
#pragma once

#include "esp_err.h"
#include "r32_config.h"

esp_err_t r32_http_start(const r32_config_t *cfg);
void r32_http_stop(void);
