#include "r32_config.h"

#include <string.h>

#include "argtable3/argtable3.h"
#include "esp_console.h"
#include "esp_log.h"
#include "esp_system.h"
#include "nvs.h"
#include "nvs_flash.h"

static const char *TAG = "r32_config";
static const char *NVS_NAMESPACE = "remo32";

static void copy_str(char *dst, size_t dst_size, const char *src)
{
    if (src == NULL) {
        dst[0] = '\0';
        return;
    }
    strncpy(dst, src, dst_size - 1);
    dst[dst_size - 1] = '\0';
}

static void load_str(nvs_handle_t handle, const char *key, char *dst, size_t dst_size,
                     const char *fallback)
{
    size_t len = dst_size;
    if (nvs_get_str(handle, key, dst, &len) != ESP_OK) {
        copy_str(dst, dst_size, fallback);
    }
}

esp_err_t r32_config_load(r32_config_t *out)
{
    memset(out, 0, sizeof(*out));
    /* Значения по умолчанию: устройство должно осмысленно вести себя даже
     * с чистым NVS — иначе первую настройку не сделать. */
    copy_str(out->device_id, sizeof(out->device_id), "esp32-main");
    copy_str(out->mqtt_prefix, sizeof(out->mqtt_prefix), "remo32");
    out->http_enabled = true;
    out->guard_grace_minutes = 10;
    out->guard_retry_minutes = 15;
    out->guard_max_attempts = 3;

    /* Значения по умолчанию — для «официальной» ESP32-S3 DevKitC-1:
     * кнопка BOOT на GPIO0, адресный светодиод на GPIO48. На другой плате
     * поправьте командой «pins» или по сети. */
    out->button_pin = 0;
    out->led_pin = 48;
    out->led_type = R32_LED_ADDRESSABLE;

    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READONLY, &handle);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        ESP_LOGW(TAG, "конфигурация не найдена, устройство не настроено");
        return ESP_OK;
    }
    if (err != ESP_OK) {
        return err;
    }

    load_str(handle, "device_id", out->device_id, sizeof(out->device_id), "esp32-main");
    load_str(handle, "ssid", out->wifi_ssid, sizeof(out->wifi_ssid), "");
    load_str(handle, "wifi_pass", out->wifi_password, sizeof(out->wifi_password), "");
    load_str(handle, "token", out->token, sizeof(out->token), "");
    load_str(handle, "mqtt_uri", out->mqtt_uri, sizeof(out->mqtt_uri), "");
    load_str(handle, "mqtt_user", out->mqtt_username, sizeof(out->mqtt_username), "");
    load_str(handle, "mqtt_pass", out->mqtt_password, sizeof(out->mqtt_password), "");
    load_str(handle, "mqtt_prefix", out->mqtt_prefix, sizeof(out->mqtt_prefix), "remo32");

    uint8_t http_enabled = 1;
    nvs_get_u8(handle, "http_en", &http_enabled);
    out->http_enabled = http_enabled != 0;

    load_str(handle, "g_host", out->guard_host, sizeof(out->guard_host), "");
    load_str(handle, "g_mac", out->guard_mac, sizeof(out->guard_mac), "");
    load_str(handle, "g_bcast", out->guard_broadcast, sizeof(out->guard_broadcast), "");

    uint8_t guard_enabled = 0;
    nvs_get_u8(handle, "g_en", &guard_enabled);
    out->guard_enabled = guard_enabled != 0;

    int32_t value = 0;
    if (nvs_get_i32(handle, "g_grace", &value) == ESP_OK) out->guard_grace_minutes = (int) value;
    if (nvs_get_i32(handle, "g_retry", &value) == ESP_OK) out->guard_retry_minutes = (int) value;
    if (nvs_get_i32(handle, "g_tries", &value) == ESP_OK) out->guard_max_attempts = (int) value;
    if (nvs_get_i32(handle, "btn_pin", &value) == ESP_OK) out->button_pin = (int) value;
    if (nvs_get_i32(handle, "led_pin", &value) == ESP_OK) out->led_pin = (int) value;
    if (nvs_get_i32(handle, "led_type", &value) == ESP_OK) out->led_type = (int) value;

    nvs_close(handle);
    return ESP_OK;
}

esp_err_t r32_config_save(const r32_config_t *cfg)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        return err;
    }

    nvs_set_str(handle, "device_id", cfg->device_id);
    nvs_set_str(handle, "ssid", cfg->wifi_ssid);
    nvs_set_str(handle, "wifi_pass", cfg->wifi_password);
    nvs_set_str(handle, "token", cfg->token);
    nvs_set_str(handle, "mqtt_uri", cfg->mqtt_uri);
    nvs_set_str(handle, "mqtt_user", cfg->mqtt_username);
    nvs_set_str(handle, "mqtt_pass", cfg->mqtt_password);
    nvs_set_str(handle, "mqtt_prefix", cfg->mqtt_prefix);
    nvs_set_u8(handle, "http_en", cfg->http_enabled ? 1 : 0);

    nvs_set_str(handle, "g_host", cfg->guard_host);
    nvs_set_str(handle, "g_mac", cfg->guard_mac);
    nvs_set_str(handle, "g_bcast", cfg->guard_broadcast);
    nvs_set_u8(handle, "g_en", cfg->guard_enabled ? 1 : 0);
    nvs_set_i32(handle, "g_grace", cfg->guard_grace_minutes);
    nvs_set_i32(handle, "g_retry", cfg->guard_retry_minutes);
    nvs_set_i32(handle, "g_tries", cfg->guard_max_attempts);
    nvs_set_i32(handle, "btn_pin", cfg->button_pin);
    nvs_set_i32(handle, "led_pin", cfg->led_pin);
    nvs_set_i32(handle, "led_type", cfg->led_type);

    err = nvs_commit(handle);
    nvs_close(handle);
    ESP_LOGI(TAG, "конфигурация сохранена");
    return err;
}

esp_err_t r32_config_erase(void)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        return err;
    }
    nvs_erase_all(handle);
    err = nvs_commit(handle);
    nvs_close(handle);
    ESP_LOGW(TAG, "конфигурация стёрта");
    return err;
}

bool r32_config_is_provisioned(const r32_config_t *cfg)
{
    return cfg->wifi_ssid[0] != '\0';
}

/* ------------------------------------------------------------------ консоль */

static r32_config_t *s_cfg = NULL;

static struct {
    struct arg_str *ssid;
    struct arg_str *password;
    struct arg_end *end;
} wifi_args;

static struct {
    struct arg_str *uri;
    struct arg_str *username;
    struct arg_str *password;
    struct arg_end *end;
} mqtt_args;

static struct {
    struct arg_str *value;
    struct arg_end *end;
} value_args;

static int cmd_wifi(int argc, char **argv)
{
    int errors = arg_parse(argc, argv, (void **) &wifi_args);
    if (errors != 0) {
        arg_print_errors(stderr, wifi_args.end, argv[0]);
        return 1;
    }
    copy_str(s_cfg->wifi_ssid, sizeof(s_cfg->wifi_ssid), wifi_args.ssid->sval[0]);
    copy_str(s_cfg->wifi_password, sizeof(s_cfg->wifi_password),
             wifi_args.password->count ? wifi_args.password->sval[0] : "");
    printf("Wi-Fi: SSID задан. Выполните save, затем restart\n");
    return 0;
}

static int cmd_mqtt(int argc, char **argv)
{
    int errors = arg_parse(argc, argv, (void **) &mqtt_args);
    if (errors != 0) {
        arg_print_errors(stderr, mqtt_args.end, argv[0]);
        return 1;
    }
    copy_str(s_cfg->mqtt_uri, sizeof(s_cfg->mqtt_uri), mqtt_args.uri->sval[0]);
    copy_str(s_cfg->mqtt_username, sizeof(s_cfg->mqtt_username),
             mqtt_args.username->count ? mqtt_args.username->sval[0] : "");
    copy_str(s_cfg->mqtt_password, sizeof(s_cfg->mqtt_password),
             mqtt_args.password->count ? mqtt_args.password->sval[0] : "");
    printf("MQTT: адрес задан. Выполните save, затем restart\n");
    return 0;
}

static int cmd_token(int argc, char **argv)
{
    if (arg_parse(argc, argv, (void **) &value_args) != 0) {
        arg_print_errors(stderr, value_args.end, argv[0]);
        return 1;
    }
    copy_str(s_cfg->token, sizeof(s_cfg->token), value_args.value->sval[0]);
    printf("токен задан (%d символов)\n", (int) strlen(s_cfg->token));
    return 0;
}

static int cmd_id(int argc, char **argv)
{
    if (arg_parse(argc, argv, (void **) &value_args) != 0) {
        arg_print_errors(stderr, value_args.end, argv[0]);
        return 1;
    }
    copy_str(s_cfg->device_id, sizeof(s_cfg->device_id), value_args.value->sval[0]);
    printf("идентификатор устройства: %s\n", s_cfg->device_id);
    return 0;
}

static int cmd_show(int argc, char **argv)
{
    (void) argc;
    (void) argv;
    printf("device_id   : %s\n", s_cfg->device_id);
    printf("wifi_ssid   : %s\n", s_cfg->wifi_ssid[0] ? s_cfg->wifi_ssid : "(не задан)");
    /* Пароли и токен не печатаем: консоль пишет в терминал, который могут
     * записывать. Показываем только факт наличия. */
    printf("wifi_pass   : %s\n", s_cfg->wifi_password[0] ? "(задан)" : "(пусто)");
    printf("token       : %s\n", s_cfg->token[0] ? "(задан)" : "(ПУСТО — небезопасно)");
    printf("mqtt_uri    : %s\n", s_cfg->mqtt_uri[0] ? s_cfg->mqtt_uri : "(выключен)");
    printf("mqtt_user   : %s\n", s_cfg->mqtt_username[0] ? s_cfg->mqtt_username : "(нет)");
    printf("mqtt_pass   : %s\n", s_cfg->mqtt_password[0] ? "(задан)" : "(пусто)");
    printf("mqtt_prefix : %s\n", s_cfg->mqtt_prefix);
    printf("http        : %s\n", s_cfg->http_enabled ? "включён" : "выключен");
    printf("сторож      : %s\n", s_cfg->guard_enabled ? "включён" : "выключен");
    if (s_cfg->guard_enabled) {
        printf("  ПК        : %s (%s)\n",
               s_cfg->guard_host[0] ? s_cfg->guard_host : "адрес не задан",
               s_cfg->guard_mac[0] ? s_cfg->guard_mac : "MAC не задан");
        printf("  ожидание  : %d мин, пауза %d мин, попыток %d\n",
               s_cfg->guard_grace_minutes, s_cfg->guard_retry_minutes,
               s_cfg->guard_max_attempts);
    }
    printf("  кнопка    : GPIO%d\n", s_cfg->button_pin);
    printf("  светодиод : GPIO%d (%s)\n", s_cfg->led_pin,
           s_cfg->led_type == 2 ? "адресный" : s_cfg->led_type == 1 ? "обычный" : "нет");
    return 0;
}

/* Выводы кнопки и светодиода.
 *
 * Плат ESP32-S3 много, и расходятся они именно здесь: у одних адресный
 * светодиод на GPIO48, у других на 38, у третьих его нет вовсе. Подобрать
 * вывод перепрошивкой — полчаса на попытку; командой — секунды.
 */
static struct {
    struct arg_str *what;
    struct arg_int *pin;
    struct arg_end *end;
} pins_args;

static int cmd_pins(int argc, char **argv)
{
    int errors = arg_parse(argc, argv, (void **) &pins_args);
    if (errors != 0) {
        arg_print_errors(stderr, pins_args.end, argv[0]);
        return 1;
    }

    const char *what = pins_args.what->sval[0];
    const int pin = pins_args.pin->count > 0 ? pins_args.pin->ival[0] : -1;

    if (strcmp(what, "button") == 0) {
        s_cfg->button_pin = pin;
        printf("кнопка: GPIO%d%s\n", pin, pin < 0 ? " (выключена)" : "");
    } else if (strcmp(what, "led") == 0) {
        s_cfg->led_pin = pin;
        printf("светодиод: GPIO%d%s\n", pin, pin < 0 ? " (выключен)" : "");
    } else if (strcmp(what, "led-type") == 0) {
        if (pin < 0 || pin > 2) {
            printf("тип: 0 — нет, 1 — обычный, 2 — адресный WS2812\n");
            return 1;
        }
        s_cfg->led_type = pin;
        printf("тип светодиода: %s\n",
               pin == 2 ? "адресный WS2812" : pin == 1 ? "обычный" : "нет");
    } else {
        printf("что именно: button, led или led-type\n");
        return 1;
    }

    printf("не забудьте save и restart\n");
    return 0;
}

static int cmd_save(int argc, char **argv)
{
    (void) argc;
    (void) argv;
    esp_err_t err = r32_config_save(s_cfg);
    printf(err == ESP_OK ? "сохранено\n" : "ошибка сохранения\n");
    return err == ESP_OK ? 0 : 1;
}

static int cmd_erase(int argc, char **argv)
{
    (void) argc;
    (void) argv;
    r32_config_erase();
    printf("конфигурация стёрта, выполните restart\n");
    return 0;
}

static int cmd_restart(int argc, char **argv)
{
    (void) argc;
    (void) argv;
    printf("перезагрузка…\n");
    esp_restart();
    return 0;
}

void r32_config_register_console(r32_config_t *cfg)
{
    s_cfg = cfg;

    wifi_args.ssid = arg_str1(NULL, NULL, "<ssid>", "имя сети Wi-Fi");
    wifi_args.password = arg_str0(NULL, NULL, "<password>", "пароль (можно опустить)");
    wifi_args.end = arg_end(2);
    const esp_console_cmd_t wifi_cmd = {
        .command = "wifi",
        .help = "Задать сеть Wi-Fi: wifi <ssid> [пароль]",
        .hint = NULL,
        .func = &cmd_wifi,
        .argtable = &wifi_args,
    };
    ESP_ERROR_CHECK(esp_console_cmd_register(&wifi_cmd));

    mqtt_args.uri = arg_str1(NULL, NULL, "<uri>", "например mqtts://broker:8883");
    mqtt_args.username = arg_str0(NULL, NULL, "<user>", "имя пользователя");
    mqtt_args.password = arg_str0(NULL, NULL, "<pass>", "пароль");
    mqtt_args.end = arg_end(3);
    const esp_console_cmd_t mqtt_cmd = {
        .command = "mqtt",
        .help = "Задать MQTT-брокер: mqtt <uri> [пользователь] [пароль]",
        .hint = NULL,
        .func = &cmd_mqtt,
        .argtable = &mqtt_args,
    };
    ESP_ERROR_CHECK(esp_console_cmd_register(&mqtt_cmd));

    value_args.value = arg_str1(NULL, NULL, "<значение>", "значение");
    value_args.end = arg_end(1);
    const esp_console_cmd_t token_cmd = {
        .command = "token",
        .help = "Задать общий токен с контроллером",
        .hint = NULL,
        .func = &cmd_token,
        .argtable = &value_args,
    };
    ESP_ERROR_CHECK(esp_console_cmd_register(&token_cmd));

    const esp_console_cmd_t id_cmd = {
        .command = "id",
        .help = "Задать идентификатор устройства",
        .hint = NULL,
        .func = &cmd_id,
        .argtable = &value_args,
    };
    ESP_ERROR_CHECK(esp_console_cmd_register(&id_cmd));

    const esp_console_cmd_t show_cmd = {
        .command = "show", .help = "Показать конфигурацию", .hint = NULL, .func = &cmd_show,
    };
    ESP_ERROR_CHECK(esp_console_cmd_register(&show_cmd));

    pins_args.what = arg_str1(NULL, NULL, "<что>", "button | led | led-type");
    pins_args.pin = arg_int1(NULL, NULL, "<номер>", "номер GPIO, -1 — выключить");
    pins_args.end = arg_end(2);
    const esp_console_cmd_t pins_cmd = {
        .command = "pins",
        .help = "Выводы кнопки и светодиода: pins button 0 | pins led 48 | pins led-type 2",
        .hint = NULL,
        .func = &cmd_pins,
        .argtable = &pins_args,
    };
    ESP_ERROR_CHECK(esp_console_cmd_register(&pins_cmd));

    const esp_console_cmd_t save_cmd = {
        .command = "save", .help = "Сохранить конфигурацию в NVS", .hint = NULL, .func = &cmd_save,
    };
    ESP_ERROR_CHECK(esp_console_cmd_register(&save_cmd));

    const esp_console_cmd_t erase_cmd = {
        .command = "erase", .help = "Стереть конфигурацию", .hint = NULL, .func = &cmd_erase,
    };
    ESP_ERROR_CHECK(esp_console_cmd_register(&erase_cmd));

    const esp_console_cmd_t restart_cmd = {
        .command = "restart", .help = "Перезагрузить устройство", .hint = NULL, .func = &cmd_restart,
    };
    ESP_ERROR_CHECK(esp_console_cmd_register(&restart_cmd));
}
