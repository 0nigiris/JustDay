"""QR сопряжения с телефоном: пустой ввод должен отказывать, а не рисовать мусор, и код должен читаться камерой."""
import pytest

from justday import qr


def test_matrix_is_square_and_encodes_a_link():
    rows = qr.matrix("https://example.org/a?b=1")
    assert len(rows) == len(rows[0]) >= 21 and set("".join(rows)) == {"0", "1"}
    # три поисковых квадрата в углах: у каждого центр и рамка тёмные
    assert rows[0][:7] == "1111111" and rows[0][-7:] == "1111111" and rows[-1][:7] == "1111111"


def test_empty_text_is_refused():
    with pytest.raises(ValueError):
        qr.matrix("")


def test_ascii_art_is_square_in_characters():
    art = qr.ascii_art(qr.matrix("hi")).splitlines()
    assert len(set(map(len, art))) == 1 and len(art[0]) == 21 + 8
