from justday import media


def test_titles_with_signs_and_digits_go_after_letters():
    """В медиатеке «(Remix)» и «2 Phut Hon» лежали первыми и закрывали весь алфавит."""
    names = ["Zebra", "(Remix)", "Abba", "2 Phut", "Яблоко"]
    assert sorted(names, key=media._abc) == ["Abba", "Zebra", "Яблоко", "(Remix)", "2 Phut"]
