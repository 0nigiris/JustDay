"""Private mail lane: Gmail (or any IMAP/SMTP mailbox) handled entirely on this computer.

Letters are fetched over IMAP, summarised and replies are drafted by the *local* model (Ollama), and sent over
SMTP after a spoken confirmation. Nothing from the mailbox is ever given to the cloud brain.
Gmail's own categories do the spam filtering: only "Primary" is read; promotions/social are just counted.
The password is a Google "app password" stored in the desktop keyring (`justday mail setup`).
"""
from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import json
import re
import smtplib
import ssl
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from html.parser import HTMLParser

from . import config, contacts, events, localllm, providers

MAIL_WORDS = re.compile(r"\b(почт\w*|письм\w*|писем|имейл\w*|емейл\w*|e-?mail\w*|мейл\w*|gmail|джимейл\w*|inbox|входящ\w*)\b", re.I)


# ---------------- IMAP / SMTP ----------------
class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        self._skip += tag in ("style", "script")

    def handle_endtag(self, tag):
        self._skip -= tag in ("style", "script") and self._skip > 0

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _decode(value: str | None) -> str:
    return str(email.header.make_header(email.header.decode_header(value or ""))) if value else ""


def _body(msg: email.message.Message, limit: int = 2500) -> str:
    plain, html = "", ""
    for part in msg.walk():
        if part.get_content_maintype() != "text" or part.get_filename():
            continue
        try:
            text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        if part.get_content_subtype() == "plain" and not plain:
            plain = text
        elif part.get_content_subtype() == "html" and not html:
            p = _Text()
            p.feed(text)
            html = " ".join(p.parts)
    text = plain or html
    text = re.sub(r"(?m)^>.*$", "", text)  # quoted previous messages
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _settings() -> tuple[dict, str]:
    m = config.load()["mail"]
    if not m.get("address"):
        raise RuntimeError("почта не настроена: justday mail setup")
    pw = providers.secret_get("mail")
    if not pw:
        raise RuntimeError("нет пароля приложения в связке ключей: justday mail setup")
    return m, pw


def _imap() -> imaplib.IMAP4_SSL:
    m, pw = _settings()
    box = imaplib.IMAP4_SSL(m["imap_host"], 993, ssl_context=ssl.create_default_context(), timeout=20)
    box.login(m["address"], pw)
    return box


def _all_mail(box: imaplib.IMAP4_SSL) -> str:
    """Gmail's "All Mail" folder name is localised; find it by its \\All flag."""
    _, lines = box.list()
    for raw in lines or []:
        line = raw.decode(errors="replace")
        if "\\All" in line:
            return line.rsplit(' "/" ', 1)[-1]
    return "INBOX"


@dataclass
class Letter:
    uid: str
    sender: str
    address: str
    subject: str
    date: str
    body: str
    message_id: str = ""


def _search(box: imaplib.IMAP4_SSL, gmail_query: str) -> list[bytes]:
    if config.load()["mail"]["imap_host"].endswith("gmail.com"):
        typ, data = box.uid("SEARCH", "X-GM-RAW", f'"{gmail_query}"')
    else:  # generic IMAP: unread only
        typ, data = box.uid("SEARCH", "UNSEEN")
    return data[0].split() if typ == "OK" and data and data[0] else []


def fetch(query: str, limit: int = 10, folder: str = "INBOX") -> list[Letter]:
    box = _imap()
    try:
        box.select(folder if folder != "ALL" else _all_mail(box), readonly=True)  # readonly: nothing marked as read
        uids = _search(box, query)[-limit:][::-1]
        out = []
        for uid in uids:
            _, data = box.uid("FETCH", uid, "(BODY.PEEK[]<0.150000>)")
            raw = next((d[1] for d in data if isinstance(d, tuple)), b"")
            msg = email.message_from_bytes(raw)
            name, addr = email.utils.parseaddr(_decode(msg.get("From")))
            out.append(Letter(uid.decode(), name or addr, addr, _decode(msg.get("Subject")), msg.get("Date", ""),
                              _body(msg), msg.get("Message-ID", "")))
        return out
    finally:
        box.logout()


def count(query: str) -> int:
    box = _imap()
    try:
        box.select("INBOX", readonly=True)
        return len(_search(box, query))
    finally:
        box.logout()


def find_address(name: str) -> str:
    """Resolve "мама" / "Петя" to an address from past correspondence (sent or received)."""
    if "@" in name:
        return name.strip()
    known, _ = contacts.email_for(name)
    if known:
        return known
    for letter in fetch(f"from:({name}) OR to:({name})", limit=5, folder="ALL"):
        if letter.address and name.lower() in (letter.sender + letter.address).lower():
            contacts.upsert(letter.sender or name, email=letter.address, aliases=[name])  # learned from the mailbox
            return letter.address
    return ""


def send(to: str, subject: str, body: str, in_reply_to: str = "", attachments: list[str] | None = None) -> None:
    import mimetypes
    from pathlib import Path

    m, pw = _settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = m["address"], to, subject
    if in_reply_to:
        msg["In-Reply-To"] = msg["References"] = in_reply_to
    msg.set_content(body)
    for path in attachments or []:
        p = Path(path).expanduser()
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name)
    with smtplib.SMTP_SSL(m["smtp_host"], 465, context=ssl.create_default_context(), timeout=30) as s:
        s.login(m["address"], pw)
        s.send_message(msg)
    events.emit("mail_sent", to=to)  # no subject/body in the journal


# ---------------- voice assistant (local model) ----------------
SUMMARY_PROMPT = """Ты голосовой помощник. Перескажи новые письма по-русски для озвучки: коротко, разговорно, без markdown и списков.
Для каждого письма: от кого (имя, не адрес) и суть в нескольких словах. Порядковые номера называй («первое», «второе»), чтобы пользователь мог сказать «прочитай второе».
Если писем много, объедини однотипные (например, уведомления GitHub). Не выдумывай ничего, чего нет в письмах. Не больше 5 предложений."""

READ_PROMPT = """Ты голосовой помощник. Перескажи письмо по-русски для озвучки: от кого, суть, что от пользователя хотят (если хотят).
Без markdown, 2–4 предложения. Ссылки и подписи не зачитывай. Не выдумывай."""

DRAFT_PROMPT = """Ты пишешь письмо от имени пользователя. Верни JSON {{"subject": "...", "body": "..."}}.
Пиши на языке, на котором к адресату обращались в переписке (по умолчанию русский), естественно, как написал бы сам пользователь, без канцелярита.
Только то, что просил пользователь: не добавляй вопросов, предложений, пожеланий и деталей от себя. Коротко: обычно 1–3 предложения.
Подпись: {name}."""

INTENT_PROMPT = """Ты разбираешь голосовую команду о почте. Верни только JSON:
{"action": "summary|read|reply|compose|send|cancel|edit|not_mail", "index": номер письма из списка или 0, "to": "кому (для compose)", "what": "что написать или какую правку внести"}
summary — что пришло / проверь почту; read — прочитать/пересказать письмо; reply — ответить на письмо из списка; compose — написать новое письмо кому-то;
send — подтверждение отправки черновика («да», «отправляй»); cancel — не отправлять; edit — изменить черновик; not_mail — команда не про почту."""


@dataclass
class MailAssistant:
    letters: list[Letter] = field(default_factory=list)
    draft: dict | None = None
    active_until: float = 0.0
    last_action: str = ""
    last_letter: Letter | None = None
    last_sent: dict | None = None

    def wants(self, text: str) -> bool:
        return bool(MAIL_WORDS.search(text)) or time.monotonic() < self.active_until

    def handle(self, text: str) -> tuple[str, bool] | None:
        """Returns (spoken reply, expects an answer) or None if the utterance is not about mail."""
        listing = "\n".join(f"{i}. от {l.sender}: {l.subject}" for i, l in enumerate(self.letters, 1)) or "(нет)"
        draft = json.dumps(self.draft, ensure_ascii=False) if self.draft else "(нет)"
        raw = localllm.chat(INTENT_PROMPT, f"Письма в разговоре:\n{listing}\nЧерновик: {draft}\nКоманда: {text}",
                            json_mode=True, max_tokens=150)
        try:
            intent = json.loads(raw)
        except json.JSONDecodeError:
            intent = {"action": "not_mail"}
        action = intent.get("action", "not_mail")
        self.last_action = action
        events.emit("mail_intent", action=action)  # the command text is already in the journal; no mail content
        if action == "not_mail" and not MAIL_WORDS.search(text):
            self.active_until = 0
            return None
        self.active_until = time.monotonic() + 120
        idx = int(intent.get("index") or 0)
        letter = self.letters[idx - 1] if 0 < idx <= len(self.letters) else None
        try:
            if action == "send" and self.draft:
                d, self.draft = self.draft, None
                send(d["to"], d["subject"], d["body"], d.get("in_reply_to", ""), d.get("attachments"))
                self.last_sent = d
                return "Отправил.", False
            if action == "send" and self.letters:  # "да" after "новое письмо от … Сказать, о чём?"
                return self._summary(cached=True)
            if action == "cancel":
                self.draft = None
                return "Хорошо, не отправляю.", False
            if action == "edit" and self.draft:
                return self._draft(self.draft["to"], self.draft["name"],
                                   f"{self.draft['body']}\n\nПравка: {intent.get('what', text)}",
                                   self.draft.get("in_reply_to", ""), self.draft["subject"])
            if action == "read":
                letter = letter or (self.letters[0] if self.letters else None)
                if not letter:
                    return "Сначала скажите «проверь почту».", False
                self.last_letter = letter
                return localllm.chat(READ_PROMPT, f"От: {letter.sender}\nТема: {letter.subject}\n\n{letter.body}"), False
            if action == "reply":
                letter = letter or (self.letters[0] if len(self.letters) == 1 else None)
                if not letter:
                    return "На какое письмо ответить?", True
                context = f"Отвечаем на письмо от {letter.sender}, тема «{letter.subject}»:\n{letter.body[:1500]}\n\n"
                subject = letter.subject if letter.subject.lower().startswith("re:") else f"Re: {letter.subject}"
                return self._draft(letter.address, letter.sender, context + f"Что ответить: {intent.get('what', text)}",
                                   letter.message_id, subject)
            if action == "compose":
                who = (intent.get("to") or "").strip()
                addr = find_address(who) if who else ""
                if not addr:
                    return f"Не нашёл адрес для «{who or 'получателя'}». Скажите адрес или имя, как в переписке.", True
                return self._draft(addr, who, f"Что написать: {intent.get('what', text)}")
            return self._summary()
        except RuntimeError as e:
            return f"Почта не настроена: {e}.", False
        except (imaplib.IMAP4.error, smtplib.SMTPException, OSError) as e:
            events.emit("mail_error", error=type(e).__name__)
            return "Не получилось связаться с почтой.", False

    def card(self, reply: str) -> dict | None:
        """What the Dynamic Island shows for the last mail action (rendered locally, never sent anywhere)."""
        if self.draft:
            from pathlib import Path

            return {"type": "mail_draft", "to": self.draft["name"] or self.draft["to"], "address": self.draft["to"],
                    "subject": self.draft["subject"], "body": self.draft["body"],
                    "attachments": [Path(a).name for a in self.draft.get("attachments") or []]}
        if self.last_action == "send" and self.last_sent:
            s, self.last_sent = self.last_sent, None
            return {"type": "mail_sent", "to": s["name"] or s["to"], "subject": s["subject"]}
        if self.last_action == "read" and self.last_letter:
            return {"type": "mail_read", "from": self.last_letter.sender, "subject": self.last_letter.subject, "text": reply}
        if self.letters and self.last_action in ("summary", "send", "not_mail"):
            return {"type": "mail_list", "text": reply,
                    "items": [{"n": i, "from": l.sender, "subject": l.subject} for i, l in enumerate(self.letters, 1)]}
        return None

    def _summary(self, cached: bool = False) -> tuple[str, bool]:
        m = config.load()["mail"]
        tail = ""
        if not cached:
            self.letters = fetch(m["query"], limit=m["max_letters"])
            other = count(m["other_query"])
            tail = f" Ещё {other} в рекламе и соцсетях, их не читал." if other else ""
        if not self.letters:
            return "Новых важных писем нет." + tail, False
        listing = "\n\n".join(f"Письмо {i}. От: {l.sender}\nТема: {l.subject}\n{l.body[:600]}"
                              for i, l in enumerate(self.letters, 1))
        return localllm.chat(SUMMARY_PROMPT, listing, max_tokens=350) + tail, False

    def compose(self, who: str, about: str, attachments: list[str]) -> tuple[str, bool] | None:
        """Draft requested by the brain ("send this file to mom"). None = address unknown (the brain should ask)."""
        from pathlib import Path

        addr = find_address(who)
        if not addr:
            return None
        _, name = contacts.email_for(who)
        files = [str(Path(a).expanduser()) for a in attachments if Path(a).expanduser().is_file()]
        self.last_action = "compose"
        self.active_until = time.monotonic() + 120
        note = f"\nВложения: {', '.join(Path(f).name for f in files)}" if files else ""
        reply = self._draft(addr, name or who, f"Что написать: {about}{note}")
        if self.draft is not None:
            self.draft["attachments"] = files
        return reply

    def _draft(self, to: str, name: str, instruction: str, in_reply_to: str = "", subject: str = "") -> tuple[str, bool]:
        user = config.load()["user"].get("name") or ""
        raw = localllm.chat(DRAFT_PROMPT.format(name=user or "без подписи"), instruction, json_mode=True, max_tokens=500)
        d = json.loads(raw)
        self.draft = {"to": to, "name": name, "subject": subject or d.get("subject", ""), "body": d.get("body", ""),
                      "in_reply_to": in_reply_to}
        return f"Кому: {name or to}. Текст: «{self.draft['body']}». Отправить?", True

    # ---- new-mail announcements (daemon housekeeping) ----
    def check_new(self) -> str:
        m = config.load()["mail"]
        state = events.load_state()
        seen = int(state.get("mail_last_uid", 0))
        letters = fetch(m["query"], limit=5)
        fresh = [l for l in letters if int(l.uid) > seen]
        if letters:
            events.save_state(mail_last_uid=max(int(l.uid) for l in letters))
        if not fresh or not seen:  # first run: just remember where we are
            return ""
        self.letters = fresh
        self.active_until = time.monotonic() + 120
        senders = ", ".join(dict.fromkeys(l.sender for l in fresh))
        return f"Новое письмо от {senders}." if len(fresh) == 1 else f"{len(fresh)} новых письма: {senders}."
