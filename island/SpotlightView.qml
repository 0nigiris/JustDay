// Spotlight: поиск по всему сразу, клавишей и с клавиатуры.
//
// Это не уменьшенный «Пуск». Пуск открывают, чтобы посмотреть, что вообще есть, — там разделы,
// плитки и полка питания. Spotlight открывают, уже зная, что нужно: нажал, напечатал три буквы,
// Enter. Всё остальное на этой поверхности лишнее, и поэтому его здесь нет.
//
// Но когда запрос пуст (Р2-5): показываем режим «Приложения» — закреплённые и недавние сверху, ниже сетка
// всех программ по разделам из того же каталога, что и меню. Переключатель категорий — сегменты
// сверху, как у Tahoe. Стрелки и Enter работают по сетке.
//
// Правила, которым подчинён этот вид:
//   — поле ввода стоит на месте и не шевелится, когда меняются находки: прыгающая строка под
//     пальцами — худшее, что может сделать поиск;
//   — карточка растёт вниз от своего верхнего края, а не из середины: верх прибит, низ едет;
//   — выбор — это логика, а не картинка: он меняется мгновенно, пружина только догоняет подсветку;
//   — находки сгруппированы по роду (программы, окна, файлы), потому что искать глазами в
//     перемешанном списке дольше, чем прочитать подпись.
import QtQuick
import QtQuick.Layouts

Item {
    id: sp

    readonly property var rows: JD.menuFound || []
    readonly property bool asking: JD.menuSearching && rows.length === 0
    // Режим «Приложения» в Spotlight: пустой запрос в режиме поиска
    readonly property bool appsMode: JD.menuSearchMode && !JD.menuSearching

    function appsByKeys(keys) {
        const by = {}
        for (const a of (JD.menuCatalog.apps || [])) by[a.kind + ":" + a.id] = a
        return (keys || []).map(k => by[k]).filter(a => a !== undefined)
    }
    // Закреплённые — настоящие, а не запасной вариант лаунчера (`pinned` при пустом избранном
    // подставляет недавние, и тогда обе полосы показали бы одно и то же).
    readonly property var favApps: appsByKeys(JD.menuCatalog.favourites).slice(0, 8)
    readonly property var recentApps: {
        const fav = JD.menuCatalog.favourites || []
        return appsByKeys((JD.menuCatalog.recent || []).filter(k => fav.indexOf(k) < 0)).slice(0, 8)
    }

    // Приложения по категориям для режима приложений
    readonly property var appsByCategory: {
        const apps = JD.menuCatalog.apps || []
        const groups = JD.menuCatalog.groups || []
        const cats = {}
        for (const a of apps) {
            const cat = a.cat || "tools"
            if (!cats[cat]) cats[cat] = []
            cats[cat].push(a)
        }
        // Сортируем внутри категории по имени
        for (const cat in cats) {
            cats[cat].sort((a, b) => (a.name || "").localeCompare(b.name || ""))
        }
        // Порядок категорий из menuCatalog.groups
        const ordered = []
        for (const g of groups) {
            if (cats[g.id] && cats[g.id].length > 0) {
                ordered.push({ id: g.id, name: g.name, icon: g.icon, apps: cats[g.id] })
            }
        }
        // Остальные категории, которых нет в groups
        for (const cat in cats) {
            if (!groups.some(g => g.id === cat) && cats[cat].length > 0) {
                ordered.push({ id: cat, name: cat, icon: "folder", apps: cats[cat] })
            }
        }
        return ordered
    }

    property int catIndex: 0
    readonly property var currentCategory: appsByCategory[Math.min(catIndex, appsByCategory.length - 1)]
    readonly property int tileW: 86
    readonly property int cols: 8

    // Ряды режима «Приложения»: закреплённые, недавние, переключатель категорий, сетка рядами по
    // `cols`. `base` — сквозной номер первой плитки ряда, он же то, что лежит в JD.menuPick.
    readonly property var appRows: {
        const out = []
        let base = 0
        const add = (caption, apps) => {
            for (let i = 0; i < apps.length; i += cols)
                out.push({ caption: i === 0 ? caption : "", apps: apps.slice(i, i + cols), base: base + i })
            base += apps.length
        }
        if (favApps.length) add(JD.tr("Закреплённые"), favApps)
        if (recentApps.length) add(JD.tr("Недавние"), recentApps)
        if (appsByCategory.length > 1) out.push({ caption: "", pills: true })
        if (currentCategory) add(appsByCategory.length > 1 ? "" : currentCategory.name, currentCategory.apps)
        return out
    }
    readonly property var tileRows: appRows.filter(r => !!r.apps)
    readonly property int tileCount: tileRows.reduce((n, r) => n + r.apps.length, 0)

    function tileAt(flat) {
        for (const r of tileRows)
            if (flat >= r.base && flat < r.base + r.apps.length) return r.apps[flat - r.base]
        return undefined
    }
    // Вверх-вниз — по рядам, влево-вправо — по плиткам. В короткий ряд попадаем в его последнюю плитку.
    function moveApps(dRow, dCol) {
        if (!tileCount) return
        if (dCol) { JD.menuPick = Math.max(0, Math.min(tileCount - 1, JD.menuPick + dCol)); return }
        let r = tileRows.findIndex(t => JD.menuPick >= t.base && JD.menuPick < t.base + t.apps.length)
        const col = r < 0 ? 0 : JD.menuPick - tileRows[r].base
        r = Math.max(0, Math.min(tileRows.length - 1, (r < 0 ? 0 : r) + dRow))
        JD.menuPick = tileRows[r].base + Math.min(col, tileRows[r].apps.length - 1)
    }
    // Выбранная плитка не должна уезжать за край прокручиваемой области.
    function reveal() {
        const r = tileRows.findIndex(t => JD.menuPick >= t.base && JD.menuPick < t.base + t.apps.length)
        const it = r < 0 ? null : rowsRep.itemAt(appRows.indexOf(tileRows[r]))
        if (!it) return
        const top = it.y + appsColumn.y, bottom = top + it.height
        if (top < appsFlick.contentY) appsFlick.contentY = Math.max(0, top - 8)
        else if (bottom > appsFlick.contentY + appsFlick.height) appsFlick.contentY = bottom - appsFlick.height + 8
    }
    Connections {
        target: JD
        function onMenuPickChanged() { if (sp.appsMode) sp.reveal() }
    }

    component AppTile: Pressable {
        id: tile
        required property var app
        required property int at
        readonly property bool on: at === JD.menuPick
        width: sp.tileW
        height: 84
        radius: 12
        pressScale: JD.pressScaleSmall
        color: on ? Qt.rgba(1, 1, 1, 0.10) : (hovered ? JD.menuFill1 : "transparent")
        Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
        Accessible.role: Accessible.Button
        Accessible.name: app.name
        onHoveredChanged: if (hovered) JD.menuPick = at
        onClicked: JD.runFromMenu(app)
        // Правой кнопкой — закрепить в доке или снять (Р2-6)
        TapHandler {
            acceptedButtons: Qt.RightButton
            gesturePolicy: TapHandler.ReleaseWithinBounds
            onTapped: JD.pinFromMenu(tile.app)
        }
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 8
            spacing: 6
            Icon {
                Layout.alignment: Qt.AlignHCenter
                name: tile.app.icon
                fallback: "application-x-executable"
                implicitSize: 36
                renderSize: 72
                theme: true
            }
            Label2 {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: 11
                color: JD.text1
                elide: Text.ElideRight
                text: tile.app.name
            }
        }
    }

    // Плоский список: подписи групп и сами находки вперемешку, по порядку. Высота у строк разная,
    // поэтому ListView, а не сетка: сетке все ячейки нужны одного роста.
    readonly property var lines: {
        const out = []
        let was = ""
        for (let i = 0; i < rows.length; i++) {
            const kind = String(rows[i].kind || "")
            if (kind !== was) {
                out.push({ caption: sp.groupName(kind) })
                was = kind
            }
            out.push({ row: rows[i], at: i })
        }
        return out
    }

    function groupName(kind) {
        return kind === "app" ? JD.tr("Программы")
             : kind === "game" ? JD.tr("Игры")
             : kind === "window" ? JD.tr("Открытые окна")
             : kind === "file" ? JD.tr("Файлы")
             : kind === "link" ? JD.tr("Ссылка")
             : kind === "calc" ? JD.tr("Калькулятор")
             : JD.tr("Другое")
    }

    // Подсказки для полки (как в MenuView.mv.hintFor)
    property string hint: ""
    function hintFor(on, text) { if (on) hint = text; else if (hint === text) hint = "" }

    // Имя действия, которое ждёт второго щелчка (для питания)
    readonly property string askingName: {
        if (!JD.menuConfirm) return ""
        const rows = JD.sessionActions
        for (let i = 0; i < rows.length; ++i)
            if (rows[i].id === JD.menuConfirm)
                return rows[i].name
        return ""
    }

    // Высота: строка поиска плюс находки, но не выше предела. Её читает карточка в shell.qml —
    // поверхность растёт вниз ровно настолько, насколько есть что показать.
    readonly property int barHeight: 76
    readonly property int maxHeight: 760
    implicitWidth: 720
    implicitHeight: appsMode && tileCount ? barHeight + 520 : Math.min(maxHeight, barHeight + (list.count ? Math.min(list.contentHeight + 12, maxHeight - barHeight) : (asking ? 92 : 0)))

    function move(step) {
        if (appsMode) { moveApps(step, 0); return }
        if (!rows.length) return
        JD.menuPick = Math.max(0, Math.min(rows.length - 1, JD.menuPick + step))
    }
    function take() {
        if (asking) { JD.askFromMenu(JD.menuQuery); return }
        if (appsMode) JD.runFromMenu(tileAt(JD.menuPick))
        else JD.runFromMenu(rows[JD.menuPick] || rows[0])
    }

    // Открыли клавишей — значит печатать можно сразу, не целясь мышью в строку.
    Component.onCompleted: field.forceActiveFocus()
    Connections {
        target: JD
        function onMenuSerialChanged() { field.forceActiveFocus() }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ───────────── строка поиска ─────────────
        //
        // Без своей подложки и без рамки: подложка внутри подложки — это две рамки на одном окне,
        // а здесь всё окно и есть поле ввода.
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: sp.barHeight

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                spacing: 14

                Icon {
                    name: "search"
                    implicitSize: 26
                    tint: JD.text1
                    opacity: 0.58
                    scale: field.activeFocus ? 1.04 : 1
                    Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                }

                TextInput {
                    id: field
                    Layout.fillWidth: true
                    font.family: JD.fontFamily
                    font.pixelSize: 28
                    color: JD.text1
                    selectByMouse: true
                    selectionColor: JD.accentBlue
                    clip: true
                    text: JD.menuQuery
                    onTextChanged: if (text !== JD.menuQuery) { JD.menuQuery = text; JD.menuPick = 0; later.restart() }
                    Keys.onPressed: (e) => {
                        switch (e.key) {
                        // Первый Escape стирает набранное, второй закрывает. Так ошибку в запросе
                        // можно исправить, не открывая поиск заново.
                        case Qt.Key_Escape:
                            if (field.text) { JD.menuQuery = ""; JD.menuFound = []; JD.menuPick = 0; JD.searchMenu() }
                            else JD.closeMenu()
                            break
                        case Qt.Key_Down: sp.move(1); break
                        case Qt.Key_Up: sp.move(-1); break
                        case Qt.Key_PageDown: sp.move(5); break
                        case Qt.Key_PageUp: sp.move(-5); break
                        // Влево-вправо ходят по плиткам, пока поле пусто; с текстом это курсор.
                        case Qt.Key_Left: if (!sp.appsMode) return; sp.moveApps(0, -1); break
                        case Qt.Key_Right: if (!sp.appsMode) return; sp.moveApps(0, 1); break
                        case Qt.Key_Home: JD.menuPick = 0; break
                        case Qt.Key_End: JD.menuPick = Math.max(0, (sp.appsMode ? sp.tileCount : sp.rows.length) - 1); break
                        case Qt.Key_Return:
                        case Qt.Key_Enter: sp.take(); break
                        default: return
                        }
                        e.accepted = true
                    }
                    // Поиск не на каждую букву: пока печатают быстро, спрашивать демона незачем.
                    Timer { id: later; interval: 40; onTriggered: JD.searchMenu() }
                    Text {
                        anchors.fill: parent
                        verticalAlignment: Text.AlignVCenter
                        visible: !field.text
                        font: field.font
                        color: JD.text1
                        opacity: 0.42
                        text: JD.tr("Поиск")
                    }
                }

            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            visible: (list.count > 0 || sp.asking) && !sp.appsMode
            color: Qt.rgba(1, 1, 1, 0.07)
        }

        // ───────────── режим «Приложения» (пустой запрос в Spotlight) ─────────────
        //
        // Сверху закреплённые («избранное» старого меню), под ними недавние, ниже — сетка программ
        // выбранной категории. Всё это — один список плиток с сквозным номером (`JD.menuPick`), так что
        // стрелки и Enter ходят по нему целиком, а не по трём разным спискам.
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: sp.appsMode

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                Flickable {
                    id: appsFlick
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    contentWidth: width
                    contentHeight: appsColumn.height + 24
                    boundsBehavior: Flickable.StopAtBounds

                    Column {
                        id: appsColumn
                        x: 16
                        y: 8
                        width: parent.width - 32
                        spacing: 6

                        Repeater {
                            id: rowsRep
                            model: sp.appRows
                            delegate: Column {
                                id: rowItem
                                required property var modelData
                                width: appsColumn.width
                                spacing: 4

                                Label2 {
                                    visible: !!rowItem.modelData.caption
                                    topPadding: 6
                                    leftPadding: 4
                                    color: JD.text3
                                    font.pixelSize: 11
                                    font.weight: Font.DemiBold
                                    font.capitalization: Font.AllUppercase
                                    font.letterSpacing: 0.6
                                    text: rowItem.modelData.caption || ""
                                }

                                // Переключатель категорий сетки
                                Flow {
                                    visible: !!rowItem.modelData.pills
                                    width: parent.width
                                    spacing: 6
                                    Repeater {
                                        model: rowItem.modelData.pills ? sp.appsByCategory : []
                                        delegate: Pressable {
                                            id: catBtn
                                            required property var modelData
                                            required property int index
                                            readonly property bool current: index === sp.catIndex
                                            implicitWidth: Math.max(64, catLabel.implicitWidth + 28)
                                            implicitHeight: 28
                                            radius: 14
                                            pressScale: JD.pressScaleSmall
                                            color: current ? JD.accentBlue : (hovered ? JD.menuFill1 : "transparent")
                                            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                                            Accessible.role: Accessible.Button
                                            Accessible.name: modelData.name
                                            Label2 {
                                                id: catLabel
                                                anchors.centerIn: parent
                                                font.pixelSize: 12
                                                color: catBtn.current ? JD.text1 : JD.text3
                                                text: catBtn.modelData.name
                                            }
                                            onClicked: sp.catIndex = index
                                        }
                                    }
                                }

                                Row {
                                    visible: !!rowItem.modelData.apps
                                    spacing: 0
                                    Repeater {
                                        model: rowItem.modelData.apps || []
                                        delegate: AppTile {
                                            required property var modelData
                                            required property int index
                                            app: modelData
                                            at: rowItem.modelData.base + index
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                Item {
                    visible: sp.appsMode
                    Layout.fillWidth: true
                    Layout.preferredHeight: 40

                    Rectangle {
                        anchors { left: parent.left; right: parent.right; top: parent.top }
                        height: 1
                        color: Qt.rgba(1, 1, 1, 0.08)
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.topMargin: 6
                        spacing: 4

                        Pressable {
                            id: volDot
                            property string icon: "volume-2"
                            property string note: "Звук"
                            implicitWidth: 30
                            implicitHeight: 30
                            radius: 15
                            pressScale: JD.pressScaleSmall
                            color: hovered ? JD.menuFill3 : "transparent"
                            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                            onClicked: { JD.closeMenu(); JD.openTools("mixer") }
                            HoverHandler { cursorShape: Qt.PointingHandCursor; onHoveredChanged: sp.hintFor(hovered, parent.note) }
                            Icon { anchors.centerIn: parent; name: parent.icon; implicitSize: 16; tint: parent.hovered ? JD.text1 : JD.text3 }
                        }
                        Pressable {
                            id: emojiDot
                            property string icon: "face-smile"
                            property string note: "Эмодзи"
                            implicitWidth: 30
                            implicitHeight: 30
                            radius: 15
                            pressScale: JD.pressScaleSmall
                            color: hovered ? JD.menuFill3 : "transparent"
                            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                            onClicked: { JD.closeMenu(); JD.openTools("emoji") }
                            HoverHandler { cursorShape: Qt.PointingHandCursor; onHoveredChanged: sp.hintFor(hovered, parent.note) }
                            Icon { anchors.centerIn: parent; name: parent.icon; implicitSize: 16; tint: parent.hovered ? JD.text1 : JD.text3 }
                        }
                        Pressable {
                            id: clipDot
                            property string icon: "clipboard"
                            property string note: "Буфер обмена"
                            implicitWidth: 30
                            implicitHeight: 30
                            radius: 15
                            pressScale: JD.pressScaleSmall
                            color: hovered ? JD.menuFill3 : "transparent"
                            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                            onClicked: { JD.closeMenu(); JD.openTools("clip") }
                            HoverHandler { cursorShape: Qt.PointingHandCursor; onHoveredChanged: sp.hintFor(hovered, parent.note) }
                            Icon { anchors.centerIn: parent; name: parent.icon; implicitSize: 16; tint: parent.hovered ? JD.text1 : JD.text3 }
                        }
                        Pressable {
                            id: loadDot
                            property string icon: "cpu"
                            property string note: "Нагрузка машины"
                            implicitWidth: 30
                            implicitHeight: 30
                            radius: 15
                            pressScale: JD.pressScaleSmall
                            color: hovered ? JD.menuFill3 : "transparent"
                            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                            onClicked: { JD.closeMenu(); JD.openTools("load") }
                            HoverHandler { cursorShape: Qt.PointingHandCursor; onHoveredChanged: sp.hintFor(hovered, parent.note) }
                            Icon { anchors.centerIn: parent; name: parent.icon; implicitSize: 16; tint: parent.hovered ? JD.text1 : JD.text3 }
                        }

                        Label2 {
                            Layout.fillWidth: true
                            Layout.leftMargin: 8
                            font.pixelSize: 12
                            elide: Text.ElideRight
                            color: sp.askingName ? JD.accentRed : JD.text3
                            text: sp.askingName ? sp.askingName + "  ·  нажмите ещё раз"
                                    : (sp.hint || (JD.menuUser.name ? JD.menuUser.name + (JD.menuUser.host ? "  ·  " + JD.menuUser.host : "") : ""))
                            opacity: (sp.askingName || sp.hint) ? 1 : 0.55
                            Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                        }

                        Pressable {
                            property string icon: JD.serverMode ? "sun" : "moon"
                            property string note: JD.serverMode ? "Вернуть машину" : "Режим сервера"
                            implicitWidth: 30
                            implicitHeight: 30
                            radius: 15
                            pressScale: JD.pressScaleSmall
                            color: JD.serverMode ? (hovered ? "#3a5a3a" : "#2d4a2d") : (hovered ? JD.menuFill3 : "transparent")
                            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                            onClicked: { JD.closeMenu(); JD.toggleServerMode() }
                            HoverHandler { cursorShape: Qt.PointingHandCursor; onHoveredChanged: sp.hintFor(hovered, parent.note) }
                            Icon { anchors.centerIn: parent; name: parent.icon; implicitSize: 16; tint: parent.hovered ? JD.text1 : JD.text3 }
                        }
                        Pressable {
                            property string icon: "refresh-cw"
                            property string note: "Проверить обновление"
                            implicitWidth: 30
                            implicitHeight: 30
                            radius: 15
                            pressScale: JD.pressScaleSmall
                            color: hovered ? JD.menuFill3 : "transparent"
                            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                            onClicked: { JD.closeMenu(); JD.checkUpdate() }
                            HoverHandler { cursorShape: Qt.PointingHandCursor; onHoveredChanged: sp.hintFor(hovered, parent.note) }
                            Icon { anchors.centerIn: parent; name: parent.icon; implicitSize: 16; tint: parent.hovered ? JD.text1 : JD.text3 }
                        }
                        Pressable {
                            property string icon: "settings"
                            property string note: "Настройки"
                            implicitWidth: 30
                            implicitHeight: 30
                            radius: 15
                            pressScale: JD.pressScaleSmall
                            color: hovered ? JD.menuFill3 : "transparent"
                            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                            onClicked: { JD.closeMenu(); JD.openSettings("general") }
                            HoverHandler { cursorShape: Qt.PointingHandCursor; onHoveredChanged: sp.hintFor(hovered, parent.note) }
                            Icon { anchors.centerIn: parent; name: parent.icon; implicitSize: 16; tint: parent.hovered ? JD.text1 : JD.text3 }
                        }
                        Pressable {
                            property string icon: "sliders-horizontal"
                            property string note: "Настройки системы (KDE)"
                            implicitWidth: 30
                            implicitHeight: 30
                            radius: 15
                            pressScale: JD.pressScaleSmall
                            color: hovered ? JD.menuFill3 : "transparent"
                            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                            onClicked: { JD.closeMenu(); JD.systemSettings("") }
                            HoverHandler { cursorShape: Qt.PointingHandCursor; onHoveredChanged: sp.hintFor(hovered, parent.note) }
                            Icon { anchors.centerIn: parent; name: parent.icon; implicitSize: 16; tint: parent.hovered ? JD.text1 : JD.text3 }
                        }

                        Repeater {
                            model: JD.sessionActions
                            delegate: Pressable {
                                id: pow
                                required property var modelData
                                readonly property bool asking: JD.menuConfirm === modelData.id
                                implicitWidth: 30
                                implicitHeight: 30
                                radius: 15
                                pressScale: JD.pressScaleSmall
                                color: asking ? JD.accentRed : (pow.hovered ? JD.menuFill3 : "transparent")
                                Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                                Icon {
                                    anchors.centerIn: parent
                                    name: pow.modelData.icon
                                    implicitSize: 15
                                    tint: pow.asking || pow.hovered ? JD.text1 : JD.text3
                                }
                                onHoveredChanged: sp.hintFor(hovered, pow.modelData.danger ? pow.modelData.name + "  ·  нажать дважды"
                                                                                    : pow.modelData.name)
                                onClicked: JD.sessionDo(pow.modelData.id, pow.modelData.danger)
                            }
                        }
                    }
                }
            }
        }


        // ───────────── ничего не нашлось ─────────────
        //
        // Пустой поиск — не тупик: то, что мы не нашли, может знать ассистент.
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: sp.asking ? 90 : 0
            visible: sp.asking && !sp.appsMode
            Column {
                anchors.centerIn: parent
                spacing: 6
                Label1 {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: JD.tr("Ничего не нашлось")
                }
                Label2 {
                    anchors.horizontalCenter: parent.horizontalCenter
                    color: JD.text3
                    text: JD.tr("Enter — спросить ") + JD.assistantName
                }
            }
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !sp.asking && !sp.appsMode
            clip: true
            model: sp.lines
            boundsBehavior: Flickable.StopAtBounds
            currentIndex: {
                for (let i = 0; i < sp.lines.length; i++)
                    if (sp.lines[i].row && sp.lines[i].at === JD.menuPick) return i
                return -1
            }
            onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)
            // Одна подсветка на весь список, а не своя у каждой строки: раньше старая
            // гасла, новая зажигалась, и выбор прыгал (Р2-18). Теперь она едет за ним.
            highlightFollowsCurrentItem: true
            highlightMoveDuration: JD.animOn ? JD.durFast : 0
            highlightResizeDuration: 0
            highlight: Item {
                Rectangle {
                    anchors { fill: parent; leftMargin: 12; rightMargin: 12; topMargin: 2; bottomMargin: 2 }
                    radius: 14
                    color: Qt.rgba(1, 1, 1, 0.10)
                }
            }
            topMargin: 6
            bottomMargin: 6

            delegate: Item {
                id: line
                required property var modelData
                readonly property bool caption: !!modelData.caption
                readonly property var row: modelData.row || ({})
                readonly property bool on: !caption && modelData.at === JD.menuPick
                width: ListView.view.width
                height: caption ? 28 : 68

                Label2 {
                    visible: line.caption
                    anchors { left: parent.left; leftMargin: 26; bottom: parent.bottom; bottomMargin: 4 }
                    text: line.modelData.caption || ""
                    color: JD.text3
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                    font.capitalization: Font.AllUppercase
                    font.letterSpacing: 0.6
                }

                Rectangle {
                    visible: !line.caption
                    anchors { fill: parent; leftMargin: 12; rightMargin: 12; topMargin: 2; bottomMargin: 2 }
                    radius: 14
                    color: !line.on && hover.hovered ? Qt.rgba(1, 1, 1, 0.05) : "transparent"
                    Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                    scale: line.on ? 1.015 : 1
                    Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        spacing: 14

                        Item {
                            implicitWidth: 44
                            implicitHeight: 44
                            Icon {
                                anchors.centerIn: parent
                                name: line.row.icon || "application-x-executable"
                                fallback: "application-x-executable"
                                implicitSize: 40
                                renderSize: 96
                                // Значок самой программы, как в Пуске. Без этого признака весь список
                                // выглядел одинаковыми пустыми окошками: наше запасное имя
                                // application-x-executable само есть в штриховом наборе и перебивало
                                // настоящий значок — Spotlight отделился от Пуска и потерял это.
                                theme: true
                            }
                            // Открытое окно отмечено точкой: запускать второй раз его не надо.
                            Rectangle {
                                visible: line.row.kind === "window"
                                anchors { right: parent.right; bottom: parent.bottom }
                                implicitWidth: 8; implicitHeight: 8; radius: 4
                                color: JD.accentBlue
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1
                            Label1 {
                                Layout.fillWidth: true
                                text: line.row.name || ""
                                font.pixelSize: 17
                                font.weight: line.on ? Font.DemiBold : Font.Medium
                                elide: Text.ElideRight
                            }
                            Label2 {
                                Layout.fillWidth: true
                                visible: !!line.row.sub
                                text: line.row.sub || ""
                                font.pixelSize: 13
                                color: JD.text3
                                opacity: 0.8
                                elide: Text.ElideMiddle
                            }
                        }

                        Label2 {
                            visible: line.on
                            text: "Enter"
                            color: JD.text3
                            opacity: 0.55
                            font.pixelSize: 12
                        }
                    }

                    HoverHandler {
                        id: hover
                        cursorShape: Qt.PointingHandCursor
                        onHoveredChanged: if (hovered) JD.menuPick = line.modelData.at
                    }
                    TapHandler {
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: { JD.menuPick = line.modelData.at; sp.take() }
                    }
                }
            }
        }
    }
}
