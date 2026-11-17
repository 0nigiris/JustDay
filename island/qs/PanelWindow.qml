import QtQuick
import QtQuick.Window
import Quickshell
import Quickshell.Wayland

// PanelWindow без Wayland: безрамочное окно поверх всех, прижатое к краям экрана, как слой.
// Корень — не Window: у слоя Quickshell свой `screen` (с x/y/width/height) и `anchors` из флагов,
// а у Window свои с другим смыслом. Окно живёт внутри и подстраивается под эти свойства.
QtObject {
    id: pw
    property var screen: Quickshell.screens[0]
    property EdgeFlags anchors: EdgeFlags {}
    property Edges margins: Edges {}
    property int exclusionMode
    property int exclusiveZone
    property bool visible: true
    property color color: "white"
    property string title: "JustDay"
    property real implicitWidth: 0
    property real implicitHeight: 0
    property Region mask: null
    readonly property real width: w.width
    readonly property real height: w.height
    readonly property alias contentItem: w.contentItem
    readonly property Window window: w
    default property alias data: w.data

    // При выходе экраны разбираются раньше окон: без запасного значения каждое окно сыпало TypeError.
    readonly property var _s: screen || Quickshell.screens[0] || ({ name: "", x: 0, y: 0, width: 1, height: 1 })
    readonly property bool _wide: anchors.left && anchors.right
    readonly property bool _tall: anchors.top && anchors.bottom

    property Window _w: Window {
        id: w
        screen: pw._s ? Qt.application.screens.find(s => s.name === pw._s.name) || null : null
        flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
               | (pw.WlrLayershell.keyboardFocus === WlrKeyboardFocus.None ? Qt.WindowDoesNotAcceptFocus : 0)
        color: pw.color
        title: pw.title
        visible: pw.visible
        width: pw._wide ? pw._s.width - pw.margins.left - pw.margins.right : Math.max(1, pw.implicitWidth)
        height: pw._tall ? pw._s.height - pw.margins.top - pw.margins.bottom : Math.max(1, pw.implicitHeight)
        x: pw._s.x + (pw.anchors.left ? pw.margins.left
                      : pw.anchors.right ? pw._s.width - width - pw.margins.right
                      : (pw._s.width - width) / 2)
        y: pw._s.y + (pw.anchors.top ? pw.margins.top
                      : pw.anchors.bottom ? pw._s.height - height - pw.margins.bottom
                      : (pw._s.height - height) / 2)
        onVisibleChanged: if (visible && pw.WlrLayershell.keyboardFocus === WlrKeyboardFocus.Exclusive) requestActivate()
    }

    // Маска: щелчки проходят сквозь окно везде, кроме описанных областей (на Windows — через setMask).
    function _rects(r, out) {
        // ponytail: вычитаемые области (дыры) пропускаем целиком, а не вырезаем; нужно только меню дока.
        if (!r || r.intersection === Intersection.Subtract) return out
        if (r.item && r.item.visible) {
            const p = r.item.mapToItem(w.contentItem, 0, 0)
            out.push([p.x, p.y, r.item.width, r.item.height])
        } else if (r.width > 0 && r.height > 0) out.push([r.x, r.y, r.width, r.height])
        for (let i = 0; i < r.regions.length; ++i) _rects(r.regions[i], out)
        return out
    }
    property Timer _maskTick: Timer {
        interval: 100; repeat: true; running: w.visible && pw.mask !== null
        onTriggered: Quickshell.setMask(w, pw._rects(pw.mask, []))
    }
}
