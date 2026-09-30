// Громкость отдельной программы.
//
// Системная громкость — это громкость всего сразу, и когда мешает один Discord, крутить приходится
// весь звук. PipeWire держит громкость на каждом ручье отдельно, и вот она.
//
// Сопоставление ручья с значком в доке идёт по тому, чем программа себя называет: PipeWire знает
// application.name и имя двоичного файла, док знает имя из .desktop-файла и ключи сопоставления
// окон. Пересечения этих двух наборов хватает; промах не страшен — просто не будет ползунка.
import QtQuick
import Quickshell.Services.Pipewire

QtObject {
    id: au

    // Все ручьи воспроизведения, какие сейчас есть. Отслеживание обязательно: без него Quickshell
    // не держит свойства узлов свежими, и громкость покажется один раз и замрёт.
    readonly property var streams: Pipewire.nodes.values.filter(n => n && n.isStream && !n.isSink && n.audio)

    property var tracker: PwObjectTracker { objects: au.streams }

    function flat(text) { return String(text || "").toLowerCase().replace(/[^a-z0-9а-яё]+/g, "") }

    // Ручьи, принадлежащие этому значку дока.
    function streamsFor(entry) {
        if (!entry || (entry.t !== "app")) return []
        const names = [entry.name, entry.id, entry.key].filter(v => !!v).map(flat)
        const keys = (JD.dockMatch && entry.id ? Object.keys(JD.dockMatch).filter(k => JD.dockMatch[k].id === entry.id) : []).map(flat)
        const want = names.concat(keys).filter(v => v.length > 2)
        return streams.filter(n => {
            const p = n.properties || ({})
            const mine = [p["application.name"], p["application.process.binary"], p["node.name"], n.name, n.description]
                .filter(v => !!v).map(flat)
            return mine.some(m => want.some(w => m.indexOf(w) >= 0 || w.indexOf(m) >= 0))
        })
    }

    function volumeOf(list) {
        if (!list || !list.length) return -1
        let top = 0
        for (const n of list) if (n.audio && n.audio.volume > top) top = n.audio.volume
        return top
    }
    function mutedOf(list) {
        return !!list && list.length > 0 && list.every(n => n.audio && n.audio.muted)
    }
    function setVolume(list, value) {
        const v = Math.max(0, Math.min(1.4, value))
        for (const n of list) if (n.audio) n.audio.volume = v
    }
    function setMuted(list, on) {
        for (const n of list) if (n.audio) n.audio.muted = on
    }
}
