pragma Singleton
import QtQuick
// Звук на Windows приходит от демона (pycaw); пока демона нет — тишина, но интерфейс не падает.
QtObject {
    property bool ready: true
    property QtObject defaultAudioSink: QtObject {
        property string name: "default"; property string description: "Динамики"
        property bool isSink: true; property bool isStream: false; property var properties: ({})
        property QtObject audio: QtObject { property real volume: 0.5; property bool muted: false; property var volumes: [volume] }
    }
    property QtObject defaultAudioSource: null
    property var nodes: ({ values: [] })
}
