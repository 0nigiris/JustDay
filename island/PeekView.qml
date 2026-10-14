// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts
import Quickshell

View {
    property alias cat: clockCat
    id: pv
    readonly property color fg: JD.text1
    readonly property color fg2: JD.text2
    readonly property color hair: JD.fill2
    // Что играет — общим выбором из JD, а не жёстко вписанным Spotify: у всех, кто слушает
    // не его, полоска раньше пустовала. Показываем только играющее: трек на паузе в
    // свёрнутой полоске — это не «что сейчас», а мусор, который там и останется.
    readonly property var spot: (JD.playerInPeek && JD.musicPlaying) ? JD.musicPlayer : null
    readonly property string spotArt: {
        const u = pv.spot && pv.spot.trackArtUrl ? String(pv.spot.trackArtUrl) : ""
        if (u.indexOf("file://") === 0) return decodeURIComponent(u.slice(7))
        return u
    }
    readonly property string event: JD.workers > 0 ? JD.tr("Клод работает") + (JD.workers > 1 ? " ×" + JD.workers : "")
                                    : JD.runningJob ? JD.runningJob.title + " · " + JD.jobTime(JD.runningJob)
                                    : JD.dstate === "offline" ? JD.assistantName + JD.tr(" не запущен")
                                    : JD.nextEvent ? Qt.formatTime(new Date(JD.nextEvent.start), "HH:mm") + " · " + JD.nextEvent.title
                                    : JD.update ? JD.tr("Доступно обновление")
                                    : (JD.island.show_events !== false && JD.history.length && JD.history[0].a) ? JD.history[0].a : ""
    implicitWidth: peekRow.implicitWidth + 32
    implicitHeight: JD.islandStyle === "bar" ? JD.barHeight : 44
    property real squeeze: 1
    property real hoverScale: JD.islandStyle === "bar" && (midHover.hovered || JD.mode === "expanded" || JD.mode === "settings" || JD.mode === "tools") ? 1.08 : 1
    Behavior on hoverScale { enabled: JD.animOn; NumberAnimation { duration: JD.durBase; easing.type: JD.easeOut } }
    // Вниз и вверх одинаково. Повторный клик начинает цикл заново, а не ставит его в очередь.
    function bump() { pulse.restart() }
    SequentialAnimation {
        id: pulse
        NumberAnimation { target: pv; property: "squeeze"; to: 0.985; duration: 80; easing.type: Easing.InOutCubic }
        NumberAnimation { target: pv; property: "squeeze"; to: 1; duration: 80; easing.type: Easing.InOutCubic }
    }
    SystemClock { id: clock; precision: SystemClock.Minutes }
    RowLayout {
        id: peekRow
        anchors.centerIn: parent
        spacing: 12
        scale: pv.hoverScale * pv.squeeze
        transformOrigin: Item.Center
        HoverHandler { id: midHover; enabled: JD.islandStyle === "bar" }
        Ring {
            visible: !JD.buddyOn
            size: 18
            tint: JD.workers > 0 ? JD.accentPurple : JD.dstate === "offline" ? JD.accentRed : JD.accentCyan
            spinning: JD.workers > 0
        }
        // Существо вместо кольца: кольцо сообщает состояние цветом и вращением, и это надо
        // знать заранее. Существо сообщает тем же, чем сообщают живые, — взглядом и позой, и
        // объяснять это не нужно никому.
        //
        // Выбран скин — показываем нарисованного зверя, нет — своего, нарисованного кодом.
        // Оба живут по одной таблице состояний и носят одни и те же глаза.
        Buddy {
            visible: JD.buddyOn && !JD.mascotSkin
            size: 22
            mood: JD.buddyMood
            voice: JD.level
            lookX: JD.pointerX
            lookY: JD.pointerY
        }
        Mascot {
            visible: JD.buddyOn && !!JD.mascotSkin
            skin: JD.mascotSkin
            size: Math.round(28 * JD.mascotZoom)
            mood: JD.buddyMood
            voice: JD.level
            lookX: JD.pointerX
            lookY: JD.pointerY
        }
        DockCat {
            id: clockCat
            // На полосе кошку можно унести к значкам трея; у островка и выреза трея нет.
            visible: JD.island.cat === true && !(JD.islandStyle === "bar" && JD.catPlace === "tray")
            size: 22
            cpu: JD.cpu
            awake: true
            sleepBelow: JD.dockCfg.cat_sleep_below || 0
            opacity: JD.catFrom === clockCat ? 0.3 : 1
            HoverHandler { onHoveredChanged: JD.catTipAt = hovered ? clockCat : (JD.catTipAt === clockCat ? null : JD.catTipAt) }
            CatCarry { cat: clockCat }
        }
        Text { text: Qt.formatTime(clock.date, "HH:mm"); color: pv.fg; font.family: JD.fontFamily; font.pixelSize: 16; font.weight: Font.Bold; font.features: { "tnum": 1 } }
        Label2 { text: clock.date.toLocaleDateString(Qt.locale(JD.lang === "ru" ? "ru_RU" : "en_US"), "ddd, d MMM"); color: pv.fg2 }
        // Только Spotify. Чужие плееры (браузер, YouTube) на полосу не выводятся.
        Rectangle { visible: !!pv.spot; implicitWidth: 1; implicitHeight: 18; color: pv.hair }
        Art {
            visible: !!pv.spot
            size: 22
            src: pv.spotArt
            tint: JD.accentPink
        }
        Label2 {
            visible: !!pv.spot
            text: pv.spot ? JD.cleanTitle(pv.spot.trackTitle) : ""
            maximumLineCount: 1
            wrapMode: Text.NoWrap
            Layout.maximumWidth: 180
            color: pv.fg
        }
        EqBars { visible: !!pv.spot; tint: JD.accentPink; playing: true }
        Rectangle { visible: !!pv.event && JD.island.events_peek !== false; implicitWidth: 1; implicitHeight: 18; color: pv.hair }
        Label2 { visible: !!pv.event && JD.island.events_peek !== false; text: pv.event.replace(/\s+/g, " "); maximumLineCount: 1; wrapMode: Text.NoWrap; Layout.maximumWidth: 260; color: JD.workers > 0 ? JD.accentPurple : pv.fg2 }
        // a running timer, the way the phone shows one: the number, not a logo
        Rectangle { visible: !!JD.runningTimer; implicitWidth: 1; implicitHeight: 18; color: pv.hair }
        RowLayout {
            visible: !!JD.runningTimer
            spacing: 5
            Icon { name: "timer"; implicitSize: 15; tint: JD.accentOrange }
            Text {
                text: JD.reminderLeft(JD.runningTimer)
                color: JD.accentOrange; font.family: JD.fontFamily; font.pixelSize: 14
                font.weight: Font.DemiBold; font.features: { "tnum": 1 }
            }
        }
        // Молчит по просьбе. Об этом нужно говорить вслух — вернее, показывать: иначе «он мне
        // не отвечает» выглядит поломкой, хотя ассистент просто выполняет «молчи».
        Rectangle { visible: JD.muted; implicitWidth: 1; implicitHeight: 18; color: pv.hair }
        Rectangle {
            visible: JD.muted
            implicitWidth: mutedRow.implicitWidth + 16
            implicitHeight: 22
            radius: 11
            color: muteHover.hovered ? JD.fill2 : JD.fill1
            RowLayout {
                id: mutedRow
                anchors.centerIn: parent
                spacing: 5
                Icon { name: "audio-volume-muted"; implicitSize: 13; tint: JD.accentOrange }
                Label2 { text: JD.tr("Молчит"); color: JD.accentOrange; font.weight: Font.DemiBold }
            }
            HoverHandler { id: muteHover; cursorShape: Qt.PointingHandCursor }
            // Нажатие прямо здесь возвращает голос: пометка — она же и кнопка.
            TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: JD.setMuted(false) }
        }
        // Тишина по расписанию («Школа до 15:00»): без этой пометки молчание ассистента выглядит
        // поломкой. Не кнопка — расписание правится в настройках, а не щелчком по пометке.
        Rectangle { visible: !!JD.focusNow; implicitWidth: 1; implicitHeight: 18; color: pv.hair }
        Rectangle {
            visible: !!JD.focusNow
            implicitWidth: focusRow.implicitWidth + 16
            implicitHeight: 22
            radius: 11
            color: JD.fill1
            RowLayout {
                id: focusRow
                anchors.centerIn: parent
                spacing: 5
                Icon { name: "moon"; implicitSize: 13; tint: JD.accentPurple }
                Label2 { text: JD.focusNow ? JD.focusNow.name + JD.tr(" до ") + JD.focusNow.until : ""; color: JD.accentPurple; font.weight: Font.DemiBold }
            }
        }
        Rectangle { visible: !!JD.weather && JD.island.show_weather !== false && JD.island.weather_peek !== false; implicitWidth: 1; implicitHeight: 18; color: pv.hair }
        RowLayout {
            visible: !!JD.weather && JD.island.show_weather !== false && JD.island.weather_peek !== false
            spacing: 6
            Image { source: JD.weather ? Quickshell.shellDir + "/icons/" + JD.weather.icon + ".svg" : ""; sourceSize: Qt.size(36, 36); Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
            Text { text: JD.weather ? (JD.weather.temp > 0 ? "+" : "") + JD.weather.temp + "°" : ""; color: pv.fg; font.family: JD.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold }
        }
    }
}
