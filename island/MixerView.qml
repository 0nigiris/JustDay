// Микшер: громкость всего, что звучит, в одном месте.
//
// Зачем он, если громкость программы уже есть в доке. В доке она под рукой ровно у той программы,
// на значок которой нажали, — и это правильный путь, когда мешает один конкретный Discord. Но
// «убавь всё, кроме игры» из дока не делается: надо обойти значки по одному, а половина звучащего
// в доке и не стоит — у браузерной вкладки нет своего значка вовсе. Микшер показывает всё сразу:
// выход, микрофон и каждый ручей, который сейчас играет.
//
// Что здесь наше, а что системы. Наше — только вид: ползунки, имена, порядок. Сама громкость живёт
// в PipeWire, на каждом узле своя, и мы её не храним и не пересчитываем — читаем и пишем. Поэтому
// то же самое, сделанное из pavucontrol или из плазмы, видно здесь сразу, и наоборот.
import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Services.Pipewire

Item {
    id: mx

    // Всё, что сейчас играет: ручьи программ, без записи с микрофона.
    readonly property var streams: Pipewire.nodes.values.filter(n => n && n.isStream && !n.isSink && n.audio)
    // И то, что пишет: звонок в дискорде должно быть видно там же, где всё остальное.
    readonly property var inputs: Pipewire.nodes.values.filter(n => n && n.isStream && n.isSink && n.audio)
    readonly property var sink: Pipewire.defaultAudioSink
    readonly property var source: Pipewire.defaultAudioSource

    // Без этого свойства узлов мертвы: PipeWire отдаёт их по подписке, а не по запросу.
    PwObjectTracker { objects: [...mx.streams, ...mx.inputs, mx.sink, mx.source].filter(n => !!n) }

    function nameOf(node) {
        if (!node) return ""
        const p = node.properties || ({})
        return p["application.name"] || p["media.name"] || node.description || node.name || ""
    }
    function noteOf(node) {
        if (!node) return ""
        const p = node.properties || ({})
        const what = p["media.name"] || ""
        const who = p["application.name"] || ""
        return what && what !== who ? what : (p["application.process.binary"] || "")
    }
    function iconOf(node) {
        if (!node) return "volume-2"
        const p = node.properties || ({})
        return p["application.icon_name"] || p["application.process.binary"] || "volume-2"
    }

    // ───────────── одна строка микшера ─────────────
    //
    // Ползунок отдаёт значение сразу, без пружин: звук правят на слух, и задержка между рукой и
    // громкостью тут недопустима — руку ведут по тому, что слышно.
    component Lane: Rectangle {
        id: lane
        property var node: null
        property string title: ""
        property string note: ""
        property string glyph: "volume-2"
        property bool strong: false        // выход и микрофон — крупнее прочих
        property color tint: JD.accentBlue

        readonly property real value: node && node.audio ? node.audio.volume : 0
        readonly property bool silent: !!node && !!node.audio && node.audio.muted

        Layout.fillWidth: true
        implicitHeight: strong ? 66 : 54
        radius: 14
        color: laneHover.hovered ? JD.fill1 : Qt.rgba(1, 1, 1, 0.04)
        Behavior on color { enabled: JD.animOn; ColorAnimation { duration: 130 } }
        HoverHandler { id: laneHover }

        function setVolume(v) {
            if (lane.node && lane.node.audio) lane.node.audio.volume = Math.max(0, Math.min(1.5, v))
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            spacing: 12

            // Значок глушения он же и значок источника: две кнопки на одно и то же — лишняя.
            Rectangle {
                Layout.alignment: Qt.AlignVCenter
                implicitWidth: lane.strong ? 38 : 32
                implicitHeight: implicitWidth
                radius: width / 2
                color: lane.silent ? Qt.rgba(1, 0.27, 0.23, 0.22) : JD.fill1
                Behavior on color { enabled: JD.animOn; ColorAnimation { duration: 130 } }
                Icon {
                    anchors.centerIn: parent
                    name: lane.silent ? "volume-x" : lane.glyph
                    fallback: lane.silent ? "volume-x" : "volume-2"
                    implicitSize: lane.strong ? 19 : 16
                    tint: lane.silent ? JD.accentRed : JD.text1
                    theme: !lane.silent && lane.glyph !== "volume-2" && lane.glyph !== "mic"
                }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler {
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: if (lane.node && lane.node.audio) lane.node.audio.muted = !lane.silent
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignVCenter
                spacing: lane.note ? 3 : 0

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Label1 {
                        Layout.fillWidth: true
                        font.pixelSize: lane.strong ? 14 : 13
                        color: lane.silent ? JD.text3 : JD.text1
                        text: lane.title
                    }
                    Label2 {
                        font.pixelSize: 12
                        font.features: ({ "tnum": 1 })
                        color: lane.silent ? JD.text3 : JD.text2
                        text: Math.round(lane.value * 100) + "%"
                    }
                }

                Label2 {
                    Layout.fillWidth: true
                    visible: !!lane.note && !!text
                    font.pixelSize: 11
                    color: JD.text3
                    text: JD.flat(lane.note)
                }

                // Дорожка во всю ширину строки: целиться в неё надо не глядя.
                Rectangle {
                    id: track
                    Layout.fillWidth: true
                    Layout.preferredHeight: lane.strong ? 7 : 5
                    radius: height / 2
                    color: Qt.rgba(1, 1, 1, 0.16)

                    Rectangle {
                        height: parent.height
                        radius: parent.radius
                        width: parent.width * Math.max(0, Math.min(1, lane.value))
                        color: lane.silent ? JD.text3 : lane.tint
                        Behavior on color { enabled: JD.animOn; ColorAnimation { duration: 130 } }
                    }
                    // Громче ста процентов — другим цветом: это уже усиление, и звучит оно
                    // соответственно. Молча дорисовывать полоску дальше было бы нечестно.
                    Rectangle {
                        height: parent.height
                        radius: parent.radius
                        visible: lane.value > 1
                        x: parent.width
                        width: parent.width * Math.max(0, Math.min(0.5, lane.value - 1))
                        color: JD.accentOrange
                    }
                    Rectangle {
                        width: lane.strong ? 15 : 13
                        height: width
                        radius: width / 2
                        color: "#ffffff"
                        y: (parent.height - height) / 2
                        x: Math.max(0, Math.min(parent.width - width,
                                    parent.width * Math.max(0, Math.min(1, lane.value)) - width / 2))
                    }

                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    DragHandler {
                        target: null
                        xAxis.enabled: true
                        yAxis.enabled: false
                        onCentroidChanged: if (active) lane.setVolume(centroid.position.x / track.width)
                    }
                    TapHandler {
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onSingleTapped: e => lane.setVolume(e.position.x / track.width)
                    }
                    // Колесом — по пять процентов: точность руки на узкой дорожке кончается
                    // примерно там же.
                    WheelHandler {
                        onWheel: event => {
                            lane.setVolume(lane.value + (event.angleDelta.y > 0 ? 0.05 : -0.05))
                            event.accepted = true
                        }
                    }
                }
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 10

        // ───────────── выход и микрофон ─────────────
        Lane {
            node: mx.sink
            strong: true
            glyph: "volume-2"
            tint: JD.accentBlue
            title: mx.sink ? (mx.sink.description || mx.sink.name || "Выход") : "Выхода нет"
            note: "Общая громкость — всё сразу"
        }
        Lane {
            node: mx.source
            strong: true
            glyph: "mic"
            tint: JD.accentCyan
            title: mx.source ? (mx.source.description || mx.source.name || "Микрофон") : "Микрофона нет"
            note: "Что слышат остальные"
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: Qt.rgba(1, 1, 1, 0.08)
        }

        // ───────────── кто сейчас звучит ─────────────
        //
        // Пусто — так и сказано словами. Пустой список без объяснения читается как поломка: не
        // видно, то ли ничего не играет, то ли микшер не нашёл звук вовсе.
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            Column {
                anchors.centerIn: parent
                spacing: 8
                visible: mx.streams.length === 0 && mx.inputs.length === 0
                Icon {
                    anchors.horizontalCenter: parent.horizontalCenter
                    name: "volume-x"
                    implicitSize: 26
                    tint: JD.text3
                }
                Label2 {
                    anchors.horizontalCenter: parent.horizontalCenter
                    color: JD.text3
                    text: "Сейчас никто не звучит"
                }
            }

            Flickable {
                anchors.fill: parent
                contentHeight: rows.implicitHeight
                clip: true
                interactive: contentHeight > height
                boundsBehavior: Flickable.StopAtBounds

                ColumnLayout {
                    id: rows
                    width: parent.width
                    spacing: 8

                    Repeater {
                        model: mx.streams
                        delegate: Lane {
                            required property var modelData
                            node: modelData
                            title: mx.nameOf(modelData)
                            note: mx.noteOf(modelData)
                            glyph: mx.iconOf(modelData)
                            tint: JD.accentPurple
                        }
                    }
                    Repeater {
                        model: mx.inputs
                        delegate: Lane {
                            required property var modelData
                            node: modelData
                            title: mx.nameOf(modelData)
                            note: "слушает микрофон"
                            glyph: "mic"
                            tint: JD.accentCyan
                        }
                    }
                }
            }
        }
    }
}
