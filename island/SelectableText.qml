// Текст, который можно выделить и забрать себе.
//
// Почему не Text. Обычный Text в QML не выделяется вовсе: он нарисован, как картинка. Для подписи
// это правильно, а для ответа ассистента — нет: в ответе бывает команда, ссылка, имя файла, адрес,
// и человеку нужен кусок, а не всё целиком. Кнопка «скопировать всё» этого не заменяет — из неё
// потом всё равно вырезают руками в другом окне.
//
// Поэтому здесь TextEdit, которому запрещено редактировать. Снаружи он выглядит ровно как Text:
// тот же шрифт, тот же цвет, тот же перенос. Разница одна — по нему можно провести мышью.
//
// Выделение не пропадает, когда островок теряет фокус (persistentSelection). Островок — слой, и
// клавиатура ему достаётся редко; выделение, исчезающее от того, что человек отвёл взгляд на своё
// окно, было бы выделением, которым нельзя воспользоваться.
import QtQuick
import Quickshell

TextEdit {
    id: st

    readOnly: true
    selectByMouse: true
    persistentSelection: true
    wrapMode: Text.Wrap
    textFormat: Text.PlainText
    font.family: JD.fontFamily
    font.pixelSize: 15
    color: JD.text1
    selectionColor: Qt.rgba(JD.accentBlue.r, JD.accentBlue.g, JD.accentBlue.b, 0.42)
    selectedTextColor: JD.text1
    activeFocusOnPress: true

    readonly property bool picked: selectionStart !== selectionEnd

    // Ctrl+C работает, только когда островку досталась клавиатура, а достаётся она ему не всегда:
    // это слой поверх чужих окон, и фокус у него бывает только в полях ввода. Поэтому главный путь
    // — кнопка рядом с выделением, а эта привязка просто не мешает тем, у кого фокус есть.
    Keys.onPressed: event => {
        if (event.key === Qt.Key_C && (event.modifiers & Qt.ControlModifier)) {
            st.take()
            event.accepted = true
        }
    }

    // Забрать выделенное, а если ничего не выделено — всё.
    function take() {
        const what = picked ? selectedText : text
        if (!what) return
        Quickshell.execDetached(["wl-copy", "--", what])
        JD.flash(picked ? "Скопировано выделенное" : "Скопировано", "edit-copy", JD.accentGreen)
    }

    // Где нарисовать кнопку: над началом выделения, но не левее края и не выше его.
    readonly property rect pickRect: picked ? positionToRectangle(selectionStart) : Qt.rect(0, 0, 0, 0)
}
