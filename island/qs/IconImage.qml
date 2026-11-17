import QtQuick
Image {
    property real implicitSize: 0
    property bool asynchronous: true
    implicitWidth: implicitSize; implicitHeight: implicitSize
    sourceSize.width: width; sourceSize.height: height
    fillMode: Image.PreserveAspectFit
}
