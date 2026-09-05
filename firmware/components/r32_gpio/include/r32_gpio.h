/* Работа с выводами платы.
 *
 * Раскладка задана таблицей в r32_gpio.c: менять её нужно там и только
 * там, чтобы схема подключения и прошивка не разъезжались.
 *
 * ВНИМАНИЕ: ни один вывод не проверен на живой плате. Перед подключением
 * к материнской плате компьютера сверьтесь с docs/HARDWARE.md.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>

#include "esp_err.h"

typedef enum {
    R32_PIN_UNUSED = 0,
    R32_PIN_INPUT,
    R32_PIN_OUTPUT,
} r32_pin_mode_t;

typedef struct {
    int pin;
    r32_pin_mode_t mode;
    const char *label;
} r32_pin_desc_t;

/* Настраивает все выводы из таблицы. */
esp_err_t r32_gpio_init(void);

/* Число описанных выводов и доступ к описанию по индексу. */
size_t r32_gpio_count(void);
const r32_pin_desc_t *r32_gpio_describe(size_t index);

/* Чтение входа. Возвращает ESP_ERR_NOT_FOUND, если вывод не описан. */
esp_err_t r32_gpio_read(int pin, bool *level);

/* Запись в выход. pulse_ms > 0 — импульс: выставить и вернуть обратно. */
esp_err_t r32_gpio_write(int pin, bool level, int pulse_ms);
