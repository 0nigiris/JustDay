"""«Кофе» (Р3-30): раньше экран держали две службы, запущенные руками, и после перезагрузки они
пропадали — монитор снова гас посреди его работы. Теперь включённость в настройке, а службы
заводит демон; повторный вызов не плодит вторые копии, выключение гасит обе."""

from justday import server


def test_coffee_starts_both_once_and_stops_both(monkeypatch):
    calls = []
    active = set()

    def run(*cmd, timeout=10):
        calls.append(cmd)
        if cmd[:3] == ("systemctl", "--user", "is-active"):
            return cmd[-1].removesuffix(".service") in active
        if cmd[0] == "systemd-run":
            active.add(next(a for a in cmd if a.startswith("--unit=")).split("=", 1)[1])
        return True

    monkeypatch.setattr(server, "_run", run)
    monkeypatch.setattr(server.shutil, "which", lambda name: "/usr/bin/" + name)

    server.coffee(True)
    server.coffee(True)  # демон перезапущен — вторых служб быть не должно
    assert active == set(server.COFFEE_UNITS)
    assert sum(c[0] == "systemd-run" for c in calls) == 2

    calls.clear()
    server.coffee(False)
    assert {c[-1] for c in calls if c[:3] == ("systemctl", "--user", "stop")} == {u + ".service" for u in server.COFFEE_UNITS}
