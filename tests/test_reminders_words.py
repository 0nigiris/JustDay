from justday import reminders


def test_spoken_numbers_and_loose_word_order_still_make_a_timer():
    """«Минут на десять», «засеки две минуты», «двадцать пять минут» уходили нейросети вместо мгновенного таймера."""
    for phrase, span in [("ну поставь мне пожалуйста таймер минут на десять", 600), ("засеки две минуты", 120),
                         ("заведи таймер двадцать пять минут", 1500), ("поставь таймер на пять минут", 300)]:
        got = reminders.parse(phrase)
        assert got and got["kind"] == "timer" and got["span"] == span, phrase
    assert reminders.parse("ну поставь таймер на 5 минут")["label"] == ""
    assert reminders.parse("поставь будильник на семь утра")["kind"] == "alarm"
