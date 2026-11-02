// Первое знакомство, уже в островке: терминал при установке спрашивает только самое нужное, а имя,
// модель и место острова человек выбирает здесь, глазами. Показывается один раз (user.onboarded).
import QtQuick
import QtQuick.Layouts

Item {
    id: wl
    property int step: 0
    readonly property int last: 3
    property string provider: JD.settings.provider || "claude"
    property string place: JD.island.position === "bottom-center" ? "bottom" : "top"
    readonly property var models: [
        { id: "claude", label: "Claude", model: "sonnet", hint: JD.tr("по подписке Claude") },
        { id: "ollama_cloud", label: JD.tr("Бесплатная"), model: "kimi-k3:cloud", hint: JD.tr("облако, без оплаты") },
        { id: "ollama", label: JD.tr("Локальная"), model: "qwen3.5:9b", hint: JD.tr("всё остаётся на компьютере") },
        { id: "openrouter", label: "OpenRouter", model: "openrouter/free", hint: JD.tr("50 запросов в день") },
    ]

    function finish() {
        JD.setConfig("user.onboarded", true)
        JD.closeTools()
    }
    function next() {
        if (step === 0) {
            if (nameField.text.trim()) JD.setConfig("user.name", nameField.text.trim())
            if (botField.text.trim()) JD.setConfig("user.assistant_name", botField.text.trim())
        }
        if (step >= last) finish()
        else step++
    }

    // Каждый шаг выезжает справа и гаснет влево: видно, что идёшь вперёд, а не листаешь с нуля.
    component Slide: Item {
        required property int at
        anchors.fill: parent
        visible: opacity > 0.01
        opacity: wl.step === at ? 1 : 0
        x: wl.step === at ? 0 : (wl.step > at ? -40 : 40)
        Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.dur(260); easing.type: JD.easeOut } }
        Behavior on x { enabled: JD.animOn; NumberAnimation { duration: JD.dur(320); easing.type: JD.easeOut } }
    }
    component Card: Rectangle {
        property bool on: false
        property string title: ""
        property string hint: ""
        signal picked()
        implicitHeight: 62
        radius: 16
        color: on ? JD.text1 : (hv.hovered ? JD.fill2 : JD.fill1)
        Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast } }
        Column {
            anchors.centerIn: parent
            spacing: 2
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: title; font.family: JD.fontFamily; font.pixelSize: 15; font.weight: Font.DemiBold; color: on ? "black" : JD.text1 }
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: hint; font.family: JD.fontFamily; font.pixelSize: 11; color: on ? Qt.rgba(0, 0, 0, 0.55) : JD.text3 }
        }
        HoverHandler { id: hv; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: picked() }
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
            x: 16; y: 22; width: parent.width - 32
            font.family: JD.fontFamily; font.pixelSize: 16; color: JD.text1
            selectByMouse: true; clip: true
            onAccepted: wl.next()
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
                    Text { width: parent.width; wrapMode: Text.Wrap; text: JD.tr("Бесплатное работает сразу. Claude нужен вход по подписке."); font.family: JD.fontFamily; font.pixelSize: 14; color: JD.text2 }
                    Repeater {
                        model: wl.models
                        Card {
                            required property var modelData
                            width: parent.width
                            title: modelData.label; hint: modelData.hint
                            on: wl.provider === modelData.id
                            onPicked: { wl.provider = modelData.id; JD.run(["model", "use", modelData.id, modelData.model]) }
                        }
                    }
                }
            }
            Slide {
                at: 2
                Column {
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                    spacing: 12
                    Text { text: JD.tr("Где жить островку"); font.family: JD.fontFamily; font.pixelSize: 26; font.weight: Font.DemiBold; color: JD.text1 }
                    Text { width: parent.width; wrapMode: Text.Wrap; text: JD.tr("Он прячется у края экрана и выезжает, когда вы быстро подводите к нему курсор."); font.family: JD.fontFamily; font.pixelSize: 14; color: JD.text2 }
                    Card { width: parent.width; title: JD.tr("Сверху"); hint: JD.tr("как в телефоне"); on: wl.place === "top"
                           onPicked: { wl.place = "top"; JD.setConfig("island.position", "top-center") } }
                    Card { width: parent.width; title: JD.tr("Снизу"); hint: JD.tr("у дока"); on: wl.place === "bottom"
                           onPicked: { wl.place = "bottom"; JD.setConfig("island.position", "bottom-center") } }
                }
            }
            Slide {
                at: 3
                Column {
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                    spacing: 12
                    Text { text: JD.tr("Готово"); font.family: JD.fontFamily; font.pixelSize: 26; font.weight: Font.DemiBold; color: JD.text1 }
                    Text { width: parent.width; wrapMode: Text.Wrap; lineHeight: 1.25
                           text: JD.tr("Meta+K — написать ассистенту. Нажатие на островок — главное меню, в нём кнопка карандаша меняет виджеты. Остальное (голос, почта, док) добавляется из настроек, когда понадобится.")
                           font.family: JD.fontFamily; font.pixelSize: 14; color: JD.text2 }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Row {
                spacing: 6
                Repeater {
                    model: wl.last + 1
                    Rectangle {
                        required property int index
                        width: wl.step === index ? 22 : 7; height: 7; radius: 3.5
                        color: wl.step >= index ? JD.accentBlue : JD.fill2
                        Behavior on width { enabled: JD.animOn; NumberAnimation { duration: JD.dur(220); easing.type: JD.easeOut } }
                    }
                }
            }
            Item { Layout.fillWidth: true }
            Label2 { text: JD.tr("Пропустить"); visible: wl.step < wl.last
                     HoverHandler { cursorShape: Qt.PointingHandCursor }
                     TapHandler { onTapped: wl.finish() } }
            Rectangle {
                implicitWidth: 120; implicitHeight: 40; radius: 20
                color: JD.accentBlue
                Text { anchors.centerIn: parent; text: wl.step >= wl.last ? JD.tr("Начать") : JD.tr("Дальше"); color: "white"; font.family: JD.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: wl.next() }
            }
        }
    }
}
