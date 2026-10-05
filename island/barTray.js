.pragma library
// Какие значки трея остаются на полосе, а какие уходят под шеврон. Отдельным файлом и без QML —
// чтобы это можно было проверить без экрана (tests/test_bar_tray.py).
//
// Сама полоса держит ВЕСЬ список значков и прячет лишние через `visible`, а не строит список
// заново фильтром: пока в Repeater подсовывали свежий массив, любая новая программа в трее (экран
// делится, Telegram сменил подпись) пересобирала все значки, и каждый заново плыл из прозрачности —
// при частых событиях полоса мигала и значки были полупрозрачными.

// Остаётся на полосе: показываем (shown) и не дальше `max` по счёту. Порядок — как у трея.
function inBar(items, item, shown, max) {
    let n = 0
    for (const o of items) {
        if (!o) continue
        const s = shown(o)
        if (o === item) return s && n < max
        if (s) n++
    }
    return false
}

// Сколько значков ушло под шеврон.
function overflow(items, shown, max) {
    let out = 0
    for (const o of items)
        if (o && !inBar(items, o, shown, max)) out++
    return out
}
