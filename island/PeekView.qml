// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts
import Quickshell

View {
    // Кошка живёт внутри загрузчика виджета; снаружи (shell.qml) её берут отсюда.
    property var cat: null
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
    // Порядок и состав полоски — `island.peek` в конфиге (JD.peekLayout). Раньше она была одной
    // жёстко вписанной строкой: двигать и убирать виджеты можно было только правкой этого файла.
    readonly property var parts: ({
        assistant: cAssistant, cat: cCat, clock: cClock, date: cDate, player: cPlayer, event: cEvent,
        timer: cTimer, muted: cMuted, focus: cFocus, weather: cWeather
    })
    function save(l) { JD.setConfig("island.peek", l) }
    function remove(id) { save(JD.peekLayout.filter(k => k !== id)) }
    // Куда встал перетащенный виджет: перед первым видимым, чей центр правее. Скрытые (таймер без
    // таймера) в счёт не идут, у них нет места на экране.
    function drop(from, cx) {
        const l = JD.peekLayout.slice(), id = l.splice(from, 1)[0]
        let at = l.length
        for (let k = 0, n = 0; k < rep.count; k++) {
            if (k === from) continue
            const it = rep.itemAt(k)
            if (it && it.visible && it.x + it.width / 2 > cx) { at = n; break }
            n++
        }
        l.splice(at, 0, id)
        save(l)
    }
    // Удержание включает режим правки, как на iPhone; забытый режим гаснет через две минуты.
    TapHandler {
        acceptedButtons: Qt.LeftButton
        gesturePolicy: TapHandler.DragThreshold
        longPressThreshold: 0.8
        onLongPressed: JD.editMode = true
    }
    Timer { interval: 120000; running: JD.editMode; onTriggered: JD.editMode = false }
    RowLayout {
        id: peekRow
        anchors.centerIn: parent
        spacing: 12
        scale: pv.hoverScale * pv.squeeze
        transformOrigin: Item.Center
        HoverHandler { id: midHover; enabled: JD.islandStyle === "bar" }
        Repeater {
            id: rep
            model: JD.peekLayout
            delegate: Loader {
                id: slot
                required property int index
                required property string modelData
                // Разделитель перед виджетом нужен, если он не первый.
                readonly property bool lead: index > 0
                sourceComponent: pv.parts[modelData] || null
                visible: status === Loader.Ready && !!item && item.shown
                onLoaded: if (modelData === "cat") pv.cat = item.catItem

                // Режим правки: дрожание (у соседей чуть разное по времени, иначе строем), без анимаций
                // вместо него рамка. Стрелки двигают виджет, крестик убирает.
                property real wiggle: 0
                rotation: JD.editMode && JD.animOn ? wiggle : 0
                SequentialAnimation on wiggle {
                    running: JD.editMode && JD.animOn && slot.visible
                    loops: Animation.Infinite
                    NumberAnimation { to: 2.4; duration: 95 + (slot.index % 3) * 18; easing.type: Easing.InOutSine }
                    NumberAnimation { to: -2.4; duration: 95 + (slot.index % 3) * 18; easing.type: Easing.InOutSine }
                }
                Rectangle {
                    anchors.fill: parent; anchors.margins: -4
                    visible: JD.editMode && !JD.animOn
                    color: "transparent"; radius: 8
                    border.width: 1; border.color: JD.accentBlue
                }
                // Перетаскивание вместо стрелок: двигаем только рисунок (translate), а место в списке
                // решаем при отпускании, иначе RowLayout пересчитывался бы под пальцем на каждый пиксель.
                property real dragX: 0
                transform: Translate { x: slot.dragX }
                z: drag.active ? 10 : 0
                DragHandler {
                    id: drag
                    enabled: JD.editMode
                    yAxis.enabled: false
                    onTranslationChanged: slot.dragX = translation.x
                    onActiveChanged: if (!active) { pv.drop(slot.index, slot.x + slot.width / 2 + slot.dragX); slot.dragX = 0 }
                }
                Rectangle {
                    visible: JD.editMode
                    anchors.horizontalCenter: parent.right; anchors.verticalCenter: parent.top
                    width: 14; height: 14; radius: 7; color: JD.fill2
                    Icon { anchors.centerIn: parent; name: "x"; implicitSize: 9; tint: JD.text1 }
                    TapHandler { onTapped: pv.remove(slot.modelData) }
                }
            }
        }
        // Одна кнопка нормального размера: гасит дрожание и открывает галерею виджетов под островком.
        Rectangle {
            visible: JD.editMode
            height: 28; width: galText.implicitWidth + 32; radius: 14; color: JD.accentBlue
            Label2 { id: galText; anchors.centerIn: parent; color: "white"; text: "+ " + JD.tr("Виджеты") }
            TapHandler { onTapped: { JD.editMode = false; JD.openTools("widgets") } }
        }
        Rectangle {
            visible: JD.editMode
            height: 28; width: doneText.implicitWidth + 28; radius: 14; color: JD.fill2
            Label2 { id: doneText; anchors.centerIn: parent; color: JD.text1; text: JD.tr("Готово") }
            TapHandler { onTapped: JD.editMode = false }
        }
    }

    // Общая черта между виджетами.
    component Sep: Rectangle { implicitWidth: 1; implicitHeight: 18; color: pv.hair }

    Component {
        id: cAssistant
        RowLayout {
            readonly property bool shown: true
            Orb { visible: !JD.buddyOn && JD.orbsOn; main: true; size: 18 }
            Ring {
                visible: !JD.buddyOn && !JD.orbsOn
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
        }
    }

    Component {
        id: cCat
        Item {
            // На полосе кошку можно унести к значкам трея; у островка и выреза трея нет.
            readonly property bool shown: JD.island.cat === true && !(JD.islandStyle === "bar" && JD.catPlace === "tray")
            readonly property alias catItem: clockCat
            implicitWidth: clockCat.implicitWidth
            implicitHeight: clockCat.implicitHeight
            DockCat {
                id: clockCat
                size: 22
                cpu: JD.cpu
                awake: true
                sleepBelow: JD.dockCfg.cat_sleep_below || 0
                opacity: JD.catFrom === clockCat ? 0.3 : 1
                HoverHandler { onHoveredChanged: JD.catTipAt = hovered ? clockCat : (JD.catTipAt === clockCat ? null : JD.catTipAt) }
                CatCarry { cat: clockCat }
            }
        }
    }

    Component {
        id: cClock
        Text {
            readonly property bool shown: true
            text: Qt.formatTime(clock.date, "HH:mm"); color: pv.fg; font.family: JD.fontFamily; font.pixelSize: 16; font.weight: Font.Bold; font.features: { "tnum": 1 }
        }
    }

    Component {
        id: cDate
        Label2 {
            readonly property bool shown: true
            text: clock.date.toLocaleDateString(Qt.locale(JD.lang === "ru" ? "ru_RU" : "en_US"), "ddd, d MMM"); color: pv.fg2
        }
    }

    // Только играющее. Чужие плееры (браузер, YouTube) на полосу не выводятся.
    Component {
        id: cPlayer
        RowLayout {
            readonly property bool shown: !!pv.spot
            spacing: 12
            readonly property bool lead: parent ? parent.lead : false
            Sep { visible: parent && parent.lead }
            Art { size: 22; src: pv.spotArt; tint: JD.accentPink }
            Label2 {
                text: pv.spot ? JD.cleanTitle(pv.spot.trackTitle) : ""
                maximumLineCount: 1
                wrapMode: Text.NoWrap
                Layout.maximumWidth: 180
                color: pv.fg
            }
            EqBars { tint: JD.accentPink; playing: true }
        }
    }

    Component {
        id: cEvent
        RowLayout {
            readonly property bool shown: !!pv.event && JD.island.events_peek !== false
            spacing: 12
            readonly property bool lead: parent ? parent.lead : false
            Sep { visible: parent && parent.lead }
            Label2 { text: pv.event.replace(/\s+/g, " "); maximumLineCount: 1; wrapMode: Text.NoWrap; Layout.maximumWidth: 260; color: JD.workers > 0 ? JD.accentPurple : pv.fg2 }
        }
    }

    // Запущенный таймер, как на телефоне: число, а не значок.
    Component {
        id: cTimer
        RowLayout {
            readonly property bool shown: !!JD.runningTimer
            spacing: 12
            readonly property bool lead: parent ? parent.lead : false
            Sep { visible: parent && parent.lead }
            RowLayout {
                spacing: 5
                Icon { name: "timer"; implicitSize: 15; tint: JD.accentOrange }
                Text {
                    text: JD.reminderLeft(JD.runningTimer)
                    color: JD.accentOrange; font.family: JD.fontFamily; font.pixelSize: 14
                    font.weight: Font.DemiBold; font.features: { "tnum": 1 }
                }
            }
        }
    }

    // Молчит по просьбе. Об этом нужно говорить вслух — вернее, показывать: иначе «он мне
    // не отвечает» выглядит поломкой, хотя ассистент просто выполняет «молчи».
    Component {
        id: cMuted
        RowLayout {
            readonly property bool shown: JD.muted
            spacing: 12
            readonly property bool lead: parent ? parent.lead : false
            Sep { visible: parent && parent.lead }
            Rectangle {
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
        }
    }

    // Тишина по расписанию («Школа до 15:00»): без этой пометки молчание ассистента выглядит
    // поломкой. Не кнопка — расписание правится в настройках, а не щелчком по пометке.
    Component {
        id: cFocus
        RowLayout {
            readonly property bool shown: !!JD.focusNow
            spacing: 12
            readonly property bool lead: parent ? parent.lead : false
            Sep { visible: parent && parent.lead }
            Rectangle {
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
        }
    }

    Component {
        id: cWeather
        RowLayout {
            readonly property bool shown: !!JD.weather && JD.island.show_weather !== false && JD.island.weather_peek !== false
            spacing: 12
            readonly property bool lead: parent ? parent.lead : false
            Sep { visible: parent && parent.lead }
            RowLayout {
                spacing: 6
                Image { source: JD.weather ? Quickshell.shellDir + "/icons/" + JD.weather.icon + ".svg" : ""; sourceSize: Qt.size(36, 36); Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
                Text { text: JD.weather ? (JD.weather.temp > 0 ? "+" : "") + JD.weather.temp + "°" : ""; color: pv.fg; font.family: JD.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold }
            }
        }
    }
}
