import json

from justday import school


def test_адрес_из_строки_браузера_не_ломает_вход():
    """В AULES.txt он вставил адрес из браузера: с /login/index.php или без https — токен просили
    бы по несуществующему пути, и Джарвис отвечал бы «школа не отвечает»."""
    want = "https://aules.edu.gva.es/eso03"
    for raw in ("aules.edu.gva.es/eso03", "https://aules.edu.gva.es/eso03/",
                "https://aules.edu.gva.es/eso03/login/index.php", " https://aules.edu.gva.es/eso03/my/ "):
        assert school.base(raw) == want


def test_выключенные_уведомления_не_прячут_сроки(monkeypatch):
    """Плагин всплывающих уведомлений на сайте могут выключить — сроки заданий всё равно нужны."""
    monkeypatch.setattr(school, "_secret", lambda k: {"site": "aules.edu.gva.es/eso03"}.get(k, "x"))

    def post(url, data):
        fn = data.get("wsfunction")
        if url.endswith("token.php"):
            return {"token": "t"}
        if fn == "core_webservice_get_site_info":
            return {"userid": 7}
        if fn == "core_calendar_get_action_events_by_timesort":
            return {"events": [{"name": "Redacció", "timesort": 0, "course": {"fullname": "Valencià"}}]}
        raise RuntimeError("plugin off")

    monkeypatch.setattr(school, "_post", post)
    out = school.news(now=0)
    assert out["ok"] and out["deadlines"][0]["course"] == "Valencià" and out["unread"] == []
    json.dumps(out)


def test_без_ключей_честно_говорит_чего_нет(monkeypatch):
    monkeypatch.setattr(school, "_secret", lambda k: "")
    assert not school.news()["ok"]
