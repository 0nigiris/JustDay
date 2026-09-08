/* Индикация состояния платы.
 *
 * Поддерживаются два вида светодиодов, потому что на платах ESP32-S3
 * встречаются оба: обычный, включаемый уровнем, и адресный WS2812, который
 * умеет цвет. Драйвер WS2812 здесь свой, на RMT: готовый компонент
 * led_strip пришлось бы тянуть из сети при каждой сборке, а протокол —
 * это два разных импульса и пауза.
 *
 * Яркость намеренно низкая. Плата висит в комнате, где спят; светодиод,
 * освещающий потолок, выключат физически — и он перестанет что-либо
 * показывать.
 */

#include "r32_led.h"

#include <string.h>

#include "driver/gpio.h"
#include "driver/rmt_tx.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "r32_config.h"

static const char *TAG = "r32_led";

#define RMT_RESOLUTION_HZ 10000000  /* 10 МГц: один тик = 0.1 мкс */
#define TICK_NS 100

static int s_pin = -1;
static int s_type = R32_LED_NONE;
static r32_led_state_t s_state = R32_LED_NOT_CONFIGURED;
static volatile int s_blip = 0;      /* 0 — нет, 1 — успех, -1 — отказ */

static rmt_channel_handle_t s_channel = NULL;
static rmt_encoder_handle_t s_encoder = NULL;

/* --- WS2812 -------------------------------------------------------------
 *
 * Бит кодируется длиной импульса: единица — длинный высокий и короткий
 * низкий, ноль — наоборот. Цифры взяты из документации на WS2812B
 * (T0H 0.4 мкс, T1H 0.8 мкс, период около 1.25 мкс) и сознательно
 * округлены: чип терпит заметный разброс, а точные значения у клонов
 * всё равно свои.
 */
static esp_err_t ws2812_init(int pin)
{
    rmt_tx_channel_config_t tx_config = {
        .gpio_num = pin,
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = RMT_RESOLUTION_HZ,
        .mem_block_symbols = 64,
        .trans_queue_depth = 4,
    };
    esp_err_t err = rmt_new_tx_channel(&tx_config, &s_channel);
    if (err != ESP_OK) {
        return err;
    }

    rmt_bytes_encoder_config_t bytes_config = {
        .bit0 = {
            .level0 = 1, .duration0 = 400 / TICK_NS,
            .level1 = 0, .duration1 = 850 / TICK_NS,
        },
        .bit1 = {
            .level0 = 1, .duration0 = 800 / TICK_NS,
            .level1 = 0, .duration1 = 450 / TICK_NS,
        },
        .flags.msb_first = 1,
    };
    err = rmt_new_bytes_encoder(&bytes_config, &s_encoder);
    if (err != ESP_OK) {
        return err;
    }
    return rmt_enable(s_channel);
}

static void ws2812_write(uint8_t r, uint8_t g, uint8_t b)
{
    /* Порядок именно GRB — так устроен сам чип. */
    const uint8_t grb[3] = {g, r, b};
    rmt_transmit_config_t tx = {.loop_count = 0};
    rmt_transmit(s_channel, s_encoder, grb, sizeof(grb), &tx);
    rmt_tx_wait_all_done(s_channel, 100);
}

/* --- общий вывод -------------------------------------------------------- */

static void show(uint8_t r, uint8_t g, uint8_t b)
{
    if (s_type == R32_LED_ADDRESSABLE) {
        ws2812_write(r, g, b);
    } else if (s_type == R32_LED_SIMPLE) {
        /* Обычный светодиод цвета не знает: горит, если яркость есть. */
        gpio_set_level(s_pin, (r || g || b) ? 1 : 0);
    }
}

static void off(void)
{
    show(0, 0, 0);
}

/* Один «вдох»: короткая вспышка заданного цвета и пауза.
 *
 * Мигание, а не постоянное свечение: постоянно горящий светодиод в тёмной
 * комнате раздражает и через неделю оказывается заклеен изолентой.
 */
static void pulse(uint8_t r, uint8_t g, uint8_t b, int on_ms, int off_ms)
{
    show(r, g, b);
    vTaskDelay(pdMS_TO_TICKS(on_ms));
    off();
    vTaskDelay(pdMS_TO_TICKS(off_ms));
}

static void led_task(void *arg)
{
    (void) arg;

    while (true) {
        /* Отклик на нажатие важнее фонового состояния: человек только что
         * нажал и ждёт ответа именно сейчас. */
        const int blip = s_blip;
        if (blip != 0) {
            s_blip = 0;
            for (int i = 0; i < 2; i++) {
                if (blip > 0) {
                    pulse(40, 40, 40, 60, 60);   /* белый — принято */
                } else {
                    pulse(60, 0, 0, 60, 60);     /* красный — не вышло */
                }
            }
            continue;
        }

        switch (s_state) {
        case R32_LED_WATCHING:
            /* Раз в пять секунд, еле заметно: «я тут, всё хорошо». */
            pulse(0, 12, 0, 40, 4960);
            break;
        case R32_LED_MISSING:
            /* ПК пропал, идёт отсчёт — жёлтый, чаще. */
            pulse(20, 12, 0, 120, 880);
            break;
        case R32_LED_WAKING:
            /* Побудка: единственное состояние, которое видно издалека. */
            pulse(40, 0, 0, 120, 200);
            break;
        case R32_LED_NO_NETWORK:
            /* Нет Wi-Fi — плата бесполезна, и это должно быть заметно. */
            pulse(30, 8, 0, 300, 300);
            break;
        case R32_LED_NOT_CONFIGURED:
            pulse(0, 0, 30, 500, 500);   /* синий: ждём настройки */
            break;
        case R32_LED_OFF:
        default:
            /* Слежка выключена. Не гасим совсем: иначе выключенный сторож
             * не отличить от мёртвой платы, а это ровно та ошибка, из-за
             * которой однажды не проснётся компьютер. */
            pulse(6, 0, 12, 30, 9970);
            break;
        }
    }
}

esp_err_t r32_led_start(int pin, int type)
{
    if (pin < 0 || type == R32_LED_NONE) {
        ESP_LOGI(TAG, "светодиод выключен в настройках");
        s_type = R32_LED_NONE;
        return ESP_OK;
    }

    s_pin = pin;
    s_type = type;

    if (type == R32_LED_ADDRESSABLE) {
        esp_err_t err = ws2812_init(pin);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "WS2812 на GPIO%d не поднялся: %s", pin, esp_err_to_name(err));
            s_type = R32_LED_NONE;
            return err;
        }
    } else {
        const gpio_config_t cfg = {
            .pin_bit_mask = 1ULL << pin,
            .mode = GPIO_MODE_OUTPUT,
            .pull_up_en = GPIO_PULLUP_DISABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        esp_err_t err = gpio_config(&cfg);
        if (err != ESP_OK) {
            return err;
        }
    }

    off();

    if (xTaskCreate(led_task, "led", 3072, NULL, 3, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "индикация на GPIO%d (%s)", pin,
             type == R32_LED_ADDRESSABLE ? "адресный" : "обычный");
    return ESP_OK;
}

void r32_led_set(r32_led_state_t state)
{
    s_state = state;
}

void r32_led_blip(bool success)
{
    s_blip = success ? 1 : -1;
}
