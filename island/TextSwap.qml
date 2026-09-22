// put `TextSwap on text {}` on a Text: a new text fades out the old one and fades itself in
import QtQuick

Behavior {
    id: sw
    enabled: JD.animOn
    SequentialAnimation {
        NumberAnimation { target: sw.targetProperty.object; property: "opacity"; to: 0; duration: 70; easing.type: Easing.InQuad }
        PropertyAction {}
        NumberAnimation { target: sw.targetProperty.object; property: "opacity"; to: 1; duration: 170; easing.type: Easing.OutCubic }
    }
}
