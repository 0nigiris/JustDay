import QtQuick

// Один ползунок на плеер, громкость и настройки. Раньше их было три (SeekBar, VolumeRow, SSlider) — у
// каждого свои высота, ручка, кривая и обработка мыши, и у настроек клавиатура работала, а у плеера нет.
// Название не `Slider`: в SettingsView подключён QtQuick.Controls с таким же типом.
Item {
    id: sl
    property real value: 0
    property real from: 0
    property real to: 1
    property real stepSize: 0           // 0 — плавно, иначе значение липнет к шагу
    property color tint: JD.text1
    property color rail: JD.fill2
    property int thickness: 5           // дорожка громкости тоньше: это не ход чего-то
    property bool knob: false
    // Со live=true значение уходит с каждым шагом мыши (громкость), но не чаще раза в 50 мс: демон на
    // каждое пересобирал настройки (Р-31); без него — один раз, при отпускании (перемотка, настройки).
    property bool live: false
    property bool dragging: false
    property real dragValue: 0
    signal moved(real v)
    readonly property real shown: Math.max(from, Math.min(to, dragging ? dragValue : value))
    readonly property real fraction: to > from ? (shown - from) / (to - from) : 0
    readonly property bool active: hover.hovered || dragging

    function snap(frac) {
        const raw = from + Math.max(0, Math.min(1, frac)) * (to - from)
        return stepSize > 0 ? Math.max(from, Math.min(to, from + Math.round((raw - from) / stepSize) * stepSize)) : raw
    }
    // Клавиатура: без неё ползунком нельзя пользоваться без мыши. Шаг — свой или двадцатая часть хода.
    function nudge(dir) {
        const step = stepSize > 0 ? stepSize : (to - from) / 20
        const v = Math.max(from, Math.min(to, shown + dir * step))
        if (v !== value) moved(v)
    }

    implicitHeight: 16
    activeFocusOnTab: true
    Keys.onLeftPressed: nudge(-1)
    Keys.onDownPressed: nudge(-1)
    Keys.onRightPressed: nudge(1)
    Keys.onUpPressed: nudge(1)

    Timer {
        id: throttle
        property real pending: NaN
        interval: 50
        onTriggered: if (!isNaN(pending)) { const v = pending; pending = NaN; sl.moved(v) }
    }

    Rectangle {
        id: track
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width
        height: sl.active ? sl.thickness + 2 : sl.thickness
        radius: height / 2
        color: sl.rail
        Behavior on height { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
        Rectangle {
            width: parent.width * sl.fraction
            height: parent.height
            radius: parent.radius
            color: sl.tint
            Behavior on width { enabled: JD.animOn && !sl.dragging; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
        }
    }
    // ручка: где значение и за что взяться
    Rectangle {
        visible: sl.knob
        width: sl.active ? 18 : 14; height: width; radius: width / 2
        x: Math.max(0, Math.min(sl.width - width, sl.width * sl.fraction - width / 2))
        anchors.verticalCenter: parent.verticalCenter
        color: "#f5f5f7"
        border.width: sl.activeFocus ? 2 : 0
        border.color: JD.accentBlue
        Behavior on width { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
        Behavior on x { enabled: JD.animOn && !sl.dragging; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
    }
    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    MouseArea {
        anchors.fill: parent
        function at(x) { return sl.snap(x / width) }
        onPressed: m => { sl.forceActiveFocus(); sl.dragValue = at(m.x); sl.dragging = true; sl.step() }
        onPositionChanged: m => { if (pressed) { sl.dragValue = at(m.x); sl.step() } }
        onReleased: {
            throttle.stop(); throttle.pending = NaN
            const v = sl.dragValue
            sl.moved(v)
            sl.dragging = false
        }
    }
    function step() {
        if (!live) return
        throttle.pending = dragValue
        if (!throttle.running) throttle.start()
    }
}
