"""П23: обновление проваливалось с «Не удалось: justday update» — без причины, человек не знал, что чинить."""
import subprocess

from justday import modules


def test_failed_update_notice_carries_the_reason(tmp_path):
    log = tmp_path / "update.log"
    log.write_text("Обновляю: 3 изменений\ngit pull не удался: Could not resolve host: github.com\n\n")
    said = subprocess.run(["bash", "-c", f'echo "Не удалось: {modules._why(log)}"'], capture_output=True, text=True).stdout
    assert "Could not resolve host" in said and str(log) in said
