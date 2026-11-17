import QtQuick
// ponytail: «никогда не простаивает»; на Windows — GetLastInputInfo, когда понадобится присутствие.
QtObject { property bool enabled: true; property real timeout; property bool respectInhibitors; property bool isIdle: false }
