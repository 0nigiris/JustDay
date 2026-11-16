from justday import config, island


def test_old_install_is_not_greeted_again():
    """У кого JustDay уже стоит, ключа onboarded в конфиге нет: знакомство не должно выскочить после обновления."""
    assert config.DEFAULTS["user"]["onboarded"] is True
    assert island.settings_snapshot(config.load())["onboarded"] is True


def test_menu_order_default_lists_every_block():
    """Правка меню: у блока без места в menu_order не было бы строки в редакторе, и его нельзя было бы вернуть."""
    import re
    from pathlib import Path

    from justday.config import DEFAULTS
    isl = DEFAULTS["island"]
    qml = (Path(__file__).parent.parent / "island" / "ExpandedView.qml").read_text(encoding="utf-8")
    ids = re.findall(r'"(\w+)"', re.search(r"blockIds: \[(.*?)\]", qml, re.S).group(1))
    assert isl["menu_order"] == ids
    # у нижнего ряда свои флаги (уведомления и недавнее), режим сервера гасит экраны и спрятан нарочно
    assert all(isl.get(f"menu_{b}", True) is True for b in ids if b not in ("lists", "t_server"))
    assert isl["menu_t_server"] is False


def test_persona_does_not_claim_plasma6_wayland_on_x11(monkeypatch):
    """Школьный ПК: Plasma 5 и X11, а мозгу в промпте говорили «Plasma 6, Wayland» и не перезапускать kwin_wayland."""
    from justday import kde
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setattr(kde, "KWRITE", "kwriteconfig5")
    assert kde.session() == ("5", "x11")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(kde, "KWRITE", "kwriteconfig6")
    assert kde.session() == ("6", "wayland")
