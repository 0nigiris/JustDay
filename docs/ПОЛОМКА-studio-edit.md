# Поломка: `justday studio edit` (правка картинки по образцу)

Нашла студия (`~/ai-studio-v3`) 16 октября ночью. В JustDay сама не чинила: это чужой репозиторий.
Этот файл — задание для сессии JustDay. После починки файл удалить.

## Симптом
`justday studio edit <картинка> "<что поменять>"` падает сразу: ComfyUI отклоняет граф
(`prompt_outputs_failed_validation`, у узла 11 не хватает обязательного входа).

## Причина (проверено)
`src/justday/studio.py:255`, функция `g_edit`: узел `ImageScaleToTotalPixels` собран без входа
`resolution_steps`. В ComfyUI (`~/ai-local/ComfyUI`, коммит f197357) этот вход стал **обязательным**:
`'resolution_steps': ['INT', {'default': 1, 'min': 1, 'max': 256}]`.

Все остальные графы (`g_image`, `g_upscale`, `g_video` в обоих режимах, `g_music`, `g_3d`) сверены
скриптом с `/object_info` работающего ComfyUI: недостающих и лишних входов нет. Сломан только `edit`.

## Починка (одна строка)
```python
"11": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["4", 0], "upscale_method": "lanczos",
                                                           "megapixels": 1.0, "resolution_steps": 1}},
```
`resolution_steps: 1` — то же поведение, что было до обновления.

## Вторая проблема: edit на этой машине идёт около 40 минут, а ждём 400 с
Замерено ночью: Qwen-Edit на 1.0 МП / 20 шагов ≈ **115 с на шаг** (12 ГБ видео + 15 ГБ ОЗУ, модель
выгружается в ОЗУ) → около 40 мин на одну картинку. А в коде `ETA["edit"] = 120`, `edit(..., wait_s=400)`:
запрос закончится по таймауту, хотя ComfyUI продолжит считать.

Рабочий режим, проверен глазами на 10 кадрах (качество хорошее): **0.5 МП, 8 шагов, cfg 1.0** → 8–10 мин.
cfg 1.0 отключает негативный промпт, поэтому шаг вдвое быстрее.

Предложение:
- в `g_edit`: `megapixels: 0.5`, `steps: 8`, `cfg: 1.0` по умолчанию;
- `ETA["edit"] = 600`, `wait_s` у `edit` ≈ 900;
- если правка нужна в полном размере — после неё делать `upscale` (он быстрый).

## Как проверить после починки
1. Сверка графов (ComfyUI должен быть запущен):
```python
import json, urllib.request, justday.studio as s
oi = json.load(urllib.request.urlopen("http://127.0.0.1:8188/object_info"))
g = s.g_edit("a.png", "x", 1)
for n in g.values():
    req = oi[n["class_type"]]["input"]["required"]
    assert all(r in n["inputs"] for r in req), n["class_type"]
```
2. Живой запуск: `justday studio edit <любой png> "make the background blue"` → картинка за ≤ 10 мин.

## Временный обход в студии
`~/ai-studio-v3/projects/сериал/kadr.py` дописывает `resolution_steps` в граф сам. После починки
в JustDay обход можно убрать (студия поправит у себя).
