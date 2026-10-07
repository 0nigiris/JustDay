import QtQuick
import QtQuick.Layouts

// Скачанная музыка прямо в плеере (Р2-32): поиск, сортировка, «играть», «в очередь», «удалить».
ColumnLayout {
    id: lib
    property color tint: JD.accentBlue
    property string query: ""
    property string confirm: ""      // файл, у которого спросили «Удалить?»
    spacing: 8

    readonly property var shown: {
        const q = query.trim().toLowerCase()
        const all = JD.libTracks || []
        return q ? all.filter(t => (t.title + " " + t.artist).toLowerCase().indexOf(q) >= 0) : all
    }
    function fmt(sec) { sec = Math.round(sec || 0); return sec > 0 ? Math.floor(sec / 60) + ":" + String(sec % 60).padStart(2, "0") : "" }

    Rectangle {
        Layout.fillWidth: true; implicitHeight: 34; radius: 10; color: JD.fill1
        RowLayout {
            anchors { fill: parent; leftMargin: 12; rightMargin: 10 }
            spacing: 8
            Icon { name: "search"; implicitSize: 14; tint: JD.text3 }
            TextInput {
                id: field
                Layout.fillWidth: true
                font.family: JD.fontFamily; font.pixelSize: 13; color: JD.text1
                selectByMouse: true; clip: true
                text: lib.query
                onTextChanged: lib.query = text
                Text { visible: !field.text; text: JD.tr("Поиск по медиатеке"); color: JD.text3; font: field.font }
            }
            IconButton { visible: field.text !== ""; icon: "edit-clear"; size: 20; onClicked: field.text = "" }
        }
    }
    Row {
        spacing: 6
        Repeater {
            model: [{ v: "recent", l: JD.tr("Недавние") }, { v: "title", l: JD.tr("По названию") }, { v: "artist", l: JD.tr("По исполнителю") }]
            Rectangle {
                required property var modelData
                width: sortText.implicitWidth + 20; height: 24; radius: 12
                color: JD.libSort === modelData.v ? Qt.rgba(1, 1, 1, 0.18) : JD.fill1
                Text { id: sortText; anchors.centerIn: parent; text: modelData.l; font.pixelSize: 12
                       color: JD.libSort === modelData.v ? "#ffffff" : JD.text2 }
                TapHandler { onTapped: { JD.libSort = modelData.v; JD.libRefresh() } }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
            }
        }
    }
    Text {
        visible: lib.shown.length === 0
        Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; topPadding: 20; bottomPadding: 20
        text: (JD.libTracks || []).length === 0 ? JD.tr("Здесь появится скачанная музыка") : JD.tr("Ничего не найдено")
        color: JD.text3; font.pixelSize: 13
    }
    ListView {
        id: list
        visible: lib.shown.length > 0
        Layout.fillWidth: true
        implicitHeight: Math.min(7, count) * 46
        clip: true; spacing: 2
        boundsBehavior: Flickable.StopAtBounds
        model: lib.shown
        delegate: Rectangle {
            id: row
            required property var modelData
            readonly property bool asking: lib.confirm === modelData.file
            width: list.width; height: 44; radius: 10
            color: rowHover.hovered ? JD.fill1 : "transparent"
            HoverHandler { id: rowHover }
            // щелчок по строке играет; кнопки справа его перехватывают сами
            TapHandler { onTapped: JD.send({ cmd: "media_play", query: row.modelData.file, mode: "replace" }) }
            RowLayout {
                anchors { fill: parent; leftMargin: 8; rightMargin: 8 }
                spacing: 10
                Rectangle {
                    Layout.preferredWidth: 32; Layout.preferredHeight: 32; radius: 6; color: Qt.rgba(lib.tint.r, lib.tint.g, lib.tint.b, 0.25)
                    clip: true
                    Image { anchors.fill: parent; source: row.modelData.thumb || ""; fillMode: Image.PreserveAspectCrop; asynchronous: true }
                }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 0
                    visible: !row.asking
                    Label1 { text: row.modelData.title; Layout.fillWidth: true; elide: Text.ElideRight }
                    Label2 { text: row.modelData.artist || ""; visible: !!row.modelData.artist; font.pixelSize: 11; Layout.fillWidth: true; elide: Text.ElideRight }
                }
                Label2 { visible: !row.asking; text: lib.fmt(row.modelData.duration); font.pixelSize: 11 }
                IconButton { visible: !row.asking && rowHover.hovered; icon: "list-add"; size: 24
                             onClicked: JD.send({ cmd: "media_play", query: row.modelData.file, mode: "append" }) }
                IconButton { visible: !row.asking && rowHover.hovered; icon: "user-trash"; size: 24
                             onClicked: lib.confirm = row.modelData.file }
                // необратимое спрашивает в самой строке, а не системным окном
                Label1 { visible: row.asking; text: JD.tr("Удалить в корзину?"); Layout.fillWidth: true }
                Rectangle {
                    visible: row.asking; implicitWidth: yes.implicitWidth + 20; implicitHeight: 26; radius: 13; color: JD.accentRed
                    Text { id: yes; anchors.centerIn: parent; text: JD.tr("Удалить"); color: "#ffffff"; font.pixelSize: 12 }
                    TapHandler { onTapped: { JD.send({ cmd: "music_trash", file: row.modelData.file }); lib.confirm = ""; refetch.restart() } }
                }
                Rectangle {
                    visible: row.asking; implicitWidth: no.implicitWidth + 20; implicitHeight: 26; radius: 13; color: JD.fill2
                    Text { id: no; anchors.centerIn: parent; text: JD.tr("Отмена"); color: JD.text1; font.pixelSize: 12 }
                    TapHandler { onTapped: lib.confirm = "" }
                }
            }
        }
    }
    Timer { id: refetch; interval: 400; onTriggered: JD.libRefresh() }
}
