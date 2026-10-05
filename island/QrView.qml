// QR-код ссылкой, текстом или входом в Wi-Fi — чтобы снять телефоном с экрана.
//
// Рисует не демон, а мы: демон присылает только матрицу из «0» и «1» (qr.py). Пароль сети вводится
// здесь и уходит демону одним запросом; код держится в JD.qrRows, пока открыта страница, и стирается
// при закрытии панели — код с паролем не должен переживать окно, в котором его показывали.
import QtQuick
import QtQuick.Layouts

Item {
    id: qv

    property bool wifi: false
    readonly property var rows: JD.qrRows || []

    function ask() {
        if (qv.wifi) JD.qrAsk({ wifi: ssid.text.trim() ? ssid.text : "", password: pass.text })
        else JD.qrAsk({ text: link.text })
    }
    onWifiChanged: { ask(); Qt.callLater(() => (wifi ? ssid : link).forceActiveFocus()) }
    // Страница создаётся вместе с панелью и просто прячется: фокус берём, когда её показали, а поля — в
    // первую очередь пароль — чистим, когда спрятали.
    onVisibleChanged: {
        if (visible) Qt.callLater(() => (wifi ? ssid : link).forceActiveFocus())
        else { link.text = ""; ssid.text = ""; pass.text = "" }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 24

        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            spacing: 12

            RowLayout {
                spacing: 8
                Repeater {
                    model: [{ w: false, name: JD.tr("Ссылка или текст") }, { w: true, name: "Wi-Fi" }]
                    delegate: PillButton {
                        required property var modelData
                        label: modelData.name
                        tint: qv.wifi === modelData.w ? JD.accentBlue : JD.fill1
                        onClicked: qv.wifi = modelData.w
                    }
                }
            }

            Label2 { visible: !qv.wifi; text: JD.tr("Что закодировать"); color: JD.text3 }
            Rectangle {
                visible: !qv.wifi
                Layout.fillWidth: true
                implicitHeight: 40
                radius: 12
                color: JD.fill1
                border.width: link.activeFocus ? 1 : 0
                border.color: JD.accentBlue
                TextInput {
                    id: link
                    anchors { fill: parent; leftMargin: 14; rightMargin: 14 }
                    verticalAlignment: TextInput.AlignVCenter
                    font.family: JD.fontFamily
                    font.pixelSize: 14
                    color: JD.text1
                    selectByMouse: true
                    selectionColor: JD.accentBlue
                    clip: true
                    onTextChanged: qv.ask()
                    Keys.onEscapePressed: JD.closeTools()
                    Text { anchors.fill: parent; verticalAlignment: Text.AlignVCenter; visible: !link.text
                           font: link.font; color: JD.text3; text: "https://… или любой текст" }
                }
            }

            Label2 { visible: qv.wifi; text: JD.tr("Имя сети"); color: JD.text3 }
            Rectangle {
                visible: qv.wifi
                Layout.fillWidth: true
                implicitHeight: 40
                radius: 12
                color: JD.fill1
                border.width: ssid.activeFocus ? 1 : 0
                border.color: JD.accentBlue
                TextInput {
                    id: ssid
                    anchors { fill: parent; leftMargin: 14; rightMargin: 14 }
                    verticalAlignment: TextInput.AlignVCenter
                    font.family: JD.fontFamily
                    font.pixelSize: 14
                    color: JD.text1
                    selectByMouse: true
                    selectionColor: JD.accentBlue
                    clip: true
                    onTextChanged: qv.ask()
                    Keys.onEscapePressed: JD.closeTools()
                    KeyNavigation.tab: pass
                }
            }
            Label2 { visible: qv.wifi; text: JD.tr("Пароль (пусто — открытая сеть)"); color: JD.text3 }
            Rectangle {
                visible: qv.wifi
                Layout.fillWidth: true
                implicitHeight: 40
                radius: 12
                color: JD.fill1
                border.width: pass.activeFocus ? 1 : 0
                border.color: JD.accentBlue
                TextInput {
                    id: pass
                    anchors { fill: parent; leftMargin: 14; rightMargin: 14 }
                    verticalAlignment: TextInput.AlignVCenter
                    font.family: JD.fontFamily
                    font.pixelSize: 14
                    color: JD.text1
                    echoMode: TextInput.Password
                    selectByMouse: true
                    selectionColor: JD.accentBlue
                    clip: true
                    onTextChanged: qv.ask()
                    Keys.onEscapePressed: JD.closeTools()
                }
            }

            Label2 {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                color: JD.text3
                text: JD.tr("Наведите камеру телефона на код. Пароль не сохраняется: код стирается, когда закроете панель.")
            }
        }

        // Белая плитка с рамкой в четыре модуля: на тёмной подложке камера без неё не находит углы.
        Item {
            Layout.preferredWidth: 340
            Layout.preferredHeight: 340
            Layout.alignment: Qt.AlignTop
            Canvas {
                id: cv
                anchors.fill: parent
                visible: qv.rows.length > 0
                onPaint: {
                    const ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    const n = qv.rows.length
                    if (!n) return
                    const cell = Math.floor(Math.min(width, height) / (n + 8))
                    const side = cell * (n + 8)
                    ctx.fillStyle = "#ffffff"
                    ctx.fillRect(0, 0, side, side)
                    ctx.fillStyle = "#000000"
                    for (let y = 0; y < n; y++)
                        for (let x = 0; x < n; x++)
                            if (qv.rows[y][x] === "1") ctx.fillRect((x + 4) * cell, (y + 4) * cell, cell, cell)
                }
                Connections { target: qv; function onRowsChanged() { cv.requestPaint() } }
            }
            Label2 { visible: qv.rows.length === 0; anchors.centerIn: parent; color: JD.text3; text: JD.tr("Введите текст — появится код") }
        }
    }
}
