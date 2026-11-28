pragma Singleton
import QtQuick
import Quickshell
// Pipewire на Windows: одно устройство — динамики Windows, громкость через pycaw (host.py).
// Ползунок пишет сюда, а раз в две секунды подтягиваем то, что сменили клавишами или в Windows.
QtObject {
    id: pw
    property bool ready: true
    property bool syncing: false
    // Через var: у настоящего Quickshell (по нему смотрит qmllint) этих двух вызовов нет, они есть только в host.py.
    readonly property var host: Quickshell
    property QtObject defaultAudioSink: QtObject {
        property string name: "default"; property string description: "Динамики"
        property bool isSink: true; property bool isStream: false; property var properties: ({})
        property QtObject audio: QtObject {
            id: sinkAudio
            property real volume: 0.5
            property bool muted: false
            property var volumes: [volume]
            onVolumeChanged: if (!pw.syncing) pw.host.setSystemVolume(volume, muted)
            onMutedChanged: if (!pw.syncing) pw.host.setSystemVolume(volume, muted)
        }
    }
    property QtObject defaultAudioSource: null
    property var nodes: ({ values: [] })
    function pull() {
        const got = host.systemVolume()
        if (!got || got.length < 2) return
        const a = sinkAudio
        syncing = true
        if (Math.abs(a.volume - got[0]) > 0.005) a.volume = got[0]
        if (a.muted !== got[1]) a.muted = got[1]
        syncing = false
    }
    property Timer poll: Timer { interval: 2000; running: true; repeat: true; triggeredOnStart: true; onTriggered: pw.pull() }
}
