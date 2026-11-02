from justday import config, island


def test_old_install_is_not_greeted_again():
    """У кого JustDay уже стоит, ключа onboarded в конфиге нет: знакомство не должно выскочить после обновления."""
    assert config.DEFAULTS["user"]["onboarded"] is True
    assert island.settings_snapshot(config.load())["onboarded"] is True
