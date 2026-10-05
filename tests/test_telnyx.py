"""Настоящий звонок: Джарвис набирает номер и говорит в трубку.

Беды, ради которых написаны эти проверки, стоят денег. Звонок — единственное место в JustDay,
где ошибка в коде списывается с карты, поэтому проверяется не «работает ли», а «не разорит ли».
"""
from __future__ import annotations

import pytest

from justday import telnyx


def test_the_assistant_must_never_dial_a_premium_line() -> None:
    """Платные справочные (900, 902, 803, 806…) стоят не центы, а до 68 центов за минуту.

    Ассистент, который сам ищет номер в картах, однажды найдёт именно такой. Это не настройка
    и не предупреждение — такие номера он не набирает вовсе.
    """
    for bad in ("+34902123456", "+34900112233", "+34803555666", "+34806111222"):
        with pytest.raises(RuntimeError, match="справочная"):
            telnyx.check_number(bad)


def test_a_number_without_a_country_code_would_dial_somewhere_else() -> None:
    """«600111222» без кода страны — это не испанский мобильный, а неизвестно что.

    Набирать такое значит звонить наугад за чужой счёт. Проверка требует международного вида.
    """
    for bad in ("600111222", "8 800 555", "", "кебабня"):
        with pytest.raises(RuntimeError, match="международном"):
            telnyx.check_number(bad)


def test_an_ordinary_mobile_goes_through_untouched() -> None:
    """Обычный мобильный — это дешёвый случай ($0.023/мин), и ему мешать не надо."""
    assert telnyx.check_number("+34 612 345 678") == "+34612345678"
    assert telnyx.check_number("+1-555-010-9999") == "+15550109999"


def test_a_call_in_a_loop_would_run_for_an_hour_unnoticed() -> None:
    """Потолок по времени существует затем, что худший случай — шестьдесят центов, а не час.

    Разговор «вы сегодня открыты?» дольше полутора минут не бывает ни у кого.
    """
    assert telnyx.MAX_SECONDS <= 90, "потолок разговора вырос — незамеченный звонок станет дорогим"


def test_it_says_what_is_missing_instead_of_failing_silently(monkeypatch) -> None:
    """Без ключа, номера или туннеля звонок невозможен — и это надо сказать словами.

    Молчаливый отказ здесь означает, что человек ждёт звонка, которого не будет.
    """
    monkeypatch.setattr(telnyx, "key", lambda: "")
    ok, why = telnyx.ready()
    assert not ok and "secret-tool" in why, "про отсутствующий ключ никто не сказал"
    monkeypatch.setattr(telnyx, "key", lambda: "KEY")
    monkeypatch.setattr(telnyx, "settings", dict)
    ok, why = telnyx.ready()
    assert not ok and "номер" in why, "про отсутствующий свой номер никто не сказал"


def test_the_webhook_listener_binds_to_localhost_only() -> None:
    """Слушатель событий звонка не должен появляться на внешнем интерфейсе.

    Правило проекта: наружу не смотрит ничего. Публичный адрес даёт туннель — соединение,
    которое наша машина открывает сама, — а не открытый порт.
    """
    import inspect

    src = inspect.getsource(telnyx.call)
    assert '("127.0.0.1", port)' in src, "слушатель событий больше не привязан к localhost"
    assert "0.0.0.0" not in src, "порт открылся на внешнем интерфейсе"


def test_a_premium_number_was_refused_only_after_the_key_was_set(monkeypatch) -> None:
    """«Эту цифру не набирать» — запрет, а не следствие того, что ключ ещё не положен.

    Сначала проверка готовности отвечала «нет ключа» даже на платную справочную: человек клал
    ключ, покупал номер и только тогда узнавал настоящую причину отказа.
    """
    monkeypatch.setattr(telnyx, "key", lambda: "")
    got = telnyx.call("+34902123456", "проверка")
    assert "справочная" in got.get("error", ""), "платный номер отклоняется не первым делом"


# ───────────── подпись и размер события (Р-7 ревизии) ─────────────
def _signed_server(monkeypatch):
    """Настоящий слушатель на localhost с настоящим ключом Ed25519; возвращает (порт, закрыть, ключ, вызовы _api)."""
    import base64
    import http.server
    import threading

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    pub = base64.b64encode(priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    calls = []
    monkeypatch.setattr(telnyx, "_api", lambda method, path, body=None: calls.append(path) or {})
    monkeypatch.setattr(telnyx._Hook, "public_key", pub)
    job = {"text": "x", "answered": 0.0, "done": False}
    monkeypatch.setattr(telnyx._Hook, "said", {"cc1": job})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), telnyx._Hook)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, priv, job, calls


def _post(srv, body: bytes, headers: dict, length: str | None = None) -> int:
    import http.client

    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    c.putrequest("POST", "/")
    for k, v in headers.items():
        c.putheader(k, v)
    if length is not None:
        c.putheader("Content-Length", length)
    c.endheaders(body)
    try:
        return c.getresponse().status
    finally:
        c.close()


def test_only_events_signed_by_telnyx_move_a_call(monkeypatch) -> None:
    """Адрес туннеля виден всему интернету: без подписи любой подставил бы свой call_control_id в запросы с нашим ключом."""
    import base64
    import json
    import time

    srv, priv, job, calls = _signed_server(monkeypatch)
    try:
        body = json.dumps({"data": {"event_type": "call.answered", "payload": {"call_control_id": "cc1"}}}).encode()
        ts = str(int(time.time()))
        sig = base64.b64encode(priv.sign(ts.encode() + b"|" + body)).decode()
        good = {"telnyx-signature-ed25519": sig, "telnyx-timestamp": ts}
        assert _post(srv, body, {}, str(len(body))) == 403, "событие без подписи принято"
        assert _post(srv, body, {**good, "telnyx-signature-ed25519": sig[:-4] + "AAAA"}, str(len(body))) == 403
        old = str(int(time.time()) - 3600)
        old_sig = base64.b64encode(priv.sign(old.encode() + b"|" + body)).decode()
        assert _post(srv, body, {"telnyx-signature-ed25519": old_sig, "telnyx-timestamp": old}, str(len(body))) == 403, \
            "перехваченное событие часовой давности принято"
        assert not job["answered"] and calls == []
        assert _post(srv, body, good, str(len(body))) == 200
        for _ in range(50):            # ответ уходит раньше, чем обработано событие
            if job["answered"]:
                break
            time.sleep(0.05)
        assert job["answered"] and calls == ["/calls/cc1/actions/speak"]
    finally:
        srv.shutdown()


def test_a_stranger_call_id_gets_no_request_to_telnyx(monkeypatch) -> None:
    import base64
    import json
    import time

    srv, priv, job, calls = _signed_server(monkeypatch)
    try:
        body = json.dumps({"data": {"event_type": "call.answered", "payload": {"call_control_id": "чужой"}}}).encode()
        ts = str(int(time.time()))
        sig = base64.b64encode(priv.sign(ts.encode() + b"|" + body)).decode()
        _post(srv, body, {"telnyx-signature-ed25519": sig, "telnyx-timestamp": ts}, str(len(body)))
        time.sleep(0.3)
        assert calls == [] and not job["answered"]
    finally:
        srv.shutdown()


def test_an_oversized_or_unsized_body_is_not_read(monkeypatch) -> None:
    srv, _, _, calls = _signed_server(monkeypatch)
    try:
        assert _post(srv, b"", {}, str(telnyx.MAX_BODY + 1)) == 413, "гигантское тело принято к чтению"
        assert _post(srv, b"", {}, None) == 411, "тело без длины принято к чтению"
        assert calls == []
    finally:
        srv.shutdown()


def test_calling_needs_the_webhook_public_key_to_be_set(monkeypatch) -> None:
    monkeypatch.setattr(telnyx, "key", lambda: "KEY")
    monkeypatch.setattr(telnyx, "settings", lambda: {"from": "+1", "app_id": "A"})
    ok, why = telnyx.ready()
    assert not ok and "публичного ключа" in why
