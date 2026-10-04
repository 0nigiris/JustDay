// The content of one island state: it rides the island's growth — fading in over the last part of it.
import QtQuick

Item {
    id: view
    property bool shown: false
    // how far the island has grown towards this view's size (the island springs, the content rides along):
    // the content fades in over the last part of the growth and settles from 94 % to full size with it
    readonly property real fit: Math.min(1, parent.width / Math.max(1, implicitWidth), parent.height / Math.max(1, implicitHeight))
    // Сплошная полоса открывает карточку обрезкой сверху вниз. Пока высота догоняет содержимое,
    // fit маленький — и обычный reveal гасил бы его до нуля, карточка «пропадает» на полпути.
    readonly property bool barSlide: JD.islandStyle === "bar" && (JD.settingsOpen || JD.expanded || (parent !== null && parent.objectName === "dropCard"))
    // Карточка уже открыта: смена страницы (настройки ↔ виджеты) должна таять, а не вспыхивать.
    readonly property bool cardSettled: parent !== null && parent.objectName === "dropCard" && parent.grow > 48
    readonly property real reveal: barSlide ? 1 : (JD.animOn ? Math.max(0, Math.min(1, (fit - 0.55) / 0.4)) : 1)
    property real fade: shown ? 1 : 0
    Behavior on fade {
        enabled: JD.animOn && (!barSlide || cardSettled)
        NumberAnimation { duration: view.cardSettled ? JD.slideMs : (view.shown ? 160 : 100); easing.type: Easing.OutCubic }
    }
    anchors.top: parent.top
    anchors.horizontalCenter: parent.horizontalCenter
    width: implicitWidth
    height: implicitHeight
    transformOrigin: Item.Top
    opacity: shown ? fade * reveal : fade
    scale: barSlide ? 1 : (0.94 + 0.06 * (shown ? reveal : fade))
    visible: opacity > 0.01
}

// put `TextSwap on text {}` on a Text: a new text fades out the old one and fades itself in
