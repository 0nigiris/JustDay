#include "r32_button.h"

#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "r32_button";

/* Опрос вместо прерывания. Кнопку нажимает человек, пятьдесят раз в
 * секунду более чем достаточно, а обработчики отсюда ходят в сеть — из
 * прерывания так нельзя. Заодно это и подавление дребезга: чтобы
 * состояние считалось изменившимся, оно должно повториться дважды подряд. */
#define POLL_PERIOD_MS 20
#define DEBOUNCE_SAMPLES 2

static r32_button_handler_t s_on_short = NULL;
static r32_button_handler_t s_on_long = NULL;
static r32_button_status_t s_status = {0};

static void button_task(void *arg)
{
    (void) arg;

    bool stable = false;      /* подтверждённое состояние: true — нажата */
    int same_count = 0;       /* сколько раз подряд увидели новое состояние */
    int64_t pressed_at_us = 0;
    bool long_fired = false;  /* долгое уже сработало, отпускание игнорируем */

    while (true) {
        /* Кнопка замыкает вывод на землю: ноль означает «нажата». */
        const bool raw = gpio_get_level(s_status.pin) == 0;
        s_status.pressed_now = raw;

        if (raw != stable) {
            if (++same_count >= DEBOUNCE_SAMPLES) {
                stable = raw;
                same_count = 0;

                /* Считаем ЛЮБОЕ изменение уровня, ещё до разбора коротких и
                 * долгих нажатий. Если это число стоит на месте, значит до
                 * платы не доходит сам сигнал — дело в выводе или в кнопке,
                 * и искать ошибку в логике бесполезно. */
                s_status.level_changes++;
                s_status.last_change_ms = esp_timer_get_time() / 1000;

                if (stable) {
                    pressed_at_us = esp_timer_get_time();
                    long_fired = false;
                } else if (!long_fired) {
                    const int64_t held_ms = (esp_timer_get_time() - pressed_at_us) / 1000;
                    s_status.short_presses++;
                    ESP_LOGI(TAG, "короткое нажатие (%lld мс)", held_ms);
                    if (s_on_short) {
                        s_on_short();
                    }
                }
            }
        } else {
            same_count = 0;

            /* Долгое нажатие срабатывает, не дожидаясь отпускания: так
             * человек по реакции платы понимает, что держал достаточно. */
            if (stable && !long_fired
                && (esp_timer_get_time() - pressed_at_us) / 1000 >= R32_BUTTON_LONG_PRESS_MS) {
                long_fired = true;
                s_status.long_presses++;
                ESP_LOGI(TAG, "долгое нажатие");
                if (s_on_long) {
                    s_on_long();
                }
            }
        }

        vTaskDelay(pdMS_TO_TICKS(POLL_PERIOD_MS));
    }
}

esp_err_t r32_button_start(int pin, r32_button_handler_t on_short, r32_button_handler_t on_long)
{
    if (pin < 0) {
        ESP_LOGI(TAG, "кнопка выключена в настройках");
        s_status.configured = false;
        s_status.pin = -1;
        return ESP_OK;
    }

    s_on_short = on_short;
    s_on_long = on_long;
    s_status.pin = pin;

    const gpio_config_t cfg = {
        .pin_bit_mask = 1ULL << pin,
        .mode = GPIO_MODE_INPUT,
        /* Подтяжка вверх обязательна: кнопка умеет только замыкать вывод
         * на землю, без подтяжки отпущенная кнопка читалась бы как шум. */
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    esp_err_t err = gpio_config(&cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "не удалось настроить GPIO%d: %s", pin, esp_err_to_name(err));
        return err;
    }

    s_status.configured = true;
    s_status.pressed_now = gpio_get_level(pin) == 0;

    /* Задача маленькая, но обработчики отправляют пакеты — стек берём с
     * запасом, иначе первое же нажатие уронит плату. */
    if (xTaskCreate(button_task, "button", 4096, NULL, 5, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "кнопка на GPIO%d (сейчас %s): коротко — включить ПК, держать %d с — сторож",
             pin, s_status.pressed_now ? "НАЖАТА" : "отпущена",
             R32_BUTTON_LONG_PRESS_MS / 1000);
    return ESP_OK;
}

void r32_button_get_status(r32_button_status_t *out)
{
    if (out) {
        *out = s_status;
    }
}
