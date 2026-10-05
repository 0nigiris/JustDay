"""Мост разрешений OpenCode: подтверждение опасного шага — кнопкой на телефоне (пункт 31, хвост 2).

Почему не `opencode run`. Он не отдаёт вызывающему запрос разрешения: на телефоне кнопка просто не появилась
бы, а шаг либо выполнился сам, либо отклонился молча. Заменять это флагом «разрешать всё» нельзя — это
снятая защита. Единственный честный путь — серверный интерфейс OpenCode: он присылает событие
`permission.asked` и ждёт ответа `once` или `reject`.

Как устроено.
  — `opencode serve` поднимается на 127.0.0.1 со случайным портом и случайным паролем, на один ход;
  — разрешения `bash`, `edit`, `webfetch`, `external_directory`, `doom_loop`, `task` переведены в «спрашивать»
    переменной `OPENCODE_CONFIG_CONTENT`, а перед ходом мы читаем итоговый конфиг сервера и, если там хоть
    одно не «ask» (чей-то проектный opencode.json разрешил всё), хода не начинаем: лучше отказ, чем шаг без
    вопроса;
  — вопрос уходит человеку через `approve(что, почему)`; ответ «нет», сбой и молчание — `reject`.
    «Всегда» не предлагается и никогда не отправляется: одно «да» — один шаг.
Если событие не пришло (сервер сменил имена событий), всё равно безопасно: сервер ждёт ответа, и ход
повисает, а не выполняется."""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import secrets
import socket
import subprocess
import threading
import time
import urllib.request

ASK = ("bash", "edit", "webfetch", "external_directory", "doom_loop", "task")
CONFIG = {"permission": {k: "ask" for k in ASK}}
BOOT_S = 25.0
DESC_MAX = 400


class Unsafe(RuntimeError):
    """Сервер не гарантирует вопроса перед опасным шагом — работать с ним нельзя."""


class Client:
    """Тонкий HTTP-клиент к одному серверу OpenCode (блокирующий: зовут из потоков)."""

    def __init__(self, base: str, password: str) -> None:
        self.base = base.rstrip("/")
        self.auth = "Basic " + base64.b64encode(f"opencode:{password}".encode()).decode()

    def call(self, method: str, path: str, body: dict | None = None, timeout: float = 30.0):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Authorization": self.auth, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
        return json.loads(raw) if raw else None

    def events(self, stop: threading.Event):
        """События сервера по одному, пока не скажут стоп или не оборвётся соединение.

        Читаем без короткого таймаута: оборванная посреди строки попытка чтения теряет её начало. Поток
        кончается сам, когда сервер потушен в конце хода."""
        req = urllib.request.Request(self.base + "/event", headers={"Authorization": self.auth})
        with urllib.request.urlopen(req, timeout=3600) as r:
            while not stop.is_set():
                line = r.readline()
                if not line:
                    return
                if line.startswith(b"data:"):
                    with contextlib.suppress(ValueError):
                        yield json.loads(line[5:])

    def check_asks(self) -> None:
        """Убедиться, что опасное спрашивается. Иначе — `Unsafe`."""
        perm = (self.call("GET", "/config") or {}).get("permission")
        bad = [k for k in ASK if (perm.get(k) if isinstance(perm, dict) else perm) != "ask"]
        if bad:
            raise Unsafe("OpenCode не спросит перед: " + ", ".join(bad))


def describe(props: dict) -> tuple[str, str]:
    """(что, почему) для человека по событию `permission.asked`."""
    what = str(props.get("permission") or "действие")
    patterns = ", ".join(str(p) for p in props.get("patterns") or [])
    meta = props.get("metadata") or {}
    detail = str(meta.get("command") or meta.get("filepath") or patterns or "")
    return f"OpenCode: {what}" + (f" — {detail}" if detail else ""), ""


async def serve(cli: str, env: dict[str, str], cwd: str | None = None) -> tuple[subprocess.Popen, Client]:
    """Поднять сервер на этот ход; вернуть процесс и клиента. Не поднялся — исключение."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    password = secrets.token_urlsafe(24)
    proc = subprocess.Popen(
        [cli, "serve", "--hostname", "127.0.0.1", "--port", str(port)], cwd=cwd,
        env={**env, "OPENCODE_SERVER_PASSWORD": password, "OPENCODE_CONFIG_CONTENT": json.dumps(CONFIG)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    client = Client(f"http://127.0.0.1:{port}", password)
    loop = asyncio.get_running_loop()
    deadline = time.monotonic() + BOOT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("opencode serve завершился, не начав работу")
        try:
            await loop.run_in_executor(None, client.check_asks)
            return proc, client
        except Unsafe:
            stop(proc)
            raise
        except Exception:
            await asyncio.sleep(0.3)
    stop(proc)
    raise TimeoutError("opencode serve не отвечает")


def stop(proc: subprocess.Popen) -> None:
    with contextlib.suppress(Exception):
        proc.terminate()
        proc.wait(timeout=5)
    if proc.poll() is None:
        with contextlib.suppress(Exception):
            proc.kill()


async def turn(client: Client, text: str, session: str, model: str, approve, on_text, on_tool) -> dict:
    """Один ход через сервер. Возвращает {"session", "text", "tools", "used", "error"}.

    `approve(что, почему) -> bool` — спрашивает человека; None — отвечать отказом на всё."""
    loop = asyncio.get_running_loop()
    out = {"session": session, "text": "", "tools": [], "used": 0, "error": ""}
    if not session:
        out["session"] = session = (await loop.run_in_executor(None, client.call, "POST", "/session", {}))["id"]
    body: dict = {"parts": [{"type": "text", "text": text}]}
    if model and "/" in model:
        provider, _, name = model.partition("/")
        body["model"] = {"providerID": provider, "modelID": name}

    stop_ev = threading.Event()
    asked: asyncio.Queue = asyncio.Queue()

    def watch() -> None:
        try:
            for ev in client.events(stop_ev):
                if ev.get("type") == "permission.asked":
                    loop.call_soon_threadsafe(asked.put_nowait, ev.get("properties") or {})
        except Exception:
            pass

    threading.Thread(target=watch, daemon=True, name="oc-events").start()
    work = loop.run_in_executor(None, lambda: client.call("POST", f"/session/{session}/message", body, timeout=3600))

    async def answer(props: dict) -> None:
        if props.get("sessionID") not in (None, session):
            return
        ok = False
        if approve:
            what, why = describe(props)
            try:
                ok = bool(await approve(what[:DESC_MAX], why))
            except asyncio.CancelledError:
                raise
            except Exception:
                ok = False
        await loop.run_in_executor(None, client.call, "POST", f"/permission/{props.get('id')}/reply",
                                   {"reply": "once" if ok else "reject"})

    pending: set[asyncio.Task] = set()
    try:
        while not work.done():
            getter = asyncio.ensure_future(asked.get())
            done, _ = await asyncio.wait({work, getter}, return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                pending.add(asyncio.ensure_future(answer(getter.result())))
            else:
                getter.cancel()
        reply = work.result()
    except asyncio.CancelledError:
        # Отмена («/стоп»): прервать работу сервера, иначе модель продолжит в пустоту.
        with contextlib.suppress(Exception):
            await loop.run_in_executor(None, client.call, "POST", f"/session/{session}/abort", None, 5)
        raise
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"[:400]
        reply = None
    finally:
        stop_ev.set()
        for t in pending:
            t.cancel()
    if reply:
        info = reply.get("info") or {}
        if err := info.get("error"):
            out["error"] = str((err.get("data") or {}).get("message") or err.get("name") or err)[:400]
        tok = info.get("tokens") or {}
        cache = tok.get("cache") or {}
        out["used"] = (sum(int(tok.get(k) or 0) for k in ("input", "output"))
                       + sum(int(cache.get(k) or 0) for k in ("read", "write")))
        for part in reply.get("parts") or []:
            if part.get("type") == "text" and part.get("text"):
                out["text"] += part["text"]
                on_text(part["text"])
            elif part.get("type") == "tool" and part.get("tool"):
                out["tools"].append(str(part["tool"]))
                on_tool(str(part["tool"]))
    return out


async def ask(cli: str, env: dict[str, str], rung_model: str, text: str, session: str, approve,
              on_text, on_tool, cwd: str | None = None) -> dict:
    """Поднять сервер, сделать один ход, потушить сервер."""
    proc, client = await serve(cli, env, cwd)
    try:
        return await turn(client, text, session, rung_model, approve, on_text, on_tool)
    finally:
        stop(proc)


__all__ = ["ASK", "CONFIG", "Client", "Unsafe", "ask", "describe", "serve", "stop", "turn"]
