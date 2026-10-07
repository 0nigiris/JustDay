// Живые сессии Claude Code: что каждая делает прямо сейчас.
//
// Раньше островок говорил «Клод работает ×3». Это не сведения, а обещание, что что-то происходит:
// три работают, одна, может быть, застряла, другая делает не то — не видно ничего.
//
// Здесь видно каждую: где она работает, занята ли, сколько уже идёт и что именно сейчас делает —
// читает, правит, запускает. Шаги показаны глаголами, а не именами инструментов: «Read» и «Edit» —
// слова для того, кто писал агента, а человеку нужно «читает» и «правит».
//
// Список сам не обновляется в фоне: он живёт, только пока на него смотрят. Опрос ради страницы,
// которую закрыли, — это работа впустую, и на неё уходит заметно больше, чем кажется: каждая
// сессия это чтение хвоста её стенограммы.
import QtQuick
import QtQuick.Layouts

Item {
    id: sv

    readonly property var all: JD.sessions || []
    readonly property var busy: all.filter(s => s && s.busy)

    // Пока страница открыта, демон присылает список сам — когда стенограммы изменились, а не по таймеру. Страница
    // только подтверждает раз в полминуты, что ещё смотрит, и один раз говорит, что закрылась.
    Timer {
        interval: 30000
        repeat: true
        running: sv.visible
        triggeredOnStart: true
        onTriggered: JD.sessionsWatch(true)
    }
    onVisibleChanged: if (!visible) JD.sessionsWatch(false)
    Component.onDestruction: JD.sessionsWatch(false)

    ColumnLayout {
        anchors.fill: parent
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Label1 {
                Layout.fillWidth: true
                text: sv.all.length === 0 ? JD.tr("Сессий нет")
                    : sv.all.some(s => s && s.waiting) ? JD.tr("Ждёт тебя: ") + sv.all.filter(s => s && s.waiting).length
                    : sv.busy.length ? JD.tr("Работают: ") + sv.busy.length + JD.tr(" из ") + sv.all.length
                    : JD.tr("Все ждут: ") + sv.all.length
            }
            PillButton {
                label: JD.tr("Открыть терминал")
                onClicked: JD.send({ cmd: "claude_terminal" })
            }
        }

        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: rows.implicitHeight
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds

            ColumnLayout {
                id: rows
                width: parent.width
                spacing: 8

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: sv.all.length ? 0 : 130
                    visible: sv.all.length === 0
                    Column {
                        anchors.centerIn: parent
                        spacing: 8
                        Icon {
                            anchors.horizontalCenter: parent.horizontalCenter
                            name: "code"; implicitSize: 26; tint: JD.text3
                        }
                        Label2 {
                            anchors.horizontalCenter: parent.horizontalCenter
                            color: JD.text3
                            text: JD.tr("Сейчас ничего не запущено")
                        }
                    }
                }

                Repeater {
                    model: sv.all
                    delegate: Rectangle {
                        id: card
                        required property var modelData
                        readonly property var step: modelData.now || ({})
                        Layout.fillWidth: true
                        implicitHeight: body.implicitHeight + 22
                        radius: 14
                        color: Qt.rgba(1, 1, 1, 0.05)
                        border.width: 1
                        border.color: modelData.waiting ? Qt.rgba(JD.accentOrange.r, JD.accentOrange.g, JD.accentOrange.b, 0.6)
                                    : modelData.busy ? Qt.rgba(JD.accentBlue.r, JD.accentBlue.g, JD.accentBlue.b, 0.35)
                                                     : Qt.rgba(1, 1, 1, 0.07)

                        ColumnLayout {
                            id: body
                            anchors { left: parent.left; right: parent.right; top: parent.top
                                      leftMargin: 14; rightMargin: 14; topMargin: 11 }
                            spacing: 6

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 9

                                // Занята — голубая точка, которая дышит. Ждёт — серая и неподвижная.
                                // Это единственное, что видно боковым зрением, и значит оно должно
                                // значить самое важное: идёт работа или нет.
                                Rectangle {
                                    implicitWidth: 8
                                    implicitHeight: 8
                                    radius: 4
                                    color: card.modelData.busy ? JD.accentBlue : JD.text3
                                    SequentialAnimation on opacity {
                                        running: card.modelData.busy && sv.visible && JD.animOn
                                        loops: Animation.Infinite
                                        NumberAnimation { to: 0.35; duration: 700; easing.type: Easing.InOutSine }
                                        NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
                                    }
                                }
                                // Цвет — семейство модели: на каком уровне лимита сидит сессия, видно без слов
                                Rectangle {
                                    visible: !!card.modelData.model
                                    implicitWidth: 6; implicitHeight: 6; radius: 3
                                    color: ({ opus: "#c084fc", sonnet: "#60a5fa", haiku: "#4ade80", fable: "#fbbf24" })[card.modelData.model] || JD.text3
                                }
                                Label1 {
                                    text: card.modelData.name || card.modelData.short
                                    font.pixelSize: 13
                                }
                                Label2 {
                                    Layout.fillWidth: true
                                    font.pixelSize: 11
                                    color: JD.text3
                                    text: card.modelData.where
                                }
                                Label2 {
                                    font.pixelSize: 11
                                    color: JD.text3
                                    font.features: ({ "tnum": 1 })
                                    text: card.modelData.minutes >= 60
                                          ? Math.round(card.modelData.minutes / 60) + JD.tr(" ч")
                                          : Math.round(card.modelData.minutes) + JD.tr(" мин")
                                }
                            }

                            // Что делает сейчас — крупнее всего остального: за этим сюда и приходят.
                            RowLayout {
                                Layout.fillWidth: true
                                visible: !!card.step.verb || card.modelData.waiting
                                spacing: 7
                                Label2 {
                                    color: card.modelData.waiting ? JD.accentOrange : card.modelData.busy ? JD.accentBlue : JD.text2
                                    font.pixelSize: 12
                                    font.weight: Font.DemiBold
                                    text: card.modelData.waiting ? JD.tr("ждёт ответа") : (card.step.verb || "")
                                }
                                Label2 {
                                    Layout.fillWidth: true
                                    font.pixelSize: 12
                                    color: JD.text1
                                    elide: Text.ElideRight
                                    text: card.step.what || ""
                                }
                            }

                            // Предыдущие шаги — мельче и тусклее: они объясняют, как сюда пришли,
                            // но соперничать с тем, что происходит сейчас, не должны.
                            Repeater {
                                model: (card.modelData.steps || []).slice(0, -1).slice(-3).reverse()
                                delegate: RowLayout {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    spacing: 6
                                    Label2 {
                                        font.pixelSize: 10
                                        color: JD.text3
                                        text: modelData.verb
                                    }
                                    Label2 {
                                        Layout.fillWidth: true
                                        font.pixelSize: 10
                                        color: JD.text3
                                        elide: Text.ElideRight
                                        text: modelData.what
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
