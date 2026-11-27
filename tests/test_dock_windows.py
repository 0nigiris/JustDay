"""Док на Windows: программы из «Пуска» должны узнавать свои окна, а новый док — не быть пустым."""
import json
import subprocess

from justday import config, desktop, dock, launcher


def test_window_finds_its_app_by_exe(monkeypatch):
    """У окна Windows есть только имя exe («chrome»). Раньше у программ «Пуска» не было ни exe, ни
    значка: каждое окно в доке вставало вторым значком-кляксой рядом с закреплённым."""
    got = [{"Name": "Google Chrome", "AppID": "Chrome", "Exe": r"C:\Program Files\Google\Chrome\Application\chrome.exe"},
           {"Name": "Калькулятор", "AppID": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App", "Exe": None}]
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(got), ""))
    chrome, calc = desktop._scan_windows_apps()
    assert chrome["wmclass"] == "chrome" and "chrome" in dock.match_keys(chrome)
    assert chrome["icon"].startswith("image://icon/win:")
    assert calc["wmclass"] == "" and calc["icon"].endswith("Microsoft.WindowsCalculator_8wekyb3d8bbwe%21App")


def test_new_windows_dock_is_not_empty(monkeypatch):
    """Категорий у программ Windows нет, и стартовый набор по категориям давал пустой док."""
    monkeypatch.setattr(config, "WINDOWS", True)
    monkeypatch.setattr(launcher, "favourites", lambda: [])
    monkeypatch.setattr(desktop, "list_apps", lambda: [
        {"id": "Chrome", "wmclass": "chrome"}, {"id": "Microsoft.Windows.Explorer", "wmclass": ""},
        {"id": "Telegram.TelegramDesktop", "wmclass": "telegram"}])
    assert dock._seed() == ["app:Microsoft.Windows.Explorer", "app:Chrome", "app:Telegram.TelegramDesktop"]
