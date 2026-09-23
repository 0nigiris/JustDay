"""JustDay's own player: YouTube (yt-dlp) → a file on disk → mpv, shown live on the Dynamic Island.

Music: the song is found on YouTube, its audio is downloaded to ~/Music/JustDay/YouTube (the next time it plays
from disk, even offline) and plays in a background mpv — a systemd user unit (`justday-player`), so music keeps
playing when the daemon restarts. The daemon talks to it over mpv's JSON IPC socket.
Video: on the YouTube page in the browser, in a separate mpv window (streamed), or inside the island
(downloaded ≤720p, played by the island itself).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from . import config, palette
from .desktop import detached

log = logging.getLogger("justday.media")

SOCK = config.RUNTIME_DIR / "justday-player.sock"
VIDEO_SOCK = config.RUNTIME_DIR / "justday-video.sock"
UNIT = "justday-player"
INDEX = config.STATE_DIR / "media.json"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", config.HOME / ".cache")) / "justday"
THUMBS = CACHE / "thumbs"
VIDEO_CACHE = CACHE / "video"
VIDEO_CACHE_BYTES = 3 * 1024 ** 3  # island videos are a cache: the oldest go past 3 GB

WHERE = ("island", "window", "browser")

# ───────────── recognising a request without the brain ─────────────
_NAME = re.compile(r"^[\s,.!?]*(джарвис|jarvis|justday|джастдей)[\s,.!?]*", re.I)
_PLAY = re.compile(
    r"^(?:включи|поставь|вруби|запусти|сыграй|проиграй|play|put on)\s+(?:мне\s+|me\s+)?"
    r"(?:песню|песенку|трек|музыку|song|track|music)\s+(?:(?:от|группы|исполнителя|by)\s+)?(?P<q>.+)$", re.I)
_VIDEO = re.compile(
    r"^(?:включи|поставь|покажи|запусти|открой|play|show|put on)\s+(?:мне\s+|me\s+)?"
    r"(?:(?:рандомн\w+|случайн\w+|какое-нибудь|какой-нибудь|любое|random|any)\s+)?"
    r"(?:видео|видос\w*|ролик|клип|video|clip)\s+"
    r"(?:(?:про|о|об|с|по|от|у|about|of|with|from|by)\s+)?(?P<q>.+)$", re.I)
# "рандомное видео от Марка Робера": the daemon picks one itself instead of the model scripting a choice
_RANDOM = re.compile(r"\b(рандомн\w+|случайн\w+|какое-нибудь|какой-нибудь|любое|наугад|random|any)\b", re.I)
# "моё видео", "которое я записал", "последнее" — a local file: that is the brain's job
_LOCAL = re.compile(r"\b(мо[йеёиюя]\w*|котор\w+|последн\w+|вчерашн\w+|записал\w*|скачанн\w+|папк\w+|диск\w*|файл\w*|"
                    r"компьютер\w*|рабоч\w+ стол\w*|my|which|last|recorded|downloaded|folder|file)\b", re.I)


# «включи мою музыку» — what is already on disk: the one request that works with no network at all
_LIBRARY = re.compile(r"^(?:включи|поставь|вруби|запусти|сыграй|play|put on)\s+"
                      r"(?:мне\s+|me\s+)?(?:мою|моё|мои|свою|нашу|любимую|любимое|my|our|some)?\s*"
                      r"(?:музыку|песни|плейлист|фонотеку|что-нибудь|что нибудь|"
                      r"music|songs|playlist|something|anything)$", re.I)


def parse(text: str) -> tuple[str, str] | None:
    """("music" | "video" | "video_random" | "library", query) for "включи песню …", else None."""
    t = _NAME.sub("", text.strip()).strip().rstrip(".!?…")
    if _LIBRARY.match(t) and library():
        return "library", ""
    for kind, rx in (("music", _PLAY), ("video", _VIDEO)):
        m = rx.match(t)
        if m:
            q = _RANDOM.sub(" ", m.group("q")).strip(" ,.«»\"'")
            q = re.sub(r"\s+", " ", q)
            if q and len(q) <= 120 and not _LOCAL.search(q):
                if kind == "video" and _RANDOM.search(t):
                    return "video_random", q
                return kind, q
    return None


_CONTROLS = [
    (re.compile(r"^(поставь на паузу|пауза|на паузу|останови (музыку|песню|трек)|pause( the music)?)$"), "pause"),
    (re.compile(r"^(продолжи|продолжай|играй|сними с паузы|плей|включи музыку|верни музыку|resume|play|unpause)( музыку)?$"), "resume"),
    (re.compile(r"^(следующ\w+|некст|дальше|переключи|другую|next|skip)( трек| песн\w+| track| song)?$"), "next"),
    (re.compile(r"^(предыдущ\w+|назад|previous)( трек| песн\w+| track| song)?$"), "prev"),
    (re.compile(r"^(выключи|вырубай|выруби|убери|stop|turn off) (музыку|песню|плеер|the music|music)$"), "stop"),
    (re.compile(r"^(заново|сначала|с начала|replay|restart)( трек| песню| track| song)?$"), "restart"),
    (re.compile(r"^((выключи|убери|отключи|сними) (с )?повтор\w*|без повтора|не повторяй|repeat off|stop repeating)$"), "repeat_off"),
    (re.compile(r"^(повторяй|повтор|зацикли) (все|всё|плейлист|альбом|очередь|список)|repeat all$"), "repeat_all"),
    (re.compile(r"^((поставь |включи )?(на )?повтор\w*|повторяй|зацикли)( (эту|этот|это|песню|трек))*$|^repeat( this| one)?( song| track)?$"), "repeat_one"),
    (re.compile(r"^(выключи перемешивание|по порядку|не перемешивай|shuffle off)$"), "shuffle_off"),
    (re.compile(r"^(перемешай|перемешать|включи перемешивание|в случайном порядке|вперемешку|shuffle( on)?)( все| всё| песни| плейлист| очередь)?$"), "shuffle_on"),
]


def control_word(text: str) -> str | None:
    t = re.sub(r"[^\w\s]", " ", _NAME.sub("", text.lower().replace("ё", "е")))
    t = re.sub(r"\b(пожалуйста|please|давай|ка|ну)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return next((act for rx, act in _CONTROLS if rx.match(t)), None)


# ───────────── YouTube ─────────────
def _ytdlp(*args: str, timeout: float = 60) -> subprocess.CompletedProcess:
    if not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp is not installed")
    return subprocess.run(["yt-dlp", "--no-warnings", "--ignore-config", *args],
                          capture_output=True, text=True, timeout=timeout)


def is_url(q: str) -> bool:
    return bool(re.match(r"^https?://", q.strip()))


def _entry(e: dict) -> dict:
    vid = e.get("id") or ""
    return {"id": vid, "title": e.get("title") or "", "channel": e.get("channel") or e.get("uploader") or "",
            "duration": int(e.get("duration") or 0), "views": int(e.get("view_count") or 0),
            "live": e.get("live_status") in ("is_live", "is_upcoming") or e.get("duration") is None,
            "url": e.get("webpage_url") or e.get("url") or f"https://www.youtube.com/watch?v={vid}",
            "thumb_url": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg" if vid else ""}


def search(query: str, n: int = 8) -> list[dict]:
    r = _ytdlp("--flat-playlist", "-J", f"ytsearch{n}:{query}", timeout=30)
    if r.returncode:
        raise RuntimeError((r.stderr.strip().splitlines() or ["YouTube search failed"])[-1])
    return [_entry(e) for e in json.loads(r.stdout).get("entries") or [] if e.get("id")]


def info(url: str) -> dict:
    r = _ytdlp("-J", "--no-playlist", "--skip-download", url, timeout=40)
    if r.returncode:
        raise RuntimeError((r.stderr.strip().splitlines() or ["cannot open the link"])[-1])
    return _entry(json.loads(r.stdout))


_JUNK = re.compile(r"\b(cover|кавер|live|концерт|karaoke|караоке|remix|ремикс|slowed|sped ?up|nightcore|8d|reaction|реакция|"
                   r"tutorial|урок|разбор|how to play|drum|guitar|piano|минус|instrumental|1 hour|10 hours|час)\b", re.I)


def pick_song(entries: list[dict], query: str) -> list[dict]:
    """Best song versions first: the original audio beats covers, live versions, hour-long loops and reactions."""
    wanted = set(_JUNK.findall(query.lower()))

    def score(i_e):
        i, e = i_e
        s = -i * 0.6  # YouTube's own relevance matters most
        title = (e["title"] + " " + e["channel"]).lower()
        if e["live"] or not 45 <= e["duration"] <= 900:
            s -= 6
        junk = {j.lower() for j in _JUNK.findall(title)} - wanted
        s -= 3 * len(junk)
        if e["channel"].endswith(" - Topic") or re.search(r"\((official )?audio\)|official audio|аудио", title):
            s += 2
        if re.search(r"official (music )?video|music video|клип|\bmv\b", title) and "клип" not in query.lower():
            s -= 1  # music videos often open with a skit
        if e["views"]:
            s += min(3.0, len(str(e["views"])) / 3)
        return s

    return [e for _, e in sorted(enumerate(entries), key=score, reverse=True)]


def split_title(title: str, channel: str, artist: str = "", track: str = "") -> tuple[str, str]:
    """("Believer", "Imagine Dragons") from "Imagine Dragons - Believer (Official Music Video)"."""
    if artist and track:
        return track, artist.split(",")[0].strip()
    t = re.sub(r"\s*[\(\[【][^\)\]】]*(official|video|audio|lyric|lyrics|клип|visualizer|hd|4k|mv|премьера|текст)[^\)\]】]*[\)\]】]",
               "", title, flags=re.I)
    t = re.sub(r"\s*\|.*$", "", t).strip() or title
    ch = re.sub(r"\s*-\s*Topic$|VEVO$|\s*Official$", "", channel, flags=re.I).strip()
    m = re.match(r"^(.+?)\s+[-–—]\s+(.+)$", t)
    if m:
        left, right = m.group(1).strip(), m.group(2).strip(" \"'«»")
        norm = lambda x: re.sub(r"\W+", "", x.lower())  # noqa: E731
        if ch and norm(right).startswith(norm(ch)) and not norm(left).startswith(norm(ch)):
            # "In The End - Linkin Park", "Foreword - Linkin Park (Meteora)" on Linkin Park's channel
            return left.strip(" \"'«»"), ch
        return right, left
    return t, ch


def _load_index() -> dict:
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_index(idx: dict) -> None:
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    tmp = INDEX.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(INDEX)


TRACKS_STATE = config.STATE_DIR / "player_tracks.json"


def _remember_tracks(source: str, tracks: dict) -> None:
    """The player outlives the daemon (it is its own service): what each file in its playlist is must
    outlive it too."""
    try:
        TRACKS_STATE.parent.mkdir(parents=True, exist_ok=True)
        TRACKS_STATE.write_text(json.dumps({"source": source, "tracks": tracks}, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        log.warning("cannot save the playlist notes: %s", e)


def _recall_tracks() -> dict:
    try:
        got = json.loads(TRACKS_STATE.read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def thumb_color(path: str) -> str:
    """The main colour of the cover, as the island shows it: like Apple Music, the bars take it on.

    Only the centred square counts — that is the part the island shows, and a YouTube thumbnail is a
    16:9 frame with the square artwork between two black bars, which used to drag every colour towards
    black. Within it the most vivid pixel wins; a sleeve with nothing vivid gives its average colour, so a
    grey drawing stays grey instead of being turned into a colour it never had."""
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf",
                              "crop='min(iw,ih)':'min(iw,ih)',scale=8:8:flags=area", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    px = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw) - 2, 3)]
    if not px:
        return ""
    best, best_s = None, -1.0
    for r, g, b in px:
        mx, mn = max(r, g, b) / 255, min(r, g, b) / 255
        # chroma, not HSL saturation: near black, saturation is noise (#030000 is «100 % red»)
        s = (mx - mn) * (1 - abs((mx + mn) / 2 - 0.55) * 1.2)
        if s > best_s:
            best, best_s = (r, g, b), s
    if best and best_s > 0.12:
        return "#{:02x}{:02x}{:02x}".format(*best)
    lit = [c for c in px if max(c) > 16] or px   # black bars left inside the square are not the artwork
    avg = tuple(round(sum(c[k] for c in lit) / len(lit)) for k in range(3))
    return "#{:02x}{:02x}{:02x}".format(*avg)


_covers: dict[str, str] = {}


def cover_color(track: dict) -> str:
    """The colour of a track's artwork, worked out once per picture for as long as the daemon runs."""
    thumb = track.get("thumb") or ""
    if not thumb or not os.path.exists(thumb):
        return track.get("color", "")
    if thumb not in _covers:
        _covers[thumb] = thumb_color(thumb) or track.get("color", "")
    return _covers[thumb]


def music_dir() -> Path:
    from .studio import out_dir
    d = out_dir("music") / "YouTube"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _progress_lines(proc: subprocess.Popen, progress: Callable[[float], None] | None) -> list[str]:
    out: list[str] = []
    for line in proc.stdout:  # type: ignore[union-attr]
        line = line.rstrip("\n")
        m = re.match(r"^JDPROG (\d+) (\d+|NA)$", line)
        if m:
            if progress and m.group(2) != "NA" and int(m.group(2)):
                progress(min(1.0, int(m.group(1)) / int(m.group(2))))
            continue
        out.append(line)
    return out


def _download(entry: dict, kind: str, progress: Callable[[float], None] | None = None) -> dict:
    """yt-dlp → file. Returns the track: id, title, artist, duration, file, thumb, color, url, kind."""
    idx = _load_index()
    key = f"{kind}:{entry['id']}"
    old = idx.get(key)
    if old and Path(old.get("file", "")).exists():
        old["played"] = time.time()
        idx[key] = old
        _save_index(idx)
        return old
    THUMBS.mkdir(parents=True, exist_ok=True)
    if kind == "music":
        folder = music_dir()
        title, artist = split_title(entry["title"], entry["channel"])
        name = re.sub(r'[/\\:*?"<>|\x00-\x1f]+', " ", f"{artist} - {title}" if artist else title).strip()[:120]
        fmt = ["-f", "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio", "-o", str(folder / f"{name} [%(id)s].%(ext)s")]
    else:
        VIDEO_CACHE.mkdir(parents=True, exist_ok=True)
        _prune_video_cache()
        fmt = ["-f", "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/b[height<=720][ext=mp4]/bv*[height<=720]+ba/b",
               "--merge-output-format", "mp4", "-o", str(VIDEO_CACHE / "%(id)s.%(ext)s")]
    cmd = ["yt-dlp", "--no-warnings", "--ignore-config", "--no-playlist", "--newline", "-N", "8",  # 8 fragments at once
           "--write-thumbnail", "--convert-thumbnails", "jpg", "-o", f"thumbnail:{THUMBS}/%(id)s.%(ext)s", *fmt,
           "--progress-template", "download:JDPROG %(progress.downloaded_bytes)s %(progress.total_bytes,progress.total_bytes_estimate)s",
           "--print", "after_move:JDINFO %(.{id,title,channel,uploader,artist,track,duration,filepath,webpage_url})j",
           entry["url"]]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        lines = _progress_lines(proc, progress)
        err = proc.stderr.read()  # type: ignore[union-attr]
        proc.wait(timeout=600)
    except BaseException:
        proc.kill()
        raise
    got = next((json.loads(line[7:]) for line in lines if line.startswith("JDINFO ")), None)
    if proc.returncode or not got or not Path(got.get("filepath") or "").exists():
        raise RuntimeError((err.strip().splitlines() or ["download failed"])[-1][:300])
    title, artist = split_title(got.get("title") or entry["title"], got.get("channel") or got.get("uploader") or "",
                                got.get("artist") or "", got.get("track") or "")
    thumb = THUMBS / f"{got['id']}.jpg"
    track = {"id": got["id"], "kind": kind, "title": title, "artist": artist, "duration": int(got.get("duration") or 0),
             "file": got["filepath"], "thumb": str(thumb) if thumb.exists() else "",
             "url": got.get("webpage_url") or entry["url"], "played": time.time()}
    track["color"] = thumb_color(track["thumb"]) if track["thumb"] else ""
    idx[key] = track
    _save_index(idx)
    return track


def cached_track(entry: dict, kind: str = "music") -> dict | None:
    """The already downloaded track for this video, if the file is still there."""
    got = _load_index().get(f"{kind}:{entry['id']}")
    return got if got and Path(got.get("file", "")).exists() else None


def fetch_thumb(entry: dict) -> str:
    """The YouTube preview as a local jpg (~30 kB): the island has a cover before the song is downloaded."""
    vid = entry.get("id") or ""
    if not vid or not entry.get("thumb_url"):
        return ""
    THUMBS.mkdir(parents=True, exist_ok=True)
    path = THUMBS / f"{vid}.jpg"
    if path.exists():
        return str(path)
    try:
        import urllib.request

        with urllib.request.urlopen(entry["thumb_url"], timeout=8) as r, open(path, "wb") as f:
            f.write(r.read())
    except (OSError, ValueError):
        return ""
    return str(path)


def stream_track(entry: dict) -> dict:
    """A track mpv can play straight away: one yt-dlp call for the audio URL, no download and no wait.

    The link is short-lived (a few hours) — enough to listen now, while _download fills the library."""
    r = _ytdlp("-f", "bestaudio[ext=m4a]/bestaudio", "--no-playlist", "-g", entry["url"], timeout=25)
    url = (r.stdout or "").strip().splitlines()
    if r.returncode or not url:
        raise RuntimeError((r.stderr.strip().splitlines() or ["cannot open the stream"])[-1][:300])
    title, artist = split_title(entry["title"], entry["channel"])
    thumb = fetch_thumb(entry)
    return {"id": entry["id"], "kind": "music", "title": title, "artist": artist,
            "duration": int(entry.get("duration") or 0), "file": url[0], "thumb": thumb,
            "color": thumb_color(thumb) if thumb else "", "url": entry["url"], "streaming": True}


def download_audio(entry: dict, progress=None) -> dict:
    return _download(entry, "music", progress)


def download_video(entry: dict, progress=None) -> dict:
    return _download(entry, "video", progress)


def _prune_video_cache() -> None:
    files = sorted((p for p in VIDEO_CACHE.glob("*") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    total = 0
    for p in files:
        total += p.stat().st_size
        if total > VIDEO_CACHE_BYTES:
            p.unlink(missing_ok=True)


_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
               ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u",
                "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def library(kind: str = "music") -> list[dict]:
    """Everything already downloaded — the half of the player that never needs the network.

    Newest first by the last time it played, so «включи что-нибудь» starts from what is actually listened to."""
    out = [rec for key, rec in _load_index().items()
           if key.startswith(f"{kind}:") and Path(rec.get("file", "")).exists()]
    return sorted(out, key=lambda r: -r.get("played", 0))


def find_local(query: str, kind: str = "music", limit: int = 5) -> list[dict]:
    """Downloaded tracks matching a spoken name, best first, each with a `score`.

    Whisper writes English titles the Russian way («блэк ин блэк»), so the query is also compared
    in transliteration — that is what makes the offline library usable by voice at all."""
    import difflib

    clean = lambda s: re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower().replace("ё", "е"))).strip()  # noqa: E731
    q = clean(query)
    variants = {q, "".join(_TR.get(c, c) for c in q)}

    def close(needle: str, hay: str) -> float:
        """How well the name sits inside the title — a title carries a chapter number and a channel too."""
        if not needle or not hay:
            return 0.0
        if needle in hay:
            return 0.95
        best = difflib.SequenceMatcher(None, needle, hay).ratio()
        step = max(1, len(needle) // 3)
        for i in range(0, max(1, len(hay) - len(needle) + 1), step):  # the name may be anywhere in the title
            best = max(best, difflib.SequenceMatcher(None, needle, hay[i:i + len(needle)]).ratio())
        return best

    scored = []
    for rec in library(kind):
        title, artist = clean(rec.get("title", "")), clean(rec.get("artist", ""))
        best = max(close(v, h) for v in variants if v for h in (title, f"{artist} {title}".strip()))
        scored.append((best, rec))
    scored.sort(key=lambda x: -x[0])
    return [{**rec, "score": round(s, 2)} for s, rec in scored[:limit] if s > 0.45]


def local_track(path: str) -> dict:
    p = Path(path).expanduser()
    title, artist = split_title(p.stem, "")
    for t in _load_index().values():
        if t.get("file") == str(p):
            return t
    return {"id": "", "kind": "music", "title": title, "artist": artist, "duration": 0, "file": str(p),
            "thumb": "", "color": "", "url": ""}


def track_for(path: str) -> dict:
    return local_track(path)


def find(query: str, kind: str = "music", count: int = 1) -> list[dict]:
    """Search results to download: the best `count` distinct songs (music) or the top video."""
    if is_url(query):
        return [info(query)]
    if kind == "music":
        ranked = pick_song(search(query, max(8, count * 3)), query)
        out, seen = [], set()
        for e in ranked:
            t, _a = split_title(e["title"], e["channel"])
            key = re.sub(r"\W+", "", t.lower())
            if key in seen or (count > 1 and (e["live"] or not 45 <= e["duration"] <= 900)):
                continue
            seen.add(key)
            out.append(e)
            if len(out) >= count:
                break
        return out or ranked[:1]
    got = [e for e in search(query, max(5, count * 2)) if not e["live"]]
    return (got or search(query, 1))[:max(1, count)]


def search_playlists(query: str, n: int = 6) -> list[dict]:
    """YouTube playlists (albums, "best of", mixes) for a query."""
    import urllib.parse
    url = "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": query, "sp": "EgIQAw=="})
    r = _ytdlp("--flat-playlist", "-J", "--playlist-end", str(n), url, timeout=30)
    if r.returncode:
        raise RuntimeError((r.stderr.strip().splitlines() or ["YouTube search failed"])[-1])
    return [{"title": e.get("title") or "", "channel": e.get("channel") or e.get("uploader") or "",
             "url": e.get("url") or f"https://www.youtube.com/playlist?list={e['id']}"}
            for e in json.loads(r.stdout).get("entries") or [] if e.get("id")]


def playlist(query: str, limit: int = 100) -> tuple[str, list[dict]]:
    """(name, songs) of a playlist: a link, or the best playlist found for an album / artist / mood.
    Official uploads (the artist's own channel or «… - Topic») win over fan compilations."""
    if is_url(query):
        url = query
    else:
        found = search_playlists(query)
        if not found:
            raise RuntimeError("no playlist found")
        words = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 2}
        official = lambda p: any(w in p["channel"].lower() for w in words) or p["channel"].endswith(" - Topic")  # noqa: E731
        url = next((p for p in found if official(p)), found[0])["url"]
    r = _ytdlp("--flat-playlist", "-J", "--playlist-end", str(limit), url, timeout=60)
    if r.returncode:
        raise RuntimeError((r.stderr.strip().splitlines() or ["cannot open the playlist"])[-1])
    d = json.loads(r.stdout)
    songs = [_entry(e) for e in d.get("entries") or [] if e.get("id") and e.get("title") not in ("[Deleted video]", "[Private video]")]
    if not songs:
        raise RuntimeError("the playlist is empty")
    return d.get("title") or query, songs


# ───────────── video outside the island ─────────────
def open_browser(url: str, start: float = 0) -> None:
    if start > 3 and "youtube.com/watch" in url:
        url += f"&t={int(start)}s"
    subprocess.Popen(detached(["xdg-open", url]), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def open_window(target: str, start: float = 0, title: str = "", fullscreen: bool = False) -> None:
    """A separate mpv window: YouTube links are streamed (no waiting), files play from disk."""
    VIDEO_SOCK.unlink(missing_ok=True)
    cmd = ["mpv", "--force-window=immediate", "--keep-open=no", "--wayland-app-id=justday-video",
           f"--input-ipc-server={VIDEO_SOCK}", "--ytdl-format=bv*[height<=1080]+ba/b"]
    if start > 1:
        cmd.append(f"--start={int(start)}")
    if title:
        cmd.append(f"--force-media-title={title}")
    if fullscreen:
        cmd.append("--fs")
    subprocess.Popen(detached([*cmd, "--", target]), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def window_command(*args) -> bool:
    """Pause / resume the video window, if one is open."""
    import socket
    if not VIDEO_SOCK.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(1)
            s.connect(str(VIDEO_SOCK))
            s.sendall((json.dumps({"command": list(args)}) + "\n").encode())
        return True
    except OSError:
        return False


# ───────────── the music player (mpv over JSON IPC) ─────────────
class MusicPlayer:
    """Background mpv. `on_change(state | None)` is called on the event loop whenever the island should update."""

    PROPS = ("pause", "time-pos", "duration", "playlist", "playlist-pos", "idle-active", "volume", "loop-file", "loop-playlist")

    def __init__(self, on_change: Callable[[dict | None], None], volume: int = 70) -> None:
        self.on_change = on_change
        self.volume = volume  # the user's level; ducking lowers mpv below it for a while
        self._ducked = False
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._req = 0
        self._waiting: dict[int, asyncio.Future] = {}
        self._props: dict = {}
        self._tracks: dict[str, dict] = {}
        self._last_pub: tuple = ()
        self._task: asyncio.Task | None = None
        self.loading: dict | None = None  # {"title", "progress"} while a song downloads
        self.shuffle = False
        self._order: dict[str, int] = {}
        self._seq = 0
        self.source = ""  # what is playing as a whole: a playlist / album / artist name

    # connection
    @property
    def alive(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def attach(self) -> bool:
        """Reconnect to an mpv that outlived a daemon restart (music keeps playing)."""
        if SOCK.exists():
            try:
                await self._connect()
                return True
            except OSError:
                pass
        return False

    async def ensure(self) -> None:
        if self.alive:
            return
        if await self.attach():
            return
        subprocess.run(["systemctl", "--user", "stop", UNIT], capture_output=True, timeout=10)
        SOCK.unlink(missing_ok=True)
        args = ["mpv", "--idle=yes", "--no-video", "--no-terminal", "--audio-display=no", f"--input-ipc-server={SOCK}",
                "--audio-client-name=JustDay", f"--volume={self.volume}", "--volume-max=130", "--gapless-audio=weak",
                "--keep-open=no", "--prefetch-playlist=yes"]
        if os.environ.get("JUSTDAY_MPV_AO"):  # tests: JUSTDAY_MPV_AO=null plays silently
            args.append(f"--ao={os.environ['JUSTDAY_MPV_AO']}")
        r = subprocess.run(["systemd-run", "--user", f"--unit={UNIT}", "--collect", "--quiet",
                            "-p", "Description=JustDay music player", "--", *args], capture_output=True, text=True, timeout=10)
        if r.returncode:  # no systemd user session: a plain child process
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(50):
            await asyncio.sleep(0.1)
            if SOCK.exists():
                try:
                    await self._connect()
                    return
                except OSError:
                    pass
        raise RuntimeError("mpv did not start")

    async def _connect(self) -> None:
        self._reader, self._writer = await asyncio.open_unix_connection(str(SOCK), limit=1 << 22)
        self._task = asyncio.create_task(self._read())
        for i, p in enumerate(self.PROPS, 1):
            await self._send(["observe_property", i, p], wait=False)
        vol = await self.command("get_property", "volume")
        if isinstance(vol, (int, float)) and not self._ducked:
            self.volume = round(vol)
        known = _recall_tracks()                                        # after a daemon restart
        self.source = self.source or known.get("source", "")
        saved = known.get("tracks") or {}
        for f in await self.command("get_property", "playlist") or []:
            # a streamed song lives under a long yt-dlp URL: without the note taken when it started, its
            # title on the island would be that URL
            self._tracks.setdefault(f["filename"], saved.get(f["filename"]) or track_for(f["filename"]))

    async def _read(self) -> None:
        try:
            while self._reader:
                line = await self._reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if "request_id" in msg and msg.get("request_id") in self._waiting:
                    fut = self._waiting.pop(msg["request_id"])
                    if not fut.done():
                        fut.set_result(msg)
                elif msg.get("event") == "property-change":
                    self._props[msg["name"]] = msg.get("data")
                    self._changed()
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            self._writer = None
            self._props = {}
            self._changed(force=True)

    async def _send(self, cmd: list, wait: bool = True):
        if not self.alive:
            raise RuntimeError("player is not running")
        self._req += 1
        rid = self._req
        fut = asyncio.get_running_loop().create_future()
        if wait:
            self._waiting[rid] = fut
        self._writer.write((json.dumps({"command": cmd, "request_id": rid}) + "\n").encode())
        await self._writer.drain()
        if not wait:
            return None
        try:
            msg = await asyncio.wait_for(fut, 5)
        finally:
            self._waiting.pop(rid, None)
        return msg

    async def command(self, *cmd):
        try:
            msg = await self._send(list(cmd))
        except (TimeoutError, RuntimeError, OSError):
            return None
        return msg.get("data") if msg and msg.get("error") == "success" else None

    # state
    def state(self) -> dict | None:
        p = self._props
        playlist = p.get("playlist") or []
        pos = p.get("playlist-pos")
        ended = not self.alive or not playlist or (p.get("idle-active") and (pos is None or pos < 0))
        if ended and not self.loading:
            return None
        cur = playlist[pos]["filename"] if isinstance(pos, int) and 0 <= pos < len(playlist) else ""
        t = self._tracks.get(cur) or (track_for(cur) if cur else {})
        nxt = playlist[pos + 1]["filename"] if isinstance(pos, int) and 0 <= pos < len(playlist) - 1 else ""
        start = pos if isinstance(pos, int) and pos >= 0 else 0
        queue = [{"i": i, "title": (self._tracks.get(f["filename"]) or track_for(f["filename"])).get("title", ""),
                  "artist": (self._tracks.get(f["filename"]) or {}).get("artist", ""),
                  "thumb": (self._tracks.get(f["filename"]) or {}).get("thumb", ""),
                  "cover": cover_color(self._tracks.get(f["filename"]) or {})}
                 for i, f in enumerate(playlist[max(0, start - 2):start + 40], max(0, start - 2))]
        return {"repeat": self.repeat, "shuffle": self.shuffle, "source": self.source, "queue": queue,"title": t.get("title") or (self.loading or {}).get("title", ""), "artist": t.get("artist", ""),
                "thumb": t.get("thumb", ""), "file": cur, "url": t.get("url", ""),
                # what the music is about, when that is known; otherwise the brightest pixel of the cover
                "color": palette.color(t.get("title", ""), t.get("artist", "")) or cover_color(t),
                "cover": cover_color(t),   # the artwork's own colour, which the question takes into account
                "pos": round(float(p.get("time-pos") or 0), 1), "duration": round(float(p.get("duration") or t.get("duration") or 0), 1),
                "paused": bool(p.get("pause")) or not cur, "index": pos if isinstance(pos, int) else -1, "count": len(playlist),
                "next": (self._tracks.get(nxt) or track_for(nxt)).get("title", "") if nxt else "",
                "volume": self.volume, "loading": self.loading}

    def remember(self) -> None:
        """Write down what is in the playlist, so a restart of the daemon knows the titles again."""
        _remember_tracks(self.source, self._tracks)

    def refresh(self) -> None:
        """Republish the state although nothing in mpv moved — a track's colour has just been learned."""
        self._changed(force=True)

    def _changed(self, force: bool = False) -> None:
        s = self.state()
        key = None if s is None else (s["file"], s["paused"], int(s["pos"]), s["duration"], s["count"], s["index"],
                                      s["volume"], json.dumps(s["loading"]), s["repeat"], s["shuffle"], s["source"])
        if force or key != self._last_pub:
            self._last_pub = key
            self.on_change(s)

    @property
    def repeat(self) -> str:
        """off | all | one"""
        lf, lp = self._props.get("loop-file"), self._props.get("loop-playlist")
        on = lambda v: v not in (None, False, "no", 0)  # noqa: E731
        return "one" if on(lf) else "all" if on(lp) else "off"

    @property
    def active(self) -> bool:
        s = self.state()
        return bool(s and s["file"])

    @property
    def playing(self) -> bool:
        s = self.state()
        return bool(s and s["file"] and not s["paused"])

    # control
    async def load(self, tracks: list[dict], mode: str = "replace") -> None:
        """mode: replace (play now) | append (after the queue) | next (right after the current song)."""
        import random
        await self.ensure()
        if mode == "replace":
            self.shuffle = False
            self._order.clear()
        for i, t in enumerate(tracks):
            self._tracks[t["file"]] = t
            self._seq += 1
            self._order.setdefault(t["file"], self._seq)  # the order songs were added: "shuffle off" returns to it
            flag = {"replace": "replace" if i == 0 else "append", "append": "append-play", "next": "insert-next"}[mode]
            if mode == "next" and i:
                flag = "append"
            if flag in ("append", "append-play") and self.shuffle:  # shuffled: new songs land somewhere after this one
                pos = await self.command("get_property", "playlist-pos")
                count = await self.command("get_property", "playlist-count") or 0
                if isinstance(pos, int) and 0 <= pos < count - 1:
                    await self.command("loadfile", t["file"], "insert-at", random.randint(pos + 1, count))
                    continue
            await self.command("loadfile", t["file"], flag)
        _remember_tracks(self.source, self._tracks)
        if mode == "replace":
            await self.command("set_property", "pause", False)

    async def toggle(self) -> None:
        await self.command("cycle", "pause")

    async def pause(self) -> None:
        await self.command("set_property", "pause", True)

    async def resume(self) -> None:
        await self.command("set_property", "pause", False)

    async def next(self) -> None:
        await self.command("playlist-next", "force")

    async def prev(self) -> None:
        if float(self._props.get("time-pos") or 0) > 5 or (self._props.get("playlist-pos") or 0) <= 0:
            await self.command("seek", 0, "absolute")
        else:
            await self.command("playlist-prev", "force")

    async def jump(self, index: int) -> None:
        await self.command("playlist-play-index", int(index))
        await self.resume()

    async def set_repeat(self, mode: str) -> None:
        """off | all | one | cycle (off → all → one → off, like a phone)"""
        if mode == "cycle":
            mode = {"off": "all", "all": "one", "one": "off"}[self.repeat]
        await self.command("set_property", "loop-file", "inf" if mode == "one" else "no")
        await self.command("set_property", "loop-playlist", "inf" if mode == "all" else "no")

    async def _reorder(self, target: list[str]) -> None:
        live = [f["filename"] for f in await self.command("get_property", "playlist") or []]
        for i, name in enumerate(target):
            j = live.index(name) if name in live else -1
            if j > i:
                await self.command("playlist-move", j, i)
                live.insert(i, live.pop(j))

    async def set_shuffle(self, on: bool | None = None) -> None:
        """Like a phone: the song that plays stays and goes first, the rest is shuffled after it;
        switching it off puts everything back in the order it was added."""
        import random
        on = (not self.shuffle) if on is None else on
        files = [f["filename"] for f in await self.command("get_property", "playlist") or []]
        pos = await self.command("get_property", "playlist-pos")
        if on != self.shuffle and files:
            cur = files[pos] if isinstance(pos, int) and 0 <= pos < len(files) else None
            if on:
                rest = [f for f in files if f != cur]
                random.shuffle(rest)
                target = ([cur] if cur else []) + rest
            else:
                target = sorted(files, key=lambda f: self._order.get(f, 1 << 30))
            await self._reorder(target)
        self.shuffle = on
        self._changed(force=True)

    async def seek(self, seconds: float) -> None:
        await self.command("seek", max(0.0, seconds), "absolute")

    async def stop(self) -> None:
        await self.command("stop")
        self._tracks.clear()
        _remember_tracks("", {})
        self.source = ""
        self.shuffle = False
        self.loading = None
        self._changed(force=True)

    async def set_volume(self, value: int) -> None:
        self.volume = max(0, min(130, int(value)))
        if not self._ducked:
            await self.command("set_property", "volume", self.volume)
        self._changed()

    async def duck(self, on: bool) -> None:
        """Quieter while the assistant listens or talks (like a phone lowers music for the navigator)."""
        if on == self._ducked or not self.alive:
            return
        self._ducked = on
        await self.command("set_property", "volume", round(self.volume * 0.25) if on else self.volume)

    def set_loading(self, loading: dict | None) -> None:
        self.loading = loading
        self._changed(force=True)
