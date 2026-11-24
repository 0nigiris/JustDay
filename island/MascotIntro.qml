import QtQuick

// Первое знакомство начинается с маскота: шарик падает сверху (или выныривает снизу), отскакивает,
// оглядывается и сам становится островком со знакомством. Первое, что человек видит после установки, —
// это он, а не окно и не терминал.
Item {
    id: intro
    // Капсула островка во время вступления стоит под шариком невидимой, того же размера и на том же
    // месте (shell.qml). В конце она проявляется в один кадр и растёт в знакомство сама, шарик исчезает,
    // а глаза остаются лицом карточки. Раньше шарик растягивался до 220 и гас, а островок вырастал отдельно из нуля: на глаз
    // это был монтажный стык, а не превращение. У полосы и выреза формы не совпадают, там прежний путь.
    readonly property bool morph: JD.islandStyle === "island"
    visible: JD.introOn
    readonly property real size: 44
    readonly property real restY: JD.atTop ? (JD.islandStyle === "island" ? JD.topMargin : 6) : parent.height - size - 8
    width: size; height: size
    x: (parent.width - size) / 2
    y: -size - 20
    Rectangle {
        id: ball
        anchors.fill: parent
        radius: height / 2
        color: JD.ink
        border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.10)
        // Приплюснуть при ударе о край: так шарик кажется мягким и живым, а не нарисованной точкой.
        transform: Scale { origin.x: ball.width / 2; origin.y: ball.height; yScale: intro.squash; xScale: 2 - intro.squash }
        Row {
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -1
            anchors.horizontalCenterOffset: intro.look
            spacing: 9
            Repeater {
                model: 2
                Rectangle { width: 6; height: intro.eyeH; radius: 3; color: "white"; anchors.verticalCenter: parent.verticalCenter }
            }
        }
    }
    property real look: 0
    property real eyeH: 9
    property real squash: 1
    SequentialAnimation {
        running: JD.introOn
        ScriptAction { script: { intro.x = (intro.parent.width - intro.size) / 2; intro.width = intro.size; intro.height = intro.size; intro.y = JD.atTop ? -intro.size - 20 : intro.parent.height + 20; intro.eyeH = 9; intro.squash = 1; intro.look = 0; intro.opacity = 1 } }
        PauseAnimation { duration: 250 }
        NumberAnimation { target: intro; property: "y"; to: intro.restY; duration: 900; easing.type: Easing.OutBounce }
        PauseAnimation { duration: 260 }
        // Оглядеться и моргнуть: «живой», а не значок загрузки.
        NumberAnimation { target: intro; property: "look"; to: -6; duration: 220; easing.type: Easing.OutCubic }
        PauseAnimation { duration: 260 }
        NumberAnimation { target: intro; property: "look"; to: 6; duration: 300; easing.type: Easing.InOutCubic }
        PauseAnimation { duration: 220 }
        NumberAnimation { target: intro; property: "look"; to: 0; duration: 200; easing.type: Easing.OutCubic }
        NumberAnimation { target: intro; property: "eyeH"; to: 1; duration: 90 }
        NumberAnimation { target: intro; property: "eyeH"; to: 9; duration: 110 }
        PauseAnimation { duration: 280 }
        // Полоса и вырез: растянуться вширь, будто это и есть островок.
        ParallelAnimation {
            NumberAnimation { target: intro; property: "width"; to: intro.morph ? intro.size : 220; duration: intro.morph ? 0 : 320; easing.type: Easing.InOutCubic }
            NumberAnimation { target: intro; property: "x"; to: (intro.parent.width - (intro.morph ? intro.size : 220)) / 2; duration: intro.morph ? 0 : 320; easing.type: Easing.InOutCubic }
        }
        ScriptAction { script: JD.openTools("welcome") }
        // Капсула: глаза уже нарисованы в островке на том же месте (лицо знакомства в shell.qml),
        // шарик просто исчезает. Полоса и вырез: глаза щурятся и гаснут.
        ParallelAnimation {
            NumberAnimation { target: intro; property: "eyeH"; to: intro.morph ? 9 : 2; duration: intro.morph ? 0 : 180 }
            NumberAnimation { target: intro; property: "opacity"; to: 0; duration: intro.morph ? 0 : 240; easing.type: Easing.OutCubic }
        }
        // Пока карточка растёт, вступление ещё идёт: по нему островок берёт медленную пружину.
        PauseAnimation { duration: 450 }
        ScriptAction { script: JD.introOn = false }
    }
}
