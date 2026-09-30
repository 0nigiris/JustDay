// Трей: чужие значки — те, что программы кладут в системный лоток, — отдельной полосой у бокового края.
//
// Отдельной, а не в островке, по той же причине, по которой док отдельно от меню: лоток не наш. Его
// содержимое решают чужие программы, оно меняется само, и значки в нём нарисованы не в нашем стиле.
// Класть это внутрь островка значит пускать чужой набор значков в единственное место, где стиль
// выдержан до конца. Полоса же — просто полоса: она уважает то, что в ней лежит.
//
// Левая кнопка — то, что программа считает главным действием (activate). Правая — её собственное
// меню: пункты берутся у программы по DBusMenu, а рисуем их мы (TrayMenu). Системное меню
// Quickshell умеет показывать только в режиме QApplication, а мы работаем без QtWidgets — и раньше
// правая кнопка просто молчала.
import QtQuick
import Quickshell
import Quickshell.Widgets
import Quickshell.Services.SystemTray

Item {
    id: tv

    readonly property real icon: JD.trayIconSize
    readonly property real pad: 8
    readonly property real cell: icon + 14
    readonly property bool atRight: JD.trayPlace === "right"

    // Показываем всё, что в лотке есть. KDE прячет «пассивные» значки во всплывающий ящик, но
    // «мой значок пропал» — худшая новость, какую может принести полоса лотка: человек не знает,
    // программа умерла или это оболочка решила за него.
    // Показываем всё, кроме того, что попросили спрятать. «Мой значок пропал» — худшая новость,
    // какую может принести полоса лотка, поэтому сама она ничего не решает: список спрятанного
    // ведёт человек, и каждый значок в нём виден в настройках.
    readonly property var items: SystemTray.items.values.filter(i => !!i && JD.trayShows(i))
    readonly property bool empty: items.length === 0

    implicitWidth: icon + pad * 2
    implicitHeight: Math.max(cell, items.length * cell + pad * 2)

    readonly property Rectangle blurItem: strip

    Rectangle {
        id: strip
        anchors.fill: parent
        radius: Math.round(tv.implicitWidth * 0.34)
        color: Qt.rgba(0, 0, 0, JD.blurOn ? 0.4 : 0.82)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.12)

        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            y: tv.pad
            Repeater {
                model: tv.items
                delegate: Item {
                    id: slot
                    required property var modelData
                    width: tv.cell
                    height: tv.cell

                    Rectangle {
                        anchors.centerIn: parent
                        width: tv.icon + 10
                        height: width
                        radius: width / 2
                        color: slotHover.hovered ? JD.fill1 : "transparent"
                        Behavior on color { enabled: JD.animOn; ColorAnimation { duration: 120 } }
                    }
                    IconImage {
                        anchors.centerIn: parent
                        implicitSize: tv.icon
                        source: slot.modelData.icon
                        scale: slotTap.pressed ? 0.88 : 1
                        Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: 110 } }
                    }

                    // Программа просит внимания — оранжевая точка. Это единственное, что полоса
                    // говорит своими словами: всё остальное в ней нарисовано чужими руками.
                    Rectangle {
                        visible: slot.modelData.status === Status.NeedsAttention
                        width: 6
                        height: 6
                        radius: 3
                        color: JD.accentOrange
                        x: tv.atRight ? 2 : parent.width - width - 2
                        y: 3
                    }

                    HoverHandler {
                        id: slotHover
                        cursorShape: Qt.PointingHandCursor
                        onHoveredChanged: {
                            if (!hovered) { tv.hint = ""; return }
                            tv.hint = slot.modelData.tooltipTitle || slot.modelData.title || slot.modelData.id || ""
                            tv.hintY = slot.y + slot.height / 2 + tv.pad
                        }
                    }
                    // Значок, у которого есть только меню (onlyMenu), по левой кнопке тоже открывает
                    // меню: у него нет главного действия, и молчать в ответ на щелчок — сломанный значок.
                    TapHandler {
                        id: slotTap
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: {
                            const it = slot.modelData
                            // Меню соседнего значка, если оно открыто, закрывается само: полоса
                            // остаётся нажимаемой из-под меню, и щелчок по ней — это работа со
                            // значком, а не с чужим меню.
                            JD.closeTrayMenu()
                            if (it.onlyMenu && it.hasMenu) tv.showMenu(it, slot)
                            else it.activate()
                        }
                    }
                    // Правая кнопка — меню самой программы, оно тут главное. Спрятать значок —
                    // Ctrl и правая кнопка: редкое действие не должно занимать частый жест. Здесь
                    // MouseArea, а не TapHandler: только она честно отдаёт зажатые модификаторы.
                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.RightButton
                        onClicked: mouse => {
                            const it = slot.modelData
                            if (mouse.modifiers & Qt.ControlModifier) JD.trayHide(it.id || it.title, true)
                            else tv.showMenu(it, slot)
                        }
                    }
                    TapHandler {
                        acceptedButtons: Qt.MiddleButton
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: slot.modelData.secondaryActivate()
                    }
                    WheelHandler {
                        onWheel: event => slot.modelData.scroll(event.angleDelta.y, false)
                    }
                }
            }
        }
    }

    property string hint: ""
    // Меню растёт от того края полосы, у которого она стоит, и от середины значка: так видно, чьё
    // оно. Точка — в координатах экрана: меню живёт в отдельном окне во весь экран.
    function showMenu(item, at) {
        if (!item || !item.hasMenu) return
        // Повторный щелчок по тому же значку закрывает меню, а не открывает его заново: иначе
        // единственный способ убрать его — целиться мимо.
        if (JD.trayMenu === item) { JD.closeTrayMenu(); return }
        const p = at.mapToItem(null, tv.atRight ? 0 : at.width, at.height / 2)
        const left = tv.atRight ? JD.screenWidth - tv.width - 10 : tv.x + tv.width
        JD.openTrayMenu(item, Math.round(tv.atRight ? left : left + 8), Math.round(p.y))
        tv.hint = ""
    }

    // Подпись рядом с полосой, а не поверх неё: полоса узкая, имя в неё не влезает.
    Rectangle {
        visible: tv.hint !== ""
        width: hintText.implicitWidth + 20
        height: 26
        radius: 13
        color: Qt.rgba(0, 0, 0, 0.82)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.12)
        x: tv.atRight ? -width - 10 : tv.width + 10
        y: Math.max(0, Math.min(tv.height - height, tv.hintY - height / 2))
        Label1 { id: hintText; anchors.centerIn: parent; text: tv.hint }
    }
    property real hintY: tv.height / 2
}
