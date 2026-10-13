from justday import launcher


def test_search_counts_like_a_calculator_but_does_not_run_code() -> None:
    """Spotlight без калькулятора заставлял открывать программу ради «2+2»; eval вместо него был бы дырой."""
    assert launcher.calc("2+2*3") == "8"
    assert launcher.calc("(10-3)/4") == "1,75"
    assert launcher.calc("2^10") == "1024"
    assert launcher.calc("__import__('os').system('x')") is None
    assert launcher.calc("1") is None and launcher.calc("firefox") is None
