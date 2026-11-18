#!/usr/bin/env bash
# Чистый пользователь для показа установки с нуля (П7): у него нет ни нашего конфига, ни памяти,
# ни ключей — установка видна так, как её увидит новый человек. Пароль вводит сам человек.
set -e
U=jdshow
echo "Создаю пользователя $U для показа установки с нуля."
echo "Сейчас sudo спросит ТВОЙ пароль, потом — новый пароль для $U (дважды)."
id "$U" >/dev/null 2>&1 || sudo useradd -m -c "JustDay: показ установки" "$U"
sudo passwd "$U"
echo
echo "Готово. Дальше: меню → Сменить пользователя → $U, и там в терминале:"
echo "  curl -fsSL https://raw.githubusercontent.com/0nigiris/JustDay/main/install.sh | bash"
echo "Удалить потом: sudo userdel -r $U"
read -rp "Enter — закрыть окно. "
