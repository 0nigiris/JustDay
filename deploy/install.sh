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

    sed "s|%h|$HOME|g" "$REPO_DIR/deploy/systemd/remo32-agent.service" \
        > "$UNIT_DIR/remo32-agent.service"
    systemctl --user daemon-reload
    ok "служба установлена: systemctl --user enable --now remo32-agent"
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
# либо по одному на ПК:
# REMO32_AGENT_TOKEN_VASYA=...
# REMO32_AGENT_TOKEN_MINEVPSEX=...
EOF
        chmod 600 "$CONFIG_DIR/controller.env"
        ok "создан $CONFIG_DIR/controller.env"
    else
        warn "$CONFIG_DIR/controller.env уже есть, пароль не меняю"
    fi

    sed "s|%h|$HOME|g" "$REPO_DIR/deploy/systemd/remo32-controller.service" \
        > "$UNIT_DIR/remo32-controller.service"
    systemctl --user daemon-reload
    ok "служба установлена: systemctl --user enable --now remo32-controller"

    echo
    warn "Проверьте адрес прослушивания в $CONFIG_DIR/controller.toml"
    warn "Для доступа с телефона укажите адрес Tailscale: $(command -v tailscale >/dev/null && tailscale ip -4 2>/dev/null | head -1 || echo '<tailscale ip -4>')"
}

install_polkit() {
    info "Установка правила polkit (нужен sudo)"
    tmp="$(mktemp)"
    sed "s/\"oni\"/\"$USER\"/" "$REPO_DIR/deploy/polkit/49-remo32-power.rules" > "$tmp"
    sudo install -m 0644 "$tmp" /etc/polkit-1/rules.d/49-remo32-power.rules
    rm -f "$tmp"
    ok "выключение и перезагрузка разрешены пользователю $USER без пароля"
}

need python3
need systemctl

case "${1:-}" in
    agent)      need uv; install_agent ;;
    controller) need uv; install_controller ;;
    both)       need uv; install_agent; install_controller ;;
    polkit)     install_polkit ;;
    *)
        cat <<EOF
Использование: $0 {agent|controller|both|polkit}

  agent       установить агент на этот ПК
  controller  установить центральный контроллер
  both        установить оба (типично для основного ПК)
  polkit      разрешить выключение/перезагрузку без пароля (запросит sudo)

Ничего не делает без явной команды.
EOF
        exit 1
        ;;
esac
