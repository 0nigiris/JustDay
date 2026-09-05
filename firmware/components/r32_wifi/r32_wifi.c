#include "r32_wifi.h"

#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"

static const char *TAG = "r32_wifi";

#define WIFI_CONNECTED_BIT BIT0

/* Пауза перед повторным подключением растёт, чтобы не молотить эфир, если
 * роутер выключен надолго. Верхний предел — минута. */
#define RETRY_MIN_MS 1000
#define RETRY_MAX_MS 60000

static EventGroupHandle_t s_events;
static uint32_t s_retry_delay_ms = RETRY_MIN_MS;
static uint32_t s_reconnects;
static char s_ssid[33];
static char s_ip[16] = "0.0.0.0";

static void reconnect_task(void *arg)
{
    (void) arg;
    vTaskDelay(pdMS_TO_TICKS(s_retry_delay_ms));
    ESP_LOGI(TAG, "повторное подключение к Wi-Fi");
    esp_wifi_connect();
    vTaskDelete(NULL);
}

static void on_wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void) arg;
    (void) base;

    if (id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
        return;
    }

    if (id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_event_sta_disconnected_t *event = (wifi_event_sta_disconnected_t *) data;
        xEventGroupClearBits(s_events, WIFI_CONNECTED_BIT);
        strcpy(s_ip, "0.0.0.0");
        ESP_LOGW(TAG, "связь потеряна (причина %d), повтор через %lu мс", event->reason,
                 (unsigned long) s_retry_delay_ms);
        s_reconnects++;
        /* Отдельная задача, потому что из обработчика события нельзя
         * блокироваться на время паузы. */
        xTaskCreate(reconnect_task, "wifi_retry", 2048, NULL, 5, NULL);
        s_retry_delay_ms = s_retry_delay_ms * 2;
        if (s_retry_delay_ms > RETRY_MAX_MS) {
            s_retry_delay_ms = RETRY_MAX_MS;
        }
    }
}

static void on_ip_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void) arg;
    (void) base;

    if (id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *) data;
        snprintf(s_ip, sizeof(s_ip), IPSTR, IP2STR(&event->ip_info.ip));
        /* Успех сбрасывает паузу: следующий обрыв снова начнём с секунды. */
        s_retry_delay_ms = RETRY_MIN_MS;
        xEventGroupSetBits(s_events, WIFI_CONNECTED_BIT);
        ESP_LOGI(TAG, "подключено, адрес %s", s_ip);
    }
}

esp_err_t r32_wifi_start(const r32_config_t *cfg)
{
    if (!r32_config_is_provisioned(cfg)) {
        ESP_LOGW(TAG, "Wi-Fi не настроен: задайте сеть командой 'wifi <ssid> <пароль>'");
        return ESP_ERR_INVALID_STATE;
    }

    s_events = xEventGroupCreate();
    strncpy(s_ssid, cfg->wifi_ssid, sizeof(s_ssid) - 1);

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init_cfg));

    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                        &on_wifi_event, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                        &on_ip_event, NULL, NULL));

    wifi_config_t wifi_cfg = {0};
    strncpy((char *) wifi_cfg.sta.ssid, cfg->wifi_ssid, sizeof(wifi_cfg.sta.ssid) - 1);
    strncpy((char *) wifi_cfg.sta.password, cfg->wifi_password,
            sizeof(wifi_cfg.sta.password) - 1);
    wifi_cfg.sta.threshold.authmode = WIFI_AUTH_OPEN;
    wifi_cfg.sta.pmf_cfg.capable = true;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg));
    /* Без энергосбережения: задержка ответа важнее экономии, устройство
     * питается от адаптера. */
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "Wi-Fi запущен, сеть «%s»", cfg->wifi_ssid);
    return ESP_OK;
}

bool r32_wifi_wait_connected(uint32_t timeout_ms)
{
    if (s_events == NULL) {
        return false;
    }
    EventBits_t bits = xEventGroupWaitBits(s_events, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE,
                                           pdMS_TO_TICKS(timeout_ms));
    return (bits & WIFI_CONNECTED_BIT) != 0;
}

void r32_wifi_get_status(r32_wifi_status_t *out)
{
    memset(out, 0, sizeof(*out));
    out->reconnect_count = s_reconnects;
    strncpy(out->ssid, s_ssid, sizeof(out->ssid) - 1);
    strncpy(out->ip, s_ip, sizeof(out->ip) - 1);

    if (s_events == NULL) {
        return;
    }
    out->connected = (xEventGroupGetBits(s_events) & WIFI_CONNECTED_BIT) != 0;

    wifi_ap_record_t ap;
    if (out->connected && esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
        out->rssi = ap.rssi;
    }
}
