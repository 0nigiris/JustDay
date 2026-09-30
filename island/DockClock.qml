// Часы в доке. По умолчанию выключены: время уже есть у верхнего края, и два одинаковых числа на
// одном экране — не удобство, а рябь. Включают их те, у кого острова сверху нет.
import QtQuick

Item {
    id: clock
    property real size: 22
    property var now: new Date()
    // Свой счётчик: общий тик острова идёт, только пока что-то отсчитывают, и часы бы замирали.
    Timer { interval: 15000; running: clock.visible; repeat: true; triggeredOnStart: true
            onTriggered: clock.now = new Date() }

    readonly property string time: Qt.formatTime(now, "HH:mm")
    readonly property string day: Qt.formatDate(now, "ddd d")

    implicitWidth: Math.max(bigText.implicitWidth, smallText.implicitWidth) + 8
    implicitHeight: size

    Column {
        anchors.centerIn: parent
        spacing: 0
        Text {
            id: bigText
            anchors.horizontalCenter: parent.horizontalCenter
            text: clock.time
            color: JD.text1
            font.family: JD.fontFamily
            font.pixelSize: Math.round(clock.size * 0.44)
            font.weight: Font.DemiBold
        }
        Text {
            id: smallText
            anchors.horizontalCenter: parent.horizontalCenter
            text: clock.day
            color: JD.text2
            font.family: JD.fontFamily
            font.pixelSize: Math.round(clock.size * 0.28)
        }
    }
}
