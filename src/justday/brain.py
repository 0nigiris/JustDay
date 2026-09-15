"""The reasoning core: one long-lived Claude Code session driven through the Claude Agent SDK.

Claude Code already provides the agent loop, tools (shell, files, web), MCP, skills, memory,
permissions (auto-mode classifier), sessions and compaction. This module only:
  * starts/resumes that session with JustDay's persona, plugin and settings,
  * streams its output to the voice layer (text → speech, tool calls → log/notifications),
  * routes permission prompts to the user (voice/notification approval),
  * supports interrupting a turn.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from . import config, events, providers
from .i18n import t

log = logging.getLogger("justday.brain")

BRAIN_DIR = config.DATA_DIR / "brain"


def describe_tool(name: str, inp: dict) -> str:
    """One-line human description of a tool call (for logs, notifications, approval prompts)."""
    if name == "Bash":
        return f"команда: {inp.get('command', '')}"
    if name in ("Edit", "Write", "Read", "NotebookEdit"):
        return f"{name} {inp.get('file_path', '')}"
    if name.startswith("mcp__"):
        _, server, tool = name.split("__", 2)
        detail = inp.get("url") or inp.get("text") or inp.get("query") or inp.get("app") or ""
        return f"{server}: {tool} {str(detail)[:120]}".strip()
    if name in ("WebSearch", "WebFetch"):
        return f"{name} {inp.get('query') or inp.get('url', '')}"
    return name


def humanize_tool(name: str, inp: dict) -> str:
    """What the user sees in the Dynamic Island while a tool runs (describe_tool stays exact for approvals)."""
    from urllib.parse import urlparse

    tool = name.rsplit("__", 1)[-1]
    if name == "Bash":
        return inp.get("description") or inp.get("command", "")[:160]
    if tool == "look":
        return t("Смотрю на экран") + (f": {inp['window']}" if inp.get("window") else "")
    if tool == "act":
        steps = inp.get("steps") or []
        typed = next((s[5:] for s in steps if s.startswith("type ")), "")
        if typed:
            return t("Печатаю «{text}»", text=typed[:60])
        ops = {s.split(" ", 1)[0] for s in steps}
        return t("Перетаскиваю" if "drag" in ops else "Нажимаю в окне" if ops & {"click", "double", "right"}
                 else "Нажимаю клавиши" if "key" in ops else "Действую в окне")
    if name.startswith("mcp__claude-in-chrome"):
        url = inp.get("url") or ""
        return t("Браузер: {what}", what=(urlparse(url).netloc or url) if url else tool.replace("_", " "))
    if name.startswith("mcp__plugin_justday_kwin"):
        return t({"list_windows": "Смотрю, какие окна открыты", "focus_window": "Переключаю окно",
                  "find_ui_elements": "Ищу кнопку", "accessibility_tree": "Изучаю окно"}.get(tool, "Управляю рабочим столом"))
    if name == "WebSearch":
        return t("Ищу в интернете: {q}", q=inp.get("query", ""))
    if name == "WebFetch":
        return t("Читаю {what}", what=urlparse(inp.get("url", "")).netloc)
    if name in ("Read", "Edit", "Write"):
        verb = {"Read": "Читаю {what}", "Edit": "Правлю {what}", "Write": "Пишу {what}"}[name]
        return t(verb, what=Path(inp.get("file_path", "")).name)
    if name in ("Grep", "Glob"):
        return t("Ищу в файлах")
    if name == "Skill":
        return t("Навык: {name}", name=inp.get("skill") or inp.get("name", ""))
    if name in ("Agent", "Task"):
        return t("Думаю глубже: {what}", what=inp.get("description") or t("субагент"))
    return describe_tool(name, inp)


class Brain:
    def __init__(
        self,
        cfg: dict,
        on_text: Callable[[str], Awaitable[None]],
        approver: Callable[[str, str], Awaitable[bool]],
    ):
        self.cfg = cfg
        self.on_text = on_text
        self.approver = approver
        self.client: ClaudeSDKClient | None = None
        self.session_id: str | None = None
        self._turn_done = asyncio.Event()
        self._turn_done.set()
        self._turn_lock = asyncio.Lock()
        self._reader: asyncio.Task | None = None
        self._last_text = ""
        self._notes: list[str] = []
        self._pending: list[str] = []   # text of the current step; spoken only if it turns out to be final
        self._turn_started = 0.0
        self.cancelled = False
        self._spoke_in_turn = False

    # ---------- lifecycle ----------
    def _options(self, resume: str | None) -> ClaudeAgentOptions:
        b = self.cfg["brain"]
        u = self.cfg["user"]
        lang = u.get("language", "ru")
        persona_file = config.REPO_DIR / "brain" / ("PERSONA.md" if lang == "ru" else f"PERSONA.{lang}.md")
        if not persona_file.exists():
            persona_file = config.REPO_DIR / "brain" / "PERSONA.md"
        persona = persona_file.read_text(encoding="utf-8")
        names = [u["assistant_name"], *u.get("assistant_aliases", [])]
        persona = (persona.replace("{address_as}", u["address_as"] or "").replace("{assistant_name}", names[0])
                   .replace("{assistant_names}", (" и " if lang == "ru" else " and ").join(f"«{n}»" for n in names)))
        claude = providers.is_claude(self.cfg)
        # Claude in Chrome and the auto-mode classifier need an Anthropic account; other models use the local policy
        extra = {"chrome": None} if b.get("chrome") and claude else {}
        return ClaudeAgentOptions(
            cwd=str(BRAIN_DIR),
            cli_path=shutil.which(b["claude_cli"]) or b["claude_cli"],
            model=b["model"] or None,
            effort=(b.get("effort") or None) if claude else None,
            permission_mode=b["permission_mode"] if claude else "default",
            system_prompt={"type": "preset", "preset": "claude_code", "append": persona},
            setting_sources=["user", "project", "local"],
            settings=str(config.REPO_DIR / "brain" / "settings.json"),
            plugins=[{"type": "local", "path": str(config.REPO_DIR / "plugin")}],
            add_dirs=[str(Path.home())],
            # kwin screenshot: full-resolution multi-monitor PNG (slow; `look` instead);
            # kwin launch_app: never reaps its children (zombies confuse "is it running?" checks; `justday apps launch`)
            # kwin keyboard_type*: layout-dependent / pastes twice and presses Enter twice — `act` "type" instead
            disallowed_tools=["mcp__plugin_justday_kwin__screenshot", "mcp__plugin_justday_kwin__launch_app",
                              "mcp__plugin_justday_kwin__keyboard_type", "mcp__plugin_justday_kwin__keyboard_type_unicode"],
            # load MCP tool schemas upfront when they fit: one round-trip less
            env={"ENABLE_TOOL_SEARCH": "auto", **providers.env(self.cfg)},
            can_use_tool=self._can_use_tool,
            resume=resume,
            extra_args=extra,
            max_buffer_size=64 * 1024 * 1024,  # screenshots come back as base64 images inside one JSON line
            stderr=lambda line: log.debug("claude: %s", line),
        )

    async def start(self) -> None:
        BRAIN_DIR.mkdir(parents=True, exist_ok=True)
        state = events.load_state()
        resume = None
        within = self.cfg["brain"]["resume_within_hours"] * 3600
        if state.get("brain_session_id") and time.time() - state.get("brain_last_active", 0) < within:
            resume = state["brain_session_id"]
        try:
            await self._connect(resume)
        except Exception:
            if not resume:
                raise
            log.exception("resume of %s failed, starting a fresh session", resume)
            await self._connect(None)

    async def _connect(self, resume: str | None) -> None:
        self.client = ClaudeSDKClient(self._options(resume))
        await self.client.connect()
        self.session_id = resume
        self._reader = asyncio.create_task(self._read_loop(), name="brain-reader")
        b = self.cfg["brain"]
        events.emit("brain_connected", resume=resume, model=b["model"], provider=b.get("provider", "claude"))

    async def stop(self) -> None:
        if self._reader:
            self._reader.cancel()
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                log.exception("disconnect failed")
        self.client = None

    async def new_session(self) -> None:
        await self.stop()
        events.save_state(brain_session_id=None)
        await self._connect(None)

    # ---------- turns ----------
    @property
    def busy(self) -> bool:
        return not self._turn_done.is_set()

    def note(self, text: str) -> None:
        """Context to prepend to the next message (e.g. what the instant path already did)."""
        self._notes.append(text)

    def _with_notes(self, text: str) -> str:
        if not self._notes:
            return text
        notes, self._notes = "\n".join(self._notes), []
        return f"{notes}\n\n{text}"

    async def inject(self, text: str, source: str = "voice") -> None:
        """Deliver a new user message while a turn is running. Claude Code picks it up at the next step
        without abandoning the current task (and starts a new turn if the current one just ended)."""
        events.emit("request", source=source, text=text, injected=True)
        await self.client.query(self._with_notes(
            "(Новая реплика пользователя, пока ты выполнял предыдущую просьбу. Предыдущую не бросай, если он явно "
            "не отменил её. Сначала выполни/ответь на эту; если по предыдущей нужен ответ, добавь его после словами "
            f"«Кстати, насчёт …».)\n{text}"))

    async def ask(self, text: str, source: str = "voice") -> str:
        """Send one user message and wait until Claude finishes the turn. Returns the final text."""
        async with self._turn_lock:
            if self.client is None or (self._reader and self._reader.done()):
                events.emit("brain_restart", reason="client not running")
                await self.stop()
                await self.start()
            events.emit("request", source=source, text=text)
            self._turn_done.clear()
            self._begin_turn()
            await self.client.query(self._with_notes(text))
            await self._turn_done.wait()
            return self._last_text

    def _begin_turn(self) -> None:
        self.cancelled = False
        self._last_text = ""
        self._pending = []
        self._turn_started = time.monotonic()
        self._spoke_in_turn = False

    async def _speak(self, text: str) -> None:
        if self.cancelled:
            events.emit("say_suppressed", text=text[:200])
            return
        self._spoke_in_turn = True
        events.emit("say", text=text)
        await self.on_text(text)

    async def interrupt(self) -> None:
        # whatever this turn still produces (text already generated, the final result) must stay silent
        self.cancelled = True
        self._pending = []
        if self.client and self.busy:
            events.emit("interrupt")
            try:
                await asyncio.wait_for(self.client.interrupt(), timeout=5)
            except Exception:
                log.exception("interrupt failed; restarting the session")
                await self.stop()
                self._turn_done.set()
                await self.start()

    async def _read_loop(self) -> None:
        """Single consumer of the SDK stream. Also handles turns Claude starts on its own
        (e.g. when a background shell task finishes)."""
        try:
            async for msg in self.client.receive_messages():
                await self._handle(msg)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            events.emit("brain_error", error=repr(e))
        finally:
            self._turn_done.set()

    async def _handle(self, msg) -> None:
        if isinstance(msg, AssistantMessage):
            if self._turn_done.is_set():  # a turn Claude started by itself (late injected message, bg task)
                self._turn_done.clear()
                self._begin_turn()
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    self._pending.append(block.text.strip())
                    events.emit("draft", text=block.text.strip())
                elif isinstance(block, ToolUseBlock):
                    # Text followed by a tool call is narration ("сейчас кликну…"): don't read it aloud —
                    # except one heads-up when a task is clearly long and nothing was said yet.
                    if self._pending and not self._spoke_in_turn and time.monotonic() - self._turn_started > 20:
                        await self._speak(self._pending[-1])
                    elif self._pending:
                        events.emit("narration_suppressed", text=" ".join(self._pending)[:300])
                    self._pending = []
                    events.emit("tool", name=block.name, input=json.dumps(block.input, ensure_ascii=False)[:2000],
                                desc=describe_tool(block.name, block.input), label=humanize_tool(block.name, block.input))
        elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, ToolResultBlock) and block.is_error:
                    events.emit("tool_error", content=str(block.content)[:1000])
        elif isinstance(msg, ResultMessage):
            if self._pending:
                self._last_text = "\n".join(self._pending)
                self._pending = []
                await self._speak(self._last_text)
            self.session_id = msg.session_id
            events.save_state(brain_session_id=msg.session_id, brain_last_active=time.time())
            events.emit("turn_done", session=msg.session_id, turns=msg.num_turns, ms=msg.duration_ms,
                        cost_usd=msg.total_cost_usd, error=msg.is_error, subtype=msg.subtype)
            self._turn_done.set()
        elif isinstance(msg, SystemMessage):
            if msg.subtype == "init":
                servers = {s.get("name"): s.get("status") for s in msg.data.get("mcp_servers", [])}
                events.emit("session_init", session=msg.data.get("session_id"), mcp=servers)
            elif msg.subtype not in ("status",):
                events.emit("system", subtype=msg.subtype)

    # ---------- permissions ----------
    @staticmethod
    def _ask_rules() -> list[str]:
        settings = json.loads((config.REPO_DIR / "brain" / "settings.json").read_text(encoding="utf-8"))
        return settings["permissions"]["ask"]

    async def _can_use_tool(self, name: str, inp: dict, ctx) -> PermissionResultAllow | PermissionResultDeny:
        if not providers.is_claude(self.cfg) and not providers.risky(name, inp, self._ask_rules()):
            return PermissionResultAllow(updated_input=inp)  # no classifier: everything but the ask-rules runs
        desc = getattr(ctx, "title", None) or describe_tool(name, inp)
        reason = getattr(ctx, "decision_reason", None) or ""
        events.emit("approval_request", tool=name, desc=desc, reason=reason)
        ok = await self.approver(desc, reason)
        events.emit("approval_result", tool=name, allowed=ok)
        if ok:
            return PermissionResultAllow(updated_input=inp)
        return PermissionResultDeny(message="Пользователь отклонил это действие. Не повторяй его; предложи альтернативу или спроси.")
