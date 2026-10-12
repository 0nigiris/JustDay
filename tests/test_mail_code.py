from justday import mail


def _letter(subject, body):
    return mail.Letter("1", "Банк", "a@b.c", subject, "", body, "")


def test_code_is_read_from_newest_letter_and_not_kept(monkeypatch):
    """«Дай код с почты»: берём код из свежего письма, а письма в разговоре не оседают."""
    got = mail.find_code([_letter("Привет", "без цифр"), _letter("Ваш код", "Код подтверждения: 482915. Никому не говорите.")])
    assert got == ("Банк", "482915")
    monkeypatch.setattr(mail, "fetch", lambda *a, **k: [_letter("Код", "123 456")])
    ma = mail.MailAssistant()
    reply, expects = ma.handle("дай код с почты")
    assert "1 2 3 4 5 6" in reply and not expects and ma.letters == [] and ma.last_action == "code"
