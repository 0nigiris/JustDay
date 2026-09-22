// One icon language for the whole island: lucide strokes from island/icons (JD.glyphs),
// with the desktop's own icon theme left for the things the theme owns — app icons.
import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Widgets

Item {
    id: ic
    property string name: ""
    property string fallback: "system-run"
    property real implicitSize: 18
    property color tint: JD.text1
    readonly property string glyph: JD.glyph(name) || JD.glyph(fallback)
    implicitWidth: implicitSize
    implicitHeight: implicitSize
    Image {
        id: glyphImage
        anchors.fill: parent
        visible: !!ic.glyph && ic.tint === JD.text1
        source: ic.glyph ? Quickshell.shellDir + "/icons/" + ic.glyph + ".svg" : ""
        sourceSize: Qt.size(ic.implicitSize * 2, ic.implicitSize * 2)
        smooth: true
    }
    MultiEffect {
        anchors.fill: parent
        visible: !!ic.glyph && ic.tint !== JD.text1
        source: glyphImage
        colorization: 1
        colorizationColor: ic.tint
        brightness: 1
    }
    IconImage {
        anchors.fill: parent
        visible: !ic.glyph
        implicitSize: ic.implicitSize
        source: Quickshell.iconPath(ic.name || ic.fallback, ic.fallback)
    }
}
