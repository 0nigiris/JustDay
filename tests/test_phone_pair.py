"""Приложение на телефоне знало только адрес одного дома: чужому человеку оно было бесполезно (Р2-21)."""
import subprocess
from urllib.parse import parse_qs, urlparse

import pytest

from justday import phone


def test_the_qr_carries_the_whole_address_to_the_app():
    """Адрес с портом и путём не должен обрезаться на первом `:` или `&`: приложение берёт его из
    `url=` целиком и показывает человеку перед тем, как сохранить."""
    url = "http://host.tail1.ts.net:8080/a?b=1&c=2"
    link = urlparse(phone.pair_link(url))
    assert (link.scheme, link.netloc) == ("remo32", "pair")
    assert parse_qs(link.query)["url"] == [url]


def test_without_an_address_the_tailscale_name_is_used(monkeypatch):
    def run(*a, **k):
        return subprocess.CompletedProcess(a, 0, stdout='{"Self": {"DNSName": "vasya.tail9.ts.net."}}')

    monkeypatch.setattr(phone.subprocess, "run", run)
    assert parse_qs(urlparse(phone.pair_link()).query)["url"] == ["https://vasya.tail9.ts.net/"]


def test_no_tailscale_says_what_to_do_instead_of_a_broken_code(monkeypatch):
    def run(*a, **k):
        raise FileNotFoundError("tailscale")

    monkeypatch.setattr(phone.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="justday phone pair https://"):
        phone.pair_link()
    with pytest.raises(RuntimeError):
        phone.pair_link("javascript:alert(1)")
