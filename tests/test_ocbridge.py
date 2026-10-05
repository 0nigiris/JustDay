"""Мост разрешений OpenCode: опасный шаг на ступени ниже ждёт кнопки, а не выполняется молча (пункт 31, хвост 2)."""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from justday import ocbridge, terminal


def sse(obj) -> bytes:
    return b"data: " + json.dumps(obj).encode() + bytes([10, 10])


class FakeOpenCode:
    """Сервер с теми же ручками, что у настоящего: /config, /session, /event (SSE), /message, /permission/…/reply."""

    def __init__(self, permission=None):
        self.permission = permission if permission is not None else dict.fromkeys(ocbridge.ASK, "ask")
        self.replies: list[dict] = []
        self.aborted = False
        self.model = None
        self.got = threading.Event()
        self.listening = threading.Event()
        self.sse = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, obj):
                data = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/config":
                    return self._json({"permission": outer.permission})
                if self.path == "/event":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.write(sse({"type": "server.connected", "properties": {}}))
                    self.wfile.flush()
                    outer.sse.append(self.wfile)
                    outer.listening.set()
                    outer.got.wait(30)
                    return

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/session":
                    return self._json({"id": "ses_1"})
                if self.path.endswith("/abort"):
                    outer.aborted = True
                    return self._json(True)
                if self.path.endswith("/message"):
                    outer.model = body.get("model")
                    outer.listening.wait(5)
                    ev = {"type": "permission.asked", "properties": {
                        "id": "per_1", "sessionID": "ses_1", "permission": "bash", "patterns": ["rm -rf /tmp/x"],
                        "metadata": {"command": "rm -rf /tmp/x"}}}
                    outer.sse[0].write(sse(ev))
                    outer.sse[0].flush()
                    outer.got.wait(10)          # ждём ответа человека
                    ran = outer.replies and outer.replies[-1]["reply"] == "once"
                    return self._json({"info": {"tokens": {"input": 5, "output": 7, "cache": {"read": 1, "write": 0}}},
                                       "parts": [{"type": "tool", "tool": "bash"} if ran else {"type": "text", "text": "отклонено"},
                                                 {"type": "text", "text": "готово" if ran else "не стал"}], "_model": body.get("model")})
                if "/permission/" in self.path and self.path.endswith("/reply"):
                    outer.replies.append(body)
                    outer.got.set()
                    return self._json(True)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.client = ocbridge.Client(f"http://127.0.0.1:{self.srv.server_address[1]}", "pw")

    def close(self):
        self.got.set()
        self.srv.shutdown()


def run(approve, fake=None):
    fake = fake or FakeOpenCode()
    seen = []
    try:
        out = asyncio.run(asyncio.wait_for(
            ocbridge.turn(fake.client, "удали x", "", "ollama/qwen3.5:9b", approve, seen.append, seen.append), 20))
    finally:
        fake.close()
    return fake, out, seen


def test_a_dangerous_step_waits_for_the_human_and_runs_after_yes():
    asked = []

    async def approve(what, why):
        asked.append(what)
        return True

    fake, out, _ = run(approve)
    assert asked == ["OpenCode: bash — rm -rf /tmp/x"]
    assert fake.replies == [{"reply": "once"}], "«всегда» не отправляется никогда"
    assert out["tools"] == ["bash"] and out["text"] == "готово" and out["session"] == "ses_1" and out["used"] == 13


def test_no_means_reject_and_so_do_silence_and_crashes():
    async def no(what, why):
        return False

    async def broken(what, why):
        raise RuntimeError("телеграм упал")

    for approve in (no, broken, None):
        fake, out, _ = run(approve)
        assert fake.replies == [{"reply": "reject"}], f"{approve}: опасный шаг не должен был пройти"
        assert out["tools"] == []


def test_server_that_would_not_ask_is_not_used():
    """Чей-то проектный opencode.json разрешил bash — наш «ask» перебит; хода не начинаем."""
    fake = FakeOpenCode(permission={**dict.fromkeys(ocbridge.ASK, "ask"), "bash": "allow"})
    try:
        with pytest.raises(ocbridge.Unsafe, match="bash"):
            fake.client.check_asks()
        FakeOpenCode(permission="ask").client.check_asks()          # общий «ask» тоже годится
    finally:
        fake.close()


def test_model_is_split_into_provider_and_name():
    fake, _, _ = run(None)
    assert fake.model == {"providerID": "ollama", "modelID": "qwen3.5:9b"}


def test_the_remote_rung_uses_the_bridge_only_when_asked_to_and_a_human_can_answer(monkeypatch):
    """Рабочий стол обходился без моста — он остаётся как был; ночью (спросить некого) мост не включается."""
    from types import SimpleNamespace

    calls = []

    async def fake_ask(*a, **kw):
        calls.append(a[2])
        return {"session": "ses_9", "text": "ok", "tools": [], "used": 0, "error": ""}

    monkeypatch.setattr(terminal.ocbridge, "ask", fake_ask)

    async def fake_run(cmd, env, on_line, quiet=90.0):
        calls.append("run")
        return [], ""

    monkeypatch.setattr(terminal, "_run", fake_run)
    rung = SimpleNamespace(model="ollama/qwen3.5:9b")

    async def go(opts):
        return await terminal.ask_opencode(rung, "t", "", {"terminal": opts}, lambda s: None, lambda s: None)

    async def yes(what, why):
        return True

    got = asyncio.run(go({"approve": yes, "bridge": True}))
    assert calls == ["ollama/qwen3.5:9b"] and got.session == "ses_9" and got.text == "ok"
    calls.clear()
    asyncio.run(go({"approve": yes}))                                  # не оболочка телефона
    asyncio.run(go({"approve": yes, "bridge": True, "unattended": True}))   # ночь
    assert calls == ["run", "run"]
