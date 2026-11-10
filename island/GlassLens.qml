// Линза «жидкого стекла» (п. 36, 10 нояб.: «ЭТО ЖИДКОЕ СТЕКЛО… хорошо на всех обоях»).
// Кладётся в карточку под значки. Показывает обои рабочего стола так, будто карточка — капля:
// середина чуть увеличена и размыта, край загибает картинку внутрь и расходится радугой.
// Обои берутся из настроек Plasma, поэтому линза сама меняется вместе с ними.
//
// Wayland не показывает нам окна под доком, поэтому, когда под карточкой окно (covered), линза
// растворяется и остаётся прежний тёмный оттенок карточки — иначе на окне были бы «обои».
pragma ComponentBehavior: Bound
import QtQuick

ShaderEffect {
    id: lens
    property real radius: 0
    property real dim: 0.62
    // Экран, на котором лежит карточка: тогда линза сама гаснет над окнами. Док отвечает за это
    // сам (его правило про перекрытие точнее) и экран не даёт.
    property var screen: null
    property bool covered: screen ? JD.rectCoveredOn(screen, at.x, at.y, width, height) : false
    property bool primary: true
    property real screenW: 1920
    property real screenH: 1080
    // Положение карточки на экране. mapToItem не следит за движением — его зовут снаружи.
    property point at: Qt.point(0, 0)

    readonly property var wall: JD.wallpaperFor(primary)
    readonly property bool ready: JD.glassOn && wall !== null && wallImg.status === Image.Ready
    anchors.fill: parent
    visible: opacity > 0.01
    opacity: ready && !covered ? 1 : 0
    Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durSlow; easing.type: Easing.OutCubic } }

    Image {
        id: wallImg
        visible: false
        asynchronous: true
        source: lens.wall ? lens.wall.src : ""
        sourceSize.width: Math.round(lens.screenW)
    }
    property variant wallTex: wallImg

    // Где лежат обои на экране. Plasma: 0 — растянуть, 1 — вписать, остальное считаем
    // «заполнить с обрезкой» (2, её умолчание).
    readonly property vector4d img: {
        const iw = Math.max(1, wallImg.implicitWidth), ih = Math.max(1, wallImg.implicitHeight)
        const fill = wall ? wall.fill : 2
        if (fill === 0) return Qt.vector4d(0, 0, screenW, screenH)
        const k = fill === 1 ? Math.min(screenW / iw, screenH / ih) : Math.max(screenW / iw, screenH / ih)
        return Qt.vector4d((screenW - iw * k) / 2, (screenH - ih * k) / 2, iw * k, ih * k)
    }

    readonly property size size: Qt.size(width, height)
    readonly property point origin: at
    readonly property real bezel: Math.min(height * 0.42, 22)

    // Рябь: карточка поменяла размер или выехала — по стеклу пробегает волна и стихает.
    property real wobble: 0
    property real time: 0
    function kick() {
        if (!JD.animOn || !visible) return
        settle.restart()
    }
    NumberAnimation { id: settle; target: lens; property: "wobble"; from: 0.9; to: 0; duration: 900; easing.type: Easing.OutCubic }
    NumberAnimation on time { running: lens.wobble > 0.001; from: 0; to: 1000; duration: 1000000; loops: Animation.Infinite }

    fragmentShader: Qt.resolvedUrl("shaders/lens.frag.qsb")
}
