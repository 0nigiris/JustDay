"""QR для телефона: Wi-Fi с «;» в имени сети ломал запись, а пустой ввод должен отказывать, а не рисовать мусор."""
import pytest

from justday import qr


def test_wifi_name_with_special_characters_is_escaped():
    bs = chr(92)  # обратная косая: в литерале рядом с «;» её легко съесть
    assert qr.wifi_payload("Дом;2", "p:a,ss") == f"WIFI:T:WPA;S:Дом{bs};2;P:p{bs}:a{bs},ss;;"


def test_open_network_has_no_password_and_hidden_is_marked():
    assert qr.wifi_payload("Кафе") == "WIFI:T:nopass;S:Кафе;P:;;"
    assert qr.wifi_payload("Кафе", "x", "WEP", hidden=True) == "WIFI:T:WEP;S:Кафе;P:x;H:true;;"


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
