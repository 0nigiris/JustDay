package ru.onigiri.remo32;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.webkit.CookieManager;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.util.concurrent.Executors;

/**
 * Обновление приложения без магазина.
 *
 * Приложение спрашивает у своего же контроллера, какая версия лежит там,
 * сравнивает с собственной и, если серверная новее, предлагает поставить.
 * Установку в любом случае подтверждает человек: тихо поставить APK без
 * системных прав нельзя, и это правильно.
 *
 * Почему это вообще понадобилось: раньше каждая сборка выходила с
 * versionCode = 1, Android считал её той же самой версией, и обновление
 * превращалось в «удалить приложение, скачать файл, найти его в загрузках,
 * разрешить установку». Теперь версия растёт сама, а телефон замечает
 * новую при запуске.
 */
final class Updater {

    private static final String TAG = "remo32.update";

    /** Проверка не должна мешать запуску: пульт нужен сразу. */
    private static final int CONNECT_TIMEOUT_MS = 4000;
    private static final int READ_TIMEOUT_MS = 30000;

    private final Activity activity;
    private final String baseUrl;
    private final Handler ui = new Handler(Looper.getMainLooper());

    Updater(Activity activity, String baseUrl) {
        this.activity = activity;
        this.baseUrl = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
    }

    /**
     * Проверить в фоне и, если есть новее, предложить обновиться.
     *
     * @param loud true — сообщать и когда обновлений нет (нажали «проверить»
     *             вручную); false — молчать, чтобы не мешать запуску.
     */
    void check(final boolean loud) {
        Executors.newSingleThreadExecutor().execute(() -> {
            try {
                JSONObject release = fetchJson(baseUrl + "/api/app/latest");
                if (release == null) {
                    if (loud) toast("Сервер не ответил про версию");
                    return;
                }
                final int serverCode = release.optInt("version_code", 0);
                final String serverName = release.optString("version_name", "?");
                final int myCode = currentVersionCode();

                Log.i(TAG, "версия на сервере " + serverCode + ", у нас " + myCode);

                if (serverCode <= myCode) {
                    if (loud) toast("Установлена последняя версия");
                    return;
                }
                ui.post(() -> offer(release, serverName, serverCode));
            } catch (Exception e) {
                Log.w(TAG, "проверка обновления не удалась: " + e);
                if (loud) toast("Не удалось проверить обновление");
            }
        });
    }

    private int currentVersionCode() {
        try {
            PackageInfo info = activity.getPackageManager()
                    .getPackageInfo(activity.getPackageName(), 0);
            if (Build.VERSION.SDK_INT >= 28) {
                return (int) info.getLongVersionCode();
            }
            //noinspection deprecation
            return info.versionCode;
        } catch (PackageManager.NameNotFoundException e) {
            return 0;
        }
    }

    private void offer(final JSONObject release, String versionName, final int code) {
        long size = release.optLong("size_bytes", 0);
        String sizeText = size > 0 ? String.format(" (%.1f МБ)", size / 1048576.0) : "";

        new AlertDialog.Builder(activity)
                .setTitle("Новая версия " + versionName)
                .setMessage("Скачать и установить" + sizeText + "?\n\n"
                        + "Удалять старую не нужно: подпись та же, поставится поверх.")
                .setPositiveButton("Обновить", (d, w) -> download(release, code))
                .setNegativeButton("Потом", null)
                .show();
    }

    private void download(final JSONObject release, final int code) {
        final AlertDialog progress = new AlertDialog.Builder(activity)
                .setTitle("Загрузка")
                .setMessage("Качаю новую версию…")
                .setCancelable(false)
                .create();
        progress.show();

        Executors.newSingleThreadExecutor().execute(() -> {
            String error = null;
            File target = null;
            try {
                File dir = UpdateProvider.updatesDir(activity);
                // Старые загрузки не копим: файл каждый раз один и тот же.
                File[] old = dir.listFiles();
                if (old != null) {
                    for (File f : old) {
                        //noinspection ResultOfMethodCallIgnored
                        f.delete();
                    }
                }
                target = new File(dir, "remo32-" + code + ".apk");
                downloadTo(baseUrl + "/api/app/download", target);

                String expected = release.optString("sha256", "");
                if (!expected.isEmpty()) {
                    String actual = sha256(target);
                    if (!expected.equalsIgnoreCase(actual)) {
                        // Оборванная закачка выглядит как обычный файл, и
                        // установщик покажет «пакет повреждён» без объяснений.
                        //noinspection ResultOfMethodCallIgnored
                        target.delete();
                        error = "Файл скачался повреждённым. Попробуйте ещё раз.";
                    }
                }
            } catch (Exception e) {
                Log.w(TAG, "загрузка не удалась: " + e);
                error = "Не удалось скачать: " + e.getMessage();
            }

            final String problem = error;
            final File file = target;
            ui.post(() -> {
                progress.dismiss();
                if (problem != null) {
                    new AlertDialog.Builder(activity)
                            .setTitle("Не вышло")
                            .setMessage(problem)
                            .setPositiveButton("Ладно", null)
                            .show();
                    return;
                }
                install(file);
            });
        });
    }

    private void install(File apk) {
        // На Android 8+ разрешение «устанавливать неизвестные приложения»
        // выдаётся не при установке, а по требованию — и только пользователем.
        if (Build.VERSION.SDK_INT >= 26 && !activity.getPackageManager().canRequestPackageInstalls()) {
            new AlertDialog.Builder(activity)
                    .setTitle("Нужно разрешение")
                    .setMessage("Android просит разрешить установку приложений из JustDay. "
                            + "Сейчас откроются настройки — включите переключатель и вернитесь назад.")
                    .setPositiveButton("Открыть настройки", (d, w) -> {
                        Intent intent = new Intent(
                                android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                Uri.parse("package:" + activity.getPackageName()));
                        activity.startActivity(intent);
                    })
                    .setNegativeButton("Отмена", null)
                    .show();
            return;
        }

        Intent intent = new Intent(Intent.ACTION_VIEW);
        intent.setDataAndType(UpdateProvider.uriFor(apk.getName()),
                "application/vnd.android.package-archive");
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
        activity.startActivity(intent);
    }

    // --- сеть ---------------------------------------------------------------

    /**
     * Запрос с теми же cookie, что и у веб-интерфейса.
     *
     * Раздача APK требует входа, как и всё остальное на контроллере. Сессия
     * уже есть — она лежит в CookieManager после входа в самом интерфейсе,
     * и её достаточно переложить в заголовок.
     */
    private HttpURLConnection open(String url) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
        connection.setReadTimeout(READ_TIMEOUT_MS);
        String cookie = CookieManager.getInstance().getCookie(url);
        if (cookie != null && !cookie.isEmpty()) {
            connection.setRequestProperty("Cookie", cookie);
        }
        return connection;
    }

    private JSONObject fetchJson(String url) throws Exception {
        HttpURLConnection connection = open(url);
        try {
            if (connection.getResponseCode() != 200) {
                Log.w(TAG, "ответ " + connection.getResponseCode() + " на " + url);
                return null;
            }
            StringBuilder body = new StringBuilder();
            try (InputStream in = connection.getInputStream()) {
                byte[] buffer = new byte[4096];
                int read;
                while ((read = in.read(buffer)) > 0) {
                    body.append(new String(buffer, 0, read, "UTF-8"));
                }
            }
            JSONObject envelope = new JSONObject(body.toString());
            if (!envelope.optBoolean("ok", false)) return null;
            return envelope.optJSONObject("data");
        } finally {
            connection.disconnect();
        }
    }

    private void downloadTo(String url, File target) throws Exception {
        HttpURLConnection connection = open(url);
        try {
            if (connection.getResponseCode() != 200) {
                throw new IllegalStateException("сервер ответил " + connection.getResponseCode());
            }
            try (InputStream in = connection.getInputStream();
                 FileOutputStream out = new FileOutputStream(target)) {
                byte[] buffer = new byte[65536];
                int read;
                while ((read = in.read(buffer)) > 0) {
                    out.write(buffer, 0, read);
                }
                out.getFD().sync();
            }
        } finally {
            connection.disconnect();
        }
    }

    private static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream in = new java.io.FileInputStream(file)) {
            byte[] buffer = new byte[65536];
            int read;
            while ((read = in.read(buffer)) > 0) {
                digest.update(buffer, 0, read);
            }
        }
        StringBuilder hex = new StringBuilder();
        for (byte b : digest.digest()) {
            hex.append(String.format("%02x", b));
        }
        return hex.toString();
    }

    private void toast(final String text) {
        ui.post(() -> android.widget.Toast.makeText(activity, text,
                android.widget.Toast.LENGTH_SHORT).show());
    }
}
