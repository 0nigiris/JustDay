#include "r32_gpio.h"

#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "r32_gpio";

/* Раскладка выводов.
 *
 * Выбраны выводы, свободные на большинстве плат ESP32-S3 DevKit:
 * не заняты флешем, PSRAM, USB и загрузочными стропами.
 *
 * ВХОДЫ рассчитаны на подключение через оптрон к светодиоду питания ПК —
 * напрямую к материнской плате подключать нельзя (см. docs/HARDWARE.md).
 */
static const r32_pin_desc_t PINS[] = {
    {4,  R32_PIN_INPUT,  "Датчик питания ПК #1"},
    {5,  R32_PIN_INPUT,  "Датчик питания ПК #2"},
    {18, R32_PIN_OUTPUT, "Светодиод состояния"},
    {21, R32_PIN_OUTPUT, "Резерв (реле)"},
};

#define PIN_COUNT (sizeof(PINS) / sizeof(PINS[0]))

static const r32_pin_desc_t *find(int pin)
{
    for (size_t i = 0; i < PIN_COUNT; i++) {
        if (PINS[i].pin == pin) {
            return &PINS[i];
        }
    }
    return NULL;
}

esp_err_t r32_gpio_init(void)
{
    for (size_t i = 0; i < PIN_COUNT; i++) {
        gpio_config_t cfg = {
            .pin_bit_mask = 1ULL << PINS[i].pin,
            .intr_type = GPIO_INTR_DISABLE,
        };
        if (PINS[i].mode == R32_PIN_INPUT) {
            cfg.mode = GPIO_MODE_INPUT;
            /* Подтяжка вниз: без сигнала вход читается как «выключено»,
             * а не как случайный шум. */
            cfg.pull_down_en = GPIO_PULLDOWN_ENABLE;
            cfg.pull_up_en = GPIO_PULLUP_DISABLE;
        } else if (PINS[i].mode == R32_PIN_OUTPUT) {
            cfg.mode = GPIO_MODE_OUTPUT;
        } else {
            continue;
        }

        esp_err_t err = gpio_config(&cfg);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "не удалось настроить GPIO%d: %s", PINS[i].pin, esp_err_to_name(err));
            return err;
        }
        if (PINS[i].mode == R32_PIN_OUTPUT) {
            gpio_set_level(PINS[i].pin, 0);
        }
    }
    ESP_LOGI(TAG, "настроено выводов: %d", (int) PIN_COUNT);
    return ESP_OK;
}

size_t r32_gpio_count(void)
{
    return PIN_COUNT;
}

const r32_pin_desc_t *r32_gpio_describe(size_t index)
{
    return index < PIN_COUNT ? &PINS[index] : NULL;
}

esp_err_t r32_gpio_read(int pin, bool *level)
{
    const r32_pin_desc_t *desc = find(pin);
    if (desc == NULL || desc->mode == R32_PIN_UNUSED) {
        return ESP_ERR_NOT_FOUND;
    }
    *level = gpio_get_level(pin) != 0;
    return ESP_OK;
}

esp_err_t r32_gpio_write(int pin, bool level, int pulse_ms)
{
    const r32_pin_desc_t *desc = find(pin);
    if (desc == NULL) {
        return ESP_ERR_NOT_FOUND;
    }
    if (desc->mode != R32_PIN_OUTPUT) {
        return ESP_ERR_INVALID_ARG;
    }

    gpio_set_level(pin, level ? 1 : 0);
    if (pulse_ms > 0) {
        /* Импульс задаёт длительность нажатия — например, короткое
         * замыкание кнопки питания. Ограничиваем сверху, чтобы ошибка в
         * запросе не привела к удержанию кнопки навсегда. */
        if (pulse_ms > 10000) {
            pulse_ms = 10000;
        }
        vTaskDelay(pdMS_TO_TICKS(pulse_ms));
        gpio_set_level(pin, level ? 0 : 1);
    }
    return ESP_OK;
}
