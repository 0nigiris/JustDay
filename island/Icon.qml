// One icon language for the whole island: lucide strokes from island/icons (JD.glyphs),
// with the desktop's own icon theme left for the things the theme owns — app icons.
//
// Растр просят крупнее, чем показывают. Значок в доке вырастает под курсором в полтора раза, и
// растр, нарисованный по его обычному размеру, в этот момент расплывается: увеличивается уже
// картинка, а не значок. renderSize — во сколько раз просить крупнее; лишняя память тут копеечная,
// а мыло видно всем.
import QtQuick
import QtQuick.Effects
import Quickshell

Item {
    id: ic
    property string name: ""
    property string fallback: "system-run"
    property real implicitSize: 18
    property real renderSize: implicitSize * 2
    property color tint: JD.text1
    // Значок самой программы, а не наш штриховой. Для списка программ важно именно это: у нас есть
    // «app-window», и без этого признака все приложения выглядели одинаковым окошком, потому что
    // запасное имя application-x-executable само есть в нашем наборе и перебивало настоящий значок.
    property bool theme: false
    readonly property string glyph: theme ? "" : (JD.glyph(name) || JD.glyph(fallback))
    implicitWidth: implicitSize
    implicitHeight: implicitSize
    Image {
        id: glyphImage
        anchors.fill: parent
        visible: !!ic.glyph && ic.tint === JD.text1
        source: ic.glyph ? Quickshell.shellDir + "/icons/" + ic.glyph + ".svg" : ""
        sourceSize: Qt.size(ic.renderSize, ic.renderSize)
        fillMode: Image.PreserveAspectFit
        mipmap: true
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
    // Не IconImage из Quickshell: он жёстко просит растр по своему видимому размеру, и увеличенный
    // значок в доке расплывался. Здесь размер растра задаём сами.
    Image {
        anchors.fill: parent
        visible: !ic.glyph
        source: Quickshell.iconPath(ic.name || ic.fallback, ic.fallback)
        sourceSize: Qt.size(ic.renderSize, ic.renderSize)
        fillMode: Image.PreserveAspectFit
        mipmap: true
        smooth: true
        asynchronous: true
    }
}
