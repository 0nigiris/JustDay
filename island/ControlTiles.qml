// Колонка плиток управления справа от сетки программ — режим меню «Launchpad» (island.menu_style).
//
// Только вид. Каждая плитка зовёт то, что и так умеет островок: те же настройки, тот же голос, тот же
// режим сервера. Своей логики здесь нет, поэтому плитка и одноимённый переключатель в раскрытом
// островке не могут разойтись.
import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: ct
    spacing: 12

    function setting(key, value) { JD.run(["config", "set", key, String(value)]) }

    component Tile: Pressable {
        id: tile
        property string icon: ""
        property string title: ""
        property string onText: "Вкл"
        property string offText: "Выкл"
        property bool on: false
        property color tint: JD.accentBlue
        signal toggled()
        onClicked: toggled()
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        implicitHeight: 64
        radius: 18
        color: hovered ? JD.menuFill2 : JD.menuFill1
        Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
        RowLayout {
            anchors { fill: parent; leftMargin: 11; rightMargin: 10 }
            spacing: 10
            Rectangle {
                implicitWidth: 38
                implicitHeight: 38
                radius: 19
                color: tile.on ? tile.tint : JD.menuFill2
                Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durBase; easing.type: JD.easeOut } }
                Icon { anchors.centerIn: parent; name: tile.icon; implicitSize: 18 }
            }
            ColumnLayout {
                spacing: 0
                Layout.fillWidth: true
                Label1 { text: tile.title; font.pixelSize: 12; Layout.fillWidth: true }
                Label2 {
                    text: tile.on ? tile.onText : tile.offText
                    font.pixelSize: 11
                    color: tile.on ? JD.text2 : JD.text3
                    Layout.fillWidth: true
                }
            }
        }
    }

    Label2 {
        text: "Управление"
        color: JD.text3
        font.pixelSize: 12
    }

    GridLayout {
        Layout.fillWidth: true
        columns: 2
        rowSpacing: 10
        columnSpacing: 10
        Tile {
            icon: "audio-input-microphone"; title: "Микрофон"; onText: "голос и текст"; offText: "только текст"
            on: JD.micOn; tint: JD.accentCyan
            onToggled: ct.setting("audio.microphone", !JD.micOn)
        }
        Tile {
            icon: "audio-speakers"; title: "Голос"; onText: "отвечает вслух"
            offText: JD.muted ? "молчит по просьбе" : "только текстом"
            on: JD.voiceOn; tint: JD.accentBlue
            onToggled: JD.setMuted(JD.voiceOn)
        }
        Tile {
            icon: "audio-lines"; title: "Звуки"; onText: "сигналы"; offText: "тишина"
            on: !!JD.settings.earcons; tint: JD.accentOrange
            onToggled: ct.setting("audio.earcons", !JD.settings.earcons)
        }
        Tile {
            icon: "preferences-desktop-notification-bell"; title: "Уведомления"; onText: "на острове"; offText: "не беспокоить"
            on: JD.island.show_notifications !== false; tint: JD.accentPurple
            onToggled: ct.setting("island.show_notifications", JD.island.show_notifications === false)
        }
        Tile {
            icon: JD.serverMode ? "sun" : "moon"; title: "Режим сервера"; onText: "экраны погашены"; offText: "выключен"
            on: JD.serverMode; tint: JD.accentPink
            onToggled: { JD.closeMenu(); JD.toggleServerMode() }
        }
        Tile {
            icon: "settings"; title: "Настройки"; onText: ""; offText: "открыть"
            tint: JD.accentBlue
            onToggled: { JD.closeMenu(); JD.openSettings("general") }
        }
    }

    // Громкость самого ассистента. Системная принадлежит системе: этот ползунок других программ не трогает.
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: 64
        radius: 18
        color: JD.menuFill1
        RowLayout {
            anchors { fill: parent; leftMargin: 14; rightMargin: 14 }
            spacing: 10
            Icon { name: "sparkles"; implicitSize: 16; tint: JD.accentBlue }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Label1 { text: JD.assistantName; font.pixelSize: 12; Layout.fillWidth: true }
                JSlider {
                    Layout.fillWidth: true
                    live: true
                    tint: JD.accentBlue
                    value: JD.volume / 100
                    onMoved: v => JD.setVolume(v * 100)
                }
            }
        }
    }

    Item { Layout.fillHeight: true }
}
