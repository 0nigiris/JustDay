#!/usr/bin/env bash
# Установка Remo32 на эту машину.
#
# Скрипт НЕ требует root и НЕ трогает системные каталоги, кроме
# необязательного правила polkit, которое ставится отдельно и явно.
#
# Использование:
#   ./deploy/install.sh agent           — поставить агент
#   ./deploy/install.sh controller      — поставить контроллер
#   ./deploy/install.sh both            — и то, и другое
#   ./deploy/install.sh polkit          — разрешить выключение без пароля (sudo)
#   ./deploy/install.sh check           — проверить, что всё работает
#   ./deploy/install.sh approvals       — подтверждение входа и sudo с телефона

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="$HOME/.config/remo32"
DATA_DIR="$HOME/.local/share/remo32"
UNIT_DIR="$HOME/.config/systemd/user"

info()  { printf '\033[1;34m→\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m!\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
fail()  { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

need() { command -v "$1" >/dev/null || fail "не найдена программа: $1"; }

gen_token() { python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; }

prepare_dirs() {
    mkdir -p "$CONFIG_DIR" "$DATA_DIR" "$UNIT_DIR"
    chmod 700 "$CONFIG_DIR" "$DATA_DIR"
    enable_linger
    sync_venv
}

# Службы запускаются прямо из .venv, минуя «uv run»: под ProtectHome=read-only
# uv не может писать в свой кэш и служба падает. Значит окружение должно быть
# готово заранее.
sync_venv() {
    if [ ! -x "$REPO_DIR/.venv/bin/python3" ]; then
        info "Создаю окружение проекта (uv sync)"
    fi
    (cd "$REPO_DIR" && uv sync --quiet) || fail "не удалось выполнить uv sync"
    ok "окружение проекта готово"
}

# Без linger пользовательские службы стартуют только после входа в систему.
# Для машины, которая перезагружается раз в неделю и управляется с телефона,
# это означало бы: перезагрузился — и до неё уже не достучаться.
enable_linger() {
    if [ "$(loginctl show-user "$USER" --property=Linger --value 2>/dev/null)" = "yes" ]; then
        return
    fi
    if loginctl enable-linger "$USER" 2>/dev/null; then
        ok "включён linger: службы поднимутся после перезагрузки без входа"
    else
        warn "не удалось включить linger. Выполните вручную:"
        warn "  sudo loginctl enable-linger $USER"
        warn "Иначе после перезагрузки Remo32 не запустится до вашего входа в систему."
    fi
}

# Юнит должен указывать на тот каталог, куда репозиторий действительно
# склонирован. Раньше в нём было зашито ~/Remo32, и у любого, кто положил
# проект в другое место, служба не стартовала с невнятным «no such file».
install_unit() {
    local name="$1"
    sed -e "s|%REPO%|$REPO_DIR|g" -e "s|%h|$HOME|g" \
        "$REPO_DIR/deploy/systemd/$name.service" > "$UNIT_DIR/$name.service"
    systemctl --user daemon-reload

    if systemctl --user is-enabled --quiet "$name" 2>/dev/null; then
        systemctl --user restart "$name"
        ok "$name перезапущен"
        return
    fi

    # Спрашиваем, а не включаем молча: служба, поднятая без ведома человека,
    # — плохое начало знакомства с программой.
    if ask "Запустить $name сейчас и добавить в автозапуск?"; then
        systemctl --user enable --now "$name"
        ok "$name запущен"
    else
        info "Позже: systemctl --user enable --now $name"
    fi
}

# Вопрос «да/нет». Если ввода нет (скрипт запустили из другого скрипта),
# отвечаем «нет»: молчание не должно означать согласие.
ask() {
    local answer
    if [ ! -t 0 ]; then
        return 1
    fi
    read -r -p "$(printf '\033[1;36m?\033[0m %s [y/N] ' "$1")" answer
    [[ "$answer" =~ ^[YyДд]$ ]]
}

install_agent() {
    info "Установка агента"
    prepare_dirs

    if [[ ! -f "$CONFIG_DIR/agent.toml" ]]; then
        cp "$REPO_DIR/config/agent.example.toml" "$CONFIG_DIR/agent.toml"
        ok "создан $CONFIG_DIR/agent.toml (отредактируйте под себя)"
    else
        warn "$CONFIG_DIR/agent.toml уже есть, не трогаю"
    fi

    if [[ ! -f "$CONFIG_DIR/agent.env" ]]; then
        token="$(gen_token)"
        umask 077
        cat > "$CONFIG_DIR/agent.env" <<EOF
# Секреты агента. Файл имеет права 0600 и НЕ должен попадать в git.
REMO32_AGENT_TOKEN=$token
EOF
        chmod 600 "$CONFIG_DIR/agent.env"
        ok "сгенерирован токен агента, он лежит в $CONFIG_DIR/agent.env"
        echo
        echo "    Этот же токен нужно прописать на машине с контроллером:"
        echo "    REMO32_AGENT_TOKEN=$token"
        echo
    else
        warn "$CONFIG_DIR/agent.env уже есть, токен не меняю"
    fi

    mkdir -p "$DATA_DIR/scripts"
    cp "$REPO_DIR/deploy/scripts/screenshot.sh" "$DATA_DIR/scripts/"
    chmod +x "$DATA_DIR/scripts/screenshot.sh"

    install_unit remo32-agent
    ok "служба установлена"
}

install_controller() {
    info "Установка контроллера"
    prepare_dirs

    if [[ ! -f "$CONFIG_DIR/controller.toml" ]]; then
        cp "$REPO_DIR/config/controller.example.toml" "$CONFIG_DIR/controller.toml"
        ok "создан $CONFIG_DIR/controller.toml (обязательно отредактируйте!)"
    else
        warn "$CONFIG_DIR/controller.toml уже есть, не трогаю"
    fi

    if [[ ! -f "$CONFIG_DIR/controller.env" ]]; then
        info "Задайте пароль для входа в веб-интерфейс"
        hash="$(cd "$REPO_DIR" && uv run remo32-controller --hash-password)"
        [[ -n "$hash" ]] || fail "не удалось получить хэш пароля"
        secret="$(cd "$REPO_DIR" && uv run remo32-controller --gen-secret)"
        umask 077
        cat > "$CONFIG_DIR/controller.env" <<EOF
# Секреты контроллера. Права 0600, в git не попадают.
REMO32_PASSWORD_HASH=$hash
REMO32_SESSION_SECRET=$secret
# Токен(ы) агентов — впишите значения с машин, где стоит агент:
# REMO32_AGENT_TOKEN=...
# либо по одному на ПК (суффикс — идентификатор ПК из controller.toml
# заглавными буквами):
# REMO32_AGENT_TOKEN_DESKTOP=...
# REMO32_AGENT_TOKEN_SERVER=...
EOF
        chmod 600 "$CONFIG_DIR/controller.env"
        ok "создан $CONFIG_DIR/controller.env"
    else
        warn "$CONFIG_DIR/controller.env уже есть, пароль не меняю"
    fi

    install_unit remo32-controller
    ok "служба установлена"

    echo
    warn "Проверьте адрес прослушивания в $CONFIG_DIR/controller.toml"
    warn "Для доступа с телефона укажите адрес Tailscale: $(command -v tailscale >/dev/null && tailscale ip -4 2>/dev/null | head -1 || echo '<tailscale ip -4>')"
}

# Проверка после установки. Отвечает на вопрос «почему не работает?»
# раньше, чем он будет задан: что установлено, что запущено, что отвечает.
# printf с %-28s выравнивает по БАЙТАМ, а кириллица в UTF-8 занимает по два
# на букву — колонка разъезжается. Добиваем пробелами по числу символов.
field() {
    local label="$1" width=26 pad=""
    local n=$(( width - ${#label} ))
    while [ "$n" -gt 0 ]; do pad+=" "; n=$(( n - 1 )); done
    printf '  %s%s' "$label" "$pad"
}

run_check() {
    info "Проверка установки"
    echo

    field "окружение проекта"
    if [ -x "$REPO_DIR/.venv/bin/python3" ]; then ok "есть"; else fail "нет — запустите: uv sync"; fi

    field "linger"
    if [ "$(loginctl show-user "$USER" --property=Linger --value 2>/dev/null)" = "yes" ]; then
        ok "включён"
    else
        warn "выключен — после перезагрузки службы не поднимутся до входа в систему"
    fi

    local any=0
    for name in remo32-agent remo32-controller; do
        [ -f "$UNIT_DIR/$name.service" ] || continue
        any=1
        field "$name"
        if systemctl --user is-active --quiet "$name"; then
            ok "работает"
        else
            warn "не работает — journalctl --user -u $name -n 30"
        fi
    done
    [ "$any" = 1 ] || warn "  ни одна служба не установлена"

    for pair in "агент:8765:/ping" "контроллер:8080:/api/health"; do
        local label=${pair%%:*}
        local rest=${pair#*:}
        local port=${rest%%:*}
        local path=${rest#*:}
        [ -f "$UNIT_DIR/remo32-agent.service" ] || [ "$label" = "контроллер" ] || continue
        field "$label отвечает"
        if curl -fsS -m 3 "http://127.0.0.1:$port$path" >/dev/null 2>&1; then
            ok "да (порт $port)"
        else
            warn "нет ответа на 127.0.0.1:$port"
        fi
    done

    echo
    field "конфигурация"
    if [ -f "$CONFIG_DIR/controller.toml" ] || [ -f "$CONFIG_DIR/agent.toml" ]; then
        ok "$CONFIG_DIR"
    else
        warn "не найдена в $CONFIG_DIR"
    fi
}

# Ставит скрипт подтверждения и печатает строки для PAM — но сам PAM не
# трогает. Ошибка в этих файлах лишает человека и root, и входа в систему;
# такую правку он должен сделать своими руками, глядя на экран, с открытым
# запасным root-терминалом.
install_approvals() {
    info "Подтверждение входа и sudo с телефона"
    sudo install -m 0755 "$REPO_DIR/deploy/scripts/remo32-pam.py" /usr/local/bin/remo32-pam
    ok "скрипт установлен: /usr/local/bin/remo32-pam"

    echo
    warn "ОСТАВШЕЕСЯ СДЕЛАЙТЕ САМИ. Сначала откройте ВТОРОЙ терминал и"
    warn "выполните в нём: sudo -i — пусть остаётся открытым."
    warn "Ошибка в PAM лишает и root, и входа в систему; этот терминал —"
    warn "единственный способ откатить правку, не загружаясь с флешки."
    echo
    echo "  1. В ~/.config/remo32/agent.toml:"
    echo
    echo "       [approvals]"
    echo "       enabled = true"
    echo
    echo "  2. Первой строкой в /etc/pam.d/sudo:"
    echo
    echo "       auth       sufficient   pam_exec.so quiet /usr/local/bin/remo32-pam request --kind sudo"
    echo
    echo "  3. Первой строкой в /etc/pam.d/kde (вход в Plasma):"
    echo
    echo "       auth        sufficient    pam_exec.so quiet /usr/local/bin/remo32-pam check --kind login"
    echo
    echo "  4. Проверка, не выходя из запасного терминала:  sudo -k && sudo true"
    echo
    echo "  Подробности и разбор неполадок — в MANUAL.md."
}

install_polkit() {
    info "Установка правила polkit (нужен sudo)"
    tmp="$(mktemp)"
    sed "s|%USER%|$USER|g" "$REPO_DIR/deploy/polkit/49-remo32-power.rules" > "$tmp"
    sudo install -m 0644 "$tmp" /etc/polkit-1/rules.d/49-remo32-power.rules
    rm -f "$tmp"
    ok "выключение и перезагрузка разрешены пользователю $USER без пароля"
}

need python3
need systemctl

case "${1:-}" in
    agent)      need uv; install_agent; echo; run_check ;;
    controller) need uv; install_controller; echo; run_check ;;
    both)       need uv; install_agent; install_controller; echo; run_check ;;
    polkit)     install_polkit ;;
    approvals)  install_approvals ;;
    check)      run_check ;;
    *)
        cat <<EOF
Использование: $0 {agent|controller|both|polkit|check|approvals}

  agent       установить агент на этот ПК
  controller  установить центральный контроллер
  both        установить оба (типично для основного ПК)
  polkit      разрешить выключение/перезагрузку без пароля (запросит sudo)
  check       проверить, что установлено и работает
  approvals   поставить скрипт подтверждения входа и sudo с телефона (sudo)

Ничего не делает без явной команды.
EOF
        exit 1
        ;;
esac
