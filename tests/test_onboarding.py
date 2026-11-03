from justday import config, island


def test_old_install_is_not_greeted_again():
    """У кого JustDay уже стоит, ключа onboarded в конфиге нет: знакомство не должно выскочить после обновления."""
    assert config.DEFAULTS["user"]["onboarded"] is True
    assert island.settings_snapshot(config.load())["onboarded"] is True


def test_menu_order_default_lists_every_block():
    """Правка меню: у блока без места в menu_order не было бы строки в редакторе, и его нельзя было бы вернуть."""
    from justday.config import DEFAULTS
    isl = DEFAULTS["island"]
    assert sorted(isl["menu_order"]) == ["ask", "event", "lists", "model", "player", "sound"]
    assert all(isl[f"menu_{b}"] is True for b in isl["menu_order"] if b != "lists")   # у нижнего ряда свои флаги: уведомления и недавнее
