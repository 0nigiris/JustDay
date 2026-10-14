// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts
import Quickshell

View {
    implicitWidth: flashRow.implicitWidth + 32
    implicitHeight: 40
    RowLayout {
        id: flashRow
        anchors.centerIn: parent
        spacing: 10
        Rectangle {
            implicitWidth: 22; implicitHeight: 22; radius: 11
            color: Qt.rgba(JD.flashColor.r, JD.flashColor.g, JD.flashColor.b, 0.2)
            Icon { visible: JD.flashIcon !== "check" && JD.flashColor !== JD.accentRed; anchors.centerIn: parent; name: JD.flashIcon; fallback: "dialog-ok"; implicitSize: 16 }
            DrawMark { visible: JD.flashIcon === "check" && JD.flashText !== ""; anchors.centerIn: parent; kind: "check"; tint: JD.flashColor; size: 14 }
            DrawMark { visible: JD.flashIcon !== "check" && JD.flashColor === JD.accentRed && JD.flashText !== ""; anchors.centerIn: parent; kind: "cross"; tint: JD.flashColor; size: 14 }
        }
        Label1 { text: JD.flashText; TextSwap on text {} Layout.maximumWidth: 520 }
        Text { visible: !JD.flashAct; font.family: JD.fontFamily; text: JD.flashColor === JD.accentRed ? "" : "✓"; color: JD.accentGreen; font.pixelSize: 15; font.weight: Font.Bold }
        Label1 {
            visible: !!JD.flashAct
            text: JD.flashAct ? JD.flashAct[0] : ""
            color: JD.accentBlue
            TapHandler { onTapped: { Quickshell.execDetached(JD.flashAct[1]); JD.flashText = ""; JD.flashAct = null } }
        }
    }
}
