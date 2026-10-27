"""«Лестницы» для острова: по каждому модулю — кто работает сейчас и кто подхватит, когда он откажет.

Раньше порядок запасных жил в config.toml (`brain.fallbacks`, голосовой движок), и увидеть его целиком можно было,
только прочитав конфиг. Здесь он собирается в карточки, которые остров рисует как есть: ступень, её состояние и
почему она может не сработать (нет ключа, служба стоит)."""
from __future__ import annotations

from . import config, fallback


def _brain(cfg: dict) -> dict:
    rungs = []
    now = str(cfg["brain"].get("provider", "claude"))
    for name in fallback.ladder(cfg):
        ok = fallback.usable(name)
        rungs.append({"name": name, "model": fallback.model_for(cfg, name), "ready": ok,
                      "now": name == now, "note": "" if ok else "нет ключа"})
    return {"id": "brain", "title": "Нейросеть", "rungs": rungs}


def _voice(cfg: dict) -> dict:
    tts = cfg.get("tts", {})
    engine = str(tts.get("engine", "silero"))
    keys = len(config.secrets("ELEVENLABS_API_KEY"))
    rungs = []
    if engine == "elevenlabs":
        for i in range(keys):
            rungs.append({"name": "ElevenLabs", "model": f"ключ {i + 1}" if keys > 1 else "", "ready": True,
                          "now": i == 0, "note": ""})
        if not keys:
            rungs.append({"name": "ElevenLabs", "model": "", "ready": False, "now": False, "note": "нет ключа"})
    elif engine != "silero":
        rungs.append({"name": engine, "model": "", "ready": True, "now": True, "note": ""})
    rungs.append({"name": "Silero", "model": "", "ready": True, "now": engine == "silero", "note": ""})
    rungs.append({"name": "espeak", "model": "", "ready": True, "now": False, "note": "запасной, без нейросети"})
    return {"id": "voice", "title": "Голос", "rungs": rungs}


def cards(cfg: dict) -> list[dict]:
    return [_brain(cfg), _voice(cfg)]
