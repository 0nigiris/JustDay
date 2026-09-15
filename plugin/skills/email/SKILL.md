---
name: email
description: Email — "проверь почту", "что пришло", "ответь маме", "напиши письмо". Mail is private: it is handled by the local mail lane of the daemon, not by you.
---

# Email: not yours to read

The user chose privacy: letters are read, summarised and written by a **local** model on this computer. You (the cloud brain) never see mailbox content, and `justday mail` is blocked for you on purpose.

The daemon catches any phrase with «почта / письмо / мейл / gmail …» before it reaches you. If a mail request still arrives here (it was worded without those words):
- Reply one short sentence: «Скажите “проверь почту” — почту я читаю локально, без облака.»
- If the user says mail isn't set up, tell them to run `justday mail setup` in a terminal (it asks for a Google app password; never ask for the password yourself).
- Do not open Gmail in the browser to read letters, do not use claude.ai Gmail connectors, do not try to work around the block.

Opening the Gmail website on request («открой почту в браузере») is fine — that is just a URL.
