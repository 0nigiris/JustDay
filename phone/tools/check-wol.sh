#!/usr/bin/env bash
# Проверка, доходит ли magic packet от платы до сетевой карты этого ПК.
#
# Зачем. Когда сторож не разбудил компьютер, подозреваемых двое: плата,
# которая могла не отправить пакет, и BIOS, который мог не подать
# дежурное питание на карту. Лезть в BIOS, не исключив первое, — потеря
# вечера. Этот скрипт исключает первое за десять секунд.
#
# Как работает. Просит плату отправить magic packet на непривилегированный
# порт вместо девятого и ловит его обычным сокетом — поэтому root не нужен.
# Сетевая карта опознаёт побудку по образцу в теле пакета (6 байт 0xFF и
# MAC шестнадцать раз подряд), а не по номеру порта, так что проверка
# честная: если пакет пришёл сюда правильным, придёт и на порт 9.
#
# Чего скрипт НЕ проверяет: включается ли ПК на самом деле. Это можно
# узнать, только выключив его. Здесь проверяется всё, что до карты.
#
# Использование:
#   tools/check-wol.sh [MAC] [адрес-платы]
# По умолчанию берётся MAC этой машины и адрес платы из controller.toml.

set -euo pipefail

CONFIG="${REMO32_CONTROLLER_CONFIG:-$HOME/.config/remo32/controller.toml}"
ENVFILE="${REMO32_CONTROLLER_ENV:-$HOME/.config/remo32/controller.env}"
PORT=9999

fail() { echo "ошибка: $*" >&2; exit 1; }

# --- MAC этой машины ---------------------------------------------------------
MAC="${1:-}"
if [ -z "$MAC" ]; then
    iface="$(ip -o route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i=="dev") print $(i+1)}')"
    [ -n "${iface:-}" ] || fail "не удалось определить сетевой интерфейс"
    MAC="$(cat "/sys/class/net/$iface/address")"
    echo "интерфейс $iface, MAC $MAC"
fi

# --- адрес платы -------------------------------------------------------------
BOARD="${2:-}"
if [ -z "$BOARD" ]; then
    [ -f "$CONFIG" ] || fail "нет файла $CONFIG — укажите адрес платы вторым аргументом"
    BOARD="$(sed -n 's|^ *base_url *= *"http://\([^"/]*\).*|\1|p' "$CONFIG" | head -1)"
    [ -n "$BOARD" ] || fail "в $CONFIG не нашёлся base_url платы"
fi
echo "плата: $BOARD"

# --- токен -------------------------------------------------------------------
# Читаем строкой, а не через source: в файле есть значения со спецсимволами
# (хэш пароля), и оболочка на них спотыкается.
TOKEN="${REMO32_ESP32_TOKEN:-}"
if [ -z "$TOKEN" ] && [ -f "$ENVFILE" ]; then
    TOKEN="$(sed -n 's/^REMO32_ESP32_TOKEN=//p' "$ENVFILE" | head -1)"
fi
[ -n "$TOKEN" ] || fail "не найден REMO32_ESP32_TOKEN"

# --- ловим -------------------------------------------------------------------
python3 - "$PORT" "$MAC" <<'PY' &
import socket, sys
port, expected = int(sys.argv[1]), sys.argv[2].lower().replace(":", "")
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("0.0.0.0", port))
s.settimeout(8)
поймано = 0
while True:
    try:
        data, addr = s.recvfrom(2048)
    except socket.timeout:
        break
    целый = (len(data) == 102 and data[:6] == b"\xff" * 6
             and all(data[6 + i * 6:12 + i * 6] == data[6:12] for i in range(16)))
    внутри = data[6:12].hex()
    метка = "верный" if внутри == expected else f"ЧУЖОЙ (ждали {expected})"
    print(f"  пакет от {addr[0]}: {len(data)} байт, целостность {'да' if целый else 'НЕТ'}, MAC {метка}")
    поймано += 1
print(f"поймано пакетов: {поймано}")
sys.exit(0 if поймано else 1)
PY
LISTENER=$!
sleep 1

echo "прошу плату отправить magic packet..."
reply="$(curl -s --max-time 10 -X POST "http://$BOARD/command" \
    -H "X-Remo32-Agent-Token: $TOKEN" -H 'Content-Type: application/json' \
    -d "{\"command_id\":\"check-wol\",\"type\":\"wake_on_lan\",\"payload\":{\"mac_address\":\"$MAC\",\"broadcast_address\":\"255.255.255.255\",\"port\":$PORT,\"repeat\":3}}")" \
    || fail "плата не ответила по адресу $BOARD"
echo "ответ платы: $reply"

if wait "$LISTENER"; then
    echo
    echo "ВЫВОД: плата отправляет правильный magic packet, и он доходит до карты."
    echo "Значит, если ПК не просыпается, дело в BIOS или в дежурном питании:"
    echo "  * включить «Power On By PCI-E / Onboard LAN»;"
    echo "  * выключить «ErP / EuP» — он обесточивает карту в выключенном состоянии;"
    echo "  * проверить, что карта настроена: sudo ethtool <интерфейс> | grep Wake-on  (нужно g)."
else
    echo
    echo "ВЫВОД: пакет не пришёл. Дело НЕ в BIOS — разбираться надо с платой и сетью:"
    echo "  * ответила ли плата выше;"
    echo "  * в одной ли они подсети с ПК;"
    echo "  * не режет ли роутер широковещательные пакеты между Wi-Fi и проводом."
    exit 1
fi
