package ru.onigiri.remo32;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * Оболочка вокруг веб-интерфейса JustDay.
 *
 * Приложение намеренно тонкое: вся логика живёт в контроллере на домашнем ПК,
 * и дублировать её здесь означало бы иметь две расходящиеся версии. Задача
 * оболочки — значок на экране, полный экран без адресной строки и адрес,
 * который не нужно набирать каждый раз.
 */
public class MainActivity extends Activity {

    /**
     * Адрес по умолчанию.
     *
     * В исходнике намеренно стоит заглушка: настоящий тайлнет-адрес — это
     * адрес конкретного дома, и в репозитории ему не место. Сборщик
     * подставляет сюда значение из REMO32_URL или из android/url.txt
     * (оба в git не идут). Если не подставить — приложение просто покажет
     * экран настройки и попросит ввести адрес руками.
     */
    private static final String DEFAULT_URL = "http://remo32.example:8080/";

    private static final String PREFS = "remo32";
    private static final String KEY_URL = "url";

    private static final int ASK_MIC = 1;

    private WebView web;
    private FrameLayout root;
    private View errorView;
    private boolean updateChecked;

    /** Просьба страницы о микрофоне, отложенная до ответа системы. */
    private PermissionRequest micRequest;

    @Override
    @SuppressLint("SetJavaScriptEnabled")
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);

        root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#000000"));
        setContentView(root);

        web = new WebView(this);
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        // Без этого не работает localStorage, а в нём живут избранные кнопки
        // и выбранная вкладка — без него приложение забывало бы настройки
        // при каждом запуске.
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setMediaPlaybackRequiresUserGesture(false);
        // Интерфейс сам задаёт масштаб через viewport; системное укрупнение
        // шрифта ломало бы сетку пульта.
        s.setTextZoom(100);

        web.setBackgroundColor(Color.parseColor("#000000"));
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);

        // Микрофон странице сам по себе не достаётся: сначала разрешение у
        // системы, и только потом — у WebView. Спрашиваем ровно в тот момент,
        // когда человек нажал кнопку голоса, а не при запуске приложения.
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                boolean wantsMic = false;
                for (String resource : request.getResources()) {
                    if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resource)) {
                        wantsMic = true;
                    }
                }
                if (!wantsMic) {
                    // Камеру и всё остальное страница не просит — и не получит.
                    request.deny();
                    return;
                }
                if (Build.VERSION.SDK_INT < 23
                        || checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                           == PackageManager.PERMISSION_GRANTED) {
                    request.grant(new String[] {PermissionRequest.RESOURCE_AUDIO_CAPTURE});
                    return;
                }
                micRequest = request;
                requestPermissions(new String[] {Manifest.permission.RECORD_AUDIO}, ASK_MIC);
            }

            @Override
            public void onPermissionRequestCanceled(PermissionRequest request) {
                micRequest = null;
            }
        });

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                // Всё в пределах своего адреса открываем внутри; чужие ссылки
                // тут появиться не должны, но если появятся — не уводим
                // пользователя из приложения молча.
                return false;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    showError(String.valueOf(error.getDescription()));
                }
            }

            @Override
            public void onPageFinished(WebView view, String loadedUrl) {
                // Проверяем обновление после загрузки страницы, а не до неё:
                // к этому моменту в CookieManager уже лежит сессия, а пульт
                // на экране — то есть проверка ничего не задерживает.
                // Один раз за запуск: спрашивать при каждом возврате на
                // вкладку значило бы дёргать сервер без повода.
                if (!updateChecked) {
                    updateChecked = true;
                    new Updater(MainActivity.this, url()).check(false);
                }
            }
        });

        // Экран не гаснет, пока приложение открыто: пульт держат в руке и
        // смотрят на него, а не листают — системный таймер гасил бы его
        // прямо посреди нажатия.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        if (Build.VERSION.SDK_INT >= 28) {
            getWindow().getAttributes().layoutInDisplayCutoutMode =
                    WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
        }

        web.loadUrl(url());
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        if (code != ASK_MIC) {
            super.onRequestPermissionsResult(code, permissions, results);
            return;
        }
        PermissionRequest request = micRequest;
        micRequest = null;
        if (request == null) return;
        if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) {
            request.grant(new String[] {PermissionRequest.RESOURCE_AUDIO_CAPTURE});
        } else {
            // Отказ — тоже ответ: страница покажет свою подсказку, а не
            // останется ждать разрешения, которого не будет.
            request.deny();
        }
    }

    private String url() {
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        return prefs.getString(KEY_URL, DEFAULT_URL);
    }

    /**
     * Экран «не достучались». Показывает адрес и даёт его исправить: без
     * этого при переезде сети приложение осталось бы навсегда сломанным,
     * и починить его было бы можно только пересборкой.
     */
    private void showError(String message) {
        if (errorView != null) return;

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setBackgroundColor(Color.parseColor("#000000"));
        int pad = (int) (24 * getResources().getDisplayMetrics().density);
        box.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("Не удалось открыть JustDay");
        title.setTextColor(Color.parseColor("#E6E9EF"));
        title.setTextSize(18);
        title.setGravity(Gravity.CENTER);

        TextView hint = new TextView(this);
        hint.setText(message + "\n\nПроверь, включён ли Tailscale и работает ли домашний ПК.");
        hint.setTextColor(Color.parseColor("#9AA4B2"));
        hint.setTextSize(13);
        hint.setGravity(Gravity.CENTER);
        hint.setPadding(0, pad / 2, 0, pad);

        final EditText field = new EditText(this);
        field.setText(url());
        field.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        field.setTextColor(Color.parseColor("#E6E9EF"));
        field.setSingleLine(true);

        Button retry = new Button(this);
        retry.setText("Сохранить и открыть");
        retry.setOnClickListener(v -> {
            String value = field.getText().toString().trim();
            if (!value.isEmpty()) {
                getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_URL, value).apply();
            }
            hideError();
            web.loadUrl(url());
        });

        Button update = new Button(this);
        update.setText("Проверить обновление");
        update.setOnClickListener(v -> new Updater(this, field.getText().toString().trim()).check(true));

        box.addView(title);
        box.addView(hint);
        box.addView(field);
        box.addView(retry);
        box.addView(update);

        errorView = box;
        root.addView(errorView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    private void hideError() {
        if (errorView != null) {
            root.removeView(errorView);
            errorView = null;
        }
    }

    @Override
    public void onBackPressed() {
        // Кнопка «назад» ходит по вкладкам интерфейса, потому что они живут
        // в адресе. Выходим только с самого первого экрана.
        if (errorView == null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
