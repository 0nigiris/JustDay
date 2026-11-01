"""Экстренная перезагрузка: снимок отладки должен лечь на диск раньше перезапуска.

Беда: остров застыл, человек перезапустил службы, и журнал, по которому можно было понять причину,
прокрутился. Снимок пишется без права чтения чужим (в журнале бывают куски разговоров)."""
from pathlib import Path

from justday import rescue


def test_bundle_writes_private_file(tmp_path):
    path = rescue.bundle(tmp_path)
    assert path.parent == tmp_path and path.read_text().startswith("JustDay: снимок")
    assert path.stat().st_mode & 0o077 == 0


def test_hotkey_is_declared_everywhere():
    from justday.manage import HOTKEYS
    assert any(name == "rescue" for name, _, _ in HOTKEYS)
    script = Path(rescue.__file__).parents[2] / "scripts" / "setup-hotkey.sh"
    assert '"rescue|' in script.read_text()
