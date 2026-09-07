#include "r32_button.h"

#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "r32_button";

/* Опрос вместо прерывания. Кнопку нажимает человек, десять раз в секунду
 * более чем достаточно, а обработчики отсюда ходят в сеть — из прерывания
 * так нельзя. Заодно это и подавление дребезга: чтобы состояние считалось
 * изменившимся, оно должно повториться дважды подряд. */
#define POLL_PERIOD_MS 20
#define DEBOUNCE_SAMPLES 2

static r32_button_handler_t s_on_short = NULL;
static r32_button_handler_t s_on_long = NULL;

static void button_task(void *arg)
{
    (void) arg;

    bool stable = false;      /* подтверждённое состояние: true — нажата */
    int same_count = 0;       /* сколько раз подряд увидели новое состояние */
    int64_t pressed_at_us = 0;
    bool long_fired = false;  /* долгое уже сработало, отпускание игнорируем */

    while (true) {
        /* Кнопка замыкает вывод на землю: ноль означает «нажата». */
        const bool raw = gpio_get_level(R32_BUTTON_GPIO) == 0;

        if (raw != stable) {
            if (++same_count >= DEBOUNCE_SAMPLES) {
                stable = raw;
                same_count = 0;

                if (stable) {
                    pressed_at_us = esp_timer_get_time();
                    long_fired = false;
                } else if (!long_fired) {
                    const int64_t held_ms = (esp_timer_get_time() - pressed_at_us) / 1000;
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
                ESP_LOGI(TAG, "долгое нажатие");
                if (s_on_long) {
                    s_on_long();
                }
            }
        }

        vTaskDelay(pdMS_TO_TICKS(POLL_PERIOD_MS));
    }
}

esp_err_t r32_button_start(r32_button_handler_t on_short, r32_button_handler_t on_long)
{
    s_on_short = on_short;
    s_on_long = on_long;

    const gpio_config_t cfg = {
        .pin_bit_mask = 1ULL << R32_BUTTON_GPIO,
        .mode = GPIO_MODE_INPUT,
        /* Подтяжка вверх обязательна: кнопка умеет только замыкать вывод
         * на землю, без подтяжки отпущенная кнопка читалась бы как шум. */
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    esp_err_t err = gpio_config(&cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "не удалось настроить GPIO%d: %s", R32_BUTTON_GPIO, esp_err_to_name(err));
        return err;
    }

    /* Задача маленькая, но обработчики отправляют пакеты — стек берём с
     * запасом, иначе первое же нажатие уронит плату. */
    if (xTaskCreate(button_task, "button", 4096, NULL, 5, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "кнопка на GPIO%d: коротко — включить ПК, держать %d с — выключить сторожа",
             R32_BUTTON_GPIO, R32_BUTTON_LONG_PRESS_MS / 1000);
    return ESP_OK;
}
