import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io

// Подробный вид плитки по долгому нажатию: сети Wi‑Fi или устройства Bluetooth. Он просил «зажал
// Bluetooth — устройства, которые можно подключить или отключить; зажал Wi‑Fi — сети» (16 нояб.).
// Лист лежит поверх пульта, а не отдельным окном: это продолжение плитки, а не новое место.
Item {
    id: rs
    property string kind: ""            // "wifi" | "bt" | "" — закрыто
    readonly property bool open: kind !== ""
    property var items: []
    property bool loading: false
    property string busyId: ""
    property string note: ""

    visible: opacity > 0
    opacity: open ? 1 : 0
    Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durBase; easing.type: JD.easeOut } }

    function show(k) { kind = k; items = []; note = ""; refresh() }
    function close() { kind = "" }
    function refresh() { if (!lister.running) { loading = true; lister.command = ["python3", Quickshell.shellDir + "/radios.py", kind]; lister.running = true } }
    function act(it) {
        if (doer.running) return
        busyId = it.id; note = ""
        const cmd = kind === "wifi" ? "wifi-up" : (it.on ? "bt-down" : "bt-up")
        doer.command = ["python3", Quickshell.shellDir + "/radios.py", cmd, it.id]
        doer.running = true
    }

    Process {
        id: lister
        stdout: StdioCollector { onStreamFinished: { try { rs.items = JSON.parse(text).items || [] } catch (e) { rs.items = [] } rs.loading = false } }
    }
    Process {
        id: doer
        stdout: StdioCollector {
            onStreamFinished: {
                let r = {}
                try { r = JSON.parse(text) } catch (e) {}
                // Пароль от новой сети вводит человек в настройках KDE — мы его не видим и не храним.
                if (r.need_password) { JD.systemSettings("kcm_networkmanagement"); rs.note = JD.tr("Сеть закрыта — пароль вводится в настройках системы") }
                else if (!r.ok) rs.note = JD.tr("Не получилось")
                rs.busyId = ""
                rs.refresh()
                JD.askLinks()
            }
        }
    }
    Timer { interval: 5000; repeat: true; running: rs.open && !doer.running; onTriggered: rs.refresh() }

    // затемнение: нажатие мимо листа закрывает его
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.55)
        MouseArea { anchors.fill: parent; onClicked: rs.close() }
    }
    Shortcut { sequence: "Escape"; enabled: rs.open; onActivated: rs.close() }

    Rectangle {
        id: card
        width: Math.min(parent.width - 40, 440)
        height: Math.min(parent.height - 60, body.implicitHeight + 32)
        anchors.centerIn: parent
        radius: 24
        color: "#1c1c1e"
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.1)
        scale: rs.open ? 1 : 0.92
        Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: JD.durBase; easing.type: Easing.OutBack; easing.overshoot: 1.2 } }
        MouseArea { anchors.fill: parent }   // нажатие по листу не должно его закрывать

        ColumnLayout {
            id: body
            anchors { fill: parent; margins: 16 }
            spacing: 10
            RowLayout {
                Layout.fillWidth: true
                Icon { name: rs.kind === "wifi" ? (JD.wifiOn ? "wifi" : "wifi-off") : "bluetooth"; implicitSize: 18 }
                Label1 { text: rs.kind === "wifi" ? "Wi‑Fi" : "Bluetooth"; font.pixelSize: 15; font.weight: Font.DemiBold; Layout.fillWidth: true }
                Pressable {
                    implicitWidth: onLbl.implicitWidth + 24; implicitHeight: 28; radius: 14
                    readonly property bool isOn: rs.kind === "wifi" ? JD.wifiOn : JD.btOn
                    color: isOn ? JD.accentBlue : JD.fill1
                    onClicked: { if (rs.kind === "wifi") JD.setWifi(!isOn); else JD.setBt(!isOn) }
                    Label1 { id: onLbl; anchors.centerIn: parent; font.pixelSize: 12; text: parent.isOn ? JD.tr("Вкл") : JD.tr("Выкл") }
                }
            }
            Label2 {
                visible: text !== ""
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                font.pixelSize: 12
                text: rs.note || (rs.loading && !rs.items.length ? JD.tr("Ищу…")
                      : !rs.items.length ? (rs.kind === "wifi" ? JD.tr("Сетей не видно") : JD.tr("Известных устройств нет")) : "")
            }
            ListView {
                id: list
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(contentHeight, 360)
                clip: true
                spacing: 4
                model: rs.items
                boundsBehavior: Flickable.DragOverBounds
                delegate: Pressable {
                    required property var modelData
                    width: list.width
                    implicitHeight: 44
                    radius: 12
                    color: modelData.on ? Qt.rgba(1, 1, 1, 0.1) : "transparent"
                    onClicked: if (!(rs.kind === "wifi" && modelData.on)) rs.act(modelData)
                    RowLayout {
                        anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                        spacing: 10
                        Icon {
                            name: rs.kind === "wifi" ? "wifi" : "bluetooth"
                            implicitSize: 16
                            opacity: rs.kind === "wifi" ? 0.35 + modelData.signal / 160 : 1
                        }
                        ColumnLayout {
                            spacing: 0
                            Layout.fillWidth: true
                            Label1 { text: modelData.name; font.pixelSize: 13; elide: Text.ElideRight; Layout.fillWidth: true }
                            Label2 {
                                font.pixelSize: 11
                                Layout.fillWidth: true
                                text: rs.busyId === modelData.id ? JD.tr("подключаю…")
                                    : modelData.on ? JD.tr("подключено")
                                    : rs.kind === "wifi" ? (modelData.saved ? JD.tr("сохранена") : modelData.lock ? JD.tr("с паролем") : JD.tr("открытая"))
                                    : JD.tr("не подключено")
                            }
                        }
                        Icon { visible: rs.kind === "wifi" && modelData.lock; name: "lock"; implicitSize: 12; opacity: 0.6 }
                        Icon { visible: modelData.on; name: "check"; implicitSize: 14 }
                    }
                }
            }
            Pressable {
                Layout.fillWidth: true
                implicitHeight: 34
                radius: 12
                color: JD.fill1
                onClicked: { JD.systemSettings(rs.kind === "wifi" ? "kcm_networkmanagement" : "kcm_bluetooth"); rs.close() }
                Label1 { anchors.centerIn: parent; font.pixelSize: 12; text: JD.tr("Настройки системы…") }
            }
        }
    }
}
