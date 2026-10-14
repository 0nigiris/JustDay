// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts
import Quickshell

// the live activity: cover · title · bars (a click opens the player)
View {
    id: mv
    readonly property var p: JD.player || ({})
    property color tint: JD.artTint(p.color)
    Behavior on tint { enabled: JD.animOn; ColorAnimation { duration: JD.durSlow; easing.type: JD.easeOut } }
    readonly property bool loading: !!p.loading
    // Он думает прямо сейчас, а островок занят музыкой: сказать об этом строкой на ней же.
    readonly property bool busy: JD.dstate === "thinking" || JD.dstate === "speaking"
    readonly property string label: loading ? JD.tr("Загружаю") + " «" + (p.loading.title || "") + "»" : (p.title || "")
    implicitWidth: mrow.implicitWidth + 26
    implicitHeight: 40
    RowLayout {
        id: mrow
        anchors { left: parent.left; verticalCenter: parent.verticalCenter; leftMargin: 8 }
        spacing: 10
        Item {
            implicitWidth: 26; implicitHeight: 26
            Art { anchors.fill: parent; size: 26; tint: mv.tint; src: mv.loading ? "" : (mv.p.thumb || ""); visible: !mv.loading }
            Ring { anchors.centerIn: parent; size: 20; visible: mv.loading; spinning: true; tint: JD.accentPink }
        }
        Label1 { text: mv.label; TextSwap on text {} Layout.maximumWidth: 200 }
        Label2 {
            visible: mv.loading && (mv.p.loading.progress || 0) > 0
            text: Math.round((mv.p.loading ? mv.p.loading.progress : 0) * 100) + "%"
            font.features: { "tnum": 1 }
        }
        EqBars { visible: !mv.loading; tint: mv.tint; playing: !mv.p.paused }
        // the music is not the only thing the island knows: the time, a running timer, what Claude is
        // doing or what comes next, the weather — the same line the island shows without music
        Rectangle { implicitWidth: 1; implicitHeight: 18; color: JD.fill2 }
        Text {
            text: Qt.formatTime(mvClock.date, "HH:mm")
            color: JD.text1; font.family: JD.fontFamily; font.pixelSize: 14; font.weight: Font.Bold; font.features: { "tnum": 1 }
        }
        RowLayout {
            visible: !!JD.runningTimer
            spacing: 4
            Icon { name: "timer"; implicitSize: 14; tint: JD.accentOrange }
            Text {
                text: JD.reminderLeft(JD.runningTimer)
                color: JD.accentOrange; font.family: JD.fontFamily; font.pixelSize: 13
                font.weight: Font.DemiBold; font.features: { "tnum": 1 }
            }
        }
        // Пока играет музыка, работа живёт здесь, а не вместо обложки: кружок и короткая
        // строка о том, что он сейчас делает. Так видно и то и другое сразу.
        Ring {
            visible: mv.busy
            size: 14
            Layout.preferredWidth: 14; Layout.preferredHeight: 14
        }
        Label2 {
            readonly property string event: mv.busy ? (JD.activity || JD.tr("Думаю…"))
                                            : JD.workers > 0 ? JD.tr("Клод работает") + (JD.workers > 1 ? " ×" + JD.workers : "")
                                            : JD.runningJob ? JD.runningJob.title + " · " + JD.jobTime(JD.runningJob)
                                            : JD.nextEvent ? Qt.formatTime(new Date(JD.nextEvent.start), "HH:mm") + " · " + JD.nextEvent.title : ""
            visible: !!event && (mv.busy || JD.island.events_expanded !== false)
            text: event.replace(/\s+/g, " "); maximumLineCount: 1; wrapMode: Text.NoWrap
            elide: Text.ElideRight
            Layout.maximumWidth: 170
            color: mv.busy ? JD.accentBlue : JD.workers > 0 ? JD.accentPurple : JD.text2
        }
        RowLayout {
            visible: !!JD.weather && JD.island.show_weather !== false && JD.island.weather_expanded !== false
            spacing: 5
            Image { source: JD.weather ? Quickshell.shellDir + "/icons/" + JD.weather.icon + ".svg" : ""; sourceSize: Qt.size(32, 32); Layout.preferredWidth: 16; Layout.preferredHeight: 16 }
            Text { text: JD.weather ? (JD.weather.temp > 0 ? "+" : "") + JD.weather.temp + "°" : ""; color: JD.text1; font.family: JD.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold }
        }
    }
    SystemClock { id: mvClock; precision: SystemClock.Minutes }
}
