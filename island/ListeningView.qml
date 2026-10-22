// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts

View {
    implicitWidth: 236
    implicitHeight: 40
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 16
        spacing: 10
        Orb { visible: JD.orbsOn; orbState: "listening"; size: 20 }
        Ring { size: 20; visible: !JD.orbsOn }
        Label1 { text: JD.tr("Слушаю"); Layout.fillWidth: true }
        Waveform { Layout.preferredWidth: 46; Layout.preferredHeight: 22 }
    }
}
