// Первое знакомство, уже в островке: терминал при установке спрашивает только самое нужное, а имя,
// модель и место острова человек выбирает здесь, глазами. Показывается один раз (user.onboarded).
import QtQuick
import QtQuick.Layouts
import QtQuick.Shapes
import Quickshell.Io

Item {
    id: wl
    property int step: 0
    readonly property int last: 4
    // Шаг «Док и лоток» (3): по умолчанию — нет. На Windows шага нет: ни дока, ни лотка там нет (JD.dockOn, JD.trayOn).
    readonly property bool canDock: !JD.islandOnly && Qt.platform.os !== "windows"
    property bool wantDock: false
    property bool wantTray: false
    property string provider: JD.settings.provider || "claude"
    property string place: JD.island.position === "bottom-center" ? "bottom" : "top"
    readonly property var models: [
        { id: "claude", label: "Claude", model: "sonnet", hint: JD.tr("по подписке Claude") },
        { id: "ollama_cloud", label: JD.tr("Бесплатная"), model: "kimi-k3:cloud", hint: JD.tr("облако, без оплаты") },
        { id: "ollama", label: JD.tr("Локальная"), model: "qwen3.5:9b", hint: JD.tr("всё остаётся на компьютере") },
        { id: "openrouter", label: "OpenRouter", model: "openrouter/free", hint: JD.tr("50 запросов в день") },
    ]

    // На Windows нет Claude Code и Ollama: мозг — бесплатная модель по ключу (freellm.py). Список
    // поставщиков со ссылками даёт демон, чтобы адреса жили в одном месте.
    readonly property bool win: Qt.platform.os === "windows"
    Component.onCompleted: if (win) { JD.send({ cmd: "free_key" }); JD.send({ cmd: "autostart" }) }
    property string saving: ""
    // Linux: установщик ставит минимум без вопросов, речь и голос докачиваются отсюда в фоне (19 нояб.).
    // 27 нояб.: раньше докачка ждала кнопки на последнем шаге, и человек, нажавший «Дальше» четыре
    // раза, оставался без голоса. Теперь она начинается сразу, как открылось знакомство: вопросы
    // идут, пока качается; что качается — видно в углу карточки, остановить можно на последнем шаге.
    property var missingParts: []
    property bool partsStarted: false
    property bool partsDone: false
    property bool partsFailed: false
    property bool partsChecked: false
    Process {
        id: partsList
        running: !wl.win
        command: ["justday", "parts", "json"]
        stdout: StdioCollector {
            onStreamFinished: {
                let miss = []
                try { miss = JSON.parse(text).filter(p => !p.have && ["speech", "voice"].includes(p.name)) } catch (e) { return }
                if (wl.partsStarted) {
                    // Повторная проверка после докачки: всё ли встало.
                    wl.partsDone = miss.length === 0
                    wl.partsFailed = miss.length > 0
                    wl.partsStarted = false
                    return
                }
                wl.missingParts = miss
                if (!wl.partsChecked && miss.length) wl.startParts()
                wl.partsChecked = true
            }
        }
    }
    function startParts() {
        partsStarted = true
        partsFailed = false
        JD.installParts(missingParts.map(p => p.name))
    }
    function stopParts() {
        JD.send({ cmd: "parts_stop" })
        partsStarted = false
    }
    // Служба докачки закончилась — пересмотреть, что теперь есть.
    Process {
        id: partsUnit
        command: ["systemctl", "--user", "is-active", "justday-parts.service"]
        stdout: StdioCollector {
            onStreamFinished: if (wl.partsStarted && !["active", "activating"].includes(text.trim())) partsList.running = true
        }
    }
    Timer {
        running: wl.partsStarted
        interval: 4000
        repeat: true
        onTriggered: partsUnit.running = true
    }
    Connections {
        target: JD
        function onFreeResultChanged() {
            wl.saving = ""
            if (JD.freeResult.ok) JD.send({ cmd: "free_key" })
        }
    }

    function finish() {
        if (canDock) {
            JD.setConfig("dock.enabled", wantDock)
            JD.setConfig("tray.enabled", wantTray)
        }
        JD.welcomeDock = false
        JD.welcomeTray = false
        JD.faceLook = null
        JD.onboardDone = true  // настройки с демона придут позже, а пускать дальше надо сразу
        JD.setConfig("user.onboarded", true)
        JD.closeTools()
    }
    function next() {
        nextPress.restart()
        JD.facePing("next")
        if (step === 0) {
            if (nameField.text.trim()) JD.setConfig("user.name", nameField.text.trim())
            if (botField.text.trim()) JD.setConfig("user.assistant_name", botField.text.trim())
        }
        if (step >= last) finish()
        else step += (step === 2 && !canDock) ? 2 : 1
        if (step !== 3) { JD.welcomeDock = false; JD.welcomeTray = false }
    }

    // Каждый шаг выезжает справа и гаснет влево: видно, что идёшь вперёд, а не листаешь с нуля.
    component Slide: Item {
        id: sl
        required property int at
        anchors.fill: parent
        visible: opacity > 0.01
        readonly property bool cur: wl.step === at
        opacity: cur ? 1 : 0
        x: cur ? 0 : (wl.step > at ? -40 : 40)
        // Уходящий шаг гаснет быстро, входящий проявляется с задержкой: при равных длительностях оба
        // полсекунды висели полупрозрачными друг на друге, и на видео это выглядело кашей (23 нояб.).
        Behavior on opacity { enabled: JD.animOn
            SequentialAnimation {
                PauseAnimation { duration: cur ? JD.durFast : 0 }
                NumberAnimation { duration: cur ? JD.dur(240) : JD.durFast; easing.type: JD.easeOut }
            } }
        Behavior on x { enabled: JD.animOn; NumberAnimation { duration: JD.dur(360); easing.type: JD.easeOut } }
        // Строки шага всплывают по очереди снизу, а не все разом: целый блок, въехавший одной
        // плитой, на видео читался как смена картинки, а не как живой интерфейс (24 нояб.).
        property real enter: 1
        onCurChanged: if (cur && JD.animOn) { enter = 0; enterWait.duration = 0; enterAnim.restart() }
        // Первый шаг ждёт, пока карточка дорастёт из шарика: иначе строки всплывали бы за краем.
        Component.onCompleted: if (cur && JD.animOn) { enter = 0; enterWait.duration = 420; enterAnim.restart() }
        SequentialAnimation {
            id: enterAnim
            PauseAnimation { id: enterWait; duration: 0 }
            NumberAnimation { target: sl; property: "enter"; to: 1; duration: JD.dur(760) }
        }
        onEnterChanged: {
            const lines = children.length ? children[0].children : []
            for (let i = 0; i < lines.length; i++) {
                const ch = lines[i]
                if (!ch.transform.length) ch.transform = [Qt.createQmlObject("import QtQuick; Translate {}", ch)]
                const t = Math.max(0, Math.min(1, (enter - i * 0.09) / 0.55))
                const e = 1 - Math.pow(1 - t, 3)
                ch.opacity = e
                ch.transform[0].y = 18 * (1 - e)
            }
        }
    }
    // Подсветка выбора одна на столбец и перетекает к выбранной карточке: передний край приходит
    // быстро, задний догоняет с пружинкой, и на ходу она вытягивается каплей. Заливка самих
    // карточек под ней прозрачная, поэтому видно, как она проходит сквозь соседние.
    component Puck: Rectangle {
        property Item target: null
        property Item column: null
        readonly property real goal: target && column ? column.y + target.y : 0
        property real head: goal
        property real tail: goal
        Behavior on head { enabled: JD.animOn; NumberAnimation { duration: JD.dur(240); easing.type: Easing.OutCubic } }
        Behavior on tail { enabled: JD.animOn; NumberAnimation { duration: JD.dur(560); easing.type: Easing.OutBack; easing.overshoot: 1.4 } }
        z: -1
        visible: !!target
        opacity: target ? target.opacity : 0   // всплывает вместе со своей карточкой, а не раньше неё
        x: column ? column.x : 0
        width: column ? column.width : 0
        y: Math.min(head, tail)
        height: (target ? target.height : 0) + Math.abs(head - tail)
        radius: 16
        color: JD.text1
    }
    component Card: Rectangle {
        id: cd
        property bool on: false
        property Puck puck: null
        property string title: ""
        property string hint: ""
        signal picked()
        implicitHeight: 62
        radius: 16
        color: on ? (puck ? "transparent" : JD.text1) : (hv.hovered ? JD.fill2 : JD.fill1)
        Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast } }
        onOnChanged: if (on && puck) puck.target = cd
        Component.onCompleted: if (on && puck) puck.target = cd
        Column {
            anchors.centerIn: parent
            spacing: 2
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: cd.title; font.family: JD.fontFamily; font.pixelSize: 15; font.weight: Font.DemiBold; color: cd.on ? "black" : JD.text1
                   Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.dur(260) } } }
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: cd.hint; font.family: JD.fontFamily; font.pixelSize: 11; color: cd.on ? Qt.rgba(0, 0, 0, 0.55) : JD.text3
                   Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.dur(260) } } }
        }
        HoverHandler { id: hv; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: picked() }
        // Глаза смотрят на выбранное и довольно щурятся.
        onPicked: { JD.faceLook = mapToItem(null, width / 2, height / 2); JD.facePing("happy") }
    }
    component Field: Rectangle {
        property alias text: inp.text
        property string label: ""
        implicitHeight: 52
        radius: 14
        color: JD.fill1
        border.width: 1
        border.color: inp.activeFocus ? JD.accentBlue : "transparent"
        Text { x: 16; y: 7; text: label; font.family: JD.fontFamily; font.pixelSize: 10; color: JD.text3 }
        TextInput {
            id: inp
            // Глаза на карточке смотрят на поле, пока его заполняют.
            onActiveFocusChanged: JD.faceLook = activeFocus ? mapToItem(null, width / 3, height / 2) : null
            x: 16; y: 22; width: parent.width - 32
            font.family: JD.fontFamily; font.pixelSize: 16; color: JD.text1
            selectByMouse: true; clip: true
            onAccepted: wl.next()
            // На каждую букву глаза чуть кивают: видно, что его слушают.
            onTextChanged: if (activeFocus) JD.facePing("nod")
        }
    }

    // Что качается в фоне — тихо в углу, вровень с глазами маскота. Вопросы от этого не ждут.
    Row {
        id: partsChip
        z: 2
        anchors { right: parent.right; rightMargin: 10; top: parent.top; topMargin: 8 }
        spacing: 7
        readonly property bool shown: wl.partsStarted || wl.partsDone
        opacity: shown ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durSlow; easing.type: Easing.OutCubic } }
        // Готово — подержать галочку и убрать, чтобы угол не висел навсегда.
        Timer { running: wl.partsDone; interval: 4000; onTriggered: wl.partsDone = false }
        Item {
            width: 14; height: 14
            anchors.verticalCenter: parent.verticalCenter
            Rectangle { anchors.fill: parent; radius: 7; color: "transparent"; border.width: 2; border.color: JD.fill2; visible: !wl.partsDone }
            Shape {
                id: spin
                anchors.fill: parent
                visible: !wl.partsDone
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: JD.accentBlue; strokeWidth: 2; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                    PathAngleArc { centerX: 7; centerY: 7; radiusX: 6; radiusY: 6; startAngle: 0; sweepAngle: 100 }
                }
                RotationAnimation on rotation { running: spin.visible && partsChip.visible && JD.animOn; from: 0; to: 360; duration: 1100; loops: Animation.Infinite }
            }
            Icon { anchors.centerIn: parent; visible: wl.partsDone; name: "check"; implicitSize: 14; tint: JD.accentBlue }
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: wl.partsDone ? JD.tr("Голос и речь готовы") : JD.tr("Голос и речь качаются в фоне")
            font.family: JD.fontFamily; font.pixelSize: 12; color: JD.text2
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 6
        spacing: 14

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            Slide {
                at: 0
                Column {
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                    spacing: 14
                    Text { text: JD.tr("Привет! Давайте познакомимся"); font.family: JD.fontFamily; font.pixelSize: 26; font.weight: Font.DemiBold; color: JD.text1 }
                    Text { width: parent.width; wrapMode: Text.Wrap; text: JD.tr("Это займёт минуту. Всё можно поменять потом в настройках."); font.family: JD.fontFamily; font.pixelSize: 14; color: JD.text2 }
                    Field { id: nameField; width: parent.width; label: JD.tr("Как вас зовут") ; text: JD.settings.user_name || "" }
                    Field { id: botField; width: parent.width; label: JD.tr("Как звать ассистента"); text: JD.assistantName }
                }
            }
            Slide {
                at: 1
                Column {
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                    spacing: 12
                    Text { text: JD.tr("Чем он будет думать"); font.family: JD.fontFamily; font.pixelSize: 26; font.weight: Font.DemiBold; color: JD.text1 }
                    Text { width: parent.width; wrapMode: Text.Wrap; text: wl.win ? JD.tr("Возьмите хотя бы один бесплатный ключ: вход аккаунтом, минута времени. Два — надёжнее: если один упрётся в лимит, ответит другой.") : JD.tr("Бесплатное работает сразу. Claude нужен вход по подписке."); font.family: JD.fontFamily; font.pixelSize: 14; color: JD.text2 }
                    Repeater {
                        // На Linux карточка OpenRouter была, а ключ к ней вписать было негде: выбор молча
                        // оставлял ассистента без мозга. Ключ ложится туда же, откуда его читает мозг.
                        model: JD.freeProviders.filter(p => wl.win || p.id === wl.provider)
                        Rectangle {
                            id: fp
                            required property var modelData
                            width: parent.width; height: 96; radius: 16
                            color: JD.fill1
                            border.width: 1
                            border.color: modelData.has ? JD.accentBlue : "transparent"
                            Text { x: 16; y: 10; text: modelData.name + (fp.modelData.has ? "  ✓" : ""); font.family: JD.fontFamily; font.pixelSize: 15; font.weight: Font.DemiBold; color: JD.text1 }
                            Text { x: 16; y: 31; width: parent.width - 150; elide: Text.ElideRight; text: JD.tr(modelData.note); font.family: JD.fontFamily; font.pixelSize: 11; color: JD.text3 }
                            Text {
                                anchors { right: parent.right; rightMargin: 16; top: parent.top; topMargin: 12 }
                                text: JD.tr("Взять ключ ↗"); font.family: JD.fontFamily; font.pixelSize: 12; color: JD.accentBlue
                                HoverHandler { cursorShape: Qt.PointingHandCursor }
                                TapHandler { onTapped: Qt.openUrlExternally(fp.modelData.keys) }
                            }
                            Rectangle {
                                x: 12; y: 52; width: parent.width - 24; height: 34; radius: 10
                                color: JD.fill2
                                TextInput {
                                    id: keyIn
                                    anchors { fill: parent; leftMargin: 12; rightMargin: 80 }
                                    verticalAlignment: TextInput.AlignVCenter
                                    echoMode: TextInput.Password
                                    font.family: JD.fontFamily; font.pixelSize: 13; color: JD.text1; clip: true
                                    Text { anchors.verticalCenter: parent.verticalCenter; visible: !keyIn.text; text: fp.modelData.has ? JD.tr("ключ сохранён") : JD.tr("вставьте ключ"); color: JD.text3; font: keyIn.font }
                                    onAccepted: saveBtn.save()
                                }
                                Text {
                                    id: saveBtn
                                    anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                                    visible: !!keyIn.text
                                    text: wl.saving === fp.modelData.id ? JD.tr("проверяю…") : JD.tr("Сохранить")
                                    font.family: JD.fontFamily; font.pixelSize: 12; font.weight: Font.DemiBold; color: JD.accentBlue
                                    function save() {
                                        wl.saving = fp.modelData.id
                                        JD.send({ cmd: "free_key", id: fp.modelData.id, key: keyIn.text })
                                        keyIn.text = ""
                                    }
                                    TapHandler { onTapped: saveBtn.save() }
                                }
                            }
                        }
                    }
                    Text {
                        width: parent.width; wrapMode: Text.Wrap; font.family: JD.fontFamily; font.pixelSize: 12
                        visible: JD.freeResult.error !== undefined && JD.freeResult.error !== ""
                        color: "#ff6b6b"
                        text: JD.tr("Ключ сохранён, но модель не ответила: ") + (JD.freeResult.error || "")
                    }
                    Repeater {
                        model: wl.win ? [] : wl.models
                        Card {
                            required property var modelData
                            puck: modelPuck
                            width: parent.width
                            title: modelData.label; hint: modelData.hint
                            on: wl.provider === modelData.id
                            onPicked: { wl.provider = modelData.id; JD.run(["model", "use", modelData.id, modelData.model]) }
                        }
                    }
                }
                Puck { id: modelPuck; column: parent.children[0] }
            }
            Slide {
                at: 2
                Column {
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                    spacing: 12
                    Text { text: JD.tr("Где жить островку"); font.family: JD.fontFamily; font.pixelSize: 26; font.weight: Font.DemiBold; color: JD.text1 }
                    Text { width: parent.width; wrapMode: Text.Wrap; text: JD.tr("Он прячется у края экрана и выезжает, когда вы быстро подводите к нему курсор."); font.family: JD.fontFamily; font.pixelSize: 14; color: JD.text2 }
                    Card { puck: placePuck; width: parent.width; title: JD.tr("Сверху"); hint: JD.tr("как в телефоне"); on: wl.place === "top"
                           onPicked: { wl.place = "top"; JD.setConfig("island.position", "top-center") } }
                    Card { puck: placePuck; width: parent.width; title: JD.tr("Снизу"); hint: JD.tr("у нижнего края"); on: wl.place === "bottom"
                           onPicked: { wl.place = "bottom"; JD.setConfig("island.position", "bottom-center") } }
                }
                Puck { id: placePuck; column: parent.children[0] }
            }
            Slide {
                at: 3
                Column {
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                    spacing: 12
                    Text { text: wl.win ? JD.tr("Док") : JD.tr("Док и лоток"); font.family: JD.fontFamily; font.pixelSize: 26; font.weight: Font.DemiBold; color: JD.text1 }
                    Text { width: parent.width; wrapMode: Text.Wrap; text: JD.tr("Можно жить с одним островком. Посмотрите, как они выглядят, и включите, если нравятся."); font.family: JD.fontFamily; font.pixelSize: 14; color: JD.text2 }
                    Repeater {
                        model: [
                            { id: "dock", title: JD.tr("Док"), hint: JD.tr("внизу: закреплённые и открытые программы") },
                            { id: "tray", title: JD.tr("Лоток"), hint: JD.tr("сбоку: значки фоновых программ") },
                        ].slice(0, wl.win ? 1 : 2)
                        Item {
                            id: dt
                            required property var modelData
                            readonly property bool want: modelData.id === "dock" ? wl.wantDock : wl.wantTray
                            readonly property bool shown: modelData.id === "dock" ? JD.welcomeDock : JD.welcomeTray
                            width: parent.width; height: 62
                            Card {
                                anchors { left: parent.left; right: peek.left; rightMargin: 10; top: parent.top; bottom: parent.bottom }
                                title: dt.modelData.title + (dt.want ? "  ✓" : "")
                                hint: dt.want ? JD.tr("будет включён") : dt.modelData.hint
                                on: dt.want
                                onPicked: { if (dt.modelData.id === "dock") wl.wantDock = !wl.wantDock; else wl.wantTray = !wl.wantTray }
                            }
                            Rectangle {
                                id: peek
                                anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
                                width: 120; radius: 16
                                color: peekHv.hovered ? JD.fill2 : JD.fill1
                                Text { anchors.centerIn: parent; text: dt.shown ? JD.tr("Спрятать") : JD.tr("Посмотреть"); font.family: JD.fontFamily; font.pixelSize: 13; color: JD.accentBlue }
                                HoverHandler { id: peekHv; cursorShape: Qt.PointingHandCursor }
                                TapHandler { onTapped: { if (dt.modelData.id === "dock") JD.welcomeDock = !JD.welcomeDock; else JD.welcomeTray = !JD.welcomeTray } }
                            }
                        }
                    }
                }
            }
            Slide {
                at: 4
                Column {
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                    spacing: 12
                    Text { text: JD.tr("Готово"); font.family: JD.fontFamily; font.pixelSize: 26; font.weight: Font.DemiBold; color: JD.text1 }
                    Text { width: parent.width; wrapMode: Text.Wrap; lineHeight: 1.25
                           text: wl.win ? JD.tr("Нажатие на островок — главное меню: в строке сверху можно написать Джарвису, а кнопка микрофона слушает голос. Карандаш меняет виджеты.")
                                        : JD.tr("Meta+K — написать ассистенту. Нажатие на островок — главное меню, в нём кнопка карандаша меняет виджеты. Почта и остальное добавляются из настроек, когда понадобятся.")
                           font.family: JD.fontFamily; font.pixelSize: 14; color: JD.text2 }
                    // На Windows установка не задаёт вопросов (П31): автозапуск выбирается здесь.
                    Card { visible: wl.win; width: parent.width
                           title: JD.tr("Запускать вместе с Windows"); hint: JD.autostartOn ? JD.tr("включено") : JD.tr("выключено")
                           on: JD.autostartOn
                           onPicked: JD.send({ cmd: "autostart", state: JD.autostartOn ? "off" : "on" }) }
                    Card { visible: !wl.win && wl.missingParts.length > 0; width: parent.width
                           title: JD.tr("Голос и распознавание речи")
                           hint: wl.partsDone ? JD.tr("установлено")
                               : wl.partsStarted ? JD.tr("качается в фоне · нажмите, чтобы остановить")
                               : wl.partsFailed ? JD.tr("не скачалось — нажмите, чтобы повторить")
                               : JD.tr("скачать в фоне") + " · " + wl.missingParts.map(p => p.size).join(" + ")
                           on: wl.partsStarted || wl.partsDone
                           onPicked: if (wl.partsStarted) wl.stopParts(); else if (!wl.partsDone) wl.startParts() }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            // Текущий шаг — капля поверх точек: голова уходит к следующей точке, хвост догоняет.
            Item {
                implicitWidth: (wl.last + 1) * 13 - 6 + 12; implicitHeight: 7
                Row {
                    x: 6; spacing: 6
                    Repeater {
                        model: wl.last + 1
                        Rectangle {
                            required property int index
                            width: 7; height: 7; radius: 3.5
                            color: wl.step > index ? Qt.alpha(JD.accentBlue, 0.5) : JD.fill2
                            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.dur(400) } }
                        }
                    }
                }
                Rectangle {
                    id: drop
                    property real head: 6 + wl.step * 13 + 3.5
                    property real tail: head
                    Behavior on head { enabled: JD.animOn; NumberAnimation { duration: JD.dur(220); easing.type: Easing.OutCubic } }
                    Behavior on tail { enabled: JD.animOn; NumberAnimation { duration: JD.dur(520); easing.type: Easing.OutBack; easing.overshoot: 1.6 } }
                    x: Math.min(head, tail) - 9; width: Math.abs(head - tail) + 18
                    height: 7; radius: 3.5
                    color: JD.accentBlue
                }
            }
            Item { Layout.fillWidth: true }
            Label2 { text: JD.tr("Пропустить"); visible: wl.step < wl.last
                     HoverHandler { cursorShape: Qt.PointingHandCursor }
                     TapHandler { onTapped: wl.finish() } }
            Rectangle {
                id: nextBtn
                implicitWidth: 120; implicitHeight: 40; radius: 20
                color: JD.accentBlue
                SequentialAnimation {
                    id: nextPress
                    NumberAnimation { target: nextBtn; property: "scale"; to: 0.92; duration: JD.dur(90); easing.type: Easing.OutCubic }
                    NumberAnimation { target: nextBtn; property: "scale"; to: 1; duration: JD.dur(420); easing.type: Easing.OutBack; easing.overshoot: 2.2 }
                }
                Text { anchors.centerIn: parent; text: wl.step >= wl.last ? JD.tr("Начать") : JD.tr("Дальше"); color: "white"; font.family: JD.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: wl.next() }
            }
        }
    }
}
