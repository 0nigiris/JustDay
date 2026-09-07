#include "r32_guard.h"

#include <string.h>

#include "argtable3/argtable3.h"
#include "esp_console.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "ping/ping_sock.h"

#include "r32_wifi.h"
#include "r32_wol.h"

static const char *TAG = "r32_guard";

#define CHECK_PERIOD_MS 30000  /* как часто проверять ПК */
#define PING_TIMEOUT_MS 1500
#define PING_COUNT 3           /* один потерянный пакет — ещё не пропажа */

static r32_config_t *s_cfg = NULL;
static r32_guard_status_t s_status = {
    .state = R32_GUARD_DISABLED,
    .last_seen_ms = -1,
};
static SemaphoreHandle_t s_lock = NULL;

/* --------------------------------------------------------------- пинг */

typedef struct {
    SemaphoreHandle_t done;
    uint32_t received;
} ping_result_t;

static void on_ping_success(esp_ping_handle_t handle, void *args)
{
    ping_result_t *result = (ping_result_t *) args;
    result->received++;
}

static void on_ping_end(esp_ping_handle_t handle, void *args)
{
    ping_result_t *result = (ping_result_t *) args;
    xSemaphoreGive(result->done);
}

/* Отвечает ли хост. Пустой адрес считаем «не отвечает»: это ошибка
 * настройки, и молча объявлять ПК живым нельзя. */
static bool host_is_alive(const char *host)
{
    if (host == NULL || host[0] == '\0') {
        return false;
    }

    ip_addr_t target;
    if (!ipaddr_aton(host, &target)) {
        ESP_LOGW(TAG, "адрес «%s» не разобран", host);
        return false;
    }

    ping_result_t result = {.done = xSemaphoreCreateBinary(), .received = 0};
    if (result.done == NULL) {
        return false;
    }

    esp_ping_config_t config = ESP_PING_DEFAULT_CONFIG();
    config.target_addr = target;
    config.count = PING_COUNT;
    config.timeout_ms = PING_TIMEOUT_MS;
    config.interval_ms = 500;

    esp_ping_callbacks_t callbacks = {
        .on_ping_success = on_ping_success,
        .on_ping_end = on_ping_end,
        .cb_args = &result,
    };

    esp_ping_handle_t session = NULL;
    if (esp_ping_new_session(&config, &callbacks, &session) != ESP_OK) {
        vSemaphoreDelete(result.done);
        return false;
    }

    esp_ping_start(session);
    /* Ждём с запасом: серия пакетов плюс таймаут последнего. */
    const TickType_t wait = pdMS_TO_TICKS(PING_COUNT * (PING_TIMEOUT_MS + 500) + 1000);
    xSemaphoreTake(result.done, wait);
    esp_ping_stop(session);
    esp_ping_delete_session(session);

    bool alive = result.received > 0;
    vSemaphoreDelete(result.done);
    return alive;
}

/* ------------------------------------------------------------- сторож */

const char *r32_guard_state_name(r32_guard_state_t state)
{
    switch (state) {
    case R32_GUARD_DISABLED:  return "выключен";
    case R32_GUARD_WATCHING:  return "наблюдение";
    case R32_GUARD_MISSING:   return "ПК пропал";
    case R32_GUARD_WAKING:    return "побудка";
    case R32_GUARD_GAVE_UP:   return "попытки исчерпаны";
    case R32_GUARD_SNOOZING:  return "плановое выключение";
    }
    return "неизвестно";
}

void r32_guard_get_status(r32_guard_status_t *out)
{
    if (s_lock != NULL) {
        xSemaphoreTake(s_lock, portMAX_DELAY);
    }
    *out = s_status;
    if (s_lock != NULL) {
        xSemaphoreGive(s_lock);
    }
}

void r32_guard_snooze(int minutes)
{
    if (s_lock != NULL) {
        xSemaphoreTake(s_lock, portMAX_DELAY);
    }
    if (minutes <= 0) {
        s_status.snooze_until_ms = 0;
        ESP_LOGI(TAG, "сон отменён, сторож снова следит за ПК");
    } else {
        s_status.snooze_until_ms = esp_timer_get_time() / 1000 + (int64_t) minutes * 60 * 1000;
        /* Плановое выключение обнуляет серию: следующая пропажа будет
         * считаться новой, а не продолжением старой. */
        s_status.attempts = 0;
        ESP_LOGI(TAG, "плановое выключение: не вмешиваемся %d мин", minutes);
    }
    if (s_lock != NULL) {
        xSemaphoreGive(s_lock);
    }
}

static void set_state(r32_guard_state_t state)
{
    if (s_status.state != state) {
        ESP_LOGI(TAG, "состояние: %s", r32_guard_state_name(state));
    }
    s_status.state = state;
}

static void guard_task(void *arg)
{
    (void) arg;

    /* Первая проверка не сразу: даём Wi-Fi подключиться, иначе стартовая
     * побудка ушла бы в никуда и сожгла попытку. */
    vTaskDelay(pdMS_TO_TICKS(CHECK_PERIOD_MS));

    int64_t missing_since_ms = 0;
    int64_t last_wake_ms = 0;

    while (true) {
        const int64_t now_ms = esp_timer_get_time() / 1000;

        if (!s_cfg->guard_enabled) {
            xSemaphoreTake(s_lock, portMAX_DELAY);
            set_state(R32_GUARD_DISABLED);
            xSemaphoreGive(s_lock);
            /* Забываем, когда ПК пропал: пока слежка выключена, время
             * не идёт. Иначе включение обратно сразу после долгой паузы
             * означало бы мгновенную побудку — а человек ждёт, что отсчёт
             * начнётся заново. */
            missing_since_ms = 0;
            vTaskDelay(pdMS_TO_TICKS(CHECK_PERIOD_MS));
            continue;
        }

        r32_wifi_status_t wifi;
        r32_wifi_get_status(&wifi);
        if (!wifi.connected) {
            /* Без своей сети мы не можем отличить «ПК выключен» от «мы
             * сами оторвались». Молчим: ложная побудка хуже пропущенной. */
            ESP_LOGD(TAG, "нет Wi-Fi, проверка пропущена");
            vTaskDelay(pdMS_TO_TICKS(CHECK_PERIOD_MS));
            continue;
        }

        const bool alive = host_is_alive(s_cfg->guard_host);

        xSemaphoreTake(s_lock, portMAX_DELAY);
        s_status.host_alive = alive;
        const bool snoozing = s_status.snooze_until_ms > now_ms;

        if (alive) {
            s_status.last_seen_ms = now_ms;
            s_status.attempts = 0;
            missing_since_ms = 0;
            set_state(R32_GUARD_WATCHING);
        } else if (snoozing) {
            set_state(R32_GUARD_SNOOZING);
        } else {
            if (missing_since_ms == 0) {
                missing_since_ms = now_ms;
                ESP_LOGW(TAG, "ПК не отвечает, отсчёт %d мин", s_cfg->guard_grace_minutes);
            }

            const int64_t missing_ms = now_ms - missing_since_ms;
            const int64_t grace_ms = (int64_t) s_cfg->guard_grace_minutes * 60 * 1000;
            const int64_t retry_ms = (int64_t) s_cfg->guard_retry_minutes * 60 * 1000;
            const bool exhausted = s_cfg->guard_max_attempts > 0
                                   && s_status.attempts >= s_cfg->guard_max_attempts;

            if (exhausted) {
                set_state(R32_GUARD_GAVE_UP);
            } else if (missing_ms < grace_ms) {
                set_state(R32_GUARD_MISSING);
            } else if (last_wake_ms != 0 && now_ms - last_wake_ms < retry_ms) {
                set_state(R32_GUARD_WAKING);
            } else {
                s_status.attempts++;
                s_status.total_wakes++;
                last_wake_ms = now_ms;
                set_state(R32_GUARD_WAKING);
                xSemaphoreGive(s_lock);

                /* Пакет шлём вне блокировки: сеть может подвиснуть, а
                 * отчёт о состоянии должен оставаться доступным. */
                ESP_LOGW(TAG, "побудка ПК %s (попытка %d)", s_cfg->guard_mac, s_status.attempts);
                esp_err_t err = r32_wol_send(s_cfg->guard_mac, s_cfg->guard_broadcast, 9, 3);
                if (err != ESP_OK) {
                    ESP_LOGE(TAG, "magic packet не отправлен: %s", esp_err_to_name(err));
                }

                vTaskDelay(pdMS_TO_TICKS(CHECK_PERIOD_MS));
                continue;
            }
        }
        xSemaphoreGive(s_lock);

        vTaskDelay(pdMS_TO_TICKS(CHECK_PERIOD_MS));
    }
}

/* Общая для консоли и сети проверка: включённый сторож без адреса или
 * MAC молча ничего не делает, и это худший из возможных исходов. */
static const char *guard_config_problem(const r32_config_t *cfg)
{
    if (!cfg->guard_enabled) {
        return NULL;
    }
    if (cfg->guard_host[0] == '\0') {
        return "сторож включён, но не задан адрес ПК";
    }
    if (cfg->guard_mac[0] == '\0') {
        return "сторож включён, но не задан MAC ПК";
    }
    return NULL;
}

esp_err_t r32_guard_wake_now(void)
{
    if (s_cfg == NULL || s_cfg->guard_mac[0] == '\0') {
        ESP_LOGE(TAG, "некого будить: MAC не задан");
        return ESP_ERR_INVALID_STATE;
    }

    /* Считаем эту побудку в общий счёт: с телефона должно быть видно, что
     * кнопку нажимали, иначе непонятно, почему ПК вдруг включился. */
    if (s_lock) xSemaphoreTake(s_lock, portMAX_DELAY);
    s_status.total_wakes++;
    if (s_lock) xSemaphoreGive(s_lock);

    ESP_LOGW(TAG, "побудка по кнопке: %s", s_cfg->guard_mac);
    return r32_wol_send(s_cfg->guard_mac, s_cfg->guard_broadcast, 9, 3);
}

bool r32_guard_toggle_enabled(void)
{
    if (s_cfg == NULL) {
        return false;
    }

    if (s_lock) xSemaphoreTake(s_lock, portMAX_DELAY);
    const bool enabled = !s_cfg->guard_enabled;
    s_cfg->guard_enabled = enabled;
    s_status.attempts = 0;
    s_status.state = enabled ? R32_GUARD_WATCHING : R32_GUARD_DISABLED;
    if (s_lock) xSemaphoreGive(s_lock);

    /* В NVS намеренно не пишем: см. комментарий у объявления. */
    ESP_LOGW(TAG, "сторож %s кнопкой (до перезагрузки платы)",
             enabled ? "включён" : "выключен");
    return enabled;
}

esp_err_t r32_guard_apply(const r32_guard_patch_t *patch, const char **error)
{
    if (s_cfg == NULL || patch == NULL) {
        if (error) *error = "сторож ещё не запущен";
        return ESP_ERR_INVALID_STATE;
    }

    /* Работаем на копии: если настройки окажутся противоречивыми, живая
     * конфигурация не должна пострадать. */
    r32_config_t draft = *s_cfg;

    if (patch->host) {
        strncpy(draft.guard_host, patch->host, sizeof(draft.guard_host) - 1);
        draft.guard_host[sizeof(draft.guard_host) - 1] = '\0';
    }
    if (patch->mac) {
        strncpy(draft.guard_mac, patch->mac, sizeof(draft.guard_mac) - 1);
        draft.guard_mac[sizeof(draft.guard_mac) - 1] = '\0';
    }
    if (patch->broadcast) {
        strncpy(draft.guard_broadcast, patch->broadcast, sizeof(draft.guard_broadcast) - 1);
        draft.guard_broadcast[sizeof(draft.guard_broadcast) - 1] = '\0';
    }
    if (patch->grace_minutes >= 0) draft.guard_grace_minutes = patch->grace_minutes;
    if (patch->retry_minutes >= 0) draft.guard_retry_minutes = patch->retry_minutes;
    if (patch->max_attempts >= 0) draft.guard_max_attempts = patch->max_attempts;
    if (patch->enabled >= 0) draft.guard_enabled = patch->enabled != 0;

    const char *problem = guard_config_problem(&draft);
    if (problem) {
        if (error) *error = problem;
        return ESP_ERR_INVALID_ARG;
    }

    esp_err_t err = r32_config_save(&draft);
    if (err != ESP_OK) {
        if (error) *error = esp_err_to_name(err);
        return err;
    }

    if (s_lock) xSemaphoreTake(s_lock, portMAX_DELAY);
    *s_cfg = draft;
    /* Счётчик попыток обнуляем: он относился к прежним настройкам.
     * Отсчёт молчания ПК живёт внутри задачи и намеренно не трогается —
     * если ожидание укоротили, новая граница должна сработать сразу. */
    s_status.attempts = 0;
    s_status.state = draft.guard_enabled ? R32_GUARD_WATCHING : R32_GUARD_DISABLED;
    if (s_lock) xSemaphoreGive(s_lock);

    ESP_LOGW(TAG, "настройки сторожа изменены: ПК %s (%s), ожидание %d мин, попыток %d",
             draft.guard_host, draft.guard_mac, draft.guard_grace_minutes,
             draft.guard_max_attempts);
    return ESP_OK;
}

esp_err_t r32_guard_start(r32_config_t *cfg)
{
    s_cfg = cfg;
    s_lock = xSemaphoreCreateMutex();
    if (s_lock == NULL) {
        return ESP_ERR_NO_MEM;
    }

    s_status.state = cfg->guard_enabled ? R32_GUARD_WATCHING : R32_GUARD_DISABLED;

    if (cfg->guard_enabled && (cfg->guard_host[0] == '\0' || cfg->guard_mac[0] == '\0')) {
        ESP_LOGE(TAG, "сторож включён, но не задан адрес или MAC — команда: guard --help");
        cfg->guard_enabled = false;
        s_status.state = R32_GUARD_DISABLED;
    }

    if (xTaskCreate(guard_task, "guard", 4096, NULL, 4, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "сторож %s (ПК %s, ожидание %d мин, попыток %d)",
             cfg->guard_enabled ? "включён" : "выключен",
             cfg->guard_host[0] ? cfg->guard_host : "не задан",
             cfg->guard_grace_minutes, cfg->guard_max_attempts);
    return ESP_OK;
}

/* ------------------------------------------------------------- консоль */

static struct {
    struct arg_str *host;
    struct arg_str *mac;
    struct arg_str *broadcast;
    struct arg_int *grace;
    struct arg_int *retry;
    struct arg_int *tries;
    struct arg_lit *on;
    struct arg_lit *off;
    struct arg_int *snooze;
    struct arg_end *end;
} s_guard_args;

static void copy_arg(char *dst, size_t size, struct arg_str *src)
{
    if (src->count > 0) {
        strncpy(dst, src->sval[0], size - 1);
        dst[size - 1] = '\0';
    }
}

static int cmd_guard(int argc, char **argv)
{
    if (s_cfg == NULL) {
        printf("конфигурация недоступна\n");
        return 1;
    }

    int errors = arg_parse(argc, argv, (void **) &s_guard_args);
    if (errors != 0) {
        arg_print_errors(stderr, s_guard_args.end, argv[0]);
        return 1;
    }

    copy_arg(s_cfg->guard_host, sizeof(s_cfg->guard_host), s_guard_args.host);
    copy_arg(s_cfg->guard_mac, sizeof(s_cfg->guard_mac), s_guard_args.mac);
    copy_arg(s_cfg->guard_broadcast, sizeof(s_cfg->guard_broadcast), s_guard_args.broadcast);

    if (s_guard_args.grace->count > 0) s_cfg->guard_grace_minutes = s_guard_args.grace->ival[0];
    if (s_guard_args.retry->count > 0) s_cfg->guard_retry_minutes = s_guard_args.retry->ival[0];
    if (s_guard_args.tries->count > 0) s_cfg->guard_max_attempts = s_guard_args.tries->ival[0];
    if (s_guard_args.on->count > 0) s_cfg->guard_enabled = true;
    if (s_guard_args.off->count > 0) s_cfg->guard_enabled = false;
    if (s_guard_args.snooze->count > 0) r32_guard_snooze(s_guard_args.snooze->ival[0]);

    r32_guard_status_t status;
    r32_guard_get_status(&status);

    printf("сторож:      %s\n", s_cfg->guard_enabled ? "включён" : "выключен");
    printf("состояние:   %s\n", r32_guard_state_name(status.state));
    printf("ПК:          %s (%s)\n",
           s_cfg->guard_host[0] ? s_cfg->guard_host : "не задан",
           s_cfg->guard_mac[0] ? s_cfg->guard_mac : "MAC не задан");
    printf("broadcast:   %s\n",
           s_cfg->guard_broadcast[0] ? s_cfg->guard_broadcast : "255.255.255.255");
    printf("ожидание:    %d мин, пауза %d мин, попыток %d\n",
           s_cfg->guard_grace_minutes, s_cfg->guard_retry_minutes, s_cfg->guard_max_attempts);
    printf("побудок:     %d (в серии %d)\n", status.total_wakes, status.attempts);
    printf("\nНе забудьте: save\n");
    return 0;
}

void r32_guard_register_console(r32_config_t *cfg)
{
    s_cfg = cfg;

    s_guard_args.host = arg_str0(NULL, "host", "<ip>", "адрес основного ПК");
    s_guard_args.mac = arg_str0(NULL, "mac", "<mac>", "MAC основного ПК");
    s_guard_args.broadcast = arg_str0(NULL, "bcast", "<ip>", "широковещательный адрес");
    s_guard_args.grace = arg_int0(NULL, "grace", "<мин>", "ждать перед побудкой");
    s_guard_args.retry = arg_int0(NULL, "retry", "<мин>", "пауза между попытками");
    s_guard_args.tries = arg_int0(NULL, "tries", "<n>", "попыток подряд, 0 — без предела");
    s_guard_args.on = arg_lit0(NULL, "on", "включить сторожа");
    s_guard_args.off = arg_lit0(NULL, "off", "выключить сторожа");
    s_guard_args.snooze = arg_int0(NULL, "snooze", "<мин>", "не вмешиваться N минут");
    s_guard_args.end = arg_end(4);

    const esp_console_cmd_t cmd = {
        .command = "guard",
        .help = "Сторож основного ПК: показать и изменить настройки",
        .hint = NULL,
        .func = &cmd_guard,
        .argtable = &s_guard_args,
    };
    ESP_ERROR_CHECK(esp_console_cmd_register(&cmd));
}
