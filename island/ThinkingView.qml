// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts

View {
    id: tv
    readonly property string line: JD.dstate === "transcribing" ? JD.tr("Распознаю…") : (JD.activity || JD.tr("Думаю…"))
    property int elapsed: 0
    Timer { interval: 1000; repeat: true; running: tv.shown; onTriggered: tv.elapsed = Math.round((Date.now() - JD.busySince) / 1000) }
    TextMetrics { font.family: JD.fontFamily; id: tm; text: tv.line; font.pixelSize: 13; font.weight: Font.DemiBold }
    readonly property bool longText: tm.width > 470
    // Ступень ноль — кружок и ничего больше: идёт работа, и этого достаточно, чтобы знать.
    implicitWidth: JD.workStep === 0 ? (JD.brainStrong ? 136 : 92)
                                     : Math.min(640, Math.max(240, tm.width + 118))
    implicitHeight: JD.detailOpen ? Math.min(260, full.implicitHeight + 58) : 40

    RowLayout {
        id: head
        anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: 12; rightMargin: 12 }
        height: 40
        spacing: 10
        Item {
            implicitWidth: 20; implicitHeight: 20
            Ring { anchors.fill: parent; size: 20; visible: !JD.activityIcon }
            Icon { anchors.centerIn: parent; name: JD.activityIcon; implicitSize: 18; visible: !!JD.activityIcon }
        }
        Label1 {
            id: oneLine
            text: tv.line
            TextSwap on text {}
            Layout.fillWidth: true
            visible: JD.workStep === 1
        }
        // На сильной модели — отметка. Про лёгкую говорить нечего: она работает всегда, и
        // сообщать об этом значило бы шуметь ровно в том месте, которое мы бережём.
        Rectangle {
            visible: JD.brainStrong
            implicitHeight: 18
            implicitWidth: strongLabel.implicitWidth + 14
            radius: 9
            color: Qt.rgba(JD.accentPurple.r, JD.accentPurple.g, JD.accentPurple.b, 0.22)
            Label2 {
                id: strongLabel
                anchors.centerIn: parent
                text: JD.brainModel
                color: JD.accentPurple
                font.pixelSize: 10
                font.weight: Font.DemiBold
            }
        }
        Label2 { text: tv.elapsed >= 3 ? tv.elapsed + JD.tr(" с") : ""; font.features: { "tnum": 1 } }
        IconButton {
            // Одна кнопка на все три ступени: значок → строка → всё → снова значок. Три
            // отдельные кнопки заняли бы ровно то место, которое мы бережём.
            visible: true
            size: 24
            icon: JD.workStep === 2 ? "go-up" : "go-down"
            onClicked: JD.workMore()
        }
    }
    Flickable {
        anchors { left: parent.left; right: parent.right; top: head.bottom; bottom: parent.bottom; leftMargin: 18; rightMargin: 18; bottomMargin: 14 }
        contentHeight: full.implicitHeight
        clip: true
        visible: JD.detailOpen
        Text {
            font.family: JD.fontFamily
            id: full
            width: parent.width
            text: tv.line
            wrapMode: Text.Wrap
            color: JD.text1
            font.pixelSize: 13
            textFormat: Text.PlainText
        }
    }
}
