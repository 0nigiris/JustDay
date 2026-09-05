#include "r32_proto.h"

#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "esp_app_desc.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "r32_gpio.h"
#include "r32_guard.h"
#include "r32_wifi.h"
#include "r32_wol.h"

static const char *TAG = "r32_proto";

#define PROTOCOL_VERSION 1

static const char *json_str(const cJSON *object, const char *key, const char *fallback)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(object, key);
    return cJSON_IsString(item) && item->valuestring != NULL ? item->valuestring : fallback;
}

static int json_int(const cJSON *object, const char *key, int fallback)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(object, key);
    return cJSON_IsNumber(item) ? item->valueint : fallback;
}

static cJSON *build_status_object(const r32_config_t *cfg)
{
    r32_wifi_status_t wifi;
    r32_wifi_get_status(&wifi);

    cJSON *status = cJSON_CreateObject();
    cJSON_AddStringToObject(status, "state", wifi.connected ? "online" : "connecting");
    cJSON_AddStringToObject(status, "device_id", cfg->device_id);

    const esp_app_desc_t *app = esp_app_get_description();
    cJSON_AddStringToObject(status, "firmware_version", app != NULL ? app->version : "unknown");

    /* Настоящее железо честно сообщает, что оно не симулятор. */
    cJSON_AddBoolToObject(status, "simulated", 0);
    cJSON_AddStringToObject(status, "chip", CONFIG_IDF_TARGET);
    cJSON_AddNumberToObject(status, "uptime_seconds",
                            (double) esp_timer_get_time() / 1000000.0);
    cJSON_AddNumberToObject(status, "free_heap_bytes", esp_get_free_heap_size());
    cJSON_AddNumberToObject(status, "min_free_heap_bytes", esp_get_minimum_free_heap_size());

    /* Прошивка собрана без PSRAM намеренно: см. sdkconfig.defaults. */
#ifdef CONFIG_SPIRAM
    cJSON_AddBoolToObject(status, "psram_present", 1);
#else
    cJSON_AddBoolToObject(status, "psram_present", 0);
#endif

    if (wifi.connected) {
        cJSON_AddNumberToObject(status, "wifi_rssi_dbm", wifi.rssi);
        cJSON_AddStringToObject(status, "wifi_ssid", wifi.ssid);
        cJSON_AddStringToObject(status, "ip_address", wifi.ip);
    } else {
        cJSON_AddNullToObject(status, "wifi_rssi_dbm");
        cJSON_AddNullToObject(status, "wifi_ssid");
        cJSON_AddNullToObject(status, "ip_address");
    }

    uint8_t mac[6] = {0};
    char mac_text[18];
    if (esp_read_mac(mac, ESP_MAC_WIFI_STA) == ESP_OK) {
        snprintf(mac_text, sizeof(mac_text), "%02x:%02x:%02x:%02x:%02x:%02x", mac[0], mac[1],
                 mac[2], mac[3], mac[4], mac[5]);
        cJSON_AddStringToObject(status, "mac_address", mac_text);
    }

    cJSON_AddNumberToObject(status, "reconnect_count", wifi.reconnect_count);

    cJSON *gpio = cJSON_AddArrayToObject(status, "gpio");
    for (size_t i = 0; i < r32_gpio_count(); i++) {
        const r32_pin_desc_t *desc = r32_gpio_describe(i);
        cJSON *entry = cJSON_CreateObject();
        cJSON_AddNumberToObject(entry, "pin", desc->pin);
        cJSON_AddStringToObject(entry, "mode",
                                desc->mode == R32_PIN_INPUT    ? "input"
                                : desc->mode == R32_PIN_OUTPUT ? "output"
                                                               : "unused");
        bool level = false;
        if (r32_gpio_read(desc->pin, &level) == ESP_OK) {
            cJSON_AddBoolToObject(entry, "level", level);
        } else {
            cJSON_AddNullToObject(entry, "level");
        }
        cJSON_AddStringToObject(entry, "label", desc->label);
        cJSON_AddItemToArray(gpio, entry);
    }

    /* Состояние сторожа: по нему видно, следит ли плата за основным ПК
     * и сколько раз ей уже приходилось его поднимать. */
    r32_guard_status_t guard;
    r32_guard_get_status(&guard);
    cJSON *guard_json = cJSON_AddObjectToObject(status, "guard");
    cJSON_AddStringToObject(guard_json, "state", r32_guard_state_name(guard.state));
    cJSON_AddBoolToObject(guard_json, "host_alive", guard.host_alive);
    cJSON_AddNumberToObject(guard_json, "attempts", guard.attempts);
    cJSON_AddNumberToObject(guard_json, "total_wakes", guard.total_wakes);

    cJSON *caps = cJSON_AddArrayToObject(status, "capabilities");
    cJSON_AddItemToArray(caps, cJSON_CreateString("wol"));
    cJSON_AddItemToArray(caps, cJSON_CreateString("gpio_in"));
    cJSON_AddItemToArray(caps, cJSON_CreateString("gpio_out"));
    cJSON_AddItemToArray(caps, cJSON_CreateString("status"));
    cJSON_AddItemToArray(caps, cJSON_CreateString("reboot"));
    cJSON_AddItemToArray(caps, cJSON_CreateString("guard"));
    /* "kvm" НЕ объявляем: физического переключателя нет. Контроллер по
     * отсутствию этой возможности честно откажет в переключении. */

    return status;
}

char *r32_proto_status_json(const r32_config_t *cfg)
{
    cJSON *status = build_status_object(cfg);
    char *text = cJSON_PrintUnformatted(status);
    cJSON_Delete(status);
    return text;
}

static char *make_reply(const char *command_id, bool ok, const char *error, cJSON *result,
                        cJSON *status)
{
    cJSON *reply = cJSON_CreateObject();
    cJSON_AddNumberToObject(reply, "protocol_version", PROTOCOL_VERSION);
    cJSON_AddStringToObject(reply, "command_id", command_id != NULL ? command_id : "");
    cJSON_AddBoolToObject(reply, "ok", ok);
    if (error != NULL) {
        cJSON_AddStringToObject(reply, "error", error);
    } else {
        cJSON_AddNullToObject(reply, "error");
    }
    if (status != NULL) {
        cJSON_AddItemToObject(reply, "status", status);
    } else {
        cJSON_AddNullToObject(reply, "status");
    }
    cJSON_AddItemToObject(reply, "result", result != NULL ? result : cJSON_CreateObject());

    char *text = cJSON_PrintUnformatted(reply);
    cJSON_Delete(reply);
    return text;
}

char *r32_proto_handle(const char *request_json, const r32_config_t *cfg)
{
    cJSON *request = cJSON_Parse(request_json);
    if (request == NULL) {
        return make_reply("", false, "некорректный JSON", NULL, NULL);
    }

    const char *command_id = json_str(request, "id", "");
    const char *type = json_str(request, "type", "");
    const cJSON *payload = cJSON_GetObjectItemCaseSensitive(request, "payload");

    char *reply = NULL;

    if (strcmp(type, "ping") == 0 || strcmp(type, "status") == 0) {
        reply = make_reply(command_id, true, NULL, NULL, build_status_object(cfg));

    } else if (strcmp(type, "wake_on_lan") == 0) {
        const char *mac = json_str(payload, "mac_address", NULL);
        if (mac == NULL) {
            reply = make_reply(command_id, false, "не указан mac_address", NULL, NULL);
        } else {
            const char *broadcast = json_str(payload, "broadcast_address", "255.255.255.255");
            int port = json_int(payload, "port", 9);
            int repeat = json_int(payload, "repeat", 3);
            esp_err_t err = r32_wol_send(mac, broadcast, port, repeat);
            if (err == ESP_OK) {
                cJSON *result = cJSON_CreateObject();
                cJSON_AddStringToObject(result, "mac_address", mac);
                cJSON_AddNumberToObject(result, "repeat", repeat);
                cJSON_AddBoolToObject(result, "simulated", 0);
                reply = make_reply(command_id, true, NULL, result, NULL);
            } else {
                reply = make_reply(command_id, false, esp_err_to_name(err), NULL, NULL);
            }
        }

    } else if (strcmp(type, "gpio_read") == 0) {
        int pin = json_int(payload, "pin", -1);
        bool level = false;
        esp_err_t err = r32_gpio_read(pin, &level);
        if (err == ESP_OK) {
            cJSON *result = cJSON_CreateObject();
            cJSON_AddNumberToObject(result, "pin", pin);
            cJSON_AddBoolToObject(result, "level", level);
            reply = make_reply(command_id, true, NULL, result, NULL);
        } else {
            reply = make_reply(command_id, false, "вывод не сконфигурирован", NULL, NULL);
        }

    } else if (strcmp(type, "gpio_write") == 0) {
        int pin = json_int(payload, "pin", -1);
        const cJSON *level_item = cJSON_GetObjectItemCaseSensitive(payload, "level");
        bool level = cJSON_IsTrue(level_item);
        int pulse_ms = json_int(payload, "pulse_ms", 0);
        esp_err_t err = r32_gpio_write(pin, level, pulse_ms);
        if (err == ESP_OK) {
            cJSON *result = cJSON_CreateObject();
            cJSON_AddNumberToObject(result, "pin", pin);
            cJSON_AddBoolToObject(result, "level", level);
            cJSON_AddNumberToObject(result, "pulse_ms", pulse_ms);
            reply = make_reply(command_id, true, NULL, result, NULL);
        } else {
            reply = make_reply(command_id, false, "вывод не настроен как выход", NULL, NULL);
        }

    } else if (strcmp(type, "kvm_switch") == 0) {
        /* Честный отказ: программа не может переключить монитор без
         * физического переключателя. */
        reply = make_reply(command_id, false, "физический KVM не подключён", NULL, NULL);

    } else if (strcmp(type, "guard_snooze") == 0) {
        /* Контроллер предупреждает о плановом выключении ПК, чтобы сторож
         * не принял его за аварию и не включил машину обратно. */
        cJSON *payload = cJSON_GetObjectItem(request, "payload");
        cJSON *minutes = payload ? cJSON_GetObjectItem(payload, "minutes") : NULL;
        if (!cJSON_IsNumber(minutes)) {
            reply = make_reply(command_id, false, "в команде отсутствует minutes", NULL, NULL);
        } else {
            r32_guard_snooze((int) minutes->valuedouble);
            cJSON *result = cJSON_CreateObject();
            cJSON_AddNumberToObject(result, "minutes", minutes->valuedouble);
            reply = make_reply(command_id, true, NULL, result, NULL);
        }

    } else if (strcmp(type, "reboot") == 0) {
        ESP_LOGW(TAG, "получена команда перезагрузки");
        reply = make_reply(command_id, true, NULL, NULL, NULL);
        /* Перезагружаемся не здесь: сначала ответ должен уйти. Этим
         * занимается вызывающий транспорт. */

    } else {
        reply = make_reply(command_id, false, "неизвестная команда", NULL, NULL);
    }

    cJSON_Delete(request);
    return reply;
}
