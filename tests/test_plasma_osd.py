"""Plasma OSD mute follows island.show_osd (plasmarc + plasmaparc)."""
from __future__ import annotations

from justday import notifications as notif


def test_plasma_osd_writes_durable_keys(monkeypatch):  # type: ignore[no-untyped-def]
    writes: list[tuple[str, str, str, str]] = []

    def fake_run(cmd, **kwargs):
        # kwriteconfig6 --file F --group G --key K V
        if cmd and cmd[0] == "kwriteconfig6":
            file = cmd[cmd.index("--file") + 1]
            group = cmd[cmd.index("--group") + 1]
            key = cmd[cmd.index("--key") + 1]
            value = cmd[-1]
            writes.append((file, group, key, value))

        class R:
            stdout = ""
            returncode = 0

        return R()

    monkeypatch.setattr(notif.subprocess, "run", fake_run)

    got = notif.plasma_osd(False)
    assert got["ok"] and got["osd"] is False
    assert ("plasmarc", "OSD", "Enabled", "false") in writes
    assert ("plasmarc", "OSD", "kbdLayoutChangedEnabled", "false") in writes
    assert ("plasmaparc", "General", "VolumeOsd", "false") in writes
    assert ("plasmaparc", "General", "MuteOsd", "false") in writes

    writes.clear()
    got = notif.plasma_osd(True)
    assert got["ok"] and got["osd"] is True
    assert ("plasmarc", "OSD", "Enabled", "true") in writes
    assert ("plasmaparc", "General", "VolumeOsd", "true") in writes


def test_sync_plasma_osd_follows_show_osd(monkeypatch):  # type: ignore[no-untyped-def]
    seen: list[bool] = []

    monkeypatch.setattr(notif, "plasma_osd", lambda on=None: seen.append(on) or {"ok": True, "osd": on})
    monkeypatch.setattr(
        "justday.config.load",
        lambda: {"island": {"show_osd": True, "system_popups": False}},
    )
    notif.sync_plasma_osd()
    assert seen[-1] is False  # Plasma muted

    seen.clear()
    notif.sync_plasma_osd(show_osd=False)
    assert seen[-1] is True  # Plasma restored
