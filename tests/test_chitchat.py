"""Болтовня отвечается местно, а просьба с «привет» в начале всё равно идёт Claude."""
import pytest

from justday import chitchat, localllm

CFG = {"brain": {"tiny_model": "qwen3:0.6b"}, "user": {"assistant_name": "Джарвис"}}


@pytest.mark.parametrize("text", ["Привет!", "привет, Джарвис", "Как дела?", "джарвис, ты тут", "спокойной ночи", "Ты молодец"])
def test_chit_chat_is_recognised(text):
    assert chitchat.kind(text)


@pytest.mark.parametrize("text", [
    "привет, открой дискорд",            # просьба с приветствием
    "как дела в школе у Маши",           # вопрос про мир, а не про него
    "как ты думаешь, стоит ли брать ноутбук",
    "ты тут можешь отправить письмо",
    "расскажи как дела с обновлением",
    "ок", "ладно", "хорошо", "ага",      # ответ на вопрос Claude («запустить?») — это «да», не болтовня
    "пока не выключай музыку",
    "",
])
def test_anything_serious_goes_up_to_claude(text):
    assert chitchat.kind(text) == ""


def test_tiny_model_speaks_when_it_answers_sanely(monkeypatch):
    seen = {}
    monkeypatch.setattr(localllm, "chat", lambda system, user, **kw: seen.update(kw) or "<think>…</think>Всё хорошо, спасибо!")
    assert chitchat.reply("how", "как дела", CFG) == "Всё хорошо, спасибо!"
    assert seen["model"] == "qwen3:0.6b" and seen["keep_alive"] == "1m"


@pytest.mark.parametrize("junk", ["Sure! I am fine.", "x" * 400, "см. https://example.org", "```py\nprint(1)\n```", ""])
def test_strange_model_output_falls_back_to_a_ready_phrase(monkeypatch, junk):
    monkeypatch.setattr(localllm, "chat", lambda *a, **kw: junk)
    assert chitchat.reply("how", "как дела", CFG) in chitchat.CANNED["how"]


def test_no_ollama_or_no_model_still_answers_fast(monkeypatch):
    def down(*a, **kw):
        raise OSError("ollama не запущен")

    monkeypatch.setattr(localllm, "chat", down)
    assert chitchat.reply("greet", "привет", CFG) in chitchat.CANNED["greet"]
    # модель не названа — к Ollama даже не обращаемся
    monkeypatch.setattr(localllm, "chat", lambda *a, **kw: pytest.fail("ходили в модель, которой нет в настройках"))
    assert chitchat.reply("bye", "пока", {"brain": {"tiny_model": ""}}) in chitchat.CANNED["bye"]


@pytest.mark.parametrize("what,wrong", [("how", "Спокойной ночи!"), ("here", "Привет!"), ("bye", "Хорошо, спасибо!")])
def test_off_topic_model_answer_is_replaced(monkeypatch, what, wrong):
    """Живая qwen3:0.6b на «как жизнь» отвечала «Спокойной ночи!» — ответ не по теме хуже готовой фразы."""
    monkeypatch.setattr(localllm, "chat", lambda *a, **kw: wrong)
    assert chitchat.reply(what, "x", CFG) in chitchat.CANNED[what]


def test_service_tokens_of_the_model_never_reach_the_voice(monkeypatch):
    """Живая модель однажды ответила «Пока /no_think» — это прочли бы вслух."""
    monkeypatch.setattr(localllm, "chat", lambda *a, **kw: "Пока /no_think")
    assert chitchat.reply("bye", "пока", CFG) in chitchat.CANNED["bye"]
