

def test_label_does_not_keep_create_verb():
    """Будильник «Создай будильник на 17:30» подписывался словами команды: «создай» не срезалось."""
    from justday.reminders import _label
    assert _label("Создай будильник на 17:30") == ""
    assert _label("добавь напоминание в 18:00 позвонить маме") == "Позвонить маме"
