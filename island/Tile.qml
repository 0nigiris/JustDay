// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts

// a control-center toggle: a round icon that lights up, the name and its state
Pressable {
    id: tile
    property string icon: ""
    property string title: ""
    property string onText: JD.tr("Вкл")
    property string offText: JD.tr("Выкл")
    property bool on: false
    property color tint: JD.accentBlue
    property bool lit: on   // цветной ли значок: у плитки-действия цветной всегда
    signal toggled()
    onClicked: toggled()
    Layout.fillWidth: true
    Layout.preferredWidth: 1
    implicitHeight: 62
    radius: 18
    // Свой оттенок у каждого вида плитки (16 нояб.: блоки должны ощущаться «индивидуально»): капля
    // цвета значка в фоне. 6% — на тёмном фоне контраст текста почти не меняется.
    color: Qt.tint(hovered ? JD.fill2 : JD.fill1, Qt.rgba(tint.r, tint.g, tint.b, 0.06))
    Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
    RowLayout {
        anchors { fill: parent; leftMargin: 11; rightMargin: 10 }
        spacing: 10
        Rectangle {
            implicitWidth: 38; implicitHeight: 38; radius: 19
            // Есть полоска Kubai — объёмный значок сам по себе цветной, круг под ним не нужен
            color: kb.ok ? "transparent" : tile.on ? tile.tint : JD.fill2
            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durBase; easing.type: JD.easeOut } }
            KubaiIcon {
                id: kb
                anchors.centerIn: parent; width: 32; height: 32
                name: tile.icon; hovered: tile.hovered
                color: tile.lit ? tile.tint : "#8e8e93"
            }
            Icon { anchors.centerIn: parent; name: tile.icon; implicitSize: 18; visible: !kb.ok }
        }
        ColumnLayout {
            spacing: 0
            Layout.fillWidth: true
            Label1 { text: tile.title; font.pixelSize: 12; Layout.fillWidth: true }
            Label2 { text: tile.on ? tile.onText : tile.offText; font.pixelSize: 11; color: tile.on ? JD.text2 : JD.text3; Layout.fillWidth: true }
        }
    }
}
