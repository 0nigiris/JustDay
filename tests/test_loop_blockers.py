"""Синхронные вызовы в цикле событий демона (Р-31, Р-32, Р-33): зависший `secret-tool`, `kreadconfig6` на каждый
шаг ползунка громкости или `notify-send` замораживали весь демон — слух, голос и островок разом."""
from __future__ import annotations

import subprocess
import threading
import time

from justday import island, manage, providers


class Запуски:
    """Подставной subprocess.run: считает вызовы и, если надо, медлит или зависает."""

    def __init__(self, stdout: str = "", delay: float = 0.0, hang: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.stdout, self.delay, self.hang = stdout, delay, hang

    def __call__(self, cmd, *a, **kw):
        self.calls.append(list(cmd))
        if self.hang:
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout") or 0)
        time.sleep(self.delay)
        return subprocess.CompletedProcess(cmd, 0, stdout=self.stdout, stderr="")


def test_ключ_спрашивают_у_связки_один_раз(monkeypatch) -> None:
    запуски = Запуски(stdout="token\n")
    monkeypatch.setattr(providers.subprocess, "run", запуски)
    monkeypatch.setattr(providers.shutil, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(providers, "_from_stick", lambda n: "")
    providers._SECRETS.clear()
    assert [providers.secret_get("telegram_token") for _ in range(5)] == ["token"] * 5
    assert len(запуски.calls) == 1


def test_зависшая_связка_не_спрашивается_каждые_две_секунды(monkeypatch) -> None:
    """Пустой календарь опрашивал `secret-tool` каждые 2 с без таймаута: KWallet встал — встал и демон."""
    запуски = Запуски(hang=True)
    monkeypatch.setattr(providers.subprocess, "run", запуски)
    monkeypatch.setattr(providers.shutil, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(providers, "_from_stick", lambda n: "")
    providers._SECRETS.clear()
    assert [providers.secret_get("calendar") for _ in range(5)] == [""] * 5
    assert len(запуски.calls) == 1


def test_сохранённый_ключ_находится_сразу(monkeypatch) -> None:
    запуски = Запуски(stdout="")
    monkeypatch.setattr(providers.subprocess, "run", запуски)
    monkeypatch.setattr(providers.shutil, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(providers, "_from_stick", lambda n: "")
    providers._SECRETS.clear()
    assert providers.secret_get("mail") == ""
    запуски.stdout = "pw\n"
    providers.secret_set("mail", "pw")
    assert providers.secret_get("mail") == "pw"


def test_снимок_настроек_не_читает_клавиши_в_цикле_событий(monkeypatch) -> None:
    """Каждый шаг ползунка публиковал настройки, а снимок 20 раз запускал kreadconfig6 (150–600 мс)."""
    запуски = Запуски(delay=0.05)
    monkeypatch.setattr(manage.subprocess, "run", запуски)
    monkeypatch.setattr(manage, "_shortcut", lambda desktop_id: ["Meta+X"])
    manage._HOTKEYS_CACHE.update(value={}, at=0.0, busy=False)
    started = time.monotonic()
    island._hotkeys()  # протухший кэш: ответ сразу, обновление — в фоне
    assert time.monotonic() - started < 0.05
    for _ in range(100):
        if manage._HOTKEYS_CACHE["at"]:
            break
        time.sleep(0.02)
    assert island._hotkeys()["talk"] == "Meta+X"
    assert island._hotkeys()["talk"] == "Meta+X"  # и дальше — из памяти


def test_уведомление_не_держит_демон(monkeypatch) -> None:
    from justday import daemon as daemon_mod

    запуски = Запуски(stdout="7", delay=0.3)
    monkeypatch.setattr(daemon_mod.subprocess, "run", запуски)
    d = daemon_mod.Daemon.__new__(daemon_mod.Daemon)
    d.cfg = {"ui": {"notifications": True}}
    d._notify_id = 0
    started = time.monotonic()
    d.notify("привет")
    assert time.monotonic() - started < 0.1
    for t in threading.enumerate():
        if t.name == "notify":
            t.join(2)
    assert d._notify_id == 7


def test_следующая_фраза_синтезируется_пока_играет_предыдущая() -> None:
    """Silero синтезировал фразу только когда дойдёт очередь: к каждой фразе прибавлялись 0,1–0,5 с (Р-53)."""
    import asyncio

    from justday import daemon as daemon_mod

    d = daemon_mod.Daemon.__new__(daemon_mod.Daemon)
    d._synth_ahead = {}
    d.tts = type("T", (), {"cfg": {"engine": "silero"}, "synth": staticmethod(lambda s: len(s))})()

    async def run():
        d._synth_in_advance("привет")
        d._synth_in_advance("привет")  # повторно не запускается
        assert list(d._synth_ahead) == ["привет"]
        assert await d._synth_ahead["привет"] == 6
        d.tts.cfg["engine"] = "qwen"  # потоковый голос не трогаем
        d._synth_in_advance("пока")
        assert "пока" not in d._synth_ahead

    asyncio.run(run())
