/* MQTT-клиент: удалённое управление без открытых портов дома.
 *
 * Соединение всегда исходящее, поэтому проброс портов на роутере не нужен
 * и дома не остаётся ничего слушающего интернет.
 */
#pragma once

#include <stdbool.h>

#include "esp_err.h"
#include "r32_config.h"

esp_err_t r32_mqtt_start(const r32_config_t *cfg);
bool r32_mqtt_is_connected(void);
void r32_mqtt_publish_status(void);
