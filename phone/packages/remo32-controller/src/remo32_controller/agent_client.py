"""Клиент агента.

Каждый вызов может закончиться тем, что ПК выключен или сеть недоступна —
это норма, а не сбой. Поэтому все сетевые ошибки превращаются в
:class:`DeviceUnreachableError`, и один недоступный ПК никак не влияет на
остальные.
"""

from __future__ import annotations

from typing import Any

import httpx

from remo32_core.errors import (
    ActionFailedError,
    ActionInvalidError,
    ActionNotFoundError,
    ActionReadOnlyError,
    ActionsNotEditableError,
    AgentAuthError,
    DeviceTimeoutError,
    DeviceUnreachableError,
    Remo32Error,
)
from remo32_core.log import current_request_id, get_logger
from remo32_core.models import (
    ActionDescriptor,
    ActionEditorState,
    ActionResult,
    AgentHealth,
    ApprovalInfo,
    ApprovalList,
    SystemStats,
)
from remo32_core.protocol import HEADER_AGENT_TOKEN, HEADER_REQUEST_ID

log = get_logger("controller.agent_client")


class AgentClient:
    """HTTP-клиент одного агента.

    Клиент переиспользует соединения: опрос идёт каждые несколько секунд,
    и создавать соединение каждый раз — расточительно.
    """

    def __init__(
        self,
        base_url: str,
        token: str | None,
        *,
        timeout: float = 3.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 2.0)),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            follow_redirects=False,
        )
        self._owns_client = client is None

    @property
    def base_url(self) -> str:
        return self._base_url

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._token:
            headers[HEADER_AGENT_TOKEN] = self._token
        if (rid := current_request_id()) is not None:
            # Один и тот же идентификатор в логах контроллера и агента.
            headers[HEADER_REQUEST_ID] = rid
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float | None = None,
        json: Any | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            response = await self._client.request(
                method,
                url,
                headers=self._headers(),
                timeout=timeout or self._timeout,
                json=json,
            )
        except httpx.TimeoutException as exc:
            raise DeviceTimeoutError(
                f"агент не ответил за {timeout or self._timeout} с", url=url
            ) from exc
        except httpx.HTTPError as exc:
            raise DeviceUnreachableError(f"агент недоступен: {exc}", url=url) from exc

        return self._parse(response, url)

    @staticmethod
    def _parse(response: httpx.Response, url: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise DeviceUnreachableError(
                f"агент вернул не JSON (HTTP {response.status_code})", url=url
            ) from exc

        if not isinstance(payload, dict):
            raise DeviceUnreachableError("агент вернул неожиданный ответ", url=url)

        if response.status_code == 401:
            raise AgentAuthError(
                "агент отверг токен контроллера: проверьте, что REMO32_AGENT_TOKEN "
                "совпадает на обеих машинах",
                url=url,
            )

        if payload.get("ok"):
            data = payload.get("data")
            return data if isinstance(data, dict) else {"value": data}

        error = payload.get("error") or {}
        code = str(error.get("code", "agent_error"))
        message = str(error.get("message", f"HTTP {response.status_code}"))
        if code == "action_not_found":
            raise ActionNotFoundError(message, **error.get("details", {}))
        if code == "actions_not_editable":
            raise ActionsNotEditableError(message)
        if code == "action_read_only":
            raise ActionReadOnlyError(message, **error.get("details", {}))
        if code == "configuration_error":
            # Кнопка описана неверно. Это ошибка человека в форме, а не сбой
            # машины: 400, и текст показываем как есть.
            raise ActionInvalidError(message)
        if code in {"terminal_disabled", "forbidden"}:
            raise Remo32Error(message)
        raise ActionFailedError(message, code=code, url=url)

    # --- ручки агента -----------------------------------------------------

    async def health(self, *, timeout: float | None = None) -> AgentHealth:
        payload = await self._request("GET", "/api/health", timeout=timeout)
        return AgentHealth.model_validate(payload)

    async def stats(self) -> SystemStats:
        return SystemStats.model_validate(await self._request("GET", "/api/stats"))

    async def actions(self) -> list[ActionDescriptor]:
        payload = await self._request("GET", "/api/actions")
        raw = payload.get("value", payload)
        if not isinstance(raw, list):
            return []
        return [ActionDescriptor.model_validate(item) for item in raw]

    async def run_action(self, action_id: str, *, timeout: float = 60.0) -> ActionResult:
        return ActionResult.model_validate(
            await self._request("POST", f"/api/actions/{action_id}", timeout=timeout)
        )

    async def action_editor(self) -> ActionEditorState:
        return ActionEditorState.model_validate(await self._request("GET", "/api/action-editor"))

    async def save_action(self, action_id: str, payload: dict[str, Any]) -> ActionDescriptor:
        return ActionDescriptor.model_validate(
            await self._request("PUT", f"/api/action-editor/{action_id}", json=payload)
        )

    async def delete_action(self, action_id: str) -> ActionEditorState:
        return ActionEditorState.model_validate(
            await self._request("DELETE", f"/api/action-editor/{action_id}")
        )

    async def approvals(self) -> ApprovalList:
        return ApprovalList.model_validate(await self._request("GET", "/api/approvals"))

    async def allow_session(self) -> ApprovalInfo:
        return ApprovalInfo.model_validate(
            await self._request("POST", "/api/approvals/session")
        )

    async def decide_approval(self, approval_id: str, approved: bool) -> ApprovalInfo:
        return ApprovalInfo.model_validate(
            await self._request(
                "POST", f"/api/approvals/{approval_id}", json={"approved": approved}
            )
        )

    # --- JustDay ---------------------------------------------------------
    # Ответ ассистента отдаётся как есть: контроллер ничего в нём не решает.

    async def justday_status(self) -> dict[str, Any]:
        got: dict[str, Any] = await self._request("GET", "/api/justday", timeout=10.0)
        return got

    async def justday_ask(self, text: str, *, silent: bool = False) -> dict[str, Any]:
        got: dict[str, Any] = await self._request(
            "POST", "/api/justday/ask", json={"text": text, "silent": silent}, timeout=190.0
        )
        return got

    async def justday_say(self, text: str) -> dict[str, Any]:
        got: dict[str, Any] = await self._request(
            "POST", "/api/justday/say", json={"text": text}, timeout=70.0
        )
        return got

    async def justday_player(self, action: str, value: Any = None) -> dict[str, Any]:
        got: dict[str, Any] = await self._request(
            "POST", "/api/justday/player", json={"action": action, "value": value}, timeout=20.0
        )
        return got

    async def justday_session(self, action: str) -> dict[str, Any]:
        got: dict[str, Any] = await self._request(
            "POST", f"/api/justday/session/{action}", timeout=70.0
        )
        return got

    async def shutdown(self) -> ActionResult:
        return ActionResult.model_validate(
            await self._request("POST", "/api/power/shutdown", timeout=15.0)
        )

    async def restart(self) -> ActionResult:
        return ActionResult.model_validate(
            await self._request("POST", "/api/power/restart", timeout=15.0)
        )

    async def cancel_power(self) -> ActionResult:
        return ActionResult.model_validate(
            await self._request("POST", "/api/power/cancel", timeout=15.0)
        )

    def terminal_ws_url(self, session: str | None, cols: int, rows: int) -> str:
        """Адрес WebSocket терминала агента вместе с токеном.

        Токен идёт параметром запроса: браузерный WebSocket не умеет
        задавать заголовки. Наружу этот адрес не отдаётся — контроллер
        подключается к агенту сам и проксирует поток браузеру.
        """
        scheme = "wss" if self._base_url.startswith("https://") else "ws"
        host = self._base_url.split("://", 1)[1]
        params = [f"cols={cols}", f"rows={rows}"]
        if session:
            params.append(f"session={session}")
        if self._token:
            params.append(f"token={self._token}")
        return f"{scheme}://{host}/api/terminal/ws?{'&'.join(params)}"
