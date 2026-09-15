// JustDay Settings — lives inside the Dynamic Island (sidebar + animated pages), opened from the island menu,
// by clicking a tile, or `qs -p <repo>/island ipc call island settings`.
// Reads everything with `justday settings-data`, writes with `justday config set` and friends.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import QtQuick.Effects
import Quickshell
import Quickshell.Io

Item {
    id: win
    implicitWidth: 940
    implicitHeight: 640

    // ───────────── palette ─────────────
    readonly property color bg: "transparent"   // the island itself is the background
    readonly property color side: Qt.rgba(1, 1, 1, 0.035)
    readonly property color card: "#1c1c1e"
    readonly property color field: "#2c2c2e"
    readonly property color line: Qt.rgba(1, 1, 1, 0.08)
    readonly property color t1: "#f5f5f7"
    readonly property color t2: Qt.rgba(235 / 255, 235 / 255, 245 / 255, 0.6)
    readonly property color t3: Qt.rgba(235 / 255, 235 / 255, 245 / 255, 0.3)
    readonly property color blue: "#0a84ff"
    readonly property string font: JD.fontFamily
    readonly property string icons: Quickshell.shellDir + "/icons/"

    // ───────────── data ─────────────
    property var d: ({})
    property bool loading: true
    property string page: JD.settingsPage
    Connections { target: JD; function onSettingsPageChanged() { win.page = JD.settingsPage } }
    property bool restartNeeded: false
    property string toast: ""

    function get(path) {
        return path.split(".").reduce((o, k) => (o === undefined || o === null) ? undefined : o[k], d.config)
    }
    function set(path, value) {
        const parts = path.split(".")
        let o = d.config
        for (let i = 0; i < parts.length - 1; i++) o = o[parts[i]]
        o[parts[parts.length - 1]] = value
        d = Object.assign({}, d)  // notify bindings
        Quickshell.execDetached(["justday", "config", "set", path, Array.isArray(value) ? value.join(",") : String(value)])
        if (/^(brain|stt|wakeword|local_llm)\./.test(path) || path === "tts.engine") restartNeeded = true
    }
    function notify(text) { toast = text; toastTimer.restart() }

    Component {
        id: procComponent
        Process {
            id: p
            property var callback: null
            running: true
            stdout: StdioCollector {
                onStreamFinished: {
                    let value = text
                    try { value = JSON.parse(text) } catch (e) {}
                    if (p.callback) p.callback(value)
                    p.destroy()
                }
            }
        }
    }
    function run(args, callback, env) {
        procComponent.createObject(win, { command: ["justday"].concat(args), callback: callback || null, environment: env || {} })
    }
    function reload() {
        run(["settings-data"], v => { if (typeof v === "object") { d = v; loading = false } })
    }
    Component.onCompleted: reload()
    Timer { id: toastTimer; interval: 2600; onTriggered: win.toast = "" }

    // ───────────── layout ─────────────
    RowLayout {
        anchors.fill: parent
        spacing: 0

        // sidebar
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 244
            color: win.side
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                anchors.topMargin: 18
                spacing: 2
                RowLayout {
                    Layout.leftMargin: 8
                    Layout.bottomMargin: 14
                    spacing: 10
                    Rectangle {
                        implicitWidth: 34; implicitHeight: 34; radius: 10
                        gradient: Gradient {
                            GradientStop { position: 0; color: "#5e5ce6" }
                            GradientStop { position: 1; color: "#0a84ff" }
                        }
                        Glyph { anchors.centerIn: parent; name: "sparkles"; size: 18 }
                    }
                    ColumnLayout {
                        spacing: 0
                        Text { text: "JustDay"; color: win.t1; font.family: win.font; font.pixelSize: 16; font.weight: Font.Bold }
                        Text { text: JD.assistantName + " · " + (win.d.about ? win.d.about.version : ""); color: win.t2; font.family: win.font; font.pixelSize: 11 }
                    }
                }
                Repeater {
                    model: [
                        { id: "general", title: "Общие", icon: "settings", tint: "#8e8e93" },
                        { id: "appearance", title: "Остров и анимации", icon: "wand-sparkles", tint: "#ff2d55" },
                        { id: "widgets", title: "Виджеты", icon: "cloud-sun", tint: "#32ade6" },
                        { id: "voice", title: "Голос и звук", icon: "audio-lines", tint: "#ff375f" },
                        { id: "buttons", title: "Кнопки", icon: "keyboard", tint: "#0a84ff" },
                        { id: "model", title: "Модель", icon: "cpu", tint: "#bf5af2" },
                        { id: "mail", title: "Почта", icon: "mail", tint: "#ff453a" },
                        { id: "people", title: "Люди", icon: "users", tint: "#30d158" },
                        { id: "memory", title: "Память", icon: "brain", tint: "#64d2ff" },
                        { id: "privacy", title: "Приватность", icon: "shield", tint: "#ff9f0a" },
                        { id: "diagnostics", title: "Диагностика", icon: "activity", tint: "#636366" },
                        { id: "about", title: "О программе", icon: "info", tint: "#5e5ce6" }
                    ]
                    Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: 34
                        radius: 8
                        color: win.page === modelData.id ? Qt.rgba(1, 1, 1, 0.1) : (navHover.hovered ? Qt.rgba(1, 1, 1, 0.05) : "transparent")
                        Behavior on color { enabled: JD.animOn; ColorAnimation { duration: 180 } }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            spacing: 10
                            Rectangle {
                                implicitWidth: 24; implicitHeight: 24; radius: 7
                                color: modelData.tint
                                Glyph { anchors.centerIn: parent; name: modelData.icon; size: 14 }
                            }
                            Text { text: modelData.title; color: win.t1; font.family: win.font; font.pixelSize: 13; Layout.fillWidth: true }
                        }
                        HoverHandler { id: navHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: win.page = modelData.id }
                    }
                }
                Item { Layout.fillHeight: true }
                Btn {
                    visible: win.restartNeeded
                    Layout.fillWidth: true
                    text: "Перезапустить JustDay"
                    primary: true
                    onClicked: { win.run(["restart"]); win.restartNeeded = false; win.notify("Перезапускаю… новый разговор начнётся с нуля") }
                }
                Text {
                    visible: win.restartNeeded
                    Layout.fillWidth: true
                    text: "Часть изменений применится после перезапуска"
                    wrapMode: Text.Wrap
                    color: win.t2; font.family: win.font; font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }

        // pages
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            RowLayout {
                z: 10
                anchors { top: parent.top; right: parent.right; topMargin: 16; rightMargin: 18 }
                spacing: 8
                RoundIcon { glyph: "house"; onClicked: { JD.settingsOpen = false; JD.expanded = true } }
                RoundIcon { glyph: "x"; onClicked: JD.closeAll() }
            }

            Text {
                anchors.centerIn: parent
                visible: win.loading
                text: "Загружаю настройки…"
                color: win.t2; font.family: win.font; font.pixelSize: 14
            }

            Flickable {
                id: scroller
                anchors.fill: parent
                visible: !win.loading
                contentHeight: pageLoader.implicitHeight + 60
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                Loader {
                    id: pageLoader
                    x: 32
                    y: 26
                    width: Math.min(700, scroller.width - 64)
                    active: !win.loading
                    sourceComponent: ({ general: generalPage, appearance: appearancePage, widgets: widgetsPage, voice: voicePage, buttons: buttonsPage, model: modelPage, mail: mailPage,
                                        people: peoplePage, memory: memoryPage, privacy: privacyPage, diagnostics: diagnosticsPage,
                                        about: aboutPage })[win.page]
                    onLoaded: { scroller.contentY = 0; pageIn.restart() }
                    ParallelAnimation {
                        id: pageIn
                        NumberAnimation { target: pageLoader; property: "opacity"; from: 0; to: 1; duration: JD.dur(240); easing.type: Easing.OutCubic }
                        NumberAnimation { target: pageLoader; property: "x"; from: 56; to: 32; duration: JD.dur(360); easing.type: JD.animStyle === "smooth" ? Easing.OutCubic : Easing.OutBack; easing.overshoot: 0.9 }
                    }
                }
            }

            // toast
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: win.toast ? 22 : 6
                visible: opacity > 0.01
                opacity: win.toast ? 1 : 0
                Behavior on anchors.bottomMargin { enabled: JD.animOn; SpringAnimation { spring: 4; damping: JD.springDamping + 0.05 } }
                Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: 180 } }
                implicitWidth: toastText.implicitWidth + 36
                implicitHeight: 38
                radius: 19
                color: "#3a3a3c"
                border.color: win.line
                Text { id: toastText; anchors.centerIn: parent; text: win.toast; color: win.t1; font.family: win.font; font.pixelSize: 13 }
            }
        }
    }

    // ═════════════════════ controls ═════════════════════
    component Glyph: Image {
        property string name: ""
        property real size: 16
        source: name ? win.icons + name + ".svg" : ""
        sourceSize: Qt.size(size * 2, size * 2)
        Layout.preferredWidth: size
        Layout.preferredHeight: size
        width: size
        height: size
        smooth: true
    }

    component PageTitle: ColumnLayout {
        property string title: ""
        property string subtitle: ""
        Layout.fillWidth: true
        Layout.bottomMargin: 8
        spacing: 4
        Text { text: title; color: win.t1; font.family: win.font; font.pixelSize: 24; font.weight: Font.Bold }
        Text { visible: !!subtitle; text: subtitle; color: win.t2; font.family: win.font; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true }
    }

    component GroupTitle: Text {
        Layout.topMargin: 14
        Layout.leftMargin: 4
        color: win.t2
        font.family: win.font
        font.pixelSize: 12
        font.weight: Font.DemiBold
    }

    component Group: Rectangle {
        default property alias content: rows.data
        Layout.fillWidth: true
        implicitHeight: rows.implicitHeight
        radius: 12
        color: win.card
        ColumnLayout {
            id: rows
            anchors.left: parent.left
            anchors.right: parent.right
            spacing: 0
        }
    }

    component Row: Item {
        id: row
        property string title: ""
        property string subtitle: ""
        default property alias control: slot.data
        Layout.fillWidth: true
        implicitHeight: Math.max(46, texts.implicitHeight + 20, slot.childrenRect.height + 16)
        Rectangle {  // separator above every row but the first
            visible: row.y > 0
            anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: 16 }
            height: 1
            color: win.line
        }
        ColumnLayout {
            id: texts
            anchors { left: parent.left; leftMargin: 16; verticalCenter: parent.verticalCenter; right: slot.left; rightMargin: 16 }
            spacing: 2
            Text { text: row.title; color: win.t1; font.family: win.font; font.pixelSize: 13; Layout.fillWidth: true; elide: Text.ElideRight }
            Text { visible: !!row.subtitle; text: row.subtitle; color: win.t2; font.family: win.font; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
        }
        Item {
            id: slot
            anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
            width: childrenRect.width
            height: childrenRect.height
        }
    }

    component RoundIcon: Rectangle {
        id: ri
        property string glyph: ""
        signal clicked()
        width: 30; height: 30; radius: 15
        color: riHover.hovered ? Qt.rgba(1, 1, 1, 0.16) : Qt.rgba(1, 1, 1, 0.08)
        scale: riTap.pressed ? 0.9 : 1
        Behavior on scale { NumberAnimation { duration: 100 } }
        Glyph { anchors.centerIn: parent; name: ri.glyph; size: 15 }
        HoverHandler { id: riHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { id: riTap; onTapped: ri.clicked() }
    }

    component Toggle: Rectangle {
        id: tg
        property bool checked: false
        signal toggled(bool value)
        implicitWidth: 44
        implicitHeight: 26
        width: implicitWidth
        height: implicitHeight
        radius: 13
        color: checked ? "#30d158" : "#48484a"
        Behavior on color { ColorAnimation { duration: 160 } }
        Rectangle {
            width: 22; height: 22; radius: 11
            y: 2
            x: tg.checked ? 20 : 2
            color: "white"
            Behavior on x { enabled: JD.animOn; SpringAnimation { spring: 6; damping: JD.animStyle === "smooth" ? 0.9 : 0.45 } }
        }
        TapHandler { onTapped: tg.toggled(!tg.checked) }
        HoverHandler { cursorShape: Qt.PointingHandCursor }
    }

    component Btn: Rectangle {
        id: b
        property string text: ""
        property bool primary: false
        property bool danger: false
        property bool busy: false
        property string glyph: ""
        signal clicked()
        implicitWidth: Math.max(80, btnRow.implicitWidth + 26)
        implicitHeight: 30
        width: implicitWidth
        height: implicitHeight
        radius: 8
        opacity: enabled ? 1 : 0.45
        color: primary ? (btnHover.hovered ? "#409cff" : win.blue) : danger ? (btnHover.hovered ? "#5a2a2a" : "#4a2323") : (btnHover.hovered ? "#4a4a4c" : win.field)
        scale: btnTap.pressed ? 0.97 : 1
        Behavior on scale { NumberAnimation { duration: 100 } }
        RowLayout {
            id: btnRow
            anchors.centerIn: parent
            spacing: 6
            BusyIndicator { visible: b.busy; running: b.busy; implicitWidth: 16; implicitHeight: 16 }
            Glyph { visible: !!b.glyph && !b.busy; name: b.glyph; size: 14 }
            Text { text: b.text; color: b.danger ? "#ff6961" : win.t1; font.family: win.font; font.pixelSize: 13; font.weight: Font.Medium }
        }
        HoverHandler { id: btnHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { id: btnTap; enabled: b.enabled && !b.busy; onTapped: b.clicked() }
    }

    component Field: TextField {
        id: f
        property string key: ""   // config path: saved on Enter / focus loss
        property var initial: key ? win.get(key) : ""
        implicitWidth: 260
        width: implicitWidth
        text: Array.isArray(initial) ? initial.join(", ") : (initial === undefined ? "" : String(initial))
        color: win.t1
        placeholderTextColor: win.t3
        selectionColor: win.blue
        font.family: win.font
        font.pixelSize: 13
        leftPadding: 10
        background: Rectangle { radius: 7; color: win.field; border.width: f.activeFocus ? 2 : 0; border.color: win.blue }
        function commit() {
            if (!key) return
            const old = win.get(key)
            const value = Array.isArray(old) ? text.split(",").map(s => s.trim()).filter(s => s) : text
            if (JSON.stringify(value) !== JSON.stringify(old)) { win.set(key, value); win.notify("Сохранено") }
        }
        onAccepted: commit()
        onActiveFocusChanged: if (!activeFocus) commit()
    }

    component Choice: ComboBox {
        id: cb
        property string key: ""
        property var options: []   // [{value, label}]
        implicitWidth: 260
        width: implicitWidth
        model: options
        textRole: "label"
        valueRole: "value"
        currentIndex: Math.max(0, options.findIndex(o => o.value === win.get(key)))
        onActivated: i => { if (key) { win.set(key, options[i].value); win.notify("Сохранено") } }
        font.family: win.font
        font.pixelSize: 13
        contentItem: Text {
            leftPadding: 10
            rightPadding: 28
            text: cb.displayText
            color: win.t1
            font: cb.font
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
        indicator: Glyph { name: "chevron-down"; size: 14; x: cb.width - width - 10; y: (cb.height - height) / 2; opacity: 0.7 }
        background: Rectangle { implicitHeight: 30; radius: 7; color: win.field }
        popup: Popup {
            y: cb.height + 4
            width: cb.width
            implicitHeight: Math.min(contentItem.implicitHeight + 8, 320)
            padding: 4
            contentItem: ListView {
                clip: true
                implicitHeight: contentHeight
                model: cb.popup.visible ? cb.delegateModel : null
                currentIndex: cb.highlightedIndex
            }
            background: Rectangle { radius: 10; color: "#2c2c2e"; border.color: win.line }
        }
        delegate: ItemDelegate {
            required property var modelData
            required property int index
            width: cb.width - 8
            contentItem: Text { text: modelData.label; color: win.t1; font.family: win.font; font.pixelSize: 13; elide: Text.ElideRight }
            background: Rectangle { radius: 6; color: highlighted ? win.blue : "transparent" }
            highlighted: cb.highlightedIndex === index
        }
    }

    component SSlider: RowLayout {
        id: ss
        property string key: ""
        property real from: 0
        property real to: 1
        property real step: 0.1
        property string unit: ""
        property int decimals: 1
        spacing: 10
        Slider {
            id: sl
            implicitWidth: 200
            from: ss.from; to: ss.to; stepSize: ss.step
            value: Number(win.get(ss.key)) || 0
            onPressedChanged: if (!pressed) { win.set(ss.key, Number(value.toFixed(ss.decimals))); win.notify("Сохранено") }
            background: Rectangle {
                x: sl.leftPadding; y: sl.topPadding + sl.availableHeight / 2 - height / 2
                width: sl.availableWidth; height: 4; radius: 2; color: "#48484a"
                Rectangle { width: sl.visualPosition * parent.width; height: parent.height; radius: 2; color: win.blue }
            }
            handle: Rectangle {
                x: sl.leftPadding + sl.visualPosition * (sl.availableWidth - width)
                y: sl.topPadding + sl.availableHeight / 2 - height / 2
                width: 20; height: 20; radius: 10; color: "white"
            }
        }
        Text { text: sl.value.toFixed(ss.decimals) + ss.unit; color: win.t2; font.family: win.font; font.pixelSize: 12; Layout.preferredWidth: 52 }
    }

    component Segmented: Rectangle {
        id: seg
        property var options: []    // [{value, label}]
        property var current
        signal picked(var value)
        implicitWidth: segRow.implicitWidth + 4
        implicitHeight: 30
        width: implicitWidth
        height: implicitHeight
        radius: 8
        color: win.field
        RowLayout {
            id: segRow
            anchors.centerIn: parent
            spacing: 2
            Repeater {
                model: seg.options
                Rectangle {
                    required property var modelData
                    implicitWidth: segText.implicitWidth + 22
                    implicitHeight: 26
                    radius: 6
                    color: seg.current === modelData.value ? "#636366" : "transparent"
                    Behavior on color { ColorAnimation { duration: 140 } }
                    Text { id: segText; anchors.centerIn: parent; text: modelData.label; color: win.t1; font.family: win.font; font.pixelSize: 13 }
                    TapHandler { onTapped: seg.picked(modelData.value) }
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                }
            }
        }
    }

    component Note: Text {
        Layout.fillWidth: true
        Layout.leftMargin: 4
        Layout.topMargin: 4
        wrapMode: Text.Wrap
        color: win.t2
        font.family: win.font
        font.pixelSize: 12
        textFormat: Text.StyledText
        linkColor: "#409cff"
        onLinkActivated: link => Quickshell.execDetached(["xdg-open", link])
    }

    // ═════════════════════ pages ═════════════════════
    Component {
        id: generalPage
        ColumnLayout {
            spacing: 6
            PageTitle { title: "Общие"; subtitle: "Как зовут ассистента и как он обращается к вам" }
            Group {
                Row { title: "Имя ассистента"; subtitle: "Показывается на острове"; Field { key: "user.assistant_name" } }
                Row { title: "Другие имена"; subtitle: "Через запятую, на все он откликается"; Field { key: "user.assistant_aliases" } }
                Row { title: "Как обращаться к вам"; Field { key: "user.address_as"; placeholderText: "сэр" } }
                Row { title: "Ваше имя"; subtitle: "Для подписи в письмах"; Field { key: "user.name"; placeholderText: "Имя" } }
            }
            GroupTitle { text: "СИСТЕМА" }
            Group {
                Row {
                    title: "Запускать вместе с системой"
                    Toggle { checked: win.d.autostart ? win.d.autostart.enabled : false
                             onToggled: v => { win.run(["autostart", v ? "on" : "off"], r => { win.d.autostart = r; win.d = Object.assign({}, win.d) }); win.notify(v ? "Автозапуск включён" : "Автозапуск выключен") } }
                }
                Row { title: "Уведомления"; subtitle: "Системные уведомления о подтверждениях и ошибках"; Toggle { checked: !!win.get("ui.notifications"); onToggled: v => win.set("ui.notifications", v) } }
                Row {
                    title: "Язык распознавания"
                    Choice { key: "stt.language"; options: [{ value: "ru", label: "Русский" }, { value: "en", label: "English" }, { value: "", label: "Автоопределение" }] }
                }
            }
        }
    }

    Component {
        id: appearancePage
        ColumnLayout {
            spacing: 6
            PageTitle { title: "Остров и анимации"; subtitle: "Как выглядит и двигается Dynamic Island" }
            Group {
                Row {
                    title: "Анимации"
                    subtitle: win.get("island.animations") === "off" ? "Мгновенные переходы" : win.get("island.animations") === "smooth" ? "Плавно, без отскока" : "Пружинные, как у Apple"
                    Segmented {
                        options: [{ value: "spring", label: "Пружинные" }, { value: "smooth", label: "Плавные" }, { value: "off", label: "Выкл" }]
                        current: win.get("island.animations")
                        onPicked: v => win.set("island.animations", v)
                    }
                }
                Row { title: "Появляться при наведении"; subtitle: "Подведите курсор к верхнему краю экрана по центру"; Toggle { checked: win.get("island.hover_reveal") !== false; onToggled: v => win.set("island.hover_reveal", v) } }
                Row {
                    title: "Монитор"
                    Choice {
                        key: "island.screen"
                        options: [{ value: "", label: "Основной (слева сверху)" }].concat(Quickshell.screens.map(s => ({ value: s.name, label: s.name + " · " + s.width + "×" + s.height })))
                    }
                }
            }
            Note { text: "Все изменения применяются сразу. Погода и события — в разделе «Виджеты». Открыть меню клавишей: команда <tt>qs -p ~/JustDay/island ipc call island toggle</tt> в Системных настройках → Комбинации клавиш." }
        }
    }

    Component {
        id: widgetsPage
        ColumnLayout {
            spacing: 6
            PageTitle { title: "Виджеты"; subtitle: "Что показывать, когда вы наводите курсор на верхний край экрана" }
            Group {
                Row { title: "Погода"; subtitle: "Open-Meteo, без ключей; в сеть уходит только название города"; Toggle { checked: win.get("island.show_weather") !== false; onToggled: v => win.set("island.show_weather", v) } }
                Row { title: "Город"; subtitle: "Пусто — погода не запрашивается"; Field { key: "island.city"; placeholderText: "Москва" } }
                Row { title: "Последние события"; subtitle: "Последний ответ ассистента, работа Клода"; Toggle { checked: win.get("island.show_events") !== false; onToggled: v => win.set("island.show_events", v) } }
            }
            Note { text: "В меню острова (клик по нему) также есть плеер — он появляется, когда что-то играет." }
        }
    }

    Component {
        id: voicePage
        ColumnLayout {
            id: vp
            spacing: 6
            property string engine: win.get("tts.engine")
            property var neural: win.d.voices ? win.d.voices.neural : []
            property bool neuralOk: win.d.voices ? win.d.voices.neural_running : false
            property bool neuralInstalled: win.d.voices ? win.d.voices.neural_installed : false
            Timer { id: reloadLater; interval: 4000; onTriggered: win.reload() }
            property string sampleText: ""
            property bool recording: false
            property bool designing: false

            PageTitle { title: "Голос и звук"; subtitle: "Каким голосом говорит ассистент и как он вас слушает" }
            Group {
                Row {
                    title: "Движок голоса"
                    subtitle: vp.engine === "qwen" ? "Нейросетевой: Qwen3-TTS на вашей видеокарте" : vp.engine === "silero" ? "Silero: быстрый, звучит роботизированно" : "Без голоса, только остров"
                    Segmented {
                        options: [{ value: "qwen", label: "Нейросетевой" }, { value: "silero", label: "Silero" }, { value: "none", label: "Выкл" }]
                        current: vp.engine
                        onPicked: v => { win.set("tts.engine", v); vp.engine = v }
                    }
                }
                Row {
                    visible: vp.engine === "qwen" && !vp.neuralInstalled
                    title: "Нейроголос не установлен"
                    subtitle: "Загрузка ~4 ГБ, нужна видеокарта NVIDIA"
                    Btn { text: "Установить"; primary: true; onClicked: Quickshell.execDetached(["kitty", "--hold", Quickshell.shellDir + "/../scripts/setup-voice.sh"]) }
                }
                Row {
                    visible: vp.engine === "qwen" && vp.neuralInstalled && !vp.neuralOk
                    title: "Служба голоса остановлена"
                    subtitle: "Пока она не запущена, ассистент говорит голосом Silero"
                    Btn { text: "Запустить"; primary: true; onClicked: { Quickshell.execDetached(["systemctl", "--user", "start", "justday-voice.service"]); win.notify("Запускаю голос…"); reloadLater.restart() } }
                }
                Row {
                    visible: vp.engine === "qwen" && vp.neuralInstalled
                    title: "Качество голоса"
                    subtitle: win.get("tts.neural_quality") === "best" ? "Модель 1.7B: чище тембр, ~4,5 ГБ видеопамяти" : "Модель 0.6B: быстрее, ~2,5 ГБ видеопамяти"
                    Segmented {
                        options: [{ value: "fast", label: "Быстрее" }, { value: "best", label: "Качественнее" }]
                        current: win.get("tts.neural_quality") || "fast"
                        onPicked: v => {
                            win.set("tts.neural_quality", v)
                            Quickshell.execDetached(["systemctl", "--user", "restart", "justday-voice.service"])
                            win.notify(v === "best" ? "Загружаю большую модель голоса (до минуты)…" : "Переключаю на быструю модель…")
                        }
                    }
                }
                Row {
                    visible: vp.engine === "silero"
                    title: "Голос Silero"
                    Choice { key: "tts.speaker"; options: (win.d.voices ? win.d.voices.silero : []).map(v => ({ value: v.id, label: v.name + " · " + v.kind })) }
                }
            }

            GroupTitle { visible: vp.engine === "qwen" && vp.neuralInstalled; text: "ГОЛОСА" }
            Group {
                visible: vp.engine === "qwen" && vp.neuralInstalled
                Repeater {
                    model: vp.neural
                    Row {
                        required property var modelData
                        title: modelData.name + (win.get("tts.voice") === modelData.id ? "  ✓" : "")
                        subtitle: modelData.description
                        RowLayout {
                            spacing: 8
                            Btn { glyph: "play"; text: "Прослушать"; onClicked: { win.set("tts.voice", modelData.id); win.run(["voice", "preview", "Здравствуйте, сэр. Так звучит мой голос."]) } }
                            Btn { text: "Выбрать"; primary: win.get("tts.voice") !== modelData.id; enabled: win.get("tts.voice") !== modelData.id; onClicked: { win.set("tts.voice", modelData.id); win.notify("Голос: " + modelData.name) } }
                            Btn { visible: !modelData.builtin; glyph: "trash"; text: ""; implicitWidth: 34; danger: true
                                  onClicked: win.run(["voice", "delete", modelData.id], () => win.reload()) }
                        }
                    }
                }
            }

            GroupTitle { visible: vp.engine === "qwen" && vp.neuralOk; text: "НОВЫЙ ГОЛОС" }
            Group {
                visible: vp.engine === "qwen" && vp.neuralOk
                Row {
                    title: "Создать по описанию"
                    subtitle: "Опишите тембр, возраст, манеру. Первый раз загрузится модель 1.7B (~3,5 ГБ)"
                    Field { id: designName; key: ""; placeholderText: "Название голоса"; implicitWidth: 200 }
                }
                Item {
                    Layout.fillWidth: true
                    implicitHeight: 96
                    Rectangle {
                        anchors { fill: parent; leftMargin: 16; rightMargin: 14; bottomMargin: 10 }
                        radius: 7
                        color: win.field
                        TextArea {
                            id: designText
                            anchors.fill: parent
                            wrapMode: TextArea.Wrap
                            color: win.t1
                            placeholderText: "Например: спокойный низкий мужской голос, чёткая дикция, манера сдержанного британского дворецкого"
                            placeholderTextColor: win.t3
                            font.family: win.font
                            font.pixelSize: 13
                            background: null
                        }
                    }
                }
                Row {
                    title: ""
                    Btn {
                        text: vp.designing ? "Создаю…" : "Создать голос"
                        primary: true
                        busy: vp.designing
                        enabled: designName.text.trim() && designText.text.trim()
                        onClicked: {
                            vp.designing = true
                            win.run(["voice", "design", designName.text.trim(), designText.text.trim()], r => {
                                vp.designing = false
                                if (r.ok) { win.notify("Голос создан"); win.set("tts.voice", r.id); win.reload() }
                                else win.notify("Не получилось: " + (r.error || ""))
                            })
                        }
                    }
                }
                Row {
                    title: "Клонировать из записи"
                    subtitle: vp.sampleText ? "Распознано: «" + vp.sampleText + "»" : "Прочитайте вслух любой текст 12 секунд. Только свой голос или голос, на который есть разрешение"
                    RowLayout {
                        spacing: 8
                        Field { id: cloneName; placeholderText: "Название"; implicitWidth: 140 }
                        Btn {
                            text: vp.recording ? "Говорите…" : "Записать"
                            glyph: "mic"
                            busy: vp.recording
                            onClicked: {
                                vp.recording = true
                                win.run(["voice", "record", "12"], r => { vp.recording = false; if (r.ok) { vp.sampleText = r.text; vp.samplePath = r.path } else win.notify("Не расслышал, попробуйте ещё раз") })
                            }
                        }
                        Btn {
                            text: "Сохранить"
                            primary: true
                            enabled: !!vp.sampleText && !!cloneName.text.trim()
                            onClicked: win.run(["voice", "clone", cloneName.text.trim(), vp.samplePath, vp.sampleText], r => {
                                if (r.ok) { win.notify("Голос сохранён"); win.set("tts.voice", r.id); vp.sampleText = ""; win.reload() }
                                else win.notify("Не получилось: " + (r.error || ""))
                            })
                        }
                    }
                }
            }
            property string samplePath: ""

            GroupTitle { text: "УСТРОЙСТВА" }
            Group {
                Row {
                    title: "Микрофон"
                    Choice {
                        key: "audio.input"
                        implicitWidth: 320
                        options: [{ value: "", label: "Системный по умолчанию" }].concat((win.d.devices ? win.d.devices.sources : []).map(s => ({ value: s.name, label: s.description })))
                        currentIndex: Math.max(0, options.findIndex(o => o.value && win.get("audio.input") && o.value.indexOf(win.get("audio.input")) >= 0))
                    }
                }
                Row {
                    title: "Вывод звука"
                    Choice {
                        key: "audio.output"
                        implicitWidth: 320
                        options: [{ value: "", label: "Системный по умолчанию" }].concat((win.d.devices ? win.d.devices.sinks : []).map(s => ({ value: s.name, label: s.description })))
                        currentIndex: Math.max(0, options.findIndex(o => o.value && win.get("audio.output") && o.value.indexOf(win.get("audio.output")) >= 0))
                    }
                }
                Row { title: "Звуковые сигналы"; subtitle: "Короткий звук в начале прослушивания и после действия"; Toggle { checked: !!win.get("audio.earcons"); onToggled: v => win.set("audio.earcons", v) } }
            }

            GroupTitle { text: "КАК СЛУШАЕТ" }
            Group {
                Row { title: "Пауза в конце фразы"; subtitle: "Сколько тишины считать концом просьбы"; SSlider { key: "audio.silence_seconds"; from: 0.5; to: 2.0; step: 0.1; unit: " с" } }
                Row { title: "Ждать ответа на вопрос"; subtitle: "Слушать без кнопки после вопроса ассистента (0 — выкл)"; SSlider { key: "audio.followup_seconds"; from: 0; to: 15; step: 1; decimals: 0; unit: " с" } }
                Row { title: "Двойное нажатие = отмена"; subtitle: "Максимальный промежуток между нажатиями (0 — выкл)"; SSlider { key: "audio.double_tap_seconds"; from: 0; to: 0.6; step: 0.05; decimals: 2; unit: " с" } }
                Row { title: "Слово «Hey Jarvis»"; subtitle: "Микрофон слушает постоянно, звук не покидает компьютер"; Toggle { checked: !!win.get("wakeword.enabled"); onToggled: v => win.set("wakeword.enabled", v) } }
            }
        }
    }

    Component {
        id: buttonsPage
        ColumnLayout {
            spacing: 6
            PageTitle { title: "Кнопки"; subtitle: "Глобальные сочетания KDE. Формат: Meta+J, Ctrl+Alt+Space, F19" }
            Group {
                Row { title: "Говорить"; subtitle: "Нажать — слушает до паузы, зажать — пока держите"; Field { id: talkKey; text: win.d.hotkeys ? win.d.hotkeys.talk : ""; implicitWidth: 180 } }
                Row { title: "Кнопка мыши"; subtitle: "Вторая клавиша «говорить», например F19 с G502"; Field { id: extraKey; text: win.d.hotkeys ? win.d.hotkeys.extra : ""; implicitWidth: 180 } }
                Row { title: "Отменить всё"; Field { id: cancelKey; text: win.d.hotkeys ? win.d.hotkeys.cancel : ""; implicitWidth: 180 } }
                Row {
                    title: ""
                    Btn {
                        text: "Применить"
                        primary: true
                        onClicked: win.run(["hotkey", "set", "--talk", talkKey.text, "--extra", extraKey.text, "--cancel", cancelKey.text],
                                           r => win.notify(r.ok ? "Сочетания обновлены" : "Не получилось"))
                    }
                }
            }
            Note {
                text: "<b>Кнопка на мыши Logitech (G502 и др.)</b>: назначьте ей клавишу F19 через libratbag, например<br>" +
                      "<tt>ratbagctl &lt;мышь&gt; profile 0 button 5 action set key KEY_F19</tt>. F13 не подходит: в KDE она открывает Системные настройки.<br><br>" +
                      "<b>Двойное нажатие</b> кнопки «говорить» отменяет всё — промежуток настраивается в разделе «Голос и звук»."
            }
        }
    }

    Component {
        id: modelPage
        ColumnLayout {
            id: mp
            spacing: 6
            property var models: win.d.models || ({ current: {}, providers: [] })
            property string provider: models.current.provider || "claude"
            property var info: (models.providers || []).find(p => p.id === mp.provider) || ({})
            PageTitle { title: "Модель"; subtitle: "Какая нейросеть думает. Память, навыки и инструменты общие для всех" }
            Group {
                Row {
                    title: "Провайдер"
                    subtitle: mp.info.desc || ""
                    Segmented {
                        options: [{ value: "claude", label: "Claude" }, { value: "ollama", label: "Локальная" }, { value: "openrouter", label: "OpenRouter" },
                                  { value: "deepseek", label: "DeepSeek" }, { value: "custom", label: "Свой адрес" }]
                        current: mp.provider
                        onPicked: v => {
                            mp.provider = v
                            const info = (mp.models.providers || []).find(p => p.id === v) || {}
                            const suggested = (v === "ollama" && win.d.local_models && win.d.local_models.length) ? win.d.local_models[0] : ((info.suggested || [])[0] || "")
                            if (suggested) win.set("brain.model", suggested)
                            win.set("brain.provider", v)
                        }
                    }
                }
                Row {
                    title: "Модель"
                    subtitle: "Можно ввести любое название модели провайдера"
                    RowLayout {
                        spacing: 8
                        Choice {
                            implicitWidth: 240
                            options: (mp.provider === "ollama" ? (win.d.local_models || []) : (mp.info.suggested || [])).map(m => ({ value: m, label: m }))
                            currentIndex: Math.max(0, options.findIndex(o => o.value === win.get("brain.model")))
                            onActivated: i => { win.set("brain.model", options[i].value); modelField.text = options[i].value }
                        }
                        Field { id: modelField; key: "brain.model"; implicitWidth: 200 }
                    }
                }
                Row {
                    visible: !!mp.info.needs_key
                    title: "API-ключ"
                    subtitle: mp.info.has_key ? "Ключ сохранён в связке ключей" : "Хранится в KWallet / GNOME Keyring, не в файлах"
                    RowLayout {
                        spacing: 8
                        Field { id: keyField; echoMode: TextInput.Password; placeholderText: mp.info.has_key ? "••••••••" : "вставьте ключ"; implicitWidth: 220 }
                        Btn {
                            text: "Сохранить"
                            primary: true
                            enabled: !!keyField.text
                            onClicked: {
                                const secretName = mp.provider
                                win.run(["secret", "set", secretName, "--stdin"], () => { keyField.text = ""; win.notify("Ключ сохранён"); win.restartNeeded = true; win.reload() },
                                        { JUSTDAY_SECRET: keyField.text })
                            }
                        }
                    }
                }
                Row { visible: mp.provider === "custom"; title: "Адрес API"; subtitle: "Anthropic-совместимый, например LiteLLM"; Field { key: "brain.base_url"; placeholderText: "http://127.0.0.1:4000" } }
                Row {
                    visible: mp.provider === "claude"
                    title: "Сколько думать"
                    subtitle: "Больше — умнее, но медленнее"
                    Segmented {
                        options: [{ value: "low", label: "Быстро" }, { value: "medium", label: "Средне" }, { value: "high", label: "Глубоко" }]
                        current: win.get("brain.effort")
                        onPicked: v => win.set("brain.effort", v)
                    }
                }
            }
            Note {
                text: mp.provider === "claude" ? "Используются лимиты вашей подписки Claude. Вход: команда <tt>claude</tt>, затем /login."
                    : mp.provider === "ollama" ? "Всё на вашей видеокарте, ничего не уходит в интернет. Модель слабее Claude в сложных действиях с окнами."
                    : mp.provider === "openrouter" ? "Модели с суффиксом :free бесплатны с лимитами. Ключ: <a href='https://openrouter.ai/keys'>openrouter.ai/keys</a>"
                    : mp.provider === "deepseek" ? "Ключ: <a href='https://platform.deepseek.com/api_keys'>platform.deepseek.com</a>"
                    : "Любой сервер с Anthropic Messages API. Для провайдеров только с OpenAI API поставьте LiteLLM."
            }
        }
    }

    Component {
        id: mailPage
        ColumnLayout {
            id: mlp
            spacing: 6
            property bool connecting: false
            property string status: win.get("mail.address") ? (win.d.mail_password ? "Подключена: " + win.get("mail.address") : "Нет пароля приложения") : "Не подключена"
            PageTitle { title: "Почта"; subtitle: "Письма читает и пишет локальная модель — в облако ничего не уходит" }
            Note {
                Layout.bottomMargin: 6
                text: "<b>Почему «пароль приложения», а не вход через Google?</b> Это не пароль от аккаунта, а отдельный ключ только для почты (IMAP/SMTP), как у Thunderbird. " +
                      "Он хранится в связке ключей KDE на этом компьютере и передаётся только серверу Google. Отозвать можно в любой момент на странице паролей приложений — остальной аккаунт он не открывает. " +
                      "Кнопка «Войти через Google» требует, чтобы у приложения была проверенная Google регистрация — у открытого проекта её пока нет."
            }
            Group {
                Row { title: "Состояние"; subtitle: mlp.status; Glyph { name: win.get("mail.address") && win.d.mail_password ? "check" : "circle-alert"; size: 18 } }
                Row { title: "Адрес Gmail"; Field { id: mailAddr; text: win.get("mail.address") || ""; placeholderText: "you@gmail.com" } }
                Row { title: "Пароль приложения"; subtitle: "16 символов, не основной пароль"; Field { id: mailPw; echoMode: TextInput.Password; placeholderText: win.d.mail_password ? "••••••••" : "xxxx xxxx xxxx xxxx" } }
                Row {
                    title: ""
                    Btn {
                        text: mlp.connecting ? "Проверяю…" : "Подключить"
                        primary: true
                        busy: mlp.connecting
                        enabled: !!mailAddr.text.trim() && (!!mailPw.text || win.d.mail_password)
                        onClicked: {
                            mlp.connecting = true
                            win.run(["mail", "setup", "--address", mailAddr.text.trim()], r => {
                                mlp.connecting = false
                                win.notify(r.ok ? "Почта подключена: во входящих " + r.inbox : "Не удалось войти: " + (r.error || ""))
                                mailPw.text = ""
                                win.reload()
                            }, { JUSTDAY_SECRET: mailPw.text })
                        }
                    }
                }
            }
            Note { text: "Нужна двухэтапная аутентификация Google. Создать пароль приложения: <a href='https://myaccount.google.com/apppasswords'>myaccount.google.com/apppasswords</a>" }
            GroupTitle { text: "ПОВЕДЕНИЕ" }
            Group {
                Row { title: "Сообщать о новых письмах"; subtitle: "«Новое письмо от …» голосом и на острове"; Toggle { checked: !!win.get("mail.announce"); onToggled: v => win.set("mail.announce", v) } }
                Row { title: "Проверять каждые"; SSlider { key: "mail.poll_seconds"; from: 60; to: 900; step: 60; decimals: 0; unit: " с" } }
                Row { title: "Что считать важным"; subtitle: "Поисковый запрос Gmail"; Field { key: "mail.query"; implicitWidth: 300 } }
            }
        }
    }

    Component {
        id: peoplePage
        ColumnLayout {
            id: pp
            spacing: 6
            property var people: []
            function refresh() { win.run(["contacts", "list"], v => pp.people = Array.isArray(v) ? v : []) }
            Component.onCompleted: refresh()
            PageTitle { title: "Люди"; subtitle: "Записная книжка, которую ассистент пополняет сам: кто есть кто и как с кем связываться" }
            Group {
                Row { visible: pp.people.length === 0; title: "Пока пусто"; subtitle: "Скажите, например: «напиши маме» — он спросит, как с ней связаться, и запомнит" }
                Repeater {
                    model: pp.people
                    Row {
                        required property var modelData
                        title: modelData.name + (modelData.aliases && modelData.aliases.length ? "  ·  " + modelData.aliases.join(", ") : "")
                        subtitle: [modelData.email ? "почта " + modelData.email : "", modelData.discord ? "Discord " + modelData.discord : "",
                                   modelData.telegram ? "Telegram " + modelData.telegram : "", modelData.whatsapp ? "WhatsApp " + modelData.whatsapp : "",
                                   modelData.preferred ? "обычно через " + modelData.preferred : "", modelData.note || ""].filter(x => x).join("  ·  ")
                        Btn { glyph: "trash"; text: ""; implicitWidth: 34; danger: true; onClicked: win.run(["contacts", "forget", modelData.name], () => pp.refresh()) }
                    }
                }
            }
            GroupTitle { text: "ДОБАВИТЬ ИЛИ ИЗМЕНИТЬ" }
            Group {
                Row { title: "Имя"; Field { id: cName; placeholderText: "Мама" } }
                Row { title: "Как вы его называете"; subtitle: "Через запятую"; Field { id: cAliases; placeholderText: "мама, мамуля" } }
                Row { title: "Почта"; Field { id: cEmail; placeholderText: "name@example.com" } }
                Row { title: "Discord / Telegram / WhatsApp"; RowLayout { spacing: 6; Field { id: cDiscord; placeholderText: "Discord"; implicitWidth: 110 } Field { id: cTelegram; placeholderText: "Telegram"; implicitWidth: 110 } Field { id: cWhatsapp; placeholderText: "WhatsApp"; implicitWidth: 110 } } }
                Row {
                    title: "Обычно связываться через"
                    Choice { id: cPreferred; options: [{ value: "", label: "—" }, { value: "discord", label: "Discord" }, { value: "telegram", label: "Telegram" }, { value: "whatsapp", label: "WhatsApp" }, { value: "email", label: "Почта" }, { value: "phone", label: "Телефон" }] }
                }
                Row { title: "Заметка"; subtitle: "Например: «живёт в Польше»"; Field { id: cNote; implicitWidth: 300 } }
                Row {
                    title: ""
                    Btn {
                        text: "Сохранить"
                        primary: true
                        enabled: !!cName.text.trim()
                        onClicked: {
                            const args = ["contacts", "set", cName.text.trim()]
                            const add = (k, v) => { if (v) args.push(k + "=" + v) }
                            add("aliases", cAliases.text.trim()); add("email", cEmail.text.trim()); add("discord", cDiscord.text.trim())
                            add("telegram", cTelegram.text.trim()); add("whatsapp", cWhatsapp.text.trim())
                            add("preferred", cPreferred.options[cPreferred.currentIndex].value); add("note", cNote.text.trim())
                            win.run(args, () => { pp.refresh(); win.notify("Сохранено"); [cName, cAliases, cEmail, cDiscord, cTelegram, cWhatsapp, cNote].forEach(f => f.text = "") })
                        }
                    }
                }
            }
        }
    }

    Component {
        id: memoryPage
        ColumnLayout {
            id: memp
            spacing: 6
            property var mem: win.d.memory || ({ files: [] })
            property string editing: ""      // file being edited
            property string header: ""       // its frontmatter, kept as is
            property string body: ""         // text loaded into the editor
            property bool profileOpen: false
            property string profile: ""

            function open(file) {
                if (editing === file) { editing = ""; return }
                win.run(["memory", "read", file], r => {
                    const t = r.text || ""
                    const m = t.match(/^(---\n[\s\S]*?\n---\n)([\s\S]*)$/)
                    memp.header = m ? m[1] : ""
                    memp.body = (m ? m[2] : t).trim()
                    memp.editing = file
                })
            }

            PageTitle { title: "Память"; subtitle: "Что ассистент запомнил о вас. Хранится в файлах и одинакова для любой модели. Нажмите на заметку, чтобы изменить" }
            Group {
                Row { visible: memp.mem.files.length === 0; title: "Пока пусто"; subtitle: "Скажите «запомни, что…» или добавьте заметку ниже" }
                Repeater {
                    model: memp.mem.files
                    ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredWidth: memp.width
                        spacing: 0
                        Row {
                            title: modelData.description || modelData.name
                            subtitle: memp.editing === modelData.file ? "Редактирование" : modelData.body.replace(/\*\*/g, "").split("\n").filter(l => l.trim()).slice(0, 2).join(" ").slice(0, 220)
                            RowLayout {
                                spacing: 6
                                Btn { glyph: memp.editing === modelData.file ? "chevron-up" : "file-text"; text: memp.editing === modelData.file ? "Свернуть" : "Изменить"; onClicked: memp.open(modelData.file) }
                                Btn { glyph: "trash"; text: ""; implicitWidth: 34; danger: true; onClicked: win.run(["memory", "forget", modelData.file], () => { win.notify("Забыто (в корзине)"); memp.editing = ""; win.reload() }) }
                            }
                        }
                        Item {
                            visible: memp.editing === modelData.file
                            Layout.fillWidth: true
                            Layout.preferredWidth: memp.width
                            implicitHeight: visible ? 230 : 0
                            Behavior on implicitHeight { enabled: JD.animOn; NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                            Rectangle {
                                anchors { fill: parent; leftMargin: 16; rightMargin: 14; bottomMargin: 48 }
                                radius: 8
                                color: win.field
                                Flickable {
                                    id: editFlick
                                    anchors.fill: parent
                                    clip: true
                                    contentHeight: editText.implicitHeight
                                    ScrollBar.vertical: ScrollBar {}
                                    TextArea {
                                        id: editText
                                        width: editFlick.width
                                        text: memp.body
                                        wrapMode: TextArea.Wrap
                                        color: win.t1
                                        font.family: win.font
                                        font.pixelSize: 13
                                        selectByMouse: true
                                        background: null
                                    }
                                }
                            }
                            Btn {
                                anchors { right: parent.right; bottom: parent.bottom; rightMargin: 14; bottomMargin: 10 }
                                text: "Сохранить"
                                primary: true
                                onClicked: win.run(["memory", "write", modelData.file], () => { win.notify("Память обновлена"); memp.editing = ""; win.reload() },
                                                   { JUSTDAY_TEXT: memp.header + "\n" + editText.text.trim() + "\n" })
                            }
                        }
                    }
                }
            }

            GroupTitle { text: "НОВАЯ ЗАМЕТКА" }
            Group {
                Row { title: "О чём"; Field { id: noteTitle; placeholderText: "Мой основной браузер"; implicitWidth: 300 } }
                Item {
                    Layout.fillWidth: true
                    implicitHeight: 90
                    Rectangle {
                        anchors { fill: parent; leftMargin: 16; rightMargin: 14; bottomMargin: 10 }
                        radius: 8
                        color: win.field
                        TextArea {
                            id: noteText
                            anchors.fill: parent
                            wrapMode: TextArea.Wrap
                            color: win.t1
                            placeholderText: "Что запомнить, например: пользуюсь Helium, закладки в нём"
                            placeholderTextColor: win.t3
                            font.family: win.font
                            font.pixelSize: 13
                            background: null
                        }
                    }
                }
                Row {
                    title: ""
                    Btn {
                        text: "Запомнить"
                        primary: true
                        enabled: !!noteTitle.text.trim() && !!noteText.text.trim()
                        onClicked: win.run(["memory", "new", noteTitle.text.trim()], () => { win.notify("Запомнил"); noteTitle.text = ""; noteText.text = ""; win.reload() },
                                           { JUSTDAY_TEXT: noteText.text })
                    }
                }
            }

            GroupTitle { text: "ПРОФИЛЬ" }
            Group {
                Row {
                    title: "Профиль пользователя и компьютера"
                    subtitle: "CLAUDE.md: кто вы, какое у вас железо и программы. Ассистент читает его в начале каждого разговора"
                    Btn {
                        text: memp.profileOpen ? "Свернуть" : "Изменить"
                        glyph: memp.profileOpen ? "chevron-up" : "file-text"
                        onClicked: {
                            if (memp.profileOpen) { memp.profileOpen = false; return }
                            win.run(["memory", "read", memp.mem.profile], r => { memp.profile = r.text || ""; memp.profileOpen = true })
                        }
                    }
                }
                Item {
                    visible: memp.profileOpen
                    Layout.fillWidth: true
                    Layout.preferredWidth: memp.width
                    implicitHeight: visible ? 300 : 0
                    Rectangle {
                        anchors { fill: parent; leftMargin: 16; rightMargin: 14; bottomMargin: 48 }
                        radius: 8
                        color: win.field
                        Flickable {
                            id: profileFlick
                            anchors.fill: parent
                            clip: true
                            contentHeight: profileText.implicitHeight
                            ScrollBar.vertical: ScrollBar {}
                            TextArea { id: profileText; width: profileFlick.width; text: memp.profile; wrapMode: TextArea.Wrap; color: win.t1; font.family: "monospace"; font.pixelSize: 12; selectByMouse: true; background: null }
                        }
                    }
                    Btn {
                        anchors { right: parent.right; bottom: parent.bottom; rightMargin: 14; bottomMargin: 10 }
                        text: "Сохранить профиль"
                        primary: true
                        onClicked: win.run(["memory", "write", memp.mem.profile], () => { win.notify("Профиль сохранён · применится в новом разговоре"); memp.profileOpen = false },
                                           { JUSTDAY_TEXT: profileText.text })
                    }
                }
            }
            RowLayout {
                Layout.topMargin: 10
                spacing: 8
                Btn { glyph: "folder-open"; text: "Открыть папку памяти"; onClicked: Quickshell.execDetached(["xdg-open", memp.mem.dir]) }
                Btn { glyph: "rotate-ccw"; text: "Новый разговор"; onClicked: { JD.send({ cmd: "new_session" }); win.notify("Разговор начат заново, память сохранена") } }
            }
        }
    }

    Component {
        id: privacyPage
        ColumnLayout {
            spacing: 6
            PageTitle { title: "Приватность"; subtitle: "Что остаётся на компьютере, а что уходит в облако" }
            Group {
                Row { title: "Только на компьютере"; subtitle: "Звук и распознавание речи, голос, мгновенные команды, почта, ключи и пароли, журнал" ; Glyph { name: "house"; size: 18 } }
                Row { title: "Уходит модели"; subtitle: (win.get("brain.provider") === "ollama" ? "Ничего: модель локальная. " : "Текст просьб, профиль и память, то, что ассистент прочитал инструментами (команды, файлы, скриншоты). ") + "Телеметрия Claude Code выключена"; Glyph { name: "cloud"; size: 18 } }
            }
            GroupTitle { text: "НАСТРОЙКИ" }
            Group {
                Row { title: "Метки кнопок на скриншотах"; subtitle: "Шина доступности: точные клики в KDE/Qt-приложениях"; Toggle { checked: !!win.get("desktop.accessibility"); onToggled: v => win.set("desktop.accessibility", v) } }
                Row { title: "Управление браузером (Claude in Chrome)"; subtitle: "Работает только с моделью Claude"; Toggle { checked: !!win.get("brain.chrome"); onToggled: v => win.set("brain.chrome", v) } }
                Row { title: "Хранение данных у Anthropic"; subtitle: "30 дней, если обучение на ваших данных выключено"; Btn { glyph: "external-link"; text: "Открыть"; onClicked: Quickshell.execDetached(["xdg-open", "https://claude.ai/settings/data-privacy-controls"]) } }
            }
            GroupTitle { text: "ОЧИСТКА" }
            Group {
                Row {
                    title: "Журнал событий"
                    subtitle: "Что вы просили и что он делал" + (win.d.memory ? " · " + win.d.memory.journal_kb + " КБ" : "")
                    Btn { text: confirmJ.armed ? "Точно очистить?" : "Очистить"; danger: true
                          property bool armed: false; id: confirmJ
                          onClicked: { if (!armed) { armed = true; return } win.run(["memory", "clear-journal"], () => { win.notify("Журнал в корзине"); win.reload() }); armed = false } }
                }
            }
        }
    }

    Component {
        id: diagnosticsPage
        ColumnLayout {
            id: dp
            spacing: 6
            property var results: []
            property bool checking: false
            PageTitle { title: "Диагностика"; subtitle: "Работают ли части JustDay" }
            Group {
                Repeater {
                    model: win.d.services || []
                    Row {
                        required property var modelData
                        title: ({ "justday.service": "Ассистент", "justday-island.service": "Dynamic Island", "justday-ollama.service": "Локальная модель", "justday-voice.service": "Нейроголос" })[modelData.unit] || modelData.unit
                        subtitle: modelData.unit + " · " + modelData.state
                        Rectangle { implicitWidth: 10; implicitHeight: 10; radius: 5; color: modelData.active ? "#30d158" : "#ff453a" }
                    }
                }
            }
            RowLayout {
                Layout.topMargin: 10
                spacing: 8
                Btn { text: dp.checking ? "Проверяю…" : "Проверить всё"; glyph: "activity"; busy: dp.checking; primary: true
                      onClicked: { dp.checking = true; win.run(["doctor", "--json"], v => { dp.checking = false; dp.results = Array.isArray(v) ? v : [] }) } }
                Btn { glyph: "refresh-cw"; text: "Перезапустить ассистента"; onClicked: { win.run(["restart"], () => win.reload()); win.notify("Перезапускаю…") } }
                Btn { glyph: "file-text"; text: "Журнал"; onClicked: Quickshell.execDetached(["kitty", "--detach", "justday", "logs", "-f"]) }
            }
            Group {
                visible: dp.results.length > 0
                Layout.topMargin: 10
                Repeater {
                    model: dp.results
                    Row {
                        required property var modelData
                        title: modelData.name
                        subtitle: modelData.detail
                        Glyph { name: modelData.ok ? "check" : "x"; size: 18 }
                    }
                }
            }
        }
    }

    Component {
        id: aboutPage
        ColumnLayout {
            spacing: 14
            Item { implicitHeight: 20 }
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                implicitWidth: 88; implicitHeight: 88; radius: 24
                gradient: Gradient {
                    GradientStop { position: 0; color: "#5e5ce6" }
                    GradientStop { position: 1; color: "#0a84ff" }
                }
                Glyph { anchors.centerIn: parent; name: "sparkles"; size: 44 }
            }
            Text { Layout.alignment: Qt.AlignHCenter; text: "JustDay"; color: win.t1; font.family: win.font; font.pixelSize: 30; font.weight: Font.Bold }
            Text { Layout.alignment: Qt.AlignHCenter; text: "Голосовой ИИ-ассистент для Linux · версия " + (win.d.about ? win.d.about.version : ""); color: win.t2; font.family: win.font; font.pixelSize: 13 }
            Group {
                Layout.topMargin: 10
                Row { title: "Claude Code"; subtitle: win.d.about ? win.d.about.claude : "" }
                Row { title: "Файл настроек"; subtitle: win.d.about ? win.d.about.config : ""; Btn { text: "Открыть"; onClicked: Quickshell.execDetached(["xdg-open", win.d.about.config]) } }
                Row { title: "Руководство"; subtitle: "Как всё устроено, модели, приватность, решение проблем"; Btn { glyph: "file-text"; text: "Открыть"; onClicked: JD.openManual() } }
                Row { title: "Лицензия"; subtitle: "GNU GPL v3 · © 2026 0nigiris · иконки Lucide (ISC)" }
                Row { title: "Исходный код"; subtitle: "github.com/0nigiris/JustDay"; Btn { glyph: "external-link"; text: "GitHub"; onClicked: Quickshell.execDetached(["xdg-open", "https://github.com/0nigiris/JustDay"]) } }
            }
            GroupTitle { text: "ОБНОВЛЕНИЯ" }
            Group {
                id: updGroup
                property var st: null
                property bool checking: false
                Row {
                    title: updGroup.checking ? "Проверяю…" : !updGroup.st ? "Проверить обновления" : !updGroup.st.ok ? "Не удалось проверить" : updGroup.st.behind ? "Доступно обновление" : "Установлена последняя версия"
                    subtitle: updGroup.st && updGroup.st.ok && updGroup.st.behind ? updGroup.st.changes.slice(0, 3).join(" · ") : updGroup.st && !updGroup.st.ok ? updGroup.st.error : "Обновления берутся из GitHub"
                    RowLayout {
                        spacing: 8
                        Btn { glyph: "refresh-cw"; text: "Проверить"; busy: updGroup.checking
                              onClicked: { updGroup.checking = true; win.run(["update", "--check"], v => { updGroup.checking = false; updGroup.st = v }) } }
                        Btn { visible: !!(updGroup.st && updGroup.st.behind); text: "Обновить"; primary: true; onClicked: JD.runUpdate() }
                    }
                }
                Row { title: "Проверять автоматически"; subtitle: "Раз в 6 часов; на острове появится кнопка"; Toggle { checked: win.get("updates.check") !== false; onToggled: v => win.set("updates.check", v) } }
            }
        }
    }
}
