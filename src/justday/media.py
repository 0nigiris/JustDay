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
from pathlib import Path
from typing import Callable

from . import config
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
    r"(?:видео|видос\w*|ролик|клип|video|clip)\s+(?:(?:про|о|об|с|по|about|of|with)\s+)?(?P<q>.+)$", re.I)
# "моё видео", "которое я записал", "последнее" — a local file: that is the brain's job
_LOCAL = re.compile(r"\b(мо[йеёиюя]\w*|котор\w+|последн\w+|вчерашн\w+|записал\w*|скачанн\w+|папк\w+|диск\w*|файл\w*|"
                    r"компьютер\w*|рабоч\w+ стол\w*|my|which|last|recorded|downloaded|folder|file)\b", re.I)


def parse(text: str) -> tuple[str, str] | None:
    """("music" | "video", query) for "включи песню …" / "включи видео про …", else None."""
    t = _NAME.sub("", text.strip()).strip().rstrip(".!?…")
    for kind, rx in (("music", _PLAY), ("video", _VIDEO)):
        m = rx.match(t)
        if m:
            q = m.group("q").strip(" ,.«»\"'")
            if q and len(q) <= 120 and not _LOCAL.search(q):
                return kind, q
    return None


_CONTROLS = [
    (re.compile(r"^(поставь на паузу|пауза|на паузу|останови (музыку|песню|трек)|pause( the music)?)$"), "pause"),
    (re.compile(r"^(продолжи|продолжай|играй|сними с паузы|плей|включи музыку|верни музыку|resume|play|unpause)( музыку)?$"), "resume"),
    (re.compile(r"^(следующ\w+|некст|дальше|переключи|другую|next|skip)( трек| песн\w+| track| song)?$"), "next"),
    (re.compile(r"^(предыдущ\w+|назад|previous)( трек| песн\w+| track| song)?$"), "prev"),
    (re.compile(r"^(выключи|вырубай|выруби|убери|stop|turn off) (музыку|песню|плеер|the music|music)$"), "stop"),
    (re.compile(r"^(заново|сначала|с начала|replay|restart)( трек| песню| track| song)?$"), "restart"),
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
        if ch and norm(right) == norm(ch) != norm(left):  # "In The End - Linkin Park" on Linkin Park's channel
            return left.strip(" \"'«»"), right
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


def thumb_color(path: str) -> str:
    """The most vivid colour of the cover (8×8 pixels): the island's bars take it on, like Apple Music."""
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", "scale=8:8:flags=area", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    best, best_s = None, -1.0
    for i in range(0, len(raw) - 2, 3):
        r, g, b = raw[i] / 255, raw[i + 1] / 255, raw[i + 2] / 255
        mx, mn = max(r, g, b), min(r, g, b)
        light = (mx + mn) / 2
        sat = 0 if mx == mn else (mx - mn) / (1 - abs(2 * light - 1) + 1e-9)
        s = sat * (1 - abs(light - 0.55) * 1.4)
        if s > best_s:
            best, best_s = (raw[i], raw[i + 1], raw[i + 2]), s
    return "#%02x%02x%02x" % best if best and best_s > 0.12 else ""


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
    cmd = ["yt-dlp", "--no-warnings", "--ignore-config", "--no-playlist", "--newline",
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
            t, a = split_title(e["title"], e["channel"])
            key = re.sub(r"\W+", "", t.lower())
            if key in seen or (count > 1 and (e["live"] or not 45 <= e["duration"] <= 900)):
                continue
            seen.add(key)
            out.append(e)
            if len(out) >= count:
                break
        return out or ranked[:1]
    return [e for e in search(query, 5) if not e["live"]][:1] or search(query, 1)


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
    subprocess.Popen(detached(cmd + ["--", target]), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


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

    PROPS = ("pause", "time-pos", "duration", "playlist", "playlist-pos", "idle-active", "volume")

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
        for f in await self.command("get_property", "playlist") or []:  # after a daemon restart
            self._tracks.setdefault(f["filename"], track_for(f["filename"]))

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
        except (RuntimeError, OSError, asyncio.TimeoutError):
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
        return {"title": t.get("title") or (self.loading or {}).get("title", ""), "artist": t.get("artist", ""),
                "thumb": t.get("thumb", ""), "color": t.get("color", ""), "file": cur, "url": t.get("url", ""),
                "pos": round(float(p.get("time-pos") or 0), 1), "duration": round(float(p.get("duration") or t.get("duration") or 0), 1),
                "paused": bool(p.get("pause")) or not cur, "index": pos if isinstance(pos, int) else -1, "count": len(playlist),
                "next": (self._tracks.get(nxt) or track_for(nxt)).get("title", "") if nxt else "",
                "volume": self.volume, "loading": self.loading}

    def _changed(self, force: bool = False) -> None:
        s = self.state()
        key = None if s is None else (s["file"], s["paused"], int(s["pos"]), s["duration"], s["count"], s["index"],
                                      s["volume"], json.dumps(s["loading"]))
        if force or key != self._last_pub:
            self._last_pub = key
            self.on_change(s)

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
        await self.ensure()
        for i, t in enumerate(tracks):
            self._tracks[t["file"]] = t
            flag = {"replace": "replace" if i == 0 else "append", "append": "append-play", "next": "insert-next"}[mode]
            if mode == "next" and i:
                flag = "append"
            await self.command("loadfile", t["file"], flag)
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

    async def seek(self, seconds: float) -> None:
        await self.command("seek", max(0.0, seconds), "absolute")

    async def stop(self) -> None:
        await self.command("stop")
        self._tracks.clear()
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
