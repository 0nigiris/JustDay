#!/usr/bin/env bash
# Сборка APK без Gradle — прямо инструментами Android SDK.
#
# Gradle тянул бы зависимости из сети при каждой сборке и добавил бы
# несколько сотен мегабайт кэша ради приложения из одного класса. Здесь
# ровно четыре шага: ресурсы, компиляция, dex, подпись.
set -euo pipefail

SDK="${ANDROID_HOME:-$HOME/Android/Sdk}"
BT="$(ls -d "$SDK"/build-tools/* | sort -V | tail -1)"
PLATFORM="$(ls -d "$SDK"/platforms/android-* | sort -V | tail -1)"
JAR="$PLATFORM/android.jar"

HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$HERE/build"
DIST="$HERE/dist"
KEYSTORE="$HERE/remo32.keystore"

[ -f "$JAR" ] || { echo "нет android.jar: $JAR" >&2; exit 1; }

echo "SDK      : $SDK"
echo "инструмен: $(basename "$BT")"
echo "платформа: $(basename "$PLATFORM")"

rm -rf "$OUT"
mkdir -p "$OUT/res" "$OUT/gen" "$OUT/classes" "$DIST"

# 1. Ресурсы: компиляция и связывание. aapt2 заодно порождает R.java.
"$BT/aapt2" compile --dir "$HERE/res" -o "$OUT/res.zip"
"$BT/aapt2" link \
    -o "$OUT/base.apk" \
    -I "$JAR" \
    --manifest "$HERE/AndroidManifest.xml" \
    --java "$OUT/gen" \
    --min-sdk-version 26 \
    --target-sdk-version 36 \
    --version-code "${VERSION_CODE:-1}" \
    --version-name "${VERSION_NAME:-1.0}" \
    "$OUT/res.zip"

# 2. Подстановка адреса. В исходнике стоит заглушка: тайлнет-адрес — это
#    адрес конкретного дома, и в репозитории ему не место. Компилируем копию,
#    а не оригинал, чтобы рабочая копия оставалась чистой.
cp -r "$HERE/java" "$OUT/src"
URL="${REMO32_URL:-}"
if [ -z "$URL" ] && [ -f "$HERE/url.txt" ]; then
    URL="$(tr -d '[:space:]' < "$HERE/url.txt")"
fi
if [ -n "$URL" ]; then
    grep -rl 'http://remo32.example:8080/' "$OUT/src" \
        | xargs sed -i "s|http://remo32.example:8080/|$URL|g"
    echo "адрес    : $URL"
else
    echo "адрес    : не задан — приложение спросит его при первом запуске"
fi

# 3. Компиляция. --release задаёт версию байткода: d8 не примет свежий
#    формат от нового javac, а он тут заведомо новее Android.
javac --release 17 \
    -classpath "$JAR" \
    -d "$OUT/classes" \
    -nowarn \
    $(find "$OUT/src" "$OUT/gen" -name '*.java')

# 4. Байткод JVM -> dex.
"$BT/d8" --release --min-api 26 --lib "$JAR" \
    --output "$OUT" \
    $(find "$OUT/classes" -name '*.class')

# 5. Складываем dex в apk, выравниваем и подписываем.
cp "$OUT/base.apk" "$OUT/unsigned.apk"
(cd "$OUT" && zip -q -X "unsigned.apk" classes.dex)
"$BT/zipalign" -f -p 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"

if [ ! -f "$KEYSTORE" ]; then
    echo "создаю ключ подписи (одноразово, лежит рядом и в git не идёт)"
    keytool -genkeypair -v \
        -keystore "$KEYSTORE" \
        -alias remo32 \
        -keyalg RSA -keysize 2048 -validity 10950 \
        -storepass remo32keystore -keypass remo32keystore \
        -dname "CN=Remo32, OU=home, O=Remo32, L=-, S=-, C=RO" >/dev/null
fi

"$BT/apksigner" sign \
    --ks "$KEYSTORE" \
    --ks-pass pass:remo32keystore \
    --key-pass pass:remo32keystore \
    --out "$DIST/remo32.apk" \
    "$OUT/aligned.apk"

"$BT/apksigner" verify --print-certs "$DIST/remo32.apk" >/dev/null
echo
echo "готово: $DIST/remo32.apk  ($(du -h "$DIST/remo32.apk" | cut -f1))"
