#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Сколько держать, чтобы нажатие считалось долгим. */
#define R32_BUTTON_LONG_PRESS_MS 3000

typedef void (*r32_button_handler_t)(void);

/* Что кнопка видела с момента включения платы.
 *
 * Отдаётся в /status и существует ровно ради одного вопроса: «нажатие
 * вообще доходит до платы?». Консоль подключена по USB, а плата живёт на
 * стене — без этих чисел «кнопка не работает» невозможно отличить от «не
 * тот вывод» или «сигнал есть, а обработчик молчит».
 */
typedef struct {
    bool configured;         /* кнопка вообще включена в настройках */
    int pin;
    bool pressed_now;        /* уровень прямо сейчас */
    int level_changes;       /* сколько раз уровень менялся: главный признак */
    int short_presses;
    int long_presses;
    int64_t last_change_ms;  /* аптайм платы на момент последнего изменения */
} r32_button_status_t;

/* Запускает опрос кнопки на указанном выводе. pin < 0 — кнопка выключена. */
esp_err_t r32_button_start(int pin, r32_button_handler_t on_short, r32_button_handler_t on_long);

void r32_button_get_status(r32_button_status_t *out);

#ifdef __cplusplus
}
#endif
