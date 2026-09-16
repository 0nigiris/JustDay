#!/usr/bin/env bash
# JustDay ↔ Minecraft: builds the bridge mod and puts it, with Baritone, into a Fabric 1.21.10 mods folder.
# Usage: minecraft/install.sh [MODS_DIR]      default: every Fabric 1.21.10 setup found (~/.minecraft, Prism instances)
# Baritone walks and mines; on multiplayer servers it counts as a cheat client — use it where that is allowed.
set -euo pipefail
cd "$(dirname "$0")"
BARITONE=1.16.0                                   # the Baritone release for Minecraft 1.21.9–1.21.10
BARITONE_SHA1=5e158a8e10ac7be215f4b7a686e85f67f8fe9cdf
JAR="baritone-api-fabric-$BARITONE.jar"

# ── a JDK ≥ 21 with javac (a JRE is not enough) ──
jdk_ok() { [[ -x "$1/bin/javac" ]] && "$1/bin/javac" -version 2>&1 | grep -qE 'javac (2[1-6])'; }
if [[ -z "${JAVA_HOME:-}" ]] || ! jdk_ok "$JAVA_HOME"; then
  JAVA_HOME=""
  for c in /usr/lib/jvm/java-21-openjdk /usr/lib/jvm/java-25-openjdk /usr/lib/jvm/java-2[1-6]* \
           /var/lib/flatpak/app/com.jetbrains.IntelliJ-IDEA-*/x86_64/stable/active/files/jbr \
           "$HOME"/.local/share/JetBrains/Toolbox/apps/*/jbr; do
    if jdk_ok "$c"; then JAVA_HOME="$c"; break; fi
  done
fi
if [[ -z "$JAVA_HOME" ]]; then
  echo "Нужен JDK 21+ с javac:  sudo dnf install java-21-openjdk-devel   (или apt install openjdk-21-jdk-headless)" >&2
  exit 1
fi
export JAVA_HOME

# ── Baritone (checksum pinned) ──
mkdir -p libs
if [[ ! -f "libs/$JAR" ]] || ! echo "$BARITONE_SHA1  libs/$JAR" | sha1sum -c --quiet 2>/dev/null; then
  echo "Baritone $BARITONE…"
  curl -fL --progress-bar -o "libs/$JAR" "https://github.com/cabaletta/baritone/releases/download/v$BARITONE/$JAR"
  echo "$BARITONE_SHA1  libs/$JAR" | sha1sum -c --quiet
fi

echo "building the bridge mod (first run downloads Minecraft mappings, ~2 min)…"
./gradlew build --no-daemon -q
BRIDGE=$(ls build/libs/justday-bridge-*.jar | grep -v sources | head -1)

# ── where to install ──
targets=()
if [[ $# -gt 0 ]]; then
  targets=("$1")
else
  if ls "$HOME/.minecraft/versions" 2>/dev/null | grep -q 'fabric-loader-.*-1\.21\.10$'; then targets+=("$HOME/.minecraft/mods"); fi
  for inst in "$HOME"/.local/share/PrismLauncher/instances/*/; do
    pack="$inst/mmc-pack.json"
    [[ -f "$pack" ]] || continue
    if grep -q '"net.fabricmc.fabric-loader"' "$pack" && grep -q '"1.21.10"' "$pack"; then targets+=("$inst/minecraft/mods"); fi
  done
fi
if [[ ${#targets[@]} -eq 0 ]]; then
  echo "Не нашёл Minecraft 1.21.10 с Fabric. Укажите папку mods: minecraft/install.sh ~/.minecraft/mods" >&2
  exit 1
fi
for dir in "${targets[@]}"; do
  mkdir -p "$dir"
  rm -f "$dir"/justday-bridge-*.jar
  cp "$BRIDGE" "$dir/"
  if ! ls "$dir" | grep -qi '^baritone'; then cp "libs/$JAR" "$dir/"; fi
  if ! ls "$dir" | grep -qi '^fabric-api'; then echo "  внимание: в $dir нет Fabric API — мост без него не запустится"; fi
  echo "✓ $dir"
done
echo "Перезапустите Minecraft. Проверка: justday mc ping"
