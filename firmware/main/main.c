/* Remo32 — прошивка аппаратного контроллера (ESP32-S3).
 *
 * Плата делает ровно две вещи: отправляет Wake-on-LAN в домашнюю сеть и
 * сообщает состояние выводов. Всё остальное — работа контроллера и агентов
 * на самих компьютерах. Это осознанное решение: чем меньше логики в
 * прошивке, тем реже придётся подходить к плате с проводом.
 *
 * PSRAM не используется. У платы автора встроенная память ESP32-S3
 * неисправна, и прошивка обязана работать без неё.
 */

#include <stdio.h>
#include <string.h>

#include "esp_console.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_task_wdt.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#include "r32_button.h"
#include "r32_config.h"
#include "r32_gpio.h"
#include "r32_guard.h"
#include "r32_http.h"
#include "r32_led.h"
#include "r32_mqtt.h"
#include "r32_proto.h"
#include "r32_wifi.h"

static const char *TAG = "remo32";

/* Как часто публиковать статус и кормить сторожевой таймер. */
#define HEARTBEAT_PERIOD_MS 10000
#define WIFI_WAIT_MS 30000

static r32_config_t s_config;

static void init_nvs(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        /* Раздел испорчен или от другой версии — стираем и начинаем заново.
         * Потеря настроек лучше, чем плата, которая не загружается. */
        ESP_LOGW(TAG, "раздел NVS повреждён, выполняется стирание");
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
}

static void start_console(void)
{
    esp_console_repl_t *repl = NULL;
    esp_console_repl_config_t repl_config = ESP_CONSOLE_REPL_CONFIG_DEFAULT();
    repl_config.prompt = "remo32>";
    repl_config.max_cmdline_length = 256;

    esp_console_dev_uart_config_t uart_config = ESP_CONSOLE_DEV_UART_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_console_new_repl_uart(&uart_config, &repl_config, &repl));

    esp_console_register_help_command();
    r32_config_register_console(&s_config);
    r32_guard_register_console(&s_config);

    ESP_ERROR_CHECK(esp_console_start_repl(repl));
}

/* --- кнопка на плате ------------------------------------------------------
 *
 * Единственный способ управлять платой, когда телефона под рукой нет, а
 * компьютер выключен — то есть ровно в той ситуации, ради которой плата и
 * существует. Кнопка одна: вторая на DevKit замкнута на сброс чипа
 * физически, и прошивка её не видит.
 */

static void on_button_short(void)
{
    esp_err_t err = r32_guard_wake_now();
    /* Отклик светом обязателен: сама побудка — это пакет в сеть, и без
     * него нажатие вообще ничем не проявляется. Человек жмёт второй раз,
     * третий, и решает, что кнопка не работает. */
    r32_led_blip(err == ESP_OK);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "кнопка: разбудить не вышло: %s", esp_err_to_name(err));
    }
}

static void on_button_long(void)
{
    const bool enabled = r32_guard_toggle_enabled();
    r32_led_blip(true);
    ESP_LOGW(TAG, "кнопка: слежка %s", enabled ? "включена" : "выключена");
}

static void heartbeat_task(void *arg)
{
    (void) arg;

    /* Задача подписана на сторожевой таймер: если она зависнет — например,
     * из-за взаимной блокировки в сетевом стеке — плата перезагрузится. */
    ESP_ERROR_CHECK(esp_task_wdt_add(NULL));

    while (true) {
        esp_task_wdt_reset();

        r32_wifi_status_t wifi;
        r32_wifi_get_status(&wifi);
        ESP_LOGI(TAG, "состояние: Wi-Fi %s (%s, %d дБм), MQTT %s, свободно %lu байт",
                 wifi.connected ? "подключён" : "нет связи", wifi.ip, wifi.rssi,
                 r32_mqtt_is_connected() ? "подключён" : "нет связи",
                 (unsigned long) esp_get_free_heap_size());

        r32_guard_status_t guard;
        r32_guard_get_status(&guard);
        if (guard.state != R32_GUARD_DISABLED) {
            ESP_LOGI(TAG, "сторож: %s, побудок %d",
                     r32_guard_state_name(guard.state), guard.total_wakes);
        }

        /* Свет обновляем здесь же, а не в самом стороже: состояние платы
         * складывается из нескольких вещей, и первой идёт сеть. Плата без
         * Wi-Fi не разбудит ПК, что бы ни думал сторож. */
        if (!wifi.connected) {
            r32_led_set(R32_LED_NO_NETWORK);
        } else {
            switch (guard.state) {
            case R32_GUARD_DISABLED: r32_led_set(R32_LED_OFF); break;
            case R32_GUARD_MISSING:  r32_led_set(R32_LED_MISSING); break;
            case R32_GUARD_WAKING:
            case R32_GUARD_GAVE_UP:  r32_led_set(R32_LED_WAKING); break;
            default:                 r32_led_set(R32_LED_WATCHING); break;
            }
        }

        r32_mqtt_publish_status();
        vTaskDelay(pdMS_TO_TICKS(HEARTBEAT_PERIOD_MS));
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "Remo32 firmware, чип %s", CONFIG_IDF_TARGET);
#ifdef CONFIG_SPIRAM
    ESP_LOGW(TAG, "PSRAM ВКЛЮЧЁН в конфигурации — на этой плате он может быть неисправен");
#else
    ESP_LOGI(TAG, "PSRAM не используется (так и задумано)");
#endif

    init_nvs();
    ESP_ERROR_CHECK(r32_config_load(&s_config));
    ESP_ERROR_CHECK(r32_gpio_init());

    /* Индикацию поднимаем раньше всего остального: на ненастроенной плате
     * это единственный признак жизни — консоль требует провода, сети ещё
     * нет, а понять «включилась ли она вообще» надо сразу. */
    r32_led_start(s_config.led_pin, s_config.led_type);
    r32_led_set(R32_LED_NOT_CONFIGURED);

    /* Консоль поднимаем всегда и до сети: если Wi-Fi не настроен или
     * настроен неверно, единственный способ это исправить — провод. */
    start_console();

    if (!r32_config_is_provisioned(&s_config)) {
        ESP_LOGW(TAG, "устройство не настроено. Выполните в консоли:");
        ESP_LOGW(TAG, "  wifi <ssid> <пароль>");
        ESP_LOGW(TAG, "  token <общий-секрет-с-контроллером>");
        ESP_LOGW(TAG, "  mqtt mqtts://брокер:8883 <пользователь> <пароль>   (необязательно)");
        ESP_LOGW(TAG, "  save");
        ESP_LOGW(TAG, "  restart");
        /* Не выходим: консоль работает, плата ждёт настройки. */
        return;
    }

    if (s_config.token[0] == '\0') {
        ESP_LOGE(TAG, "ТОКЕН НЕ ЗАДАН. Сетевые интерфейсы будут отклонять все запросы. "
                      "Задайте: token <значение>, затем save и restart");
    }

    ESP_ERROR_CHECK(r32_wifi_start(&s_config));

    if (!r32_wifi_wait_connected(WIFI_WAIT_MS)) {
        /* Не считаем это ошибкой: подключение продолжится в фоне, а
         * службы поднимем сразу — они начнут работать, как только связь
         * появится. */
        ESP_LOGW(TAG, "Wi-Fi пока не подключился, продолжаем в фоне");
    }

    if (s_config.http_enabled) {
        esp_err_t err = r32_http_start(&s_config);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "HTTP-сервер не запустился: %s", esp_err_to_name(err));
        }
    }

    r32_mqtt_start(&s_config); /* отсутствие MQTT — не ошибка */

    /* Сторож поднимается последним: к этому моменту сеть уже работает.
     * Задача создаётся даже при выключенном стороже — чтобы его можно
     * было включить командой, не перезагружая плату. */
    esp_err_t guard_err = r32_guard_start(&s_config);
    if (guard_err != ESP_OK) {
        ESP_LOGE(TAG, "сторож не запустился: %s", esp_err_to_name(guard_err));
    }

    /* Кнопку поднимаем после сторожа: её обработчики берут из него и
     * адрес для побудки, и признак слежки. */
    esp_err_t button_err = r32_button_start(s_config.button_pin,
                                            on_button_short, on_button_long);
    if (button_err != ESP_OK) {
        ESP_LOGE(TAG, "кнопка не заработала: %s", esp_err_to_name(button_err));
    }

    xTaskCreate(heartbeat_task, "heartbeat", 4096, NULL, 4, NULL);
    ESP_LOGI(TAG, "инициализация завершена");
}
