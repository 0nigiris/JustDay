// Раскладка клавиатуры внутри окна, где печатают: «EN» / «RU» в капсуле.
//
// Беда 22 окт.: смену раскладки показывала только плашка OSD сверху, а над открытым Spotlight и
// полем ввода её не видно, и человек не понимал, что переключил. Капсула стоит прямо у поля и при
// смене на миг вспыхивает акцентом и раздувается, чтобы это заметил и боковой взгляд.
import QtQuick

Rectangle {
    id: chip
    visible: JD.layoutShort !== ""
    implicitWidth: label.implicitWidth + 16
    implicitHeight: 22
    radius: 11
    color: flash ? JD.accentBlue : JD.fill2
    scale: flash ? 1.18 : 1
    property bool flash: false
    Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
    Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
    Connections { target: JD; function onLayoutTickChanged() { chip.flash = true; hold.restart() } }
    Timer { id: hold; interval: 1100; onTriggered: chip.flash = false }
    Text {
        id: label
        anchors.centerIn: parent
        text: JD.layoutShort
        color: chip.flash ? "#ffffff" : JD.text2
        font.family: JD.fontFamily; font.pixelSize: 12; font.weight: Font.DemiBold
    }
    HoverHandler { cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: JD.layoutNext() }
}
