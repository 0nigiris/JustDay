"""Просил будильник на 16:20 «потому что у меня собрание» — на экране появилось «пожалуйста, то, что у меня собрание»."""
from justday import reminders


def label(text):
    return reminders.parse(text)["label"]


def test_the_reason_after_because_became_the_label_not_the_whole_phrase():
    assert label("поставь будильник на 16:20, пожалуйста, потому что у меня собрание") == "Собрание"


def test_recognised_to_chto_instead_of_potomu_chto_still_gives_the_meeting():
    assert label("поставь будильник на 16:20 пожалуйста то, что у меня собрание") == "Собрание"


def test_plain_requests_keep_their_old_labels():
    assert label("напомни через 10 минут позвонить маме") == "Позвонить маме"
    assert label("поставь будильник на 7:30") == ""
    assert label("напомни в 18:00 про собрание") == "Собрание"
