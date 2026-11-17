import QtQuick
// Как в Quickshell: по объекту на элемент модели, у объекта есть modelData.
QtObject {
    id: v
    property var model: []
    default property Component delegate
    property list<QtObject> instances
    property Instantiator _i: Instantiator {
        model: v.model
        delegate: v.delegate
        onObjectAdded: (i, o) => { const a = []; for (let k = 0; k < v.instances.length; ++k) a.push(v.instances[k]); a.splice(i, 0, o); v.instances = a }
        onObjectRemoved: (i, o) => { const a = []; for (let k = 0; k < v.instances.length; ++k) if (v.instances[k] !== o) a.push(v.instances[k]); v.instances = a }
    }
}
