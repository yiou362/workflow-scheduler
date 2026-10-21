"""OpenCode v2 HTTP client.

All protocol assumptions live here.  Responses use the v2 ``{data: ...}``
envelope; the adapter unwraps it so callers see plain objects.  Errors are
normalised into :mod:`promptops.opencode.errors` types.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from promptops.opencode.errors import (
    AuthFailed,
    ConnectionFailed,
    HttpError,
    OpenCodeError,
    OpenCodeTimeout,
    PromptRejected,
    PromptUncertain,
    ProtocolError,
    SessionNotFound,
    UnsupportedServer,
)
from promptops.opencode.sse import SSEMessage, iter_events


@dataclass
class ServerInfo:
    version: str
    pid: int | None
    urls: list[str] = field(default_factory=list)
    paths: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionInfo:
    id: str
    title: str | None = None
    outcome: str | None = None
    cost: float | None = None
    tokens: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class UserMessage:
    id: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MessagePage:
    messages: list[dict[str, Any]]
    next_cursor: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class FileDiff:
    file: str
    patch: str | None = None
    additions: int | None = None
    deletions: int | None = None
    status: str | None = None


@dataclass
class ModelOption:
    provider_id: str
    model_id: str
    name: str | None = None
    variants: list[str] = field(default_factory=list)


@dataclass
class AgentOption:
    id: str
    name: str | None = None
    description: str | None = None
    mode: str | None = None


class OpenCodeV2Client:
    """Thin async wrapper around ``opencode serve``'s v2 HTTP API."""

    def __init__(
        self,
        base_url: str,
        *,
        username: str | None = None,
        password: str | None = None,
        connect_timeout: float = 5.0,
        read_timeout: float = 30.0,
        prompt_read_timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._auth = httpx.BasicAuth(username or "opencode", password or "") if username else None
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._prompt_read_timeout = prompt_read_timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------ lifecycle
    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                auth=self._auth,
                transport=self._transport,
                timeout=httpx.Timeout(self._read_timeout, connect=self._connect_timeout),
                follow_redirects=False,
                trust_env=False,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "OpenCodeV2Client":
        self._get_client()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ requests
    async def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: httpx.Timeout | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        client = self._get_client()
        try:
            response = await client.request(method, path, timeout=timeout, **kwargs)
        except httpx.ConnectError as exc:
            raise ConnectionFailed("Address unreachable: connection refused or cannot be resolved") from exc
        except httpx.ConnectTimeout as exc:
            raise ConnectionFailed("Address unreachable: connection timed out") from exc
        except httpx.ReadTimeout as exc:
            raise OpenCodeTimeout("Service response timed out") from exc
        except httpx.HTTPError as exc:
            raise ConnectionFailed(f"Network error: {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            raise AuthFailed("Authentication failed: check the username and password", status=response.status_code)
        return response

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise ProtocolError("Service returned an unrecognised response (not JSON)") from exc

    @staticmethod
    def _error(response: httpx.Response) -> HttpError:
        try:
            body = response.text
        except Exception:  # pragma: no cover - defensive
            body = ""
        return HttpError(response.status_code, body)

    def _unwrap(self, payload: Any) -> Any:
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    # ------------------------------------------------------------------ discovery
    async def info(self) -> ServerInfo:
        response = await self._request("GET", "/api/info")
        if response.status_code != 200:
            raise self._error(response)
        payload = self._json(response)
        if not isinstance(payload, dict):
            raise UnsupportedServer("The target is not a supported OpenCode v2 service")
        version = payload.get("version")
        if not version:
            raise UnsupportedServer("The target is not a supported OpenCode v2 service (missing version)")
        urls = payload.get("urls") or []
        paths = payload.get("paths") or {}
        if not urls and not paths:
            raise UnsupportedServer("The target is not a supported OpenCode v2 service (missing urls/paths)")
        return ServerInfo(
            version=str(version),
            pid=payload.get("pid"),
            urls=list(urls) if isinstance(urls, list) else [],
            paths=paths if isinstance(paths, dict) else {},
            raw=payload,
        )

    async def sessions(self, *, limit: int = 50, parent_id: str | None = None) -> list[SessionInfo]:
        params: dict[str, Any] = {"limit": limit}
        if parent_id:
            params["parentID"] = parent_id
        response = await self._request("GET", "/api/session", params=params)
        if response.status_code != 200:
            raise self._error(response)
        payload = self._json(response)
        data = self._unwrap(payload)
        if not isinstance(data, list):
            raise ProtocolError("SESSION_LIST_INVALID")
        return [self._session_info(item) for item in data if isinstance(item, dict)]

    async def probe(self) -> ServerInfo:
        """Test connection: ``/api/info`` plus one read-only session list call."""

        info = await self.info()
        try:
            await self.sessions(limit=1)
        except SessionNotFound:
            raise
        except AuthFailed:
            raise
        except HttpError as exc:
            if exc.status == 404:
                raise UnsupportedServer("The target OpenCode v2 API is incomplete or the version does not match") from exc
            raise
        return info

    async def models(self, directory: str) -> list[ModelOption]:
        response = await self._request(
            "GET",
            "/api/model",
            # v2 declares ``location`` as a deepObject: the wire form is
            # ``location[directory]``.  ``location.directory`` is silently
            # ignored by the server and would return the global config only.
            params={"location[directory]": directory},
        )
        if response.status_code != 200:
            raise self._error(response)
        data = self._unwrap(self._json(response))
        if not isinstance(data, list):
            raise ProtocolError("MODEL_LIST_INVALID")
        result: list[ModelOption] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            model_id = item.get("modelID") or item.get("id")
            if not model_id:
                continue
            variants = item.get("variants") or []
            if isinstance(variants, dict):
                variant_names = [str(key) for key in variants]
            elif isinstance(variants, list):
                variant_names = [
                    str(value.get("id") or value.get("name") or value)
                    if isinstance(value, dict)
                    else str(value)
                    for value in variants
                ]
            else:
                variant_names = []
            result.append(
                ModelOption(
                    provider_id=str(item.get("providerID") or ""),
                    model_id=str(model_id),
                    name=item.get("name"),
                    variants=[value for value in variant_names if value],
                )
            )
        return result

    async def agents(self, directory: str) -> list[AgentOption]:
        response = await self._request(
            "GET", "/api/agent", params={"location[directory]": directory}
        )
        if response.status_code != 200:
            raise self._error(response)
        data = self._unwrap(self._json(response))
        if not isinstance(data, list):
            raise ProtocolError("AGENT_LIST_INVALID")
        result: list[AgentOption] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            agent_id = item.get("id") or item.get("name")
            if not agent_id:
                continue
            result.append(
                AgentOption(
                    id=str(agent_id),
                    name=item.get("name"),
                    description=item.get("description"),
                    mode=item.get("mode"),
                )
            )
        return result

    # ------------------------------------------------------------------ sessions
    @staticmethod
    def _session_info(item: dict[str, Any]) -> SessionInfo:
        session_id = item.get("id")
        if not session_id:
            raise ProtocolError("SESSION_INFO_INVALID (missing id)")
        tokens = item.get("tokens")
        return SessionInfo(
            id=str(session_id),
            title=item.get("title"),
            outcome=item.get("outcome"),
            cost=item.get("cost"),
            tokens=tokens if isinstance(tokens, dict) else None,
            raw=item,
        )

    async def create_session(
        self,
        *,
        title: str,
        directory: str,
        model: dict[str, Any] | None,
        agent: str | None,
    ) -> SessionInfo:
        body: dict[str, Any] = {"title": title, "location": {"directory": directory}}
        if model:
            body["model"] = model
        if agent:
            body["agent"] = agent
        response = await self._request("POST", "/api/session", json=body)
        if response.status_code != 200:
            raise self._error(response)
        data = self._unwrap(self._json(response))
        if not isinstance(data, dict):
            raise ProtocolError("SESSION_CREATE_INVALID")
        return self._session_info(data)

    async def session(self, session_id: str) -> SessionInfo:
        response = await self._request("GET", f"/api/session/{session_id}")
        if response.status_code == 404:
            raise SessionNotFound(session_id)
        if response.status_code != 200:
            raise self._error(response)
        data = self._unwrap(self._json(response))
        if not isinstance(data, dict):
            raise ProtocolError("SESSION_INFO_INVALID")
        return self._session_info(data)

    async def prompt(self, session_id: str, text: str) -> UserMessage:
        timeout = httpx.Timeout(
            self._prompt_read_timeout, connect=self._connect_timeout
        )
        try:
            response = await self._request(
                "POST", f"/api/session/{session_id}/prompt", json={"text": text}, timeout=timeout
            )
        except (ConnectionFailed, OpenCodeTimeout) as exc:
            # Outcome unknown: the prompt may have been persisted.
            raise PromptUncertain(str(exc)) from exc
        if response.status_code == 404:
            raise SessionNotFound(session_id)
        if response.status_code >= 500:
            raise PromptUncertain(f"OpenCode returned HTTP {response.status_code}")
        if response.status_code >= 400:
            raise PromptRejected(response.status_code, response.text)
        data = self._unwrap(self._json(response))
        if isinstance(data, dict):
            return UserMessage(id=data.get("id"), raw=data)
        return UserMessage(id=None)

    async def messages(
        self,
        session_id: str,
        *,
        order: str = "asc",
        limit: int = 100,
        cursor: str | None = None,
        message_type: str | None = None,
    ) -> MessagePage:
        params: dict[str, Any] = {"order": order, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        if message_type:
            params["type"] = message_type
        response = await self._request(
            "GET", f"/api/session/{session_id}/message", params=params
        )
        if response.status_code == 404:
            raise SessionNotFound(session_id)
        if response.status_code == 400:
            raise HttpError(400, "invalid message cursor")
        if response.status_code != 200:
            raise self._error(response)
        payload = self._json(response)
        data = self._unwrap(payload)
        if not isinstance(data, list):
            raise ProtocolError("MESSAGE_LIST_INVALID")
        next_cursor = None
        if isinstance(payload, dict):
            cursor_info = payload.get("cursor")
            if isinstance(cursor_info, dict):
                next_cursor = cursor_info.get("next")
        return MessagePage(messages=[item for item in data if isinstance(item, dict)], next_cursor=next_cursor)

    async def diff(self, session_id: str) -> list[FileDiff]:
        response = await self._request("GET", f"/api/session/{session_id}/diff")
        if response.status_code == 404:
            raise SessionNotFound(session_id)
        if response.status_code != 200:
            raise self._error(response)
        data = self._unwrap(self._json(response))
        if not isinstance(data, list):
            raise ProtocolError("DIFF_INVALID")
        result: list[FileDiff] = []
        for item in data:
            if not isinstance(item, dict) or not item.get("file"):
                continue
            result.append(
                FileDiff(
                    file=str(item["file"]),
                    patch=item.get("patch"),
                    additions=item.get("additions"),
                    deletions=item.get("deletions"),
                    status=item.get("status"),
                )
            )
        return result

    async def interrupt(self, session_id: str) -> bool:
        response = await self._request("POST", f"/api/session/{session_id}/interrupt")
        if response.status_code == 404:
            raise SessionNotFound(session_id)
        if response.status_code != 200:
            raise self._error(response)
        payload = self._json(response)
        if isinstance(payload, dict) and "interrupted" in payload:
            return bool(payload["interrupted"])
        data = self._unwrap(payload)
        if isinstance(data, dict):
            return bool(data.get("interrupted", False))
        return False

    async def reply_permission(
        self,
        session_id: str,
        request_id: str,
        decision: str,
        message: str | None = None,
    ) -> None:
        body: dict[str, Any] = {"decision": decision}
        if message:
            body["message"] = message
        response = await self._request(
            "POST", f"/api/session/{session_id}/permission/{request_id}/reply", json=body
        )
        if response.status_code == 404:
            raise HttpError(404, "permission request not found")
        if response.status_code not in (200, 201, 204):
            raise self._error(response)

    # ------------------------------------------------------------------ events
    @asynccontextmanager
    async def event_stream(
        self, *, last_event_id: str | None = None
    ) -> AsyncIterator[AsyncIterator[SSEMessage]]:
        client = self._get_client()
        headers = {"Accept": "text/event-stream"}
        if last_event_id:
            headers["Last-Event-ID"] = last_event_id
        # SSE is a long-lived connection: no read timeout, only connect timeout.
        timeout = httpx.Timeout(None, connect=self._connect_timeout)
        try:
            request = client.build_request("GET", "/api/event", headers=headers)
            response = await client.send(request, stream=True, timeout=timeout)
        except httpx.ConnectError as exc:
            raise ConnectionFailed("SSE connection failed: address unreachable") from exc
        except httpx.ConnectTimeout as exc:
            raise ConnectionFailed("SSE connection failed: connection timed out") from exc
        except httpx.ReadTimeout as exc:
            raise OpenCodeTimeout("SSE connection timed out") from exc
        try:
            if response.status_code in (401, 403):
                raise AuthFailed("SSE authentication failed", status=response.status_code)
            if response.status_code != 200:
                raise HttpError(response.status_code, "SSE stream unavailable")
            yield iter_events(response)
        finally:
            await response.aclose()


def model_ref(provider_id: str, model_id: str, variant: str | None) -> dict[str, Any]:
    ref: dict[str, Any] = {"id": model_id, "providerID": provider_id}
    if variant:
        ref["variant"] = variant
    return ref


def parse_json_text(text: str | None) -> Any:
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


__all__ = [
    "AgentOption",
    "FileDiff",
    "MessagePage",
    "ModelOption",
    "OpenCodeV2Client",
    "ServerInfo",
    "SessionInfo",
    "UserMessage",
    "model_ref",
    "OpenCodeError",
]
