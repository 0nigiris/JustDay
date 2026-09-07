package ru.onigiri.remo32;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;

import java.io.File;
import java.io.FileNotFoundException;

/**
 * Отдаёт скачанный APK системному установщику.
 *
 * Начиная с Android 7 передать другому приложению ссылку {@code file://}
 * нельзя — система роняет процесс с FileUriExposedException. Нужен
 * провайдер, выдающий {@code content://}.
 *
 * Обычно для этого берут {@code androidx.core.content.FileProvider}, но
 * androidx означает Gradle и полтора десятка зависимостей ради одного
 * класса, а всё приложение здесь собирается четырьмя вызовами SDK. Свой
 * провайдер занимает меньше, чем заняло бы описание этой зависимости.
 *
 * Наружу видно ровно одно: каталог {@code updates} внутри приватных файлов
 * приложения, только на чтение.
 */
public class UpdateProvider extends ContentProvider {

    public static final String AUTHORITY = "ru.onigiri.remo32.updates";

    /** Каталог, в который скачиваются обновления. Единственный, что виден. */
    public static File updatesDir(android.content.Context context) {
        File dir = new File(context.getFilesDir(), "updates");
        //noinspection ResultOfMethodCallIgnored
        dir.mkdirs();
        return dir;
    }

    public static Uri uriFor(String fileName) {
        return Uri.parse("content://" + AUTHORITY + "/" + Uri.encode(fileName));
    }

    /**
     * Имя файла из адреса — только имя.
     *
     * {@code new File(name).getName()} отсекает любые «..» и каталоги: без
     * этого адрес вида {@code content://.../../../databases/x} увёл бы
     * читателя за пределы каталога обновлений.
     */
    private File resolve(Uri uri) throws FileNotFoundException {
        String last = uri.getLastPathSegment();
        if (last == null || last.isEmpty()) {
            throw new FileNotFoundException("пустой адрес");
        }
        File file = new File(updatesDir(getContext()), new File(last).getName());
        if (!file.isFile()) {
            throw new FileNotFoundException("нет файла: " + file.getName());
        }
        return file;
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        // Только чтение: писать сюда снаружи незачем.
        return ParcelFileDescriptor.open(resolve(uri), ParcelFileDescriptor.MODE_READ_ONLY);
    }

    /**
     * Установщик перед показом окна спрашивает имя и размер. Без ответа он
     * молча закрывается, поэтому запрос обязателен.
     */
    @Override
    public Cursor query(Uri uri, String[] projection, String selection,
                        String[] selectionArgs, String sortOrder) {
        File file;
        try {
            file = resolve(uri);
        } catch (FileNotFoundException e) {
            return null;
        }
        String[] columns = {OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE};
        MatrixCursor cursor = new MatrixCursor(columns, 1);
        cursor.addRow(new Object[]{file.getName(), file.length()});
        return cursor;
    }

    @Override
    public String getType(Uri uri) {
        return "application/vnd.android.package-archive";
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        return null;
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        return 0;
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        return 0;
    }
}
