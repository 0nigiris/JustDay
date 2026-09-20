"""The colour the island wears while a track plays.

A cover is not the colour of the music. «Flower Man» from DELTARUNE is a yellow character's theme on a
black album cover, and the island would glow red for it — the brightest pixel of the artwork wins, and it
is the wrong colour. So the colour of a track is asked once of the model that already drives the
assistant: what is this music *about*, and what colour is that? The answer is kept in one small file, so
every track is asked about once in its life; when nothing is known, the cover decides as before.

The call is a plain `claude -p`, a separate process with its own short system prompt — it never touches
the conversation the assistant is having. A whole queue goes in one call, because the price of a call is
mostly its first token.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time

from . import config, providers

log = logging.getLogger("justday.palette")

FILE = config.STATE_DIR / "colors.json"

MAX_BATCH = 20          # tracks in one question
TIMEOUT = 420.0         # a batch that searches the web takes a couple of minutes
MIN_CONFIDENCE = 0.6    # a colour the model is not sure of loses to the plain colour of the artwork
RULES_V = 2             # the question changed: answers given to an older one are asked again

# spoken colours, for `justday player color жёлтый`
NAMES = {
    "красный": "#e03131", "red": "#e03131", "алый": "#e8394a", "оранжевый": "#f76707", "orange": "#f76707",
    "жёлтый": "#ffd23f", "желтый": "#ffd23f", "yellow": "#ffd23f", "золотой": "#f2b705", "gold": "#f2b705",
    "зелёный": "#37b24d", "зеленый": "#37b24d", "green": "#37b24d", "салатовый": "#74c043", "lime": "#74c043",
    "бирюзовый": "#0ca678", "teal": "#0ca678", "голубой": "#22b8cf", "cyan": "#22b8cf",
    "синий": "#3b82f6", "blue": "#3b82f6", "фиолетовый": "#8b5cf6", "purple": "#8b5cf6",
    "сиреневый": "#a78bfa", "розовый": "#f06595", "pink": "#f06595", "малиновый": "#e64980",
    "белый": "#e9ecef", "white": "#e9ecef", "серый": "#909296", "grey": "#909296", "gray": "#909296",
    "коричневый": "#a1662f", "brown": "#a1662f",
}

SYSTEM = ("You choose the colour a music player glows with while a track plays. Reply with one line of "
          "JSON and nothing else.")

RULES = ("Each track comes with the colour of its own artwork, or with «нет цвета» when that artwork is "
         "black, white or grey. Start there: when the artwork has a colour, that colour is the answer — it "
         "was chosen for this music and it is what the person is looking at. Replace it only when the "
         "music's subject plainly owns a different colour that the artwork does not show: a character's "
         "leitmotif on a colourless sleeve, or a track sitting under a compilation cover that says nothing "
         "about it. Never trade a vivid artwork colour for a franchise's signature colour — a Blue Lock "
         "track on an orange cover is orange. A colour you choose yourself is drawn on black, so keep it "
         "vivid: HSL saturation at least 0.45, lightness between 0.45 and 0.7. Confidence is how sure you "
         "are of the colour of this very track.")

_NOISE = re.compile(r"\s*[\[(](?:official|lyric|audio|video|hd|hq|4k|mv|m/v|full|прем|clip)[^\])]*[\])]", re.I)
_NUMBER = re.compile(r"^\s*\d{1,3}\s*[.\-–)]\s+")
_HEX = re.compile(r"#?([0-9a-f]{6})\b", re.I)


_FEAT = re.compile(r"\s*(?:[&,·]|\bfeat\.?\b|\bft\.?\b|\bx\b|\bwith\b|@).*", re.I)


def key(title: str, artist: str = "") -> str:
    """One track, however its title was written: no leading track number, no «(Official Video)», and only
    the first artist — «Toby Fox» and «Toby Fox & Camellia» are the same song, asked about once."""
    flat = lambda s: re.sub(r"\s+", " ", s or "").strip().lower()  # noqa: E731
    return f"{flat(_FEAT.sub('', artist or ''))}|{flat(_NOISE.sub('', _NUMBER.sub('', title or '')))}".strip("| ")


_cache: tuple[float, dict] = (0.0, {})


def _load() -> dict:
    """The file is read once per change: the player asks for a colour several times a second."""
    global _cache
    try:
        stamp = FILE.stat().st_mtime
    except OSError:
        return {}
    if stamp != _cache[0]:
        try:
            got = json.loads(FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        _cache = (stamp, got if isinstance(got, dict) else {})
    return _cache[1]


def _save(items: dict) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(FILE)
    global _cache
    _cache = (FILE.stat().st_mtime, items)


def get(title: str, artist: str = "") -> dict | None:
    """What is known about this track: {hex, why, confidence, source}. None = never asked."""
    return _load().get(key(title, artist))


def color(title: str, artist: str = "") -> str:
    """The colour to paint with, or "" when the cover should keep its say."""
    rec = get(title, artist) or {}
    return rec.get("hex", "") if rec.get("confidence", 0) >= MIN_CONFIDENCE else ""


def put(title: str, artist: str, hex_color: str, why: str = "", confidence: float = 1.0, source: str = "user") -> dict:
    rec = {"hex": normalize(hex_color), "why": why[:60], "confidence": round(float(confidence), 2),
           "source": source, "at": round(time.time()), "v": RULES_V, "title": title, "artist": artist}
    items = _load()
    items[key(title, artist)] = rec
    _save(items)
    return rec


def forget(title: str, artist: str = "") -> bool:
    items = _load()
    if items.pop(key(title, artist), None) is None:
        return False
    _save(items)
    return True


def normalize(value: str) -> str:
    """«жёлтый», «ffd23f», «#FFD23F» → «#ffd23f». Anything unreadable → ""."""
    v = (value or "").strip().lower()
    if v in NAMES:
        return NAMES[v]
    m = _HEX.search(v)
    return "#" + m.group(1).lower() if m else ""


def _ask(prompt: str, model: str, web: bool, timeout: float) -> str:
    cfg = config.load()
    cli = shutil.which(cfg["brain"]["claude_cli"]) or "claude"
    args = [cli, "-p", prompt, "--model", model, "--output-format", "json", "--no-session-persistence",
            "--strict-mcp-config", "--system-prompt", SYSTEM]
    args += ["--allowed-tools", "WebSearch", "WebFetch"] if web else ["--disallowed-tools", "WebSearch", "WebFetch",
                                                                      "Bash", "Read", "Glob", "Grep", "Edit", "Write"]
    out = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=str(config.STATE_DIR),
                         env={**os.environ, **providers.env(cfg)})
    data = json.loads(out.stdout or "{}")
    if data.get("is_error"):
        raise RuntimeError(str(data.get("result", ""))[:200])
    log.info("colors: %d ms, %s", data.get("duration_ms", 0), data.get("result", "")[:200])
    return str(data.get("result", ""))


def _json_block(text: str) -> dict:
    text = re.sub(r"^```[a-z]*|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON in {text[:120]!r}")
    return json.loads(text[start:end + 1])


def resolve(tracks: list[dict], *, web: bool = True, model: str = "") -> dict[str, dict]:
    """Ask about a batch of tracks at once: [{title, artist, source}] → {key: record}.

    Everything already known is left alone by the caller; this only asks and remembers."""
    tracks = tracks[:MAX_BATCH]
    if not tracks:
        return {}
    lines = []
    for i, t in enumerate(tracks, 1):
        where = f", альбом: {t['source']}" if t.get("source") else ""
        cover = normalize(t.get("cover", "")) or "нет цвета"
        lines.append(f"{i}. «{t['title']}» — {t.get('artist') or '?'} [обложка: {cover}{where}]")
    ask = ("Tracks:\n" + "\n".join(lines) + "\n\n" + RULES + "\n"
           + ("A track whose artwork has no colour and whose subject you cannot place is exactly what the web "
              "is for: look those up (at most 5 searches in total) instead of guessing from the words in the "
              "title. Everything else is answered without searching.\n" if web else
              "Answer from your own knowledge only; guess nothing from the words in a title.\n")
           + 'Answer: {"colors":[{"n":1,"hex":"#rrggbb","why":"≤6 words","confidence":0.0-1.0}, …]} — one entry '
             'per track, in order. A track whose subject you do not know gets confidence 0.')
    model = model or config.load()["brain"]["model"] or "sonnet"
    got = _json_block(_ask(ask, model, web, TIMEOUT))
    items, out = _load(), {}
    # every track that was asked about is written down, answered or not: otherwise a track the model keeps
    # skipping would be asked about again on every tick of the player
    for t in tracks:
        items.setdefault(key(t["title"], t.get("artist", "")),
                         {"hex": "", "why": "", "confidence": 0.0, "source": "model", "at": round(time.time()),
                          "v": RULES_V, "title": t["title"], "artist": t.get("artist", "")})
    for entry in got.get("colors", []):
        try:
            t = tracks[int(entry["n"]) - 1]
        except (KeyError, ValueError, IndexError):
            continue
        hexa = normalize(str(entry.get("hex", "")))
        conf = max(0.0, min(1.0, float(entry.get("confidence", 0) or 0)))
        rec = {"hex": hexa, "why": str(entry.get("why", ""))[:60], "confidence": round(conf if hexa else 0.0, 2),
               "source": "model", "at": round(time.time()), "v": RULES_V,
               "title": t["title"], "artist": t.get("artist", "")}
        items[key(t["title"], t.get("artist", ""))] = rec
        out[key(t["title"], t.get("artist", ""))] = rec
    _save(items)
    return out


def unknown(tracks: list[dict]) -> list[dict]:
    """The ones nobody has asked about yet — plus those answered before the question was last rewritten.

    A colour the person chose by hand stays whatever they made it."""
    items, seen, out = _load(), set(), []
    for t in tracks:
        title = (t.get("title") or "").strip()
        # a stream whose notes were lost shows up under its URL: there is nothing to ask about there
        if not title or title.startswith(("http://", "https://")) or len(title) > 200:
            continue
        k = key(t["title"], t.get("artist", ""))
        rec = items.get(k)
        fresh = rec is not None and (rec.get("source") == "user" or rec.get("v", 1) >= RULES_V)
        if fresh or k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out
