#!/usr/bin/env bash
# Снести JustDay у текущего пользователя под корень, чтобы поставить заново и увидеть установку
# такой, какой её видит новый человек (П7). Системные пакеты (git, kitty, ffmpeg…) не трогаем:
# ими пользуются и другие программы. Папку разработки (~/JustDay) не трогаем: это не установка.
#
#   bash scripts/uninstall.sh            — спросит подтверждение
#   curl -fsSL https://raw.githubusercontent.com/0nigiris/JustDay/main/scripts/uninstall.sh | bash
set -u
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}"

echo "Будет удалено у пользователя $USER:"
echo "  программа, настройки, журналы, кэш, службы, сочетания клавиш и ярлыки JustDay,"
echo "  память Джарвиса. Уведомления и OSD Plasma вернутся как были до установки."
# Из `curl … | bash` стандартный ввод занят самим скриптом: спрашиваем через терминал.
read -rp "Напиши «да», чтобы удалить: " ok </dev/tty
[[ "$ok" == "да" || "$ok" == "yes" ]] || { echo "Ничего не удалено."; exit 1; }
read -rp "Ключи из связки (вход в модели, школа, голос) тоже удалить? [y/N] " keys </dev/tty

# Службы: сначала остановить, иначе демон допишет конфиг уже после удаления.
units=$(cd "$CONF/systemd/user" 2>/dev/null && ls -1 justday* 2>/dev/null)
for u in $units; do systemctl --user disable --now "$u" >/dev/null 2>&1; done
for u in $units; do rm -f "$CONF/systemd/user/$u"; done
systemctl --user daemon-reload 2>/dev/null

# Всплывашки и OSD Plasma установщик выключил, чтобы их показывал островок; без JustDay их не
# увидит никто — возвращаем.
kw=$(command -v kwriteconfig6 || command -v kwriteconfig5)
if [[ -n "$kw" ]]; then
  "$kw" --file plasmanotifyrc --group DoNotDisturb --key Until --delete
  "$kw" --file plasmanotifyrc --group Notifications --key CriticalInDndMode --delete
  "$kw" --file plasmarc --group OSD --key Enabled --delete
  "$kw" --file plasmarc --group OSD --key kbdLayoutChangedEnabled --delete
  for k in VolumeOsd MuteOsd MicrophoneSensitivityOsd PushToTalkOsd MutedMicrophoneReminderOsd \
           DefaultOutputDeviceOsd; do
    "$kw" --file plasmaparc --group General --key "$k" --delete
  done
  # Сочетания клавиш: без своих групп в kglobalshortcutsrc клавиши остались бы мёртвыми.
  for f in "$DATA"/applications/net.local.justday*.desktop; do
    [[ -e "$f" ]] && "$kw" --file kglobalshortcutsrc --group services --group "$(basename "$f")" \
      --key _launch --delete
  done
fi
rm -f "$DATA"/applications/net.local.justday*.desktop "$HOME/.local/bin/justday"

rm -rf "$DATA/justday" "$CONF/justday" "$STATE/justday" "$CACHE/justday" "$CACHE/justday-pyside"
# Claude Code хранит память мозга по пути его папки; без этого «чистая» установка помнит старое.
rm -rf "$HOME"/.claude/projects/*-local-share-justday-* "$HOME"/.claude/projects/*-local-state-justday

if [[ "$keys" == [yYдД]* ]]; then
  for s in justday justday-school; do
    secret-tool clear service "$s" 2>/dev/null
  done
  echo "Ключи удалены."
fi
echo "Готово. JustDay удалён. Поставить заново:"
echo "  curl -fsSL https://raw.githubusercontent.com/0nigiris/JustDay/main/install.sh | bash"
echo "Сочетания клавиш KDE подхватит после выхода из сеанса."
