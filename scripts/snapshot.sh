#!/usr/bin/env bash
# Резервные копии кода перед правками: снимок рабочего дерева и быстрый откат.
#
#   scripts/snapshot.sh save [метка]  — снять копию (молча пропустит, если ничего не менялось)
#   scripts/snapshot.sh list          — что накопилось
#   scripts/snapshot.sh back [имя]    — вернуть дерево к копии (по умолчанию к последней)
#   scripts/snapshot.sh drop [имя|--all|--accepted]
#                                     — убрать копию, все, или все кроме последней
#
# В копию попадает то, что видит git: отслеживаемое и новые файлы, но не
# игнорируемое. Виртуальные окружения и кеши внутрь не лезут — копия весит
# мегабайты и снимается за долю секунды.
set -euo pipefail

root=$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)
store=${JUSTDAY_BACKUPS:-${XDG_DATA_HOME:-$HOME/.local/share}/justday/backups}
keep=${JUSTDAY_BACKUPS_KEEP:-12}
mkdir -p "$store"

# Отпечаток дерева: коммит плюс состояние всех файлов. Совпал с прошлым
# снимком — значит с тех пор ничего не трогали, копия была бы дубликатом.
fingerprint() {
    { git -C "$root" rev-parse HEAD 2>/dev/null || echo none
      git -C "$root" status --porcelain=v1 -z --untracked-files=all
      git -C "$root" ls-files -c -o --exclude-standard -z | xargs -0 -r stat -c '%n %s %Y'
    } | sha256sum | cut -c1-16
}

files() { git -C "$root" ls-files -c -o --exclude-standard -z; }

human() { numfmt --to=iec --suffix=B "$1" 2>/dev/null || echo "$1"; }

save() {
    local label=${1:-} quiet=0
    [ "$label" = "--quiet" ] && { quiet=1; label=${2:-}; }
    local fp last
    fp=$(fingerprint)
    last=$(cat "$store/.last" 2>/dev/null || true)
    if [ "$fp" = "$last" ]; then
        [ "$quiet" = 1 ] || echo "с прошлой копии ничего не менялось"
        return 0
    fi
    local name
    name=$(date +%Y%m%d-%H%M%S)
    [ -n "$label" ] && name="$name-$(printf '%s' "$label" | LC_ALL=C.UTF-8 sed -E 's/[^[:alnum:]]+/-/g; s/^-|-$//g' | cut -c1-40)"
    # Две правки в одну секунду — обычное дело, второй копии нужно своё имя.
    local n=1 base=$name
    while [ -e "$store/$name.tar.zst" ]; do n=$((n + 1)); name="$base-$n"; done
    files | tar -C "$root" --null -T - -cf - | zstd -q -3 -o "$store/$name.tar.zst" -f
    { echo "branch=$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null || echo -)"
      echo "commit=$(git -C "$root" rev-parse --short HEAD 2>/dev/null || echo -)"
      echo "subject=$(git -C "$root" log -1 --pretty=%s 2>/dev/null | tr -d '\n' || true)"
      echo "dirty=$(git -C "$root" status --porcelain | wc -l)"
      echo "label=$label"
    } > "$store/$name.info"
    echo "$fp" > "$store/.last"
    [ "$quiet" = 1 ] || echo "копия $name ($(human "$(stat -c %s "$store/$name.tar.zst")"))"
    rotate
}

rotate() {
    local old
    old=$(ls -1t "$store"/*.tar.zst 2>/dev/null | tail -n +"$((keep + 1))" || true)
    [ -z "$old" ] && return 0
    while read -r f; do [ -n "$f" ] && rm -f "$f" "${f%.tar.zst}.info"; done <<< "$old"
}

# Описание копии читаем построчно: исполнять чужой файл ради трёх полей незачем.
field() { sed -n "s/^$2=//p" "$1" 2>/dev/null | head -1; }

list() {
    local any=0 f name info commit label dirty subject
    for f in $(ls -1t "$store"/*.tar.zst 2>/dev/null); do
        any=1; name=$(basename "$f" .tar.zst); info="${f%.tar.zst}.info"
        commit=$(field "$info" commit); label=$(field "$info" label)
        dirty=$(field "$info" dirty); subject=$(field "$info" subject)
        printf '%s  %8s  %s  %s%s\n' "$name" "$(human "$(stat -c %s "$f")")" "${commit:--}" \
            "${label:+«$label» }" "$([ "${dirty:-0}" -gt 0 ] && echo "(правок: $dirty) $subject" || echo "$subject")"
    done
    [ "$any" = 0 ] && echo "копий пока нет"
    return 0
}

latest() { ls -1t "$store"/*.tar.zst 2>/dev/null | head -1; }

back() {
    local want=${1:-} arc
    if [ -n "$want" ]; then
        arc="$store/${want%.tar.zst}.tar.zst"
    else
        arc=$(latest)
    fi
    [ -f "${arc:-}" ] || { echo "нет такой копии: ${want:-последняя}" >&2; exit 1; }
    save --quiet "перед-откатом"
    # Уносим то, что копия не знает: иначе рядом останутся файлы, созданные после неё.
    local keepers
    keepers=$(mktemp); zstd -dc "$arc" | tar -tf - | sed 's:/$::' > "$keepers"
    while IFS= read -r -d '' f; do
        grep -qxF "$f" "$keepers" || rm -f "$root/$f"
    done < <(cd "$root" && git ls-files -c -o --exclude-standard -z)
    rm -f "$keepers"
    zstd -dc "$arc" | tar -C "$root" -xf -
    echo "дерево вернулось к $(basename "$arc" .tar.zst)"
}

drop() {
    case ${1:-} in
        --all) rm -f "$store"/*.tar.zst "$store"/*.info "$store/.last"; echo "копии убраны" ;;
        --accepted|"")
            local last; last=$(latest)
            for f in "$store"/*.tar.zst; do
                [ -f "$f" ] && [ "$f" != "$last" ] && rm -f "$f" "${f%.tar.zst}.info"
            done
            echo "оставил только последнюю" ;;
        *) rm -f "$store/${1%.tar.zst}.tar.zst" "$store/${1%.tar.zst}.info"; echo "убрал $1" ;;
    esac
}

case ${1:-save} in
    save) shift || true; save "$@" ;;
    list|ls) list ;;
    back|restore) shift || true; back "${1:-}" ;;
    drop|rm) shift || true; drop "${1:-}" ;;
    *) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
esac
