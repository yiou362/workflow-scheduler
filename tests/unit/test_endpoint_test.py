from __future__ import annotations

import httpx
import pytest
from cryptography.fernet import Fernet

from promptops.api.schemas import EndpointTestRequest
from promptops.security import SecretBox
from promptops.services import endpoint_service
from promptops.timeutil import parse_iso
from tests.helpers import make_endpoint

NOW = parse_iso("2026-10-19T00:00:00Z")


@pytest.fixture
def box() -> SecretBox:
    return SecretBox(Fernet.generate_key())


def info_payload() -> dict:
    return {"version": "2.0.29", "pid": 1, "urls": ["http://127.0.0.1:4096"], "paths": {"tmp": "/tmp"}}


async def _test(session, settings, box, handler, **overrides):
    endpoint = await make_endpoint(session)
    payload = EndpointTestRequest(endpoint_id=endpoint.id, **overrides)
    return await endpoint_service.test_connection(
        session,
        payload,
        settings=settings,
        box=box,
        now=NOW,
        transport=httpx.MockTransport(handler),
    )


def handler_success(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/info":
        return httpx.Response(200, json=info_payload())
    if request.url.path == "/api/session":
        return httpx.Response(200, json={"data": []})
    return httpx.Response(404)


async def test_success(session, settings, box):
    result = await _test(session, settings, box, handler_success)
    assert result["result"] == "success"
    assert result["version"] == "2.0.29"
    assert "2.0.29" in result["message"]


async def test_auth_failed(session, settings, box):
    result = await _test(session, settings, box, lambda request: httpx.Response(401))
    assert result["result"] == "auth_failed"


async def test_unreachable(session, settings, box):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    result = await _test(session, settings, box, handler)
    assert result["result"] == "unreachable"


async def test_timeout(session, settings, box):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    result = await _test(session, settings, box, handler)
    assert result["result"] == "timeout"


async def test_html_is_unsupported(session, settings, box):
    result = await _test(
        session,
        settings,
        box,
        lambda request: httpx.Response(200, text="<html>not opencode</html>"),
    )
    assert result["result"] == "unsupported"


async def test_missing_version_is_unsupported(session, settings, box):
    result = await _test(
        session,
        settings,
        box,
        lambda request: httpx.Response(200, json={"urls": ["x"]}),
    )
    assert result["result"] == "unsupported"


async def test_missing_session_api_is_unsupported(session, settings, box):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/info":
            return httpx.Response(200, json=info_payload())
        return httpx.Response(404)

    result = await _test(session, settings, box, handler)
    assert result["result"] == "unsupported"


async def test_server_error(session, settings, box):
    result = await _test(session, settings, box, lambda request: httpx.Response(500))
    assert result["result"] == "service_error"


async def test_v1_is_reported_unsupported(session, settings, box, monkeypatch):
    async def fake_v1(*_args, **_kwargs):
        return True

    monkeypatch.setattr(endpoint_service, "_looks_like_v1", fake_v1)
    result = await _test(session, settings, box, lambda request: httpx.Response(404))
    assert result["result"] == "unsupported"
    assert "v1" in result["message"]


async def test_test_updates_saved_endpoint(session, settings, box):
    await _test(session, settings, box, handler_success)
    endpoint = (await endpoint_service.list_endpoints(session, enabled=None, page=1, page_size=10))[0][0][0]
    assert endpoint.last_test_result == "success"
    assert endpoint.last_test_version == "2.0.29"
