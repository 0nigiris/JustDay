// Анимированный значок Kubai Icons (MIT): полоска кадров из scripts/kubai-sprites.mjs. Наведение
// листает её вперёд, уход — назад. Нет полоски для этого имени и цвета (свой цвет акцента, новый
// значок) — ok = false, и плитка рисует прежний штриховой значок.
import QtQuick
import "icons/kubai/list.js" as K

Item {
    id: k
    property string name: ""
    property color color: "#8e8e93"
    property bool hovered: false
    readonly property string base: JD.glyph(name) || name
    readonly property string exact: base + "-" + String(color).slice(1, 7)
    // Свой цвет акцента (Настройки → Остров) — полоски под каждый оттенок не держим, берём синюю
    readonly property string key: K.have[exact] ? exact : base + "-0a84ff"
    readonly property bool ok: K.have[key] === true
    property real p: hovered ? 1 : 0
    Behavior on p { enabled: JD.animOn; NumberAnimation { duration: JD.durSlow; easing.type: JD.easeOut } }
    Image {
        anchors.fill: parent
        visible: k.ok
        source: k.ok ? "icons/kubai/" + k.key + ".png" : ""
        sourceClipRect: Qt.rect(Math.round(k.p * (K.frames - 1)) * K.size, 0, K.size, K.size)
        smooth: true; mipmap: true
    }
}
