"""Endpoint management: CRUD, default endpoint, enable/disable, connection test."""

from __future__ import annotations

import logging
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from promptops.api import errors
from promptops.api.schemas import EndpointCreate, EndpointTestRequest, EndpointUpdate
from promptops.config import Settings
from promptops.enums import AuthType, EndpointTestResult, RunStatus
from promptops.ids import new_id
from promptops.models import Endpoint
from promptops.opencode.client import OpenCodeV2Client
from promptops.opencode.errors import (
    AuthFailed,
    ConnectionFailed,
    HttpError,
    OpenCodeError,
    OpenCodeTimeout,
    ProtocolError,
    UnsupportedServer,
)
from promptops.repositories import endpoints as endpoint_repo
from promptops.repositories import logs as log_repo
from promptops.repositories import runs as run_repo
from promptops.security import SecretBox
from promptops.timeutil import iso

logger = logging.getLogger(__name__)


def normalize_base_url(value: str) -> str:
    text = (value or "").strip()
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https"):
        raise errors.validation_error("Base URL must start with http:// or https://", {"base_url": "invalid scheme"})
    if not parts.hostname:
        raise errors.validation_error("Base URL is missing a host", {"base_url": "host is empty"})
    if parts.username or parts.password:
        raise errors.validation_error(
            "Base URL must not contain a username or password", {"base_url": "use the auth fields instead"}
        )
    if parts.query or parts.fragment:
        raise errors.validation_error(
            "Base URL must not contain a query or fragment", {"base_url": "invalid URL"}
        )
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _validate_name(name: str) -> str:
    value = (name or "").strip()
    if not value:
        raise errors.validation_error("Endpoint name cannot be empty", {"name": "cannot be empty"})
    if len(value) > 120:
        raise errors.validation_error("Endpoint name cannot exceed 120 characters", {"name": "too long"})
    return value


async def get_or_404(session: AsyncSession, endpoint_id: str) -> Endpoint:
    endpoint = await endpoint_repo.get(session, endpoint_id)
    if endpoint is None:
        raise errors.not_found("Endpoint not found")
    return endpoint


async def list_endpoints(
    session: AsyncSession, *, enabled: bool | None, page: int, page_size: int
) -> tuple[list[tuple[Endpoint, int]], int]:
    items, total = await endpoint_repo.list_page(
        session, enabled=enabled, offset=(page - 1) * page_size, limit=page_size
    )
    counts = await endpoint_repo.task_counts(session)
    return [(item, counts.get(item.id, 0)) for item in items], total


async def create_endpoint(
    session: AsyncSession,
    payload: EndpointCreate,
    *,
    box: SecretBox,
    now: int,
) -> Endpoint:
    name = _validate_name(payload.name)
    if await endpoint_repo.get_by_name(session, name) is not None:
        raise errors.conflict("Endpoint name already exists")
    base_url = normalize_base_url(payload.base_url)
    auth_type = payload.auth_type
    username: str | None = None
    ciphertext: str | None = None
    if auth_type == AuthType.BASIC.value:
        username = (payload.auth_username or "opencode").strip() or "opencode"
        if not payload.password:
            raise errors.validation_error(
                "Basic auth requires a password", {"password": "a password is required on create"}
            )
        ciphertext = box.encrypt(payload.password)

    existing = await endpoint_repo.count(session)
    is_first = existing == 0
    is_default = is_first or payload.is_default
    if is_default:
        await endpoint_repo.clear_default(session)

    endpoint = Endpoint(
        id=new_id("endpoint"),
        name=name,
        description=(payload.description or None),
        base_url=base_url,
        auth_type=auth_type,
        auth_username=username,
        secret_ciphertext=ciphertext,
        is_default=is_default,
        enabled=True if is_first else payload.enabled,
        created_at=now,
        updated_at=now,
    )
    session.add(endpoint)
    try:
        await session.flush()
    except IntegrityError as exc:  # unique name race
        raise errors.conflict("Endpoint name already exists") from exc
    return endpoint


async def update_endpoint(
    session: AsyncSession,
    endpoint_id: str,
    payload: EndpointUpdate,
    *,
    box: SecretBox,
    now: int,
) -> Endpoint:
    endpoint = await get_or_404(session, endpoint_id)

    if payload.name is not None:
        name = _validate_name(payload.name)
        other = await endpoint_repo.get_by_name(session, name)
        if other is not None and other.id != endpoint.id:
            raise errors.conflict("Endpoint name already exists")
        endpoint.name = name
    if payload.description is not None:
        endpoint.description = payload.description or None
    if payload.base_url is not None:
        endpoint.base_url = normalize_base_url(payload.base_url)

    if payload.auth_type is not None:
        if payload.auth_type == AuthType.NONE.value:
            endpoint.auth_type = AuthType.NONE.value
            endpoint.auth_username = None
            endpoint.secret_ciphertext = None
        else:
            endpoint.auth_type = AuthType.BASIC.value
            endpoint.auth_username = (payload.auth_username or endpoint.auth_username or "opencode").strip()
            if payload.password:
                endpoint.secret_ciphertext = box.encrypt(payload.password)
            elif not endpoint.secret_ciphertext:
                raise errors.validation_error(
                    "Basic auth requires a password", {"password": "password is required"}
                )
    else:
        if payload.password and endpoint.auth_type == AuthType.BASIC.value:
            endpoint.secret_ciphertext = box.encrypt(payload.password)
        if payload.auth_username and endpoint.auth_type == AuthType.BASIC.value:
            endpoint.auth_username = payload.auth_username.strip() or "opencode"

    if payload.enabled is not None and payload.enabled != endpoint.enabled:
        if payload.enabled:
            endpoint.enabled = True
        else:
            await _disable(session, endpoint, now)

    endpoint.updated_at = now
    await session.flush()
    return endpoint


async def set_enabled(
    session: AsyncSession, endpoint_id: str, *, enabled: bool, now: int
) -> Endpoint:
    endpoint = await get_or_404(session, endpoint_id)
    if enabled:
        endpoint.enabled = True
        endpoint.updated_at = now
    else:
        await _disable(session, endpoint, now)
    await session.flush()
    return endpoint


async def _disable(session: AsyncSession, endpoint: Endpoint, now: int) -> None:
    if endpoint.is_default:
        raise errors.conflict("The default endpoint cannot be disabled; make another endpoint the default first")
    endpoint.enabled = False
    endpoint.updated_at = now
    for run in await run_repo.queued_runs_for_endpoint(session, endpoint.id):
        applied = await run_repo.transition(
            session,
            run.id,
            RunStatus.SKIPPED,
            expected=RunStatus.QUEUED,
            now=now,
            finished_at=now,
            error_phase="scheduler",
            error_type="endpoint_disabled",
            error_message="Endpoint is disabled; prompt not sent",
        )
        if applied:
            await log_repo.append(
                session,
                run.id,
                at=now,
                phase="skipped",
                message="Skipped: endpoint disabled before the run started",
                level="warn",
            )


async def set_default(session: AsyncSession, endpoint_id: str, *, now: int) -> Endpoint:
    endpoint = await get_or_404(session, endpoint_id)
    if not endpoint.enabled:
        raise errors.conflict("A disabled endpoint cannot be made the default")
    await endpoint_repo.clear_default(session)
    endpoint.is_default = True
    endpoint.updated_at = now
    await session.flush()
    return endpoint


async def delete_endpoint(session: AsyncSession, endpoint_id: str, *, now: int) -> None:
    endpoint = await get_or_404(session, endpoint_id)
    if endpoint.is_default:
        raise errors.conflict("The default endpoint cannot be deleted")
    if await endpoint_repo.task_count_for(session, endpoint.id) > 0:
        raise errors.conflict("A task still references this endpoint; it cannot be deleted")
    active = await run_repo.active_runs_for_endpoint(session, endpoint.id)
    if active:
        raise errors.conflict("A running run still depends on this endpoint; it cannot be deleted")
    if await run_repo.queued_runs_for_endpoint(session, endpoint.id):
        raise errors.conflict("A queued run still depends on this endpoint; it cannot be deleted")
    await endpoint_repo.delete(session, endpoint)

async def test_connection(
    session: AsyncSession,
    payload: EndpointTestRequest,
    *,
    settings: Settings,
    box: SecretBox,
    now: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, object]:
    """One-shot connection test.  Never raises for endpoint failures."""

    saved: Endpoint | None = None
    if payload.endpoint_id:
        saved = await get_or_404(session, payload.endpoint_id)

    base_url = payload.base_url or (saved.base_url if saved else None)
    if not base_url:
        raise errors.validation_error("Base URL is required", {"base_url": "cannot be empty"})
    try:
        base_url = normalize_base_url(base_url)
    except errors.ApiError as exc:
        raise exc

    auth_type = payload.auth_type or (saved.auth_type if saved else "none")
    username = payload.auth_username or (saved.auth_username if saved else "opencode")
    password: str | None = payload.password or None
    if not password and saved is not None and saved.secret_ciphertext:
        password = box.decrypt(saved.secret_ciphertext)

    client = OpenCodeV2Client(
        base_url,
        username=username if auth_type == AuthType.BASIC.value else None,
        password=password or "",
        connect_timeout=settings.http_connect_timeout_seconds,
        read_timeout=10.0,
        transport=transport,
    )
    result: EndpointTestResult
    message: str
    version: str | None = None
    try:
        info = await client.probe()
        result = EndpointTestResult.SUCCESS
        version = info.version
        message = f"Connected successfully, OpenCode {info.version}"
    except AuthFailed:
        result = EndpointTestResult.AUTH_FAILED
        message = "Authentication failed: check the username and password"
    except ConnectionFailed as exc:
        result = EndpointTestResult.UNREACHABLE
        message = f"Address unreachable: {exc}"
    except OpenCodeTimeout:
        result = EndpointTestResult.TIMEOUT
        message = "Service response timed out"
    except UnsupportedServer as exc:
        result = EndpointTestResult.UNSUPPORTED
        message = str(exc)
    except HttpError as exc:
        if exc.status == 404 and await _looks_like_v1(base_url, auth_type, username, password):
            result = EndpointTestResult.UNSUPPORTED
            message = "The service is OpenCode v1; only v2 is supported"
        else:
            result = EndpointTestResult.SERVICE_ERROR
            message = f"Service returned an error: HTTP {exc.status}"
    except ProtocolError:
        result = EndpointTestResult.UNSUPPORTED
        message = "The target is not a supported OpenCode v2 service"
    except OpenCodeError as exc:  # pragma: no cover - defensive
        result = EndpointTestResult.SERVICE_ERROR
        message = f"Service returned an error: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("unexpected endpoint test failure: %s", type(exc).__name__)
        result = EndpointTestResult.SERVICE_ERROR
        message = "Connection test failed: unexpected error"
    finally:
        await client.aclose()

    if saved is not None:
        saved.last_test_at = now
        saved.last_test_result = result.value
        saved.last_test_message = message
        saved.last_test_version = version
        saved.updated_at = now
        await session.flush()

    return {
        "result": result.value,
        "message": message,
        "version": version,
        "tested_at": iso(now),
    }


async def _looks_like_v1(
    base_url: str, auth_type: str, username: str | None, password: str | None
) -> bool:
    auth = httpx.BasicAuth(username or "opencode", password or "") if auth_type == "basic" else None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0), trust_env=False) as client:
            response = await client.get(f"{base_url}/global/health", auth=auth)
        if response.status_code != 200:
            return False
        payload = response.json()
        return bool(isinstance(payload, dict) and payload.get("healthy") and payload.get("version"))
    except Exception:
        return False
