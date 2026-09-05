#include "r32_mqtt.h"

#include <stdlib.h>
#include <string.h>

#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mqtt_client.h"
#include "r32_proto.h"

static const char *TAG = "r32_mqtt";

static esp_mqtt_client_handle_t s_client = NULL;
static const r32_config_t *s_cfg = NULL;
static bool s_connected = false;

static char s_topic_cmd[160];
static char s_topic_reply[160];
static char s_topic_status[160];
static char s_topic_avail[160];

static void build_topics(const r32_config_t *cfg)
{
    snprintf(s_topic_cmd, sizeof(s_topic_cmd), "%s/%s/cmd", cfg->mqtt_prefix, cfg->device_id);
    snprintf(s_topic_reply, sizeof(s_topic_reply), "%s/%s/reply", cfg->mqtt_prefix, cfg->device_id);
    snprintf(s_topic_status, sizeof(s_topic_status), "%s/%s/status", cfg->mqtt_prefix,
             cfg->device_id);
    snprintf(s_topic_avail, sizeof(s_topic_avail), "%s/%s/availability", cfg->mqtt_prefix,
             cfg->device_id);
}

void r32_mqtt_publish_status(void)
{
    if (!s_connected || s_client == NULL) {
        return;
    }
    char *status = r32_proto_status_json(s_cfg);
    if (status == NULL) {
        return;
    }
    /* retain = 1: контроллер, подключившись позже, сразу увидит состояние,
     * не дожидаясь следующего периодического сообщения. */
    esp_mqtt_client_publish(s_client, s_topic_status, status, 0, 0, 1);
    free(status);
}

static void handle_command(const char *data, int len)
{
    char *request = malloc((size_t) len + 1);
    if (request == NULL) {
        ESP_LOGE(TAG, "не хватило памяти на команду");
        return;
    }
    memcpy(request, data, (size_t) len);
    request[len] = '\0';

    bool is_reboot = strstr(request, "\"reboot\"") != NULL;

    char *reply = r32_proto_handle(request, s_cfg);
    free(request);

    if (reply != NULL) {
        esp_mqtt_client_publish(s_client, s_topic_reply, reply, 0, 1, 0);
        free(reply);
    }

    if (is_reboot) {
        /* Даём ответу уйти в сеть до перезагрузки. */
        vTaskDelay(pdMS_TO_TICKS(500));
        esp_restart();
    }
}

static void mqtt_event_handler(void *args, esp_event_base_t base, int32_t event_id, void *data)
{
    (void) args;
    (void) base;
    esp_mqtt_event_handle_t event = (esp_mqtt_event_handle_t) data;

    switch ((esp_mqtt_event_id_t) event_id) {
    case MQTT_EVENT_CONNECTED:
        s_connected = true;
        ESP_LOGI(TAG, "подключено к брокеру, подписка на %s", s_topic_cmd);
        esp_mqtt_client_subscribe(s_client, s_topic_cmd, 1);
        esp_mqtt_client_publish(s_client, s_topic_avail, "online", 0, 1, 1);
        r32_mqtt_publish_status();
        break;

    case MQTT_EVENT_DISCONNECTED:
        s_connected = false;
        /* Библиотека переподключается сама с нарастающей паузой. */
        ESP_LOGW(TAG, "связь с брокером потеряна, ожидание переподключения");
        break;

    case MQTT_EVENT_DATA:
        if (event->data_len > 0) {
            handle_command(event->data, event->data_len);
        }
        break;

    case MQTT_EVENT_ERROR:
        ESP_LOGE(TAG, "ошибка MQTT");
        break;

    default:
        break;
    }
}

esp_err_t r32_mqtt_start(const r32_config_t *cfg)
{
    if (cfg->mqtt_uri[0] == '\0') {
        ESP_LOGI(TAG, "MQTT не настроен, пропускаем");
        return ESP_ERR_INVALID_STATE;
    }

    s_cfg = cfg;
    build_topics(cfg);

    esp_mqtt_client_config_t mqtt_cfg = {
        .broker.address.uri = cfg->mqtt_uri,
        .credentials.username = cfg->mqtt_username[0] ? cfg->mqtt_username : NULL,
        .credentials.authentication.password = cfg->mqtt_password[0] ? cfg->mqtt_password : NULL,
        .credentials.client_id = cfg->device_id,
        /* Последняя воля: если плата пропадёт, брокер сам объявит её
         * офлайном, и контроллер узнает об этом без таймаутов. */
        .session.last_will.topic = s_topic_avail,
        .session.last_will.msg = "offline",
        .session.last_will.qos = 1,
        .session.last_will.retain = 1,
        .session.keepalive = 30,
        .network.reconnect_timeout_ms = 5000,
        .network.timeout_ms = 10000,
    };

    s_client = esp_mqtt_client_init(&mqtt_cfg);
    if (s_client == NULL) {
        ESP_LOGE(TAG, "не удалось создать клиента MQTT");
        return ESP_FAIL;
    }

    ESP_ERROR_CHECK(esp_mqtt_client_register_event(s_client, ESP_EVENT_ANY_ID,
                                                    mqtt_event_handler, NULL));
    esp_err_t err = esp_mqtt_client_start(s_client);
    if (err == ESP_OK) {
        ESP_LOGI(TAG, "MQTT-клиент запущен, брокер %s", cfg->mqtt_uri);
    }
    return err;
}

bool r32_mqtt_is_connected(void)
{
    return s_connected;
}
