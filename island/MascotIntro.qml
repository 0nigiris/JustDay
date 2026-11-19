import QtQuick

// Первое знакомство начинается с маскота: шарик падает сверху (или выныривает снизу), отскакивает,
// моргает и растягивается в островок со знакомством. Первое, что человек видит после установки, —
// это он, а не окно и не терминал.
Item {
    id: intro
    visible: JD.introOn
    readonly property real size: 44
    readonly property real restY: JD.atTop ? (JD.islandStyle === "island" ? JD.topMargin : 6) : parent.height - size - 8
    width: size; height: size
    x: (parent.width - width) / 2
    y: -size - 20
    Rectangle {
        id: ball
        anchors.centerIn: parent
        width: intro.size; height: intro.size; radius: height / 2
        color: JD.ink
        border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.10)
        // Приплюснуть при ударе о край: так шарик кажется мягким и живым, а не нарисованной точкой.
        transform: Scale { origin.x: ball.width / 2; origin.y: ball.height; yScale: intro.squash; xScale: 2 - intro.squash }
        Row {
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -1
            spacing: 9
            Repeater {
                model: 2
                Rectangle { width: 6; height: intro.eyeH; radius: 3; color: "white"; anchors.verticalCenter: parent.verticalCenter }
            }
        }
    }
    property real eyeH: 9
    property real squash: 1
    SequentialAnimation {
        running: JD.introOn
        ScriptAction { script: { intro.y = JD.atTop ? -intro.size - 20 : intro.parent.height + 20; intro.eyeH = 9; intro.squash = 1; ball.width = intro.size; intro.opacity = 1 } }
        PauseAnimation { duration: 250 }
        NumberAnimation { target: intro; property: "y"; to: intro.restY; duration: 900; easing.type: Easing.OutBounce }
        PauseAnimation { duration: 300 }
        // Моргнуть дважды: «живой», а не значок загрузки.
        NumberAnimation { target: intro; property: "eyeH"; to: 1; duration: 90 }
        NumberAnimation { target: intro; property: "eyeH"; to: 9; duration: 110 }
        PauseAnimation { duration: 160 }
        NumberAnimation { target: intro; property: "eyeH"; to: 1; duration: 90 }
        NumberAnimation { target: intro; property: "eyeH"; to: 9; duration: 110 }
        PauseAnimation { duration: 350 }
        // Растянуться вширь, будто это и есть островок, и уступить место знакомству.
        ParallelAnimation {
            NumberAnimation { target: ball; property: "width"; to: 220; duration: 320; easing.type: Easing.InOutCubic }
            SequentialAnimation {
                PauseAnimation { duration: 180 }
                ScriptAction { script: JD.openTools("welcome") }
            }
        }
        NumberAnimation { target: intro; property: "opacity"; to: 0; duration: 220 }
        ScriptAction { script: JD.introOn = false }
    }
}
