/* Конфигурация устройства, хранимая в NVS.
 *
 * Секретов в исходниках нет: SSID, пароль Wi-Fi, адрес брокера и токен
 * задаются через последовательный порт после первой прошивки и переживают
 * перепрошивку приложения (NVS — отдельный раздел).
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>

#include "esp_err.h"

#define R32_STR_MAX 128

typedef struct {
    char device_id[32];      /* идентификатор в топиках MQTT и в статусе */
    char wifi_ssid[R32_STR_MAX];
    char wifi_password[R32_STR_MAX];
    char token[R32_STR_MAX]; /* общий секрет с контроллером */
    char mqtt_uri[R32_STR_MAX];  /* например mqtts://broker:8883; пусто — MQTT выключен */
    char mqtt_username[R32_STR_MAX];
    char mqtt_password[R32_STR_MAX];
    char mqtt_prefix[32];
    bool http_enabled;       /* локальный HTTP-сервер в домашней сети */

    /* --- сторож основного ПК ---
     *
     * Контроллер живёт на основном ПК, поэтому сам себя разбудить не может:
     * если этот ПК умер, командовать плате некому. Сторож решает задачу без
     * чьего-либо участия — плата сама замечает пропажу и шлёт magic packet.
     */
    bool guard_enabled;
    char guard_host[64];        /* IP основного ПК в домашней сети */
    char guard_mac[24];         /* его MAC для magic packet */
    char guard_broadcast[64];   /* широковещательный адрес подсети */
    int guard_grace_minutes;    /* сколько ждать перед первой побудкой */
    int guard_retry_minutes;    /* пауза между попытками */
    int guard_max_attempts;     /* 0 — без ограничения */

    /* --- кнопка и светодиод ---
     *
     * Выводы задаются в настройках, а не в коде: плат ESP32-S3 много, и
     * они расходятся именно здесь. На «официальной» DevKitC-1 кнопка BOOT
     * сидит на GPIO0, а адресный светодиод — на GPIO48; на клонах (а у
     * автора как раз клон с мостом CH343) светодиод встречается и на
     * GPIO38, и вовсе отсутствует. Ошибиться выводом — значит молча не
     * получить ни нажатий, ни света, поэтому их можно менять по сети и
     * проверять, не перепрошивая плату.
     */
    int button_pin;             /* -1 — кнопка не используется */
    int led_pin;                /* -1 — светодиода нет */
    int led_type;               /* 0 — нет, 1 — обычный, 2 — адресный WS2812 */
} r32_config_t;

#define R32_LED_NONE 0
#define R32_LED_SIMPLE 1
#define R32_LED_ADDRESSABLE 2

/* Читает конфигурацию из NVS, подставляя значения по умолчанию. */
esp_err_t r32_config_load(r32_config_t *out);

/* Сохраняет конфигурацию в NVS. */
esp_err_t r32_config_save(const r32_config_t *cfg);

/* Стирает конфигурацию (возврат к заводскому состоянию). */
esp_err_t r32_config_erase(void);

/* Настроен ли Wi-Fi: без SSID подключаться некуда. */
bool r32_config_is_provisioned(const r32_config_t *cfg);

/* Регистрирует команды последовательной консоли: wifi, mqtt, token, id,
 * show, save, erase, restart. */
void r32_config_register_console(r32_config_t *cfg);
