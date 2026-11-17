import QtQuick
QtObject {
    id: c
    enum Precision { Hours, Minutes, Seconds }
    property int precision: SystemClock.Seconds
    property date date: new Date()
    readonly property int hours: date.getHours()
    readonly property int minutes: date.getMinutes()
    readonly property int seconds: date.getSeconds()
    property Timer _t: Timer { interval: 1000; running: true; repeat: true; onTriggered: c.date = new Date() }
}
