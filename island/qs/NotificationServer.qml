import QtQuick
// Уведомления на Windows показывает сама система; сервер-заглушка ничего не принимает.
QtObject {
    property bool bodySupported; property bool bodyMarkupSupported; property bool bodyHyperlinksSupported
    property bool bodyImagesSupported; property bool actionsSupported; property bool actionIconsSupported
    property bool imageSupported; property bool persistenceSupported; property bool keepOnReload; property bool inlineReplySupported
    property var trackedNotifications: ({ values: [] })
    signal notification(var n)
}
