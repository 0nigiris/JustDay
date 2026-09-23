/* Разбор команд и сборка ответов.
 *
 * Один и тот же обработчик используется и HTTP-сервером, и MQTT-клиентом:
 * протокол не зависит от транспорта — ровно как на стороне контроллера.
 */
#pragma once

#include "esp_err.h"
#include "r32_config.h"

/* Обрабатывает команду в виде JSON и возвращает JSON-ответ.
 * Возвращённую строку освобождает вызывающий через free(). */
char *r32_proto_handle(const char *request_json, const r32_config_t *cfg);

/* Строит JSON статуса устройства (для ретейн-топика и ручки /status). */
char *r32_proto_status_json(const r32_config_t *cfg);
