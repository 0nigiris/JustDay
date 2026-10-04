"""Список команд в docs/КОМАНДЫ.md не отстаёт от настоящего (Р-66 ревизии: документы не знали 15 команд)."""
import re
import subprocess
import sys
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "docs" / "КОМАНДЫ.md"


def test_every_command_is_in_the_commands_doc():
    out = subprocess.run([sys.executable, "-c", "from justday import cli; cli.main(['--help'])"],
                         capture_output=True, text=True, timeout=60).stdout
    names = re.search(r"\{([^}]+)\}", out).group(1).split(",")
    doc = DOC.read_text(encoding="utf-8")
    missing = [n for n in names if f"`justday {n}`" not in doc]
    assert not missing, f"в docs/КОМАНДЫ.md нет команд: {', '.join(missing)}"
