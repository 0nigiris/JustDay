/* Подключение к Wi-Fi с автоматическим восстановлением связи.
 *
 * Плата стоит дома без присмотра: роутер может перезагрузиться, связь
 * пропасть. Прошивка обязана вернуться в сеть сама, без нажатия кнопок.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "r32_config.h"

typedef struct {
    bool connected;
    int8_t rssi;
    char ssid[33];
    char ip[16];
    uint32_t reconnect_count;
} r32_wifi_status_t;

/* Запускает Wi-Fi и подключение. Возврат не означает, что связь есть:
 * подключение идёт в фоне и восстанавливается автоматически. */
esp_err_t r32_wifi_start(const r32_config_t *cfg);

/* Ждёт подключения не дольше указанного времени. */
bool r32_wifi_wait_connected(uint32_t timeout_ms);

void r32_wifi_get_status(r32_wifi_status_t *out);
