// Блик «жидкого стекла» (Р3-17): светлая кромка и мягкий отсвет сверху. Кладётся первым ребёнком
// в карточку панели и виден, только когда выбран материал «Стекло» — у матового и сплошного его нет.
import QtQuick

Rectangle {
    visible: JD.glassOn
    anchors.fill: parent
    color: "transparent"
    border.width: 1
    border.color: Qt.rgba(1, 1, 1, 0.26)
    // Отсвет сверху: стекло ловит свет верхним краем, и без него прозрачная карточка выглядит
    // просто бледной, а не стеклянной.
    Rectangle {
        anchors { top: parent.top; left: parent.left; right: parent.right; margins: 1 }
        height: parent.height * 0.45
        radius: parent.radius
        gradient: Gradient {
            GradientStop { position: 0; color: Qt.rgba(1, 1, 1, 0.12) }
            GradientStop { position: 1; color: Qt.rgba(1, 1, 1, 0) }
        }
    }
}
