// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Widgets

View {
    id: cv
    readonly property var c: JD.card || ({})
    property int openLetter: 0           // номер раскрытого письма в списке почты, 0 — все свёрнуты
    onCChanged: openLetter = 0
    // Цвет кружка от всего адреса, а не от первой буквы: у «Google», «Gmail» и «GitHub» он был
    // один и тот же, и список выглядел набором повторов.
    function hue(s) {
        let h = 7
        for (let i = 0; i < (s || "").length; i++) h = (h * 31 + s.charCodeAt(i)) % 360
        return h / 360
    }
    readonly property string mediaIcon: ({ image: "image-x-generic", video: "video-x-generic", music: "audio-x-generic",
                                           speech: "audio-x-generic", "3d": "application-x-blender" })[c.kind] || "folder-pictures"
    implicitWidth: 600
    implicitHeight: cardCol.implicitHeight + 36
    ColumnLayout {
        id: cardCol
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 18 }
        spacing: 12

        CardHeader {
            Layout.fillWidth: true
            icon: cv.c.type === "calendar" ? "view-calendar" : cv.c.type === "message_draft" ? "mail-send"
                : cv.c.type === "question" ? "dialog-question" : cv.c.type === "media" ? cv.mediaIcon : "mail-message"
            tint: cv.c.type === "mail_sent" ? JD.accentGreen : cv.c.type === "calendar" ? JD.accentOrange
                : cv.c.type === "media" ? JD.accentPurple
                : ["message_draft", "question"].includes(cv.c.type) ? JD.accentBlue : JD.accentRed
            title: ({ message_draft: JD.tr("Сообщение") + (cv.c.to ? " · " + cv.c.to : ""), question: cv.c.header || JD.tr("Вопрос"),
                      mail_draft: JD.tr("Новое письмо"), mail_sent: JD.tr("Письмо отправлено"), mail_read: cv.c.subject || JD.tr("Письмо"),
                      mail_list: JD.tr("Почта"), calendar: JD.tr("Календарь · ") + (cv.c.when || ""),
                      media: cv.c.failed ? JD.tr("Не получилось") : JD.tr("Готово") + " · " + (cv.c.label || "") })[cv.c.type] || JD.tr("Почта")
            subtitle: ({ message_draft: (cv.c.via ? cv.c.via + " · " : "") + JD.tr("проверьте перед отправкой"), question: JD.micOn ? JD.tr("выберите или ответьте голосом") : JD.tr("выберите вариант"),
                         mail_draft: JD.tr("черновик · проверьте перед отправкой"), mail_sent: JD.tr("Кому: ") + (cv.c.to || ""),
                         mail_read: JD.tr("от ") + (cv.c.from || ""), mail_list: JD.tr("важные непрочитанные · обработано локально"),
                         calendar: (cv.c.items || []).length ? (cv.c.items || []).length + JD.tr(" · обработано локально") : JD.tr("свободно"),
                         media: cv.c.failed ? (cv.c.error || "") : (cv.c.name || "") })[cv.c.type] || ""
            IconButton { icon: "window-close"; size: 26
                         onClicked: { if (["message_draft", "question"].includes(cv.c.type)) JD.send({ cmd: "deny" }); JD.card = null } }
        }

        // a finished picture / video / track / model from the studio
        ClippingRectangle {
            id: previewBox
            visible: (cv.c.type === "media" || cv.c.type === "question") && !!cv.c.thumb
            property real ratio: 0.5625  // height / width, set once the picture is loaded
            Layout.fillWidth: true
            // the card is 600 wide (564 inside): a fixed width keeps the layout from re-polishing itself
            implicitHeight: Math.min(cv.c.type === "question" ? 210 : 300, 564 * ratio)
            radius: 14
            color: JD.fill1
            Image {
                id: preview
                anchors.fill: parent
                source: cv.c.thumb ? (cv.c.thumb.startsWith("http") ? cv.c.thumb : "file://" + cv.c.thumb) : ""
                sourceSize.width: 1128
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                cache: false
                // (sourceSize.height stays 0 when only the width is requested — the implicit size is the real one)
                onStatusChanged: if (status === Image.Ready && implicitWidth > 0) previewBox.ratio = implicitHeight / implicitWidth
                opacity: status === Image.Ready ? 1 : 0
                Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.dur(220); easing.type: JD.easeOut } }
            }
            Rectangle {
                visible: cv.c.kind === "video" || cv.c.type === "question"
                anchors.centerIn: parent
                width: 52; height: 52; radius: 26
                color: Qt.rgba(0, 0, 0, 0.55)
                Icon { anchors.centerIn: parent; name: "media-playback-start"; implicitSize: 24 }
            }
            TapHandler { enabled: cv.c.type === "media"; onTapped: Quickshell.execDetached(["xdg-open", cv.c.file]) }
            HoverHandler { cursorShape: cv.c.type === "media" ? Qt.PointingHandCursor : Qt.ArrowCursor }
        }
        RowLayout {
            visible: cv.c.type === "media" && !cv.c.failed
            Layout.alignment: Qt.AlignRight
            spacing: 10
            PillButton { label: JD.tr("Показать в папке"); onClicked: { JD.showInFolder(cv.c.file); JD.card = null } }
            PillButton { visible: cv.c.kind === "image"; label: JD.tr("Копировать")
                         onClicked: { Quickshell.execDetached(["sh", "-c", 'wl-copy < "$1"', "sh", cv.c.file]); JD.flash(JD.tr("Скопировано"), "edit-copy", JD.accentGreen); JD.card = null } }
            PillButton { label: JD.tr("Открыть"); tint: JD.accentPurple; labelColor: "white"
                         onClicked: { Quickshell.execDetached(["xdg-open", cv.c.file]); JD.card = null } }
        }

        // draft: To / Subject / Body + Send
        GridLayout {
            visible: cv.c.type === "mail_draft"
            Layout.fillWidth: true
            columns: 2
            columnSpacing: 12
            rowSpacing: 6
            Label2 { text: JD.tr("Кому") }
            Label1 { text: (cv.c.to || "") + (cv.c.address && cv.c.address !== cv.c.to ? "  <" + cv.c.address + ">" : ""); Layout.fillWidth: true }
            Label2 { text: JD.tr("Тема") }
            Label1 { text: cv.c.subject || JD.tr("без темы"); Layout.fillWidth: true }
        }
        Rectangle {
            visible: ["mail_draft", "mail_read", "message_draft", "question"].includes(cv.c.type) && !cardCol.tiles
            Layout.fillWidth: true
            implicitHeight: Math.min(200, bodyText.implicitHeight + 24)
            radius: 14
            color: JD.fill1
            Flickable {
                anchors.fill: parent
                anchors.margins: 12
                contentHeight: bodyText.implicitHeight
                clip: true
                Text {
                    font.family: JD.fontFamily
                    id: bodyText
                    width: parent.width
                    text: cv.c.type === "mail_read" ? (cv.c.text || "") : cv.c.type === "question" ? (cv.c.question || "") : (cv.c.body || "")
                    wrapMode: Text.Wrap
                    color: JD.text1
                    font.pixelSize: 14
                    lineHeight: 1.15
                    textFormat: Text.PlainText
                }
            }
        }
        RowLayout {
            visible: cv.c.type === "mail_draft"
            Layout.alignment: Qt.AlignRight
            spacing: 10
            PillButton { label: JD.tr("Не отправлять"); onClicked: JD.send({ cmd: "type", text: JD.tr("не отправляй") }) }
            PillButton { label: JD.tr("Изменить голосом"); onClicked: JD.send({ cmd: "toggle" }) }
            PillButton { label: JD.tr("Отправить"); tint: JD.accentBlue; onClicked: JD.send({ cmd: "type", text: JD.tr("да, отправляй") }) }
        }

        // message draft: shown before the assistant opens the messenger
        RowLayout {
            visible: cv.c.type === "message_draft"
            Layout.alignment: Qt.AlignRight
            spacing: 10
            PillButton { label: JD.tr("Не отправлять"); onClicked: JD.send({ cmd: "deny" }) }
            PillButton { label: JD.tr("Изменить голосом"); onClicked: JD.send({ cmd: "listen" }) }
            PillButton { label: JD.tr("Отправить"); tint: JD.accentBlue; onClicked: JD.send({ cmd: "approve" }) }
        }

        // the assistant's question: one button per option (options with icons sit side by side as tiles)
        readonly property bool tiles: cv.c.type === "question" && (cv.c.options || []).length > 0 && (cv.c.options || []).length <= 4
                                      && (cv.c.options || []).every(o => !!o.icon || !!o.thumb)
        Label1 {
            visible: cardCol.tiles && !!cv.c.question
            text: cv.c.question || ""
            font.weight: Font.Medium
            wrapMode: Text.Wrap
            maximumLineCount: 3
            Layout.fillWidth: true
        }
        RowLayout {
            visible: cardCol.tiles
            Layout.fillWidth: true
            spacing: 10
            Repeater {
                model: cardCol.tiles ? cv.c.options : []
                Pressable {
                    required property var modelData
                    required property int index
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    implicitHeight: tileCol.implicitHeight + 24
                    radius: 16
                    color: hovered ? JD.fill2 : JD.fill1
                    border.width: index === 0 ? 1 : 0
                    border.color: Qt.rgba(JD.accentBlue.r, JD.accentBlue.g, JD.accentBlue.b, 0.6)
                    Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                    ColumnLayout {
                        id: tileCol
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 12 }
                        spacing: 4
                        // Вариант с картинкой — выбор песни: узнать обложку быстрее,
                        // чем прочитать название, особенно когда названия похожи.
                        Rectangle {
                            visible: !!modelData.thumb
                            Layout.fillWidth: true
                            Layout.preferredHeight: width * 9 / 16
                            radius: 10
                            clip: true
                            color: JD.fill2
                            Image {
                                anchors.fill: parent
                                source: modelData.thumb || ""
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                                cache: true
                            }
                        }
                        Icon { visible: !modelData.thumb; name: modelData.icon; implicitSize: 26; Layout.alignment: Qt.AlignHCenter }
                        Label1 { text: modelData.label; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true }
                        Label2 { text: modelData.description || ""; font.pixelSize: 11; color: JD.text3; horizontalAlignment: Text.AlignHCenter
                                 wrapMode: Text.Wrap; maximumLineCount: 2; Layout.fillWidth: true }
                        Text {
                            visible: index === 0 && !!JD.hotkeys.yes
                            text: JD.hotkeys.yes || ""
                            color: JD.text3; font.family: JD.fontFamily; font.pixelSize: 10
                            Layout.alignment: Qt.AlignHCenter
                        }
                    }
                    onClicked: JD.send({ cmd: "answer", value: modelData.label })
                }
            }
        }
        Repeater {
            model: cv.c.type === "question" && !cardCol.tiles ? (cv.c.options || []) : []
            Pressable {
                required property var modelData
                Layout.fillWidth: true
                implicitHeight: optCol.implicitHeight + 16
                radius: 12
                color: hovered ? JD.fill2 : JD.fill1
                ColumnLayout {
                    id: optCol
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 12; rightMargin: 12 }
                    spacing: 1
                    Label1 { text: modelData.label; Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2 }
                    Label2 { visible: !!modelData.description; text: modelData.description || ""; Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2 }
                }
                onClicked: JD.send({ cmd: "answer", value: modelData.label })
            }
        }
        RowLayout {
            visible: cv.c.type === "question"
            Layout.alignment: Qt.AlignRight
            spacing: 10
            PillButton { label: JD.tr("Пропустить"); onClicked: JD.send({ cmd: "deny" }) }
            PillButton { visible: JD.micOn; label: JD.tr("Ответить голосом"); tint: JD.accentBlue; onClicked: JD.send({ cmd: "listen" }) }
        }

        // calendar events
        Repeater {
            model: cv.c.type === "calendar" ? (cv.c.items || []) : []
            Rectangle {
                required property var modelData
                Layout.fillWidth: true
                implicitHeight: 44
                radius: 12
                color: JD.fill1
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 12
                    Text {
                        text: modelData.all_day ? JD.tr("весь день") : Qt.formatTime(new Date(modelData.start), "HH:mm")
                        color: JD.accentOrange; font.family: JD.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold
                        Layout.preferredWidth: 70
                    }
                    ColumnLayout {
                        spacing: 0
                        Layout.fillWidth: true
                        Label1 { text: modelData.title; Layout.fillWidth: true }
                        Label2 { visible: !!modelData.location; text: modelData.location; Layout.fillWidth: true }
                    }
                }
            }
        }

        // list of letters
        Label2 {
            visible: cv.c.type === "mail_list" && !!cv.c.text
            text: cv.c.text || ""
            wrapMode: Text.Wrap
            elide: Text.ElideNone
            maximumLineCount: 4
            Layout.fillWidth: true
        }
        Repeater {
            model: cv.c.type === "mail_list" ? (cv.c.items || []) : []
            // Нажатие раскрывает письмо прямо в списке. Раньше оно просило «прочитай письмо
            // номер N» — Джарвис начинал читать вслух, а глазами посмотреть было нечего.
            Rectangle {
                id: letterRow
                required property var modelData
                readonly property bool open: cv.openLetter === modelData.n
                Layout.fillWidth: true
                implicitHeight: letterCol.implicitHeight + 18
                radius: 12
                clip: true
                color: rowHover.hovered && !open ? JD.fill2 : JD.fill1
                Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                Behavior on implicitHeight { enabled: JD.animOn; NumberAnimation { duration: JD.dur(200); easing.type: JD.easeOut } }
                ColumnLayout {
                    id: letterCol
                    anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: 9; leftMargin: 12; rightMargin: 12 }
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        Rectangle {
                            implicitWidth: 26; implicitHeight: 26; radius: 13
                            color: Qt.hsla(cv.hue(letterRow.modelData.address || letterRow.modelData.from), 0.5, 0.45, 1)
                            Text { font.family: JD.fontFamily; anchors.centerIn: parent; text: (letterRow.modelData.from || "?").charAt(0).toUpperCase(); color: "white"; font.pixelSize: 12; font.weight: Font.Bold }
                        }
                        // Пустая тема не занимает строку: иначе имя отправителя прилипало к
                        // верху, а кружок стоял по центру — ряд выглядел съехавшим.
                        ColumnLayout {
                            spacing: 1
                            Layout.fillWidth: true
                            Label1 { text: letterRow.modelData.from; font.pixelSize: 12; Layout.fillWidth: true }
                            Label2 {
                                visible: !!letterRow.modelData.subject
                                text: letterRow.modelData.subject || ""
                                Layout.fillWidth: true
                                wrapMode: letterRow.open ? Text.Wrap : Text.NoWrap
                                maximumLineCount: letterRow.open ? 3 : 1
                            }
                        }
                        Icon {
                            name: "chevron-down"; implicitSize: 14; tint: JD.text3
                            rotation: letterRow.open ? 180 : 0
                            Behavior on rotation { enabled: JD.animOn; NumberAnimation { duration: JD.dur(200); easing.type: JD.easeOut } }
                        }
                    }
                    Label2 {
                        visible: letterRow.open
                        text: letterRow.modelData.preview || JD.tr("Текста в письме нет.")
                        color: JD.text1
                        wrapMode: Text.Wrap
                        maximumLineCount: 9
                        lineHeight: 1.15
                        Layout.fillWidth: true
                        Layout.leftMargin: 36
                    }
                    RowLayout {
                        visible: letterRow.open
                        Layout.leftMargin: 36
                        Layout.bottomMargin: 2
                        spacing: 8
                        PillButton { label: JD.tr("Прочитать вслух"); onClicked: JD.send({ cmd: "type", text: JD.tr("прочитай письмо номер ") + letterRow.modelData.n }) }
                        PillButton { label: JD.tr("Открыть в браузере"); onClicked: JD.send({ cmd: "type", text: JD.tr("открой письмо номер ") + letterRow.modelData.n + JD.tr(" в браузере") }) }
                    }
                }
                HoverHandler { id: rowHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: cv.openLetter = letterRow.open ? 0 : letterRow.modelData.n }
            }
        }
    }
}

