// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Wayland

// ───────────── меню значка лотка ─────────────
//
// Своё окно во весь экран, а не часть полосы: меню обязано закрываться щелчком мимо, а «мимо» —
// это весь остальной экран. Пункты приходят от самой программы (DBusMenu), рисуем их мы:
// системное меню Quickshell показывает только в режиме QApplication, и раньше правая кнопка в
// лотке молчала именно поэтому.
PanelWindow {
    id: trayMenuWin
    readonly property bool open: !!JD.trayMenu
    visible: open
    // IPC (trayRows / traySub) спрашивает само меню, а оно живёт внутри этого окна.
    readonly property alias menu: trayMenu
    anchors { top: true; bottom: true; left: true; right: true }
    exclusionMode: ExclusionMode.Ignore
    exclusiveZone: 0
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "justday-traymenu"
    // Меню забирает клавиатуру, пока открыто: Escape должен его закрывать, как закрывает любое
    // меню, а без фокуса до нас не доходит ни одна клавиша.
    WlrLayershell.keyboardFocus: open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    color: "transparent"

    MouseArea {
        id: trayMenuBackdrop
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: JD.closeTrayMenu()
    }
    Shortcut { sequence: "Escape"; enabled: trayMenuWin.open; onActivated: JD.closeTrayMenu() }

    // Дырка по полосе лотка — та же, что у меню приложений. Без неё полоса под перекрытием
    // становится картинкой: значки видно, а единственное, что делает щелчок по ним, — закрывает
    // меню. А человек, открыв меню не того значка, щёлкает именно по соседнему.
    Item {
        id: trayMenuHole
        visible: false
        readonly property var r: JD.trayRect
        x: r && r.live ? r.x : 0
        y: r && r.live ? r.y : 0
        width: r && r.live ? r.w : 0
        height: r && r.live ? r.h : 0
    }
    mask: Region {
        item: trayMenuWin.open ? trayMenuBackdrop : null
        Region { item: trayMenuHole; intersection: Intersection.Subtract }
    }

    // Frosted glass under the menu card, same chrome as dock/tray (armed after open settle).
    property bool blurLive: false
    onOpenChanged: {
        if (open) {
            blurLive = false
            trayMenuBlurArm.restart()
        } else {
            trayMenuBlurArm.stop()
            blurLive = false
        }
    }
    Timer {
        id: trayMenuBlurArm
        interval: JD.dur(140) + 16
        onTriggered: trayMenuWin.blurLive = trayMenuWin.open
    }
    // По региону на каждую раскрытую карточку, а не один общий прямоугольник: подменю сдвинуто вбок
    // и вниз, и рамка вокруг всех карточек размывала пустой экран вокруг меню («блюр вылетел из экрана»).
    BackgroundEffect.blurRegion: Region {
        Region {
            x: Math.round(trayMenu.sheet0.cardX); y: Math.round(trayMenu.sheet0.cardY)
            width: trayMenuWin.blurLive && JD.blurOn && trayMenu.sheet0.visible ? Math.round(trayMenu.sheet0.cardW) : 0
            height: trayMenuWin.blurLive && JD.blurOn && trayMenu.sheet0.visible ? Math.round(trayMenu.sheet0.cardH) : 0
            radius: 14
        }
        Region {
            x: Math.round(trayMenu.sheet1.cardX); y: Math.round(trayMenu.sheet1.cardY)
            width: trayMenuWin.blurLive && JD.blurOn && trayMenu.sheet1.visible ? Math.round(trayMenu.sheet1.cardW) : 0
            height: trayMenuWin.blurLive && JD.blurOn && trayMenu.sheet1.visible ? Math.round(trayMenu.sheet1.cardH) : 0
            radius: 14
        }
        Region {
            x: Math.round(trayMenu.sheet2.cardX); y: Math.round(trayMenu.sheet2.cardY)
            width: trayMenuWin.blurLive && JD.blurOn && trayMenu.sheet2.visible ? Math.round(trayMenu.sheet2.cardW) : 0
            height: trayMenuWin.blurLive && JD.blurOn && trayMenu.sheet2.visible ? Math.round(trayMenu.sheet2.cardH) : 0
            radius: 14
        }
    }
    TrayMenu {
        id: trayMenu
        anchors.fill: parent
        handle: JD.trayMenu ? JD.trayMenu.menu : null
        atX: JD.trayMenuX
        atY: JD.trayMenuY
        toLeft: JD.trayMenuFromBar || JD.trayPlace === "right"
        onDismissed: JD.closeTrayMenu()
    }
}
