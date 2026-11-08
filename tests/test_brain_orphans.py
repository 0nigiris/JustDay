"""После перезапуска демона оставался жить старый claude с детьми (7 нояб.): закрытие SDK тянется
дольше срока остановки, и обрезанное закрытие его не добивало. Демон теперь добивает всё дерево сам,
а для этого дерево должно находиться целиком, включая внуков."""

import subprocess
import time
from types import SimpleNamespace

from justday.brain import Brain


def test_cli_tree_finds_grandchildren():
    p = subprocess.Popen(["sh", "-c", "sh -c 'sleep 30' & sleep 30"])
    try:
        time.sleep(0.3)
        b = Brain.__new__(Brain)
        b.client = SimpleNamespace(_transport=SimpleNamespace(_process=p))
        tree = b.cli_tree()
        assert tree[0] == p.pid
        assert len(tree) >= 3  # sh, вложенный sh, хотя бы один sleep
    finally:
        subprocess.run(["pkill", "-P", str(p.pid)])
        p.kill()


def test_cli_tree_without_client_is_empty():
    b = Brain.__new__(Brain)
    b.client = None
    assert b.cli_tree() == []
