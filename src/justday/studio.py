"""Creative studio: pictures, video, music, 3D, voice-over, subtitles and montage on the local GPU.

Generation goes through a local ComfyUI (127.0.0.1 only) with the models already on disk; montage is ffmpeg.
Short jobs wait for the file; long ones (video, 3D) run in the background and JustDay reports when they are done.
Nothing here uses a paid service or sends anything off the computer.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import config

HOME = Path.home()
JOBS_DIR = config.STATE_DIR / "studio"
LOG = config.STATE_DIR / "comfyui.log"

# what each capability needs on disk (ComfyUI models/<folder>/<file>)
NEEDS = {
    "image": [("checkpoints", "flux1-schnell-fp8.safetensors")],
    "edit": [("diffusion_models", "qwen_image_edit_fp8_e4m3fn.safetensors"),
             ("text_encoders", "qwen_2.5_vl_7b_fp8_scaled.safetensors"), ("vae", "qwen_image_vae.safetensors")],
    "upscale": [("upscale_models", "4x-UltraSharp.pth")],
    "video": [("diffusion_models", "wan2.2_ti2v_5B_fp16.safetensors"),
              ("text_encoders", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"), ("vae", "wan2.2_vae.safetensors")],
    "music": [("checkpoints", "ace_step_v1_3.5b.safetensors")],
    "3d": [("checkpoints", "hunyuan3d-dit-v2_fp16.safetensors")],
}
NEEDS["animate"] = NEEDS["video"]
# rough time on an RTX 3060, for the "ready in about …" line
ETA = {"image": 25, "edit": 120, "upscale": 10, "video": 480, "animate": 480, "music": 60, "3d": 150}
SIZES = {"square": (1024, 1024), "wide": (1536, 864), "tall": (864, 1536), "banner": (1536, 640)}
VIDEO_SIZES = {"square": (640, 640), "wide": (832, 480), "tall": (480, 832)}


# ───────────── where things are ─────────────
def settings() -> dict:
    s = config.load().get("studio", {})
    comfy = Path(os.path.expanduser(s.get("comfy_dir") or "")) if s.get("comfy_dir") else None
    if not comfy:
        comfy = next((p for p in (HOME / "ai-local/ComfyUI", HOME / "ComfyUI", HOME / "comfy/ComfyUI")
                      if (p / "main.py").exists()), None)
    py = Path(os.path.expanduser(s["python"])) if s.get("python") else None
    if not py and comfy:
        py = next((p for p in (comfy.parent / "venv/bin/python", comfy / "venv/bin/python", comfy / ".venv/bin/python")
                   if p.exists()), None)
    rmbg = Path(os.path.expanduser(s.get("rmbg_dir") or "~/pinokio/api/RMBG-2-Studio.git"))
    return {"comfy": comfy, "python": py, "url": s.get("url") or "http://127.0.0.1:8188", "rmbg": rmbg,
            "free_after": s.get("free_after", True)}


def out_dir(kind: str) -> Path:
    """~/Pictures/JustDay, ~/Videos/JustDay, ~/Music/JustDay (the user's XDG folders)."""
    xdg = {"image": "PICTURES", "video": "VIDEOS", "music": "MUSIC", "3d": "DOCUMENTS", "speech": "MUSIC"}[kind]
    try:
        base = subprocess.run(["xdg-user-dir", xdg], capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        base = ""
    if not base or Path(base) == HOME:
        base = str(HOME / {"PICTURES": "Pictures", "VIDEOS": "Videos", "MUSIC": "Music", "DOCUMENTS": "Documents"}[xdg])
    d = Path(base) / "JustDay" / ("3D" if kind == "3d" else "")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _target(out: str | None, kind: str, ext: str, name: str) -> Path:
    if out:
        p = Path(os.path.expanduser(out)).absolute()
        if p.is_dir() or out.endswith("/"):
            p.mkdir(parents=True, exist_ok=True)
            p = p / f"{_slug(name)}{ext}"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return _unique(out_dir(kind) / f"{time.strftime('%Y-%m-%d')} {_slug(name)}{ext}")


def _slug(text: str) -> str:
    words = "".join(c if c.isalnum() else " " for c in text).split()[:6]
    return (" ".join(words) or "result")[:60]


def _unique(p: Path) -> Path:
    n = 2
    q = p
    while q.exists():
        q = p.with_name(f"{p.stem} {n}{p.suffix}")
        n += 1
    return q


def status() -> dict:
    s = settings()
    caps = {}
    if s["comfy"]:
        models = s["comfy"] / "models"
        for cap, files in NEEDS.items():
            caps[cap] = all((models / d / f).exists() for d, f in files)
    caps["remove_bg"] = (s["rmbg"] / "app/env/bin/python").exists()
    caps["speech"] = True
    caps["subtitles"] = True
    caps["montage"] = bool(shutil.which("ffmpeg"))
    return {"engine": str(s["comfy"] or ""), "running": _alive(s["url"]), "can": caps,
            "gpu": bool(shutil.which("nvidia-smi"))}


# ───────────── ComfyUI ─────────────
def _get(url: str, timeout: float = 6):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read()
            return json.loads(body) if body.strip() else {}
    except (OSError, ValueError):
        return None


def _post(url: str, payload: dict, timeout: float = 30) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return json.loads(body) if body.strip() else {}


def _alive(url: str) -> bool:
    return _get(url + "/system_stats", timeout=3) is not None


def engine() -> str:
    """URL of a running ComfyUI; starts it (localhost only) when needed."""
    s = settings()
    if _alive(s["url"]):
        return s["url"]
    if not s["comfy"] or not s["python"]:
        raise RuntimeError("локальная студия не найдена: нужен ComfyUI (studio.comfy_dir в config.toml)")
    port = s["url"].rsplit(":", 1)[-1].strip("/")
    cmd = [str(s["python"]), "main.py", "--listen", "127.0.0.1", "--port", port]
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("systemd-run"):
        # its own unit with a memory ceiling: if a job needs more RAM than there is, only the engine is stopped,
        # never the user's apps or JustDay itself
        ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        subprocess.run(["systemctl", "--user", "reset-failed", "justday-studio.service"], capture_output=True)
        subprocess.run(["systemd-run", "--user", "--unit=justday-studio", "--collect", "--quiet",
                        f"--working-directory={s['comfy']}", f"-pMemoryMax={int(ram * 0.7)}",
                        "-pOOMScoreAdjust=500", f"-pStandardOutput=append:{LOG}", f"-pStandardError=append:{LOG}", *cmd],
                       check=True, capture_output=True, timeout=15)
    else:
        with LOG.open("ab") as log:
            subprocess.Popen(cmd, cwd=s["comfy"], stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(240):
        time.sleep(1)
        if _alive(s["url"]):
            time.sleep(1)
            return s["url"]
    raise RuntimeError(f"движок студии не запустился за 4 минуты, см. {LOG}")


def stop_engine() -> bool:
    """Stop the engine JustDay started (frees its GPU and RAM)."""
    p = subprocess.run(["systemctl", "--user", "stop", "justday-studio.service"], capture_output=True, timeout=30)
    return p.returncode == 0


def free(url: str | None = None) -> None:
    try:
        _post((url or settings()["url"]) + "/free", {"unload_models": True, "free_memory": True}, timeout=10)
    except OSError:
        pass


def _upload(url: str, path: Path) -> str:
    """Copy an input file into ComfyUI's input folder (same machine) and return its name."""
    s = settings()
    if not path.is_file():
        raise RuntimeError(f"нет файла {path}")
    name = f"justday_{uuid.uuid4().hex[:10]}{path.suffix.lower()}"
    dest = s["comfy"] / "input"
    dest.mkdir(exist_ok=True)
    shutil.copy(path, dest / name)
    return name


def submit(url: str, graph: dict) -> str:
    res = _post(url + "/prompt", {"prompt": graph, "client_id": uuid.uuid4().hex})
    if not res.get("prompt_id"):
        raise RuntimeError("движок отклонил задачу: " + json.dumps(res.get("node_errors") or res, ensure_ascii=False)[:400])
    return res["prompt_id"]


def result(url: str, prompt_id: str) -> tuple[str, Path | None, str]:
    """(state, output file, error) — state is queued | running | done | failed."""
    hist = _get(f"{url}/history/{prompt_id}", timeout=10) or {}
    item = hist.get(prompt_id)
    if not item:
        q = _get(url + "/queue", timeout=5) or {}
        running = any(prompt_id in json.dumps(x) for x in q.get("queue_running", []))
        pending = any(prompt_id in json.dumps(x) for x in q.get("queue_pending", []))
        if running or pending:
            return ("running" if running else "queued"), None, ""
        return "failed", None, "задача пропала из очереди (движок перезапускали?)"
    st = item.get("status", {})
    if st.get("status_str") == "error":
        msgs = [m[1].get("exception_message", "") for m in st.get("messages", []) if m[0] == "execution_error"]
        return "failed", None, (msgs[0] if msgs else "ошибка генерации").strip()[:300]
    for out in item.get("outputs", {}).values():
        for files in out.values():
            if isinstance(files, list):
                for f in files:
                    if isinstance(f, dict) and f.get("filename") and f.get("type", "output") == "output":
                        comfy = settings()["comfy"]
                        return "done", comfy / "output" / f.get("subfolder", "") / f["filename"], ""
    return "failed", None, "движок не сохранил файл"


# ───────────── workflows ─────────────
def _seed(seed: int | None) -> int:
    return seed if seed is not None else random.randrange(2**31)


def g_image(prompt: str, w: int, h: int, seed: int | None, neg: str = "") -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "flux1-schnell-fp8.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": neg or "watermark, blurry, low quality", "clip": ["1", 1]}},
        "4": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w // 16 * 16, "height": h // 16 * 16, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {"seed": _seed(seed), "steps": 4, "cfg": 1.0, "sampler_name": "euler",
                                                   "scheduler": "simple", "denoise": 1.0, "model": ["1", 0],
                                                   "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0]}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "justday/image"}},
    }


def g_edit(image: str, prompt: str, seed: int | None) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_edit_fp8_e4m3fn.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "4": {"class_type": "LoadImage", "inputs": {"image": image}},
        "11": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["4", 0], "upscale_method": "lanczos", "megapixels": 1.0}},
        "5": {"class_type": "TextEncodeQwenImageEdit", "inputs": {"clip": ["2", 0], "prompt": prompt, "vae": ["3", 0], "image": ["11", 0]}},
        "6": {"class_type": "TextEncodeQwenImageEdit", "inputs": {"clip": ["2", 0], "prompt": "blurry, low quality, distorted", "vae": ["3", 0], "image": ["11", 0]}},
        "7": {"class_type": "VAEEncode", "inputs": {"pixels": ["11", 0], "vae": ["3", 0]}},
        "8": {"class_type": "KSampler", "inputs": {"seed": _seed(seed), "steps": 20, "cfg": 2.5, "sampler_name": "euler",
                                                   "scheduler": "simple", "denoise": 1.0, "model": ["1", 0],
                                                   "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0]}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "justday/edit"}},
    }


def g_upscale(image: str) -> dict:
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image}},
        "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-UltraSharp.pth"}},
        "3": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
        "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "justday/upscale"}},
    }


def g_video(prompt: str, w: int, h: int, seconds: float, seed: int | None, image: str | None = None) -> dict:
    fps = 16
    length = int(seconds * fps) // 4 * 4 + 1  # Wan wants 4k+1 frames
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_ti2v_5B_fp16.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": 8.0}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["3", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text":
              "static, frozen, blurry, low quality, distorted, deformed, watermark, text, subtitles, jitter, flicker"}},
        "7": {"class_type": "Wan22ImageToVideoLatent", "inputs": {"vae": ["4", 0], "width": w, "height": h,
                                                                  "length": length, "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {"seed": _seed(seed), "steps": 30, "cfg": 5.0, "sampler_name": "euler",
                                                   "scheduler": "simple", "denoise": 1.0, "model": ["2", 0],
                                                   "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0]}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["4", 0]}},
        "10": {"class_type": "CreateVideo", "inputs": {"images": ["9", 0], "fps": float(fps)}},
        "11": {"class_type": "SaveVideo", "inputs": {"video": ["10", 0], "filename_prefix": "justday/video",
                                                     "format": "mp4", "codec": "h264"}},
    }
    if image:
        g["12"] = {"class_type": "LoadImage", "inputs": {"image": image}}
        g["13"] = {"class_type": "ImageScale", "inputs": {"image": ["12", 0], "upscale_method": "lanczos",
                                                         "width": w, "height": h, "crop": "center"}}
        g["7"]["inputs"]["start_image"] = ["13", 0]
    return g


def g_music(tags: str, lyrics: str, seconds: float, seed: int | None) -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "ace_step_v1_3.5b.safetensors"}},
        "2": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": 5.0}},
        "3": {"class_type": "TextEncodeAceStepAudio", "inputs": {"clip": ["1", 1], "tags": tags,
                                                                 "lyrics": lyrics or "[instrumental]", "lyrics_strength": 0.99}},
        "4": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["3", 0]}},
        "5": {"class_type": "EmptyAceStepLatentAudio", "inputs": {"seconds": float(seconds), "batch_size": 1}},
        "6": {"class_type": "KSampler", "inputs": {"seed": _seed(seed), "steps": 50, "cfg": 5.0, "sampler_name": "euler",
                                                   "scheduler": "simple", "denoise": 1.0, "model": ["2", 0],
                                                   "positive": ["3", 0], "negative": ["4", 0], "latent_image": ["5", 0]}},
        "7": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveAudioMP3", "inputs": {"audio": ["7", 0], "filename_prefix": "justday/music", "quality": "V0"}},
    }


def g_3d(image: str, seed: int | None) -> dict:
    return {
        "1": {"class_type": "ImageOnlyCheckpointLoader", "inputs": {"ckpt_name": "hunyuan3d-dit-v2_fp16.safetensors"}},
        "2": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 1.0}},
        "3": {"class_type": "LoadImage", "inputs": {"image": image}},
        "4": {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["1", 1], "image": ["3", 0], "crop": "none"}},
        "5": {"class_type": "Hunyuan3Dv2Conditioning", "inputs": {"clip_vision_output": ["4", 0]}},
        "6": {"class_type": "EmptyLatentHunyuan3Dv2", "inputs": {"resolution": 3072, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {"seed": _seed(seed), "steps": 30, "cfg": 5.0, "sampler_name": "euler",
                                                   "scheduler": "normal", "denoise": 1.0, "model": ["2", 0],
                                                   "positive": ["5", 0], "negative": ["5", 1], "latent_image": ["6", 0]}},
        # octree 256: the clean-up below smooths away the stair-steps; 384+ needs more than 11 GB of RAM
        "8": {"class_type": "VAEDecodeHunyuan3D", "inputs": {"samples": ["7", 0], "vae": ["1", 2],
                                                             "num_chunks": 8000, "octree_resolution": 256}},
        "9": {"class_type": "VoxelToMesh", "inputs": {"voxel": ["8", 0], "algorithm": "surface net", "threshold": 0.6}},
        "10": {"class_type": "SaveGLB", "inputs": {"mesh": ["9", 0], "filename_prefix": "justday/mesh"}},
    }


# ───────────── jobs ─────────────
def _job_path(job: str) -> Path:
    return JOBS_DIR / f"{job}.json"


def _save_job(job: dict) -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _job_path(job["id"]).with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1))
    tmp.replace(_job_path(job["id"]))


def load_job(job: str) -> dict:
    p = _job_path(job)
    if not p.exists():
        raise RuntimeError(f"нет задачи {job}")
    return json.loads(p.read_text())


def jobs(limit: int = 10) -> list[dict]:
    if not JOBS_DIR.exists():
        return []
    files = sorted(JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out = []
    for f in files:
        try:
            j = json.loads(f.read_text())
        except ValueError:
            continue
        out.append({k: j.get(k) for k in ("id", "kind", "state", "what", "out", "error", "started")})
    return out


def start(kind: str, graph: dict, out: Path, what: str, post: dict | None = None) -> dict:
    url = engine()
    job = {"id": time.strftime("%H%M%S-") + uuid.uuid4().hex[:4], "kind": kind, "what": what, "state": "running",
           "prompt_id": submit(url, graph), "out": str(out), "post": post or {}, "started": time.time(),
           "eta_s": ETA.get(kind, 60)}
    _save_job(job)
    return job


def check(job: dict) -> dict:
    """Advance a job: when ComfyUI is done, move the file into place and post-process it.
    Several processes may wait for the same job (the background watcher, `studio job ID`): one finishes it."""
    import fcntl

    if job["state"] not in ("running", "queued"):
        return job
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    with open(JOBS_DIR / f"{job['id']}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        job = load_job(job["id"])  # someone else may have finished it meanwhile
        return _check_locked(job)


def _check_locked(job: dict) -> dict:
    if job["state"] not in ("running", "queued"):
        return job
    url = settings()["url"]
    if not _alive(url):
        job.update(state="failed", error="движок студии остановился (скорее всего, не хватило памяти)")
        _save_job(job)
        return job
    state, src, err = result(url, job["prompt_id"])
    if state in ("running", "queued"):
        job["state"] = state
        return job
    if state == "failed":
        job.update(state="failed", error=err)
    else:
        try:
            finish(job, src)
            job["state"] = "done"
        except Exception as e:  # noqa: BLE001 — reported to the user as text
            job.update(state="failed", error=str(e)[:300])
        if settings()["free_after"]:
            free(url)
    job["finished"] = time.time()
    _save_job(job)
    return job


def finish(job: dict, src: Path) -> None:
    out = Path(job["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    post = job.get("post") or {}
    if job["kind"] == "3d":
        _clean_mesh(src, out, post.get("stl", True))
    else:
        shutil.copy(src, out)
    if post.get("image_after") == "remove_bg":
        remove_bg(out, out)


def wait(job: dict, timeout: float) -> dict:
    end = time.monotonic() + timeout
    while True:
        job = check(job)
        if job["state"] not in ("running", "queued") or time.monotonic() > end:
            return job
        time.sleep(1.5)


def summary(job: dict) -> dict:
    s = {"job": job["id"], "state": job["state"]}
    if job["state"] == "done":
        s["file"] = job["out"]
        if job.get("post", {}).get("preview"):
            s["preview"] = job["post"]["preview"]
        if job.get("extra"):
            s["also"] = job["extra"]
    elif job["state"] == "failed":
        s["error"] = job.get("error")
    else:
        left = max(10, int(job.get("eta_s", 60) - (time.time() - job["started"])))
        s["ready_in_s"] = left
        s["note"] = "идёт в фоне; JustDay сам сообщит, когда будет готово"
    return s


def watch(job_id: str) -> None:
    """Background watcher (a detached process): waits for the job and tells the daemon."""
    job = load_job(job_id)
    job = wait(job, 3 * 3600)
    from .cli import control

    control("studio_done", timeout=10, job=summary(job), kind=job["kind"], what=job.get("what", ""))


def spawn_watch(job: dict) -> None:
    subprocess.Popen([sys.executable, "-m", "justday.studio", "watch", job["id"]], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                     env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])})


def run(kind: str, graph: dict, out: Path, what: str, wait_s: float, post: dict | None = None,
        notify: bool = True) -> dict:
    """Start a job; wait up to wait_s. Unfinished jobs keep going and are reported when done."""
    job = wait(start(kind, graph, out, what, post), wait_s)
    if job["state"] in ("running", "queued"):
        spawn_watch(job)
    elif job["state"] == "done" and notify:
        from .cli import control

        control("studio_done", timeout=5, job=summary(job), kind=kind, what=what, quiet=True)
    return summary(job)


# ───────────── high-level actions ─────────────
def image(prompt: str, size: str = "square", out: str | None = None, seed: int | None = None,
          transparent: bool = False, wait_s: float = 240) -> dict:
    w, h = _size(size, SIZES)
    if transparent:
        prompt += ", single object, isolated on a plain white background"
    return run("image", g_image(prompt, w, h, seed), _target(out, "image", ".png", prompt), prompt, wait_s,
               {"image_after": "remove_bg"} if transparent else None)


def edit(src: str, prompt: str, out: str | None = None, seed: int | None = None, wait_s: float = 400) -> dict:
    url = engine()
    name = _upload(url, Path(src).expanduser())
    return run("edit", g_edit(name, prompt, seed), _target(out, "image", ".png", Path(src).stem + " " + prompt),
               prompt, wait_s)


def upscale(src: str, out: str | None = None, wait_s: float = 240) -> dict:
    url = engine()
    p = Path(src).expanduser()
    return run("upscale", g_upscale(_upload(url, p)), _target(out, "image", ".png", p.stem + " 4x"), p.name, wait_s)


def video(prompt: str, seconds: float = 3, size: str = "wide", out: str | None = None, seed: int | None = None,
          src: str | None = None, wait_s: float = 20) -> dict:
    w, h = _size(size, VIDEO_SIZES)
    seconds = max(3.0, min(float(seconds), 8.0))  # shorter clips come out as mush
    url = engine()
    name = _upload(url, Path(src).expanduser()) if src else None
    kind = "animate" if src else "video"
    job = start(kind, g_video(prompt, w, h, seconds, seed, name),
                _target(out, "video", ".mp4", prompt), prompt)
    job["eta_s"] = int(ETA["video"] * seconds / 3 * (w * h) / (640 * 640))
    _save_job(job)
    job = wait(job, wait_s)
    if job["state"] in ("running", "queued"):
        spawn_watch(job)
    return summary(job)


def music(tags: str, seconds: float = 30, lyrics: str = "", out: str | None = None, seed: int | None = None,
          wait_s: float = 400) -> dict:
    seconds = max(5.0, min(float(seconds), 240.0))
    return run("music", g_music(tags, lyrics, seconds, seed), _target(out, "music", ".mp3", tags), tags, wait_s)


def model3d(src: str | None = None, prompt: str = "", out: str | None = None, seed: int | None = None,
            stl: bool = True, wait_s: float = 20) -> dict:
    url = engine()
    if not src:
        if not prompt:
            raise RuntimeError("нужна картинка или описание")
        pic = image(prompt + ", three-quarter view, whole object in frame, soft studio light, "
                             "single object, plain white background", out=str(JOBS_DIR / "3d-src") + "/",
                    seed=seed, wait_s=300)
        if pic["state"] != "done":
            return pic
        src = pic["file"]
    p = Path(src).expanduser()
    job = start("3d", g_3d(_upload(url, p), seed), _target(out, "3d", ".glb", prompt or p.stem), prompt or p.name,
                {"stl": stl, "preview": str(p)})
    job = wait(job, wait_s)
    if job["state"] in ("running", "queued"):
        spawn_watch(job)
    return summary(job)


def _size(size: str, table: dict) -> tuple[int, int]:
    if size in table:
        return table[size]
    try:
        w, h = (int(x) for x in size.lower().split("x"))
    except ValueError as e:
        raise RuntimeError(f"размер: {', '.join(table)} или ШxВ") from e
    return w, h


MESH_SCRIPT = r"""
import sys, trimesh, numpy as np
src, dst, stl = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
m = trimesh.load(src, force="mesh")
m.merge_vertices()
trimesh.smoothing.filter_taubin(m, lamb=0.5, nu=-0.53, iterations=10)
try:
    import fast_simplification
    if len(m.faces) > 80000:
        v, f = fast_simplification.simplify(m.vertices, m.faces, target_count=70000)
        m = trimesh.Trimesh(v, f, process=True)
except ImportError:
    pass
m.export(dst)
if stl:
    m.export(dst.rsplit(".", 1)[0] + ".stl")
print(len(m.vertices), len(m.faces))
"""


def _clean_mesh(src: Path, out: Path, stl: bool) -> None:
    """Hunyuan's raw mesh is an unwelded triangle soup: weld → smooth (Taubin, no shrink) → decimate."""
    py = settings()["python"]
    p = subprocess.run([str(py), "-c", MESH_SCRIPT, str(src), str(out), "1" if stl else "0"],
                       capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        shutil.copy(src, out)  # the raw mesh is still usable


RMBG_SCRIPT = r"""
import sys, torch
from PIL import Image
from torchvision import transforms
from transformers import AutoModelForImageSegmentation
dev = "cuda" if torch.cuda.is_available() else "cpu"
net = AutoModelForImageSegmentation.from_pretrained("cocktailpeanut/rm", trust_remote_code=True).to(dev).eval()
tf = transforms.Compose([transforms.Resize((1024, 1024)), transforms.ToTensor(),
                         transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
for src, dst in zip(sys.argv[1::2], sys.argv[2::2]):
    im = Image.open(src).convert("RGB")
    with torch.no_grad():
        pred = net(tf(im).unsqueeze(0).to(dev))[-1].sigmoid().cpu()[0].squeeze()
    im.putalpha(transforms.ToPILImage()(pred).resize(im.size))
    im.save(dst)
"""


def remove_bg(src: str | Path, out: str | Path | None = None) -> dict:
    s = settings()
    py = s["rmbg"] / "app/env/bin/python"
    if not py.exists():
        raise RuntimeError("модель удаления фона не установлена")
    srcp = Path(src).expanduser()
    dst = Path(out).expanduser() if out else _unique(srcp.with_name(srcp.stem + " без фона.png"))
    if dst.suffix.lower() != ".png":
        dst = dst.with_suffix(".png")
    env = {**os.environ, "HF_HOME": str(s["rmbg"] / "cache/HF_HOME"), "HF_HUB_OFFLINE": "1",
           "TRANSFORMERS_OFFLINE": "1"}
    p = subprocess.run([str(py), "-c", RMBG_SCRIPT, str(srcp), str(dst)], env=env, capture_output=True,
                       text=True, timeout=300)
    if p.returncode != 0:
        raise RuntimeError("не удалось убрать фон: " + (p.stderr.strip().splitlines() or ["?"])[-1][:200])
    return {"state": "done", "file": str(dst)}


# ───────────── voice-over and subtitles ─────────────
def speech(text: str, out: str | None = None, voice: str = "") -> dict:
    """Voice-over in JustDay's own voice (neural service when it runs, otherwise Silero)."""
    import asyncio
    import wave

    import numpy as np

    from .tts import TTS, normalize, split_sentences

    cfg = config.load()
    tcfg = dict(cfg["tts"], lang=cfg["user"]["language"])
    if voice:
        tcfg["voice"] = voice
    tts = TTS(tcfg)
    dst = _target(out, "speech", ".wav", "озвучка " + text)
    chunks: list[np.ndarray] = []
    rate = tts.rate
    neural = tcfg["engine"] == "qwen" and TTS.SOCKET.exists()

    async def neural_all():
        for s in split_sentences(normalize(text, tcfg["lang"])):
            buf = b""
            async for part in tts.stream(s):
                buf += part
            chunks.append(np.frombuffer(buf, dtype=np.int16))
            chunks.append(np.zeros(int(TTS.NEURAL_RATE * 0.25), dtype=np.int16))

    if neural:
        try:
            asyncio.run(neural_all())
            rate = TTS.NEURAL_RATE
        except OSError:
            chunks.clear()
            neural = False
    if not neural:
        if tcfg["engine"] in ("qwen", "none"):
            tcfg["engine"] = "silero"
        for s in split_sentences(normalize(text, tcfg["lang"])):
            chunks.append(tts.synth(s))
            chunks.append(np.zeros(int(rate * 0.25), dtype=np.int16))
    pcm = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return {"state": "done", "file": str(dst), "seconds": round(len(pcm) / rate, 1)}


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def transcribe(src: str, out: str | None = None, language: str = "", words_per_line: int = 7) -> dict:
    """Speech → .srt subtitles and plain text (local Whisper)."""
    from faster_whisper import WhisperModel

    cfg = config.load()["stt"]
    p = Path(src).expanduser()
    device = cfg["device"] if shutil.which("nvidia-smi") else "cpu"
    model = WhisperModel(cfg["model"], device=device,
                         compute_type=cfg["compute_type"] if device == "cuda" else "int8")
    segments, info = model.transcribe(str(p), language=language or cfg["language"] or None, beam_size=5,
                                      word_timestamps=True, vad_filter=True)
    lines, text = [], []
    for seg in segments:
        text.append(seg.text.strip())
        words = seg.words or []
        for i in range(0, len(words), words_per_line):
            chunk = words[i:i + words_per_line]
            lines.append((chunk[0].start, chunk[-1].end, "".join(w.word for w in chunk).strip()))
    dst = Path(out).expanduser() if out else p.with_suffix(".srt")
    dst.write_text("".join(f"{n}\n{_srt_time(a)} --> {_srt_time(b)}\n{t}\n\n" for n, (a, b, t) in enumerate(lines, 1)),
                   encoding="utf-8")
    txt = dst.with_suffix(".txt")
    txt.write_text("\n".join(text) + "\n", encoding="utf-8")
    return {"state": "done", "file": str(dst), "text_file": str(txt), "language": info.language,
            "seconds": round(info.duration, 1), "preview": " ".join(text)[:300]}


# ───────────── montage (ffmpeg) ─────────────
def _ff(args: list[str], timeout: float = 1800) -> None:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                       capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg: " + (p.stderr.strip().splitlines() or ["ошибка"])[-1][:300])


def probe(src: str | Path) -> dict:
    p = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(src)],
                       capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        raise RuntimeError(f"не читается: {src}")
    d = json.loads(p.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    num, _, den = (v or {}).get("r_frame_rate", "0/1").partition("/")
    return {"seconds": round(float(d["format"].get("duration", 0)), 2),
            "width": v and v.get("width"), "height": v and v.get("height"),
            "fps": round(float(num) / float(den), 2) if den and float(den) else 0, "audio": bool(a)}


def _out_for(src: str, out: str | None, suffix: str, ext: str | None = None) -> Path:
    p = Path(src).expanduser()
    if out:
        return Path(out).expanduser()
    return _unique(p.with_name(f"{p.stem} {suffix}{ext or p.suffix}"))


ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
       "-movflags", "+faststart"]


def cut(src: str, start: str, end: str = "", out: str | None = None) -> dict:
    dst = _out_for(src, out, "фрагмент")
    _ff(["-ss", start, *(["-to", end] if end else []), "-i", str(Path(src).expanduser()), *ENC, str(dst)])
    return {"state": "done", "file": str(dst)}


def join(files: list[str], out: str | None = None, width: int = 0, height: int = 0) -> dict:
    """Glue clips (and still pictures, 3 s each) one after another, scaled to the first clip's frame."""
    paths = [Path(f).expanduser() for f in files]
    first = next((probe(p) for p in paths if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp")), None)
    w = width or (first or {}).get("width") or 1920
    h = height or (first or {}).get("height") or 1080
    args, parts = [], []
    for i, p in enumerate(paths):
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            args += ["-loop", "1", "-t", "3", "-i", str(p)]
            has_audio = False
        else:
            args += ["-i", str(p)]
            has_audio = probe(p)["audio"]
        fit = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
               f"setsar=1,fps=30,format=yuv420p")
        parts.append(f"[{i}:v]{fit}[v{i}];")
        if has_audio:
            parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}];")
        else:  # silent clips and pictures get a silent track of the same length
            parts.append(f"aevalsrc=0:c=stereo:s=48000:d={_dur(p)}[a{i}];")
    streams = "".join(f"[v{i}][a{i}]" for i in range(len(paths)))
    graph = "".join(parts) + f"{streams}concat=n={len(paths)}:v=1:a=1[v][a]"
    dst = Path(out).expanduser() if out else _target(None, "video", ".mp4", "монтаж " + paths[0].stem)
    _ff([*args, "-filter_complex", graph, "-map", "[v]", "-map", "[a]", *ENC, str(dst)])
    return {"state": "done", "file": str(dst), "seconds": probe(dst)["seconds"]}


def _dur(p: Path) -> float:
    return 3.0 if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") else probe(p)["seconds"]


def add_audio(src: str, audio: str, out: str | None = None, volume: float = 0.35, replace: bool = False) -> dict:
    """Background music / voice-over under a video; music is looped and faded out at the end."""
    v = Path(src).expanduser()
    info = probe(v)
    dur = info["seconds"]
    dst = _out_for(src, out, "со звуком", ".mp4")
    fade = f"afade=t=out:st={max(0, dur - 2)}:d=2"
    if replace or not info["audio"]:
        graph = f"[1:a]volume={1 if replace else volume},{fade}[a]"
    else:
        graph = f"[1:a]volume={volume},{fade}[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]"
    _ff(["-i", str(v), "-stream_loop", "-1", "-i", str(Path(audio).expanduser()), "-filter_complex", graph,
         "-map", "0:v", "-map", "[a]", "-t", str(dur), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(dst)])
    return {"state": "done", "file": str(dst)}


def subtitles(src: str, srt: str | None = None, out: str | None = None, burn: bool = True) -> dict:
    """Subtitles into the video: burned in (big white text, like shorts) or as a switchable track."""
    v = Path(src).expanduser()
    s = Path(srt).expanduser() if srt else v.with_suffix(".srt")
    if not s.exists():
        s = Path(transcribe(str(v))["file"])
    dst = _out_for(src, out, "с субтитрами", ".mp4")
    if burn:
        info = probe(v)
        size = 13 if (info["height"] or 0) > (info["width"] or 1) else 18
        style = (f"FontName=Inter,FontSize={size},Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                 f"BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=40")
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "subs.srt"
            shutil.copy(s, local)
            _ff(["-i", str(v), "-vf", f"subtitles={local}:force_style='{style}'", *ENC, str(dst)])
    else:
        _ff(["-i", str(v), "-i", str(s), "-map", "0", "-map", "1", "-c", "copy", "-c:s", "mov_text", str(dst)])
    return {"state": "done", "file": str(dst), "srt": str(s)}


def vertical(src: str, out: str | None = None, mode: str = "blur") -> dict:
    """9:16 for Shorts/TikTok/Reels: blurred background (keeps the whole frame) or centre crop."""
    dst = _out_for(src, out, "вертикальное", ".mp4")
    if mode == "crop":
        vf = "crop=ih*9/16:ih,scale=1080:1920,setsar=1"
        _ff(["-i", str(Path(src).expanduser()), "-vf", vf, *ENC, str(dst)])
    else:
        graph = ("[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                 "boxblur=30:3,eq=brightness=-0.08[bg];[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]")
        _ff(["-i", str(Path(src).expanduser()), "-filter_complex", graph, "-map", "[v]", "-map", "0:a?", *ENC, str(dst)])
    return {"state": "done", "file": str(dst)}


def trim_silence(src: str, out: str | None = None, min_pause: float = 0.6, noise_db: int = -35) -> dict:
    """Cut out pauses longer than min_pause (talking-head videos, podcasts)."""
    import re

    v = Path(src).expanduser()
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(v), "-af", f"silencedetect=n={noise_db}dB:d={min_pause}",
                        "-f", "null", "-"], capture_output=True, text=True, timeout=1800)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", p.stderr)]
    dur = probe(v)["seconds"]
    keep, pos = [], 0.0
    for s, e in zip(starts, ends + [dur] * (len(starts) - len(ends))):
        if s - pos > 0.05:
            keep.append((pos, s + 0.15))  # keep a breath
        pos = max(pos, e - 0.15)
    if dur - pos > 0.05:
        keep.append((pos, dur))
    if len(keep) <= 1 and not starts:
        return {"state": "done", "file": str(v), "note": "пауз не нашлось"}
    sel = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in keep)
    dst = _out_for(src, out, "без пауз", ".mp4")
    has_audio = probe(v)["audio"]
    args = ["-i", str(v), "-vf", f"select='{sel}',setpts=N/FRAME_RATE/TB"]
    if has_audio:
        args += ["-af", f"aselect='{sel}',asetpts=N/SR/TB"]
    _ff([*args, *ENC, str(dst)])
    return {"state": "done", "file": str(dst), "was_s": dur, "now_s": probe(dst)["seconds"], "cuts": len(starts)}


def speed(src: str, factor: float, out: str | None = None) -> dict:
    factor = max(0.25, min(float(factor), 4.0))
    atempo = f"atempo={factor}" if factor >= 0.5 else f"atempo={factor ** 0.5:.4f},atempo={factor ** 0.5:.4f}"
    dst = _out_for(src, out, f"x{factor:g}", ".mp4")
    has_audio = probe(src)["audio"]
    _ff(["-i", str(Path(src).expanduser()), "-vf", f"setpts=PTS/{factor}",
         *(["-af", atempo] if has_audio else ["-an"]), *ENC, str(dst)])
    return {"state": "done", "file": str(dst)}


def gif(src: str, out: str | None = None, width: int = 480, fps: int = 12, start: str = "", seconds: float = 0) -> dict:
    dst = _out_for(src, out, "", ".gif")
    graph = f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse=dither=bayer"
    _ff([*(["-ss", start] if start else []), *(["-t", str(seconds)] if seconds else []),
         "-i", str(Path(src).expanduser()), "-vf", graph, str(dst)])
    return {"state": "done", "file": str(dst)}


def slideshow(images: list[str], out: str | None = None, per_image: float = 3.0, audio: str = "",
              size: str = "1920x1080") -> dict:
    """Pictures → video with a gentle zoom (Ken Burns) and cross-fades; optional music."""
    w, h = (int(x) for x in size.split("x"))
    paths = [Path(p).expanduser() for p in images]
    fade = 0.6
    frames = int(per_image * 30)
    args, parts = [], []
    for i, p in enumerate(paths):
        args += ["-loop", "1", "-t", str(per_image), "-i", str(p)]
        parts.append(f"[{i}:v]scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
                     f"zoompan=z='min(zoom+0.0008,1.12)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                     f"s={w}x{h}:fps=30,setsar=1,format=yuv420p[v{i}];")
    last, offset = "v0", per_image - fade
    for i in range(1, len(paths)):
        parts.append(f"[{last}][v{i}]xfade=transition=fade:duration={fade}:offset={offset:.2f}[x{i}];")
        last, offset = f"x{i}", offset + per_image - fade
    graph = "".join(parts).rstrip(";")
    dst = Path(out).expanduser() if out else _target(None, "video", ".mp4", "слайдшоу " + paths[0].stem)
    total = per_image * len(paths) - fade * (len(paths) - 1)
    cmd = [*args]
    if audio:
        cmd += ["-stream_loop", "-1", "-i", str(Path(audio).expanduser())]
        graph += f";[{len(paths)}:a]afade=t=out:st={max(0, total - 2):.2f}:d=2[a]"
    cmd += ["-filter_complex", graph, "-map", f"[{last}]", *(["-map", "[a]"] if audio else []),
            "-t", f"{total:.2f}", *ENC, str(dst)]
    _ff(cmd)
    return {"state": "done", "file": str(dst), "seconds": round(total, 1)}


def thumbnail(src: str | Path, dst: Path) -> Path | None:
    """A still frame for the island card (videos) — pictures are shown as they are."""
    src = Path(src)
    if src.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        return src
    if src.suffix.lower() not in (".mp4", ".webm", ".mkv", ".mov", ".gif"):
        return None
    try:
        _ff(["-ss", "0.5", "-i", str(src), "-frames:v", "1", "-vf", "scale=480:-2", str(dst)], timeout=30)
        return dst
    except (RuntimeError, subprocess.SubprocessError):
        return None


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "watch":
        watch(sys.argv[2])
