/* Отправка magic packet.
 *
 * Ради этой функции плата и нужна: она находится в домашней сети, а
 * широковещательный пакет через интернет и Tailscale не проходит.
 */
#pragma once

#include "esp_err.h"

/* mac — строка вида "aa:bb:cc:dd:ee:ff" (допустимы дефисы и без разделителей). */
esp_err_t r32_wol_send(const char *mac, const char *broadcast, int port, int repeat);
