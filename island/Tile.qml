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
    // Вид — по своему размеру, а не по названию размера: полколонки — одна иконка (16 нояб.:
    // «кнопки размером в иконку»), стоймя — значок сверху, подпись внизу, как у виджетов айфона.
    readonly property bool iconOnly: width < 110
    readonly property bool tall: !iconOnly && height > 100
    GridLayout {
        anchors { fill: parent; leftMargin: tile.iconOnly ? 0 : 11; rightMargin: tile.iconOnly ? 0 : 10
                  topMargin: tile.tall ? 12 : 0; bottomMargin: tile.tall ? 12 : 0 }
        columns: tile.tall || tile.iconOnly ? 1 : 2
        columnSpacing: 10; rowSpacing: 0
        Rectangle {
            Layout.alignment: tile.iconOnly ? Qt.AlignCenter : Qt.AlignLeft | (tile.tall ? Qt.AlignTop : Qt.AlignVCenter)
            Layout.fillHeight: tile.tall
            implicitWidth: tile.tall ? 48 : 38; implicitHeight: implicitWidth; radius: implicitWidth / 2
            // Есть полоска Kubai — объёмный значок сам по себе цветной, круг под ним не нужен
            color: kb.ok ? "transparent" : tile.on ? tile.tint : JD.fill2
            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durBase; easing.type: JD.easeOut } }
            KubaiIcon {
                id: kb
                anchors.centerIn: parent; width: tile.tall ? 44 : 32; height: width
                name: tile.icon; hovered: tile.hovered
                color: tile.lit ? tile.tint : "#8e8e93"
            }
            Icon { anchors.centerIn: parent; name: tile.icon; implicitSize: tile.tall ? 22 : 18; visible: !kb.ok }
        }
        ColumnLayout {
            visible: !tile.iconOnly
            spacing: 0
            Layout.fillWidth: true
            Layout.alignment: tile.tall ? Qt.AlignBottom : Qt.AlignVCenter
            Label1 { text: tile.title; font.pixelSize: tile.tall ? 13 : 12; Layout.fillWidth: true; elide: Text.ElideRight }
            Label2 { text: tile.on ? tile.onText : tile.offText; font.pixelSize: 11; color: tile.on ? JD.text2 : JD.text3; Layout.fillWidth: true; elide: Text.ElideRight }
        }
    }
}
