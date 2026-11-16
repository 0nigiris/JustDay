from pathlib import Path

K = Path(__file__).parent.parent / "island/icons/kubai"


def test_значки_kubai_не_уходят_без_лицензии_и_не_теряются():
    """Kubai Icons под MIT: без текста лицензии рядом раздавать их нельзя. А полоска, которой нет в
    list.js, просто не покажется — плитка тихо вернётся к старому значку."""
    assert "MIT" in (K / "LICENSE").read_text(encoding="utf-8")
    listed = (K / "list.js").read_text(encoding="utf-8")
    for png in K.glob("*.png"):
        assert f'"{png.stem}":true' in listed, png.name
