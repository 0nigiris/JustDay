#include "r32_http.h"

#include <stdlib.h>
#include <string.h>

#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "r32_proto.h"

static const char *TAG = "r32_http";
static httpd_handle_t s_server = NULL;
static const r32_config_t *s_cfg = NULL;

#define MAX_BODY_LEN 2048
#define TOKEN_HEADER "X-Remo32-Agent-Token"

/* Сравнение, не зависящее от длины совпадения: иначе по времени ответа
 * можно подбирать токен посимвольно. */
static bool token_equals(const char *a, const char *b)
{
    size_t len_a = strlen(a);
    size_t len_b = strlen(b);
    if (len_a != len_b) {
        return false;
    }
    unsigned char diff = 0;
    for (size_t i = 0; i < len_a; i++) {
        diff |= (unsigned char) (a[i] ^ b[i]);
    }
    return diff == 0;
}

static esp_err_t check_token(httpd_req_t *req)
{
    if (s_cfg->token[0] == '\0') {
        /* Токен не задан — считаем устройство ненастроенным и не пускаем.
         * Открытое устройство в сети хуже неработающего. */
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                            "token not configured on device");
        return ESP_FAIL;
    }

    size_t len = httpd_req_get_hdr_value_len(req, TOKEN_HEADER);
    if (len == 0 || len > R32_STR_MAX) {
        httpd_resp_send_err(req, HTTPD_401_UNAUTHORIZED, "missing token");
        return ESP_FAIL;
    }

    char presented[R32_STR_MAX + 1];
    if (httpd_req_get_hdr_value_str(req, TOKEN_HEADER, presented, sizeof(presented)) != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_401_UNAUTHORIZED, "missing token");
        return ESP_FAIL;
    }

    if (!token_equals(presented, s_cfg->token)) {
        ESP_LOGW(TAG, "отклонён запрос с неверным токеном");
        httpd_resp_send_err(req, HTTPD_401_UNAUTHORIZED, "invalid token");
        return ESP_FAIL;
    }
    return ESP_OK;
}

static esp_err_t send_json(httpd_req_t *req, char *json)
{
    if (json == NULL) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "out of memory");
        return ESP_FAIL;
    }
    httpd_resp_set_type(req, "application/json");
    esp_err_t err = httpd_resp_sendstr(req, json);
    free(json);
    return err;
}

static esp_err_t command_handler(httpd_req_t *req)
{
    if (check_token(req) != ESP_OK) {
        return ESP_FAIL;
    }

    if (req->content_len <= 0 || req->content_len > MAX_BODY_LEN) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "bad body size");
        return ESP_FAIL;
    }

    char *body = malloc((size_t) req->content_len + 1);
    if (body == NULL) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "out of memory");
        return ESP_FAIL;
    }

    int received = 0;
    while (received < req->content_len) {
        int chunk = httpd_req_recv(req, body + received, (size_t) (req->content_len - received));
        if (chunk <= 0) {
            free(body);
            httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "recv failed");
            return ESP_FAIL;
        }
        received += chunk;
    }
    body[received] = '\0';

    /* Признак перезагрузки снимаем до разбора: r32_proto_handle не
     * перезагружает сам — ответ должен успеть уйти. Раньше это делал
     * только MQTT, и по HTTP команда «перезагрузить» честно отвечала
     * «ок», ничего не делая. */
    const bool is_reboot = strstr(body, "\"reboot\"") != NULL;

    char *reply = r32_proto_handle(body, s_cfg);
    free(body);
    esp_err_t sent = send_json(req, reply);

    if (is_reboot) {
        /* Даём ответу уйти в сеть до перезагрузки. */
        vTaskDelay(pdMS_TO_TICKS(500));
        esp_restart();
    }
    return sent;
}

static esp_err_t status_handler(httpd_req_t *req)
{
    if (check_token(req) != ESP_OK) {
        return ESP_FAIL;
    }
    return send_json(req, r32_proto_status_json(s_cfg));
}

static esp_err_t ping_handler(httpd_req_t *req)
{
    /* Единственная ручка без токена: показывает только факт «плата жива». */
    httpd_resp_set_type(req, "application/json");
    return httpd_resp_sendstr(req, "{\"pong\":true,\"service\":\"remo32-firmware\"}");
}

esp_err_t r32_http_start(const r32_config_t *cfg)
{
    s_cfg = cfg;

    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.max_uri_handlers = 8;
    config.lru_purge_enable = true;
    config.stack_size = 6144;

    esp_err_t err = httpd_start(&s_server, &config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "не удалось запустить HTTP-сервер: %s", esp_err_to_name(err));
        return err;
    }

    static const httpd_uri_t command_uri = {
        .uri = "/command", .method = HTTP_POST, .handler = command_handler, .user_ctx = NULL,
    };
    static const httpd_uri_t status_uri = {
        .uri = "/status", .method = HTTP_GET, .handler = status_handler, .user_ctx = NULL,
    };
    static const httpd_uri_t ping_uri = {
        .uri = "/ping", .method = HTTP_GET, .handler = ping_handler, .user_ctx = NULL,
    };

    httpd_register_uri_handler(s_server, &command_uri);
    httpd_register_uri_handler(s_server, &status_uri);
    httpd_register_uri_handler(s_server, &ping_uri);

    ESP_LOGI(TAG, "HTTP-сервер запущен на порту %d", config.server_port);
    return ESP_OK;
}

void r32_http_stop(void)
{
    if (s_server != NULL) {
        httpd_stop(s_server);
        s_server = NULL;
    }
}
