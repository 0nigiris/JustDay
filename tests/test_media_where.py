"""Где включить видео: место, названное прямо в просьбе."""
from justday import media


def test_place_is_taken_out_of_the_query():
    assert media.where_asked("включи видео про котов в островке") == ("island", "включи видео про котов")
    assert media.where_asked("поставь видео с гуся в окне") == ("window", "поставь видео с гуся")
    assert media.where_asked("включи видео про кота на ютубе") == ("browser", "включи видео про кота")


def test_a_place_in_the_title_is_not_a_place():
    # «на острове» — про необитаемый остров, а не про остров сверху экрана
    assert media.where_asked("включи видео про выживание на острове")[0] == ""
    assert media.where_asked("включи видео про ютуб")[0] == ""
    assert media.where_asked("включи видео про кота")[0] == ""


def test_the_instant_path_keeps_the_query_clean():
    # мгновенный путь отдаёт поиск как есть, место из него вырезает play_video
    assert media.parse("включи видео про котов в островке") == ("video", "котов в островке")
    # сказано только место, искать нечего — пусть разбирается модель
    assert media.parse("включи видео в островке") is None
