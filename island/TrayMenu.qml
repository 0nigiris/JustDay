// Меню значка лотка, нарисованное нами.
//
// Раньше здесь вызывалось системное меню (`item.display`), и оно молча не открывалось: Quickshell
// умеет показывать чужое меню только в режиме QApplication, а мы работаем без QtWidgets — ради
// памяти. В журнале это видно прямым текстом: «Cannot display PlatformMenuEntry as quickshell was
// not started in QApplication mode». Правая кнопка нажималась, меню не появлялось.
//
// Поднимать ради одного меню весь QtWidgets — плохая сделка: десятки мегабайт, чужой стиль Breeze
// посреди нашего, и всё равно окно поверх слоёв. Поэтому меню мы рисуем сами, а содержимое берём
// оттуда же, откуда его брала бы система: DBusMenu (`QsMenuOpener`). Программа по-прежнему хозяин
// пунктов — галочки, переключатели, подменю и «серые» пункты приходят от неё и работают.
//
// Что здесь наше, а что чужое. Наши — форма, цвета, отступы, порядок появления. Чужие — текст,
// значки, состояние и сам факт нажатия: нажатие уходит программе как есть, без нашей трактовки.
import QtQuick
import Quickshell

Item {
    id: tm

    property var handle: null        // корневое меню значка: item.menu
    property real atX: 0             // от какого края полосы растём
    property real atY: 0             // середина значка по высоте
    property bool toLeft: false      // полоса справа — меню растёт влево
    signal dismissed()

    readonly property real screenW: JD.screenWidth
    readonly property real screenH: JD.screenHeight

    // Раскрытые подменю: только глубина, которая встречается в жизни. Трёх уровней хватает —
    // дальше не идут даже те значки, что любят складывать всё в подменю.
    property var sub1: null
    property real sub1Y: 0
    property var sub2: null
    property real sub2Y: 0

    onHandleChanged: { sub1 = null; sub2 = null }
    function finish() { sub1 = null; sub2 = null; tm.dismissed() }

    // Раскрыть подменю у строки под номером — тоже для проверки руками. Открывает только то, что
    // раскрывается: нажимать чужие пункты («Выйти из Telegram») проверка не должна.
    function poke(n) {
        const e = s0.rows[n]
        if (e && e.hasChildren) { tm.sub2 = null; tm.sub1 = e; tm.sub1Y = 400 }
        return report()
    }

    // Проверка руками: `qs -p island ipc call island trayRows`. Правую кнопку на вейланде
    // синтетически не нажать, а «меню не открылось» здесь однажды уже случилось молча.
    function report() {
        return JSON.stringify({
            open: !!tm.handle,
            at: [Math.round(tm.atX), Math.round(tm.atY)],
            card: [Math.round(s0.cardX), Math.round(s0.cardY), Math.round(s0.cardW), Math.round(s0.cardH)],
            rows: s0.rows.map(e => e.isSeparator ? "—"
                : (e.text || "") + (e.hasChildren ? " ›" : "")
                                  + (e.checkState === Qt.Checked ? " ✓" : "")
                                  + (e.enabled === false ? " (серый)" : "")),
            sub: tm.sub1 ? s1.rows.map(e => e.isSeparator ? "—" : (e.text || "")) : []
        })
    }

    // ───────────── один столбец меню ─────────────
    component Sheet: Item {
        id: sh

        property var handle: null
        property real wantLeft: 0
        property real wantTop: 0
        property real leftOf: 0      // левый край родительского столбца — если вправо места нет
        signal openSub(var entry, real atY)
        signal closeSub()
        signal chose()

        visible: !!handle && rows.length > 0
        enabled: visible
        // Куда встал столбец на самом деле: соседний растёт от этого, а не от того, куда его просили.
        readonly property real cardX: card.x
        readonly property real cardY: card.y
        readonly property real cardH: card.height
        readonly property real cardRight: card.x + card.width

        QsMenuOpener { id: opener; menu: sh.handle }

        // Чужие меню приходят и с пустыми разделителями по краям, и с двумя подряд: программа
        // складывает пункты по своему усмотрению, а прячет их по своему. Разделитель, который
        // ничего не разделяет, — мусор, и он здесь отбрасывается.
        readonly property var rows: {
            const raw = (!sh.handle || !opener.children) ? [] : opener.children.values
            const out = []
            for (let i = 0; i < raw.length; i++) {
                const e = raw[i]
                if (!e) continue
                if (e.isSeparator) {
                    if (out.length && !out[out.length - 1].isSeparator) out.push(e)
                } else {
                    out.push(e)
                }
            }
            while (out.length && out[out.length - 1].isSeparator) out.pop()
            return out
        }
        readonly property bool anyDeeper: rows.some(e => e && e.hasChildren)
        // Колея под значок и галочку нужна не всякому меню. Там, где ни значков, ни переключателей
        // нет, пустая колея — просто сдвинутый вправо текст: имена стоят не у края, а непонятно
        // отчего в отступе.
        readonly property bool anyMark: rows.some(e => e && (!!e.icon || e.buttonType !== QsMenuButtonType.None))
        readonly property real gutter: anyMark ? 20 : 0

        // Ширина — по самому длинному имени, а не «на глаз»: меню, обрезающее «Выйти из Steam»,
        // выглядит поломкой, а меню шириной во весь экран — небрежностью.
        TextMetrics {
            id: probe
            font.family: JD.fontFamily
            font.pixelSize: 13
            font.weight: Font.DemiBold
        }
        readonly property real textW: {
            let w = 0
            for (let i = 0; i < rows.length; i++) {
                const e = rows[i]
                if (!e || e.isSeparator) continue
                probe.text = e.text || ""
                w = Math.max(w, probe.width)
            }
            return w
        }
        readonly property real cardW: Math.max(176, Math.min(360,
            Math.ceil(textW) + 12 + gutter + (anyMark ? 9 : 0) + 12 + (anyDeeper ? 14 + 9 : 0) + 12))
        readonly property real contentH: {
            let h = 0
            for (let i = 0; i < rows.length; i++) h += rows[i] && rows[i].isSeparator ? 9 : 30
            return h
        }

        Rectangle {
            id: card
            width: sh.cardW
            height: Math.min(sh.contentH + 12, tm.screenH - 24)
            radius: 14
            color: Qt.rgba(0, 0, 0, 0.9)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.12)
            // Вправо, если вправо есть место; иначе слева от родителя — но никогда за краем экрана.
            x: {
                const want = sh.wantLeft
                if (want + width <= tm.screenW - 8) return Math.max(8, want)
                const flip = sh.leftOf - width - 4
                return Math.max(8, flip >= 8 ? flip : tm.screenW - width - 8)
            }
            y: Math.max(8, Math.min(tm.screenH - height - 8, sh.wantTop))

            // Меню не возникает, а раскрывается от своего угла: то же правило, по которому
            // раскрывается всё остальное в этой оболочке.
            transformOrigin: Item.TopLeft
            scale: sh.visible ? 1 : 0.94
            opacity: sh.visible ? 1 : 0
            Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: JD.dur(140); easing.type: Easing.OutCubic } }
            Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.dur(120) } }

            Flickable {
                anchors.fill: parent
                anchors.margins: 6
                contentHeight: rowsColumn.height
                interactive: contentHeight > height
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                Column {
                    id: rowsColumn
                    width: parent.width

                    Repeater {
                        model: sh.rows
                        delegate: Item {
                            id: row
                            required property var modelData
                            readonly property bool sep: !!modelData && modelData.isSeparator
                            readonly property bool deeper: !!modelData && modelData.hasChildren
                            readonly property bool on: !!modelData && modelData.checkState === Qt.Checked
                            readonly property bool live: !!modelData && modelData.enabled !== false && !sep
                            width: parent.width
                            height: sep ? 9 : 30

                            Rectangle {
                                visible: row.sep
                                anchors.centerIn: parent
                                width: parent.width - 12
                                height: 1
                                color: Qt.rgba(1, 1, 1, 0.08)
                            }

                            Rectangle {
                                visible: !row.sep
                                anchors.fill: parent
                                radius: 8
                                color: (hover.hovered && row.live) || row.deeperOpen ? JD.fill1 : "transparent"
                                Behavior on color { enabled: JD.animOn; ColorAnimation { duration: 90 } }
                            }
                            readonly property bool deeperOpen: deeper && (tm.sub1 === modelData || tm.sub2 === modelData)

                            Row {
                                visible: !row.sep
                                anchors { left: parent.left; right: parent.right; leftMargin: 6; rightMargin: 6
                                          verticalCenter: parent.verticalCenter }
                                spacing: 9

                                // Слева одна колея на всё: галочка, если пункт — переключатель, или
                                // значок, если программа его дала. Пусто — тоже колея: иначе имена
                                // съезжают строка от строки.
                                Item {
                                    anchors.verticalCenter: parent.verticalCenter
                                    visible: sh.anyMark
                                    width: sh.gutter
                                    height: 20
                                    Icon {
                                        anchors.centerIn: parent
                                        visible: row.on
                                        name: "check"
                                        implicitSize: 14
                                        tint: JD.accentBlue
                                    }
                                    Image {
                                        anchors.centerIn: parent
                                        visible: !row.on && !!row.modelData && !!row.modelData.icon
                                        source: row.modelData && row.modelData.icon ? row.modelData.icon : ""
                                        sourceSize: Qt.size(32, 32)
                                        width: 16
                                        height: 16
                                        fillMode: Image.PreserveAspectFit
                                        mipmap: true
                                        opacity: row.live ? 1 : 0.4
                                    }
                                }

                                Label1 {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - (sh.anyMark ? sh.gutter + 9 : 0)
                                           - (row.deeper ? 14 + 9 : 0) - 12
                                    color: row.live ? JD.text1 : JD.text3
                                    text: row.modelData ? (row.modelData.text || "") : ""
                                }

                                Icon {
                                    anchors.verticalCenter: parent.verticalCenter
                                    visible: row.deeper
                                    name: "chevron-right"
                                    implicitSize: 14
                                    tint: JD.text3
                                }
                            }

                            HoverHandler {
                                id: hover
                                cursorShape: row.live ? Qt.PointingHandCursor : Qt.ArrowCursor
                                onHoveredChanged: {
                                    if (!hovered || !row.live) return
                                    // Наведение на обычный пункт закрывает то, что было раскрыто
                                    // глубже: иначе на экране висит подменю, к которому мышь уже
                                    // не идёт.
                                    if (row.deeper) sh.openSub(row.modelData, row.mapToItem(tm, 0, 0).y)
                                    else sh.closeSub()
                                }
                            }
                            TapHandler {
                                enabled: row.live
                                gesturePolicy: TapHandler.ReleaseWithinBounds
                                onTapped: {
                                    if (row.deeper) {
                                        sh.openSub(row.modelData, row.mapToItem(tm, 0, 0).y)
                                        return
                                    }
                                    // Нажатие уходит программе как есть. sendTriggered — прямой
                                    // путь DBusMenu, triggered() — общий, на случай другого рода меню.
                                    const e = row.modelData
                                    if (e.sendTriggered) e.sendTriggered()
                                    else e.triggered()
                                    sh.chose()
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ───────────── три уровня ─────────────
    Sheet {
        id: s0
        handle: tm.handle
        wantLeft: tm.toLeft ? tm.atX - cardW : tm.atX
        wantTop: tm.atY - 14
        leftOf: tm.atX
        onOpenSub: (entry, y) => { tm.sub2 = null; tm.sub1 = entry; tm.sub1Y = y }
        onCloseSub: { tm.sub1 = null; tm.sub2 = null }
        onChose: tm.finish()
    }
    Sheet {
        id: s1
        handle: tm.sub1
        wantLeft: s0.cardRight - 6
        wantTop: tm.sub1Y - 6
        leftOf: s0.cardX
        onOpenSub: (entry, y) => { tm.sub2 = entry; tm.sub2Y = y }
        onCloseSub: tm.sub2 = null
        onChose: tm.finish()
    }
    Sheet {
        id: s2
        handle: tm.sub2
        wantLeft: s1.cardRight - 6
        wantTop: tm.sub2Y - 6
        leftOf: s1.cardX
        onChose: tm.finish()
    }
}
