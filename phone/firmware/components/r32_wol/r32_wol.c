#include "r32_wol.h"

#include <string.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "r32_wol";

#define MAGIC_PACKET_SIZE 102 /* 6 байт 0xFF + MAC × 16 */

static int hex_value(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

/* Разбирает MAC, пропуская любые разделители. */
static esp_err_t parse_mac(const char *mac, uint8_t out[6])
{
    int nibbles = 0;
    uint8_t current = 0;

    for (const char *p = mac; *p != '\0'; p++) {
        int value = hex_value(*p);
        if (value < 0) {
            continue; /* разделитель */
        }
        current = (uint8_t) ((current << 4) | (uint8_t) value);
        nibbles++;
        if (nibbles % 2 == 0) {
            int index = nibbles / 2 - 1;
            if (index >= 6) {
                return ESP_ERR_INVALID_ARG;
            }
            out[index] = current;
            current = 0;
        }
    }
    return nibbles == 12 ? ESP_OK : ESP_ERR_INVALID_ARG;
}

esp_err_t r32_wol_send(const char *mac, const char *broadcast, int port, int repeat)
{
    uint8_t mac_bytes[6];
    esp_err_t err = parse_mac(mac, mac_bytes);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "некорректный MAC: %s", mac);
        return err;
    }

    uint8_t packet[MAGIC_PACKET_SIZE];
    memset(packet, 0xFF, 6);
    for (int i = 0; i < 16; i++) {
        memcpy(packet + 6 + i * 6, mac_bytes, 6);
    }

    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sock < 0) {
        ESP_LOGE(TAG, "не удалось создать сокет: errno %d", errno);
        return ESP_FAIL;
    }

    int broadcast_enable = 1;
    if (setsockopt(sock, SOL_SOCKET, SO_BROADCAST, &broadcast_enable,
                   sizeof(broadcast_enable)) < 0) {
        ESP_LOGE(TAG, "SO_BROADCAST недоступен: errno %d", errno);
        close(sock);
        return ESP_FAIL;
    }

    struct sockaddr_in dest = {0};
    dest.sin_family = AF_INET;
    dest.sin_port = htons((uint16_t) (port > 0 ? port : 9));
    dest.sin_addr.s_addr = inet_addr(broadcast != NULL && broadcast[0] ? broadcast
                                                                      : "255.255.255.255");

    if (repeat < 1) {
        repeat = 1;
    }
    if (repeat > 10) {
        repeat = 10;
    }

    esp_err_t result = ESP_OK;
    for (int i = 0; i < repeat; i++) {
        int sent = sendto(sock, packet, sizeof(packet), 0, (struct sockaddr *) &dest,
                          sizeof(dest));
        if (sent < 0) {
            ESP_LOGE(TAG, "sendto не удался: errno %d", errno);
            result = ESP_FAIL;
            break;
        }
        /* Небольшая пауза между повторами: спящая сетевая карта может
         * пропустить пакеты, идущие вплотную. */
        vTaskDelay(pdMS_TO_TICKS(50));
    }

    close(sock);
    if (result == ESP_OK) {
        ESP_LOGI(TAG, "magic packet отправлен на %s (%s:%d, повторов %d)", mac,
                 broadcast, port, repeat);
    }
    return result;
}
