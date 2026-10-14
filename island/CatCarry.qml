// Вынесено из shell.qml (Р-80).
import QtQuick

// Кошку на сплошной полосе переносят рукой, как значки в доке: от часов к трею и обратно.
// Сама кошка остаётся на месте полупрозрачной, рядом с рукой едет её копия (catGhost), а
// куда она ляжет — решает отпускание, и выбор запоминается в island.cat_place.
DragHandler {
    property Item cat
    target: null
    enabled: JD.islandStyle === "bar"
    cursorShape: active ? Qt.ClosedHandCursor : Qt.PointingHandCursor
    onActiveChanged: {
        if (active) { JD.catTipAt = null; JD.catFrom = cat }
        else JD.catDrop()
    }
    onCentroidChanged: if (active) JD.catHand = centroid.scenePosition
}
