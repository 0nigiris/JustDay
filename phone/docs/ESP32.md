# ESP32: необязательный сторож

Плата не нужна, чтобы пользоваться JustDay на телефоне. Если она у вас есть, её можно
подключить: она пингует основной ПК и будит его сам, когда тот перестал отвечать.

## Симулятор ESP32

Позволяет разрабатывать и проверять всё, не имея платы под рукой.

```bash
# HTTP-режим: ведёт себя как плата в домашней сети
uv run remo32-espsim --host 127.0.0.1 --port 8090

# MQTT-режим: как плата, подключённая к брокеру
uv run remo32-espsim --mode mqtt --mqtt-host 127.0.0.1 --mqtt-port 1883

# Настоящий magic packet: пробуждение заработает ещё до появления платы
uv run remo32-espsim --real-wol
```

Направить контроллер на симулятор:

```toml
[esp32]
transport = "http"
base_url = "http://127.0.0.1:8090"
```

Управление неисправностями (ручки есть только у симулятора):

```bash
# плата «пропала»
curl -X POST -H 'Content-Type: application/json' \
     -d '{"offline":true}' localhost:8090/sim/faults

# потеря Wi-Fi
curl -X POST -H 'Content-Type: application/json' \
     -d '{"wifi_lost":true}' localhost:8090/sim/faults

# каждая третья команда завершается ошибкой
curl -X POST -H 'Content-Type: application/json' \
     -d '{"failure_rate":0.33}' localhost:8090/sim/faults

# «ПК включился» — изменился уровень на входе
curl -X POST -H 'Content-Type: application/json' \
     -d '{"pin":4,"level":true}' localhost:8090/sim/pin

# текущее состояние симуляции
curl localhost:8090/sim/state
```

Брокер для проверки MQTT:

```bash
podman run -d --rm --name remo32-mqtt -p 1883:1883 \
  -v "$PWD/deploy/mosquitto.conf:/mosquitto/config/mosquitto.conf:Z" \
  docker.io/library/eclipse-mosquitto:2
```

Симулятор всегда сообщает `simulated: true`, и интерфейс это показывает.
**Успешный вызов в симуляторе ничего не говорит о работоспособности
железа.**

## Прошивка ESP32

См. [firmware/README.md](firmware/README.md) — сборка, заливка, настройка
через последовательный порт.
Схема подключения: [docs/HARDWARE.md](docs/HARDWARE.md).

Коротко:

```bash
cd firmware
. ~/esp/esp-idf-525/export.sh
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/ttyACM0 flash monitor
```

Затем в консоли платы: `wifi <ssid> <пароль>`, `token <секрет>`, `save`,
`restart`.

## Сторож основного ПК

Контроллер работает на основном ПК, поэтому себя разбудить не может. Плата
делает это сама. Настраивается в её последовательной консоли:

```
guard --on --host 192.168.1.10 --mac 5c:f9:dd:11:22:33 --bcast 192.168.1.255
guard --grace 10 --retry 15 --tries 3
save
```

* `--host` — адрес основного ПК в домашней сети (лучше закрепить в роутере);
* `--grace` — сколько минут молчания считать пропажей;
* `--retry` — пауза между попытками, `--tries` — сколько их всего;
* `guard` без аргументов покажет текущее состояние;
* `guard --snooze 60` — не вмешиваться час (то же делает контроллер перед
  плановым выключением).

В конфигурации контроллера у охраняемого ПК нужно указать:

```toml
guarded_by_esp32 = true
guard_snooze_minutes = 480
```

Без этого плата примет ваше выключение за аварию и включит компьютер обратно.

