"""OpenCode v2 client protocol details verified against 2.0.29."""

from __future__ import annotations

import json

import httpx
import pytest

from promptops.opencode.client import OpenCodeV2Client


def _client(handler) -> OpenCodeV2Client:
    return OpenCodeV2Client(
        "http://opencode.test",
        transport=httpx.MockTransport(handler),
        connect_timeout=1,
        read_timeout=5,
    )


@pytest.mark.asyncio
async def test_models_uses_deep_object_location():
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("location[directory]"))
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "providerID": "lps",
                        "modelID": "Qwen/Qwen3.6-35B-A3B-FP8",
                        "name": "Qwen",
                        "variants": [
                            {"id": "thinking", "settings": {}},
                            {"id": "no_thinking", "settings": {}},
                        ],
                    }
                ]
            },
        )

    client = _client(handler)
    models = await client.models(r"C:\work\opencode")
    await client.aclose()
    assert seen == [r"C:\work\opencode"]
    assert models[0].provider_id == "lps"
    assert models[0].model_id == "Qwen/Qwen3.6-35B-A3B-FP8"
    assert models[0].variants == ["thinking", "no_thinking"]


@pytest.mark.asyncio
async def test_agents_uses_deep_object_location():
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("location[directory]"))
        return httpx.Response(200, json={"data": [{"id": "build", "name": "Build", "mode": "primary"}]})

    client = _client(handler)
    agents = await client.agents(r"C:\work\opencode")
    await client.aclose()
    assert seen == [r"C:\work\opencode"]
    assert agents[0].id == "build"


@pytest.mark.asyncio
async def test_info_and_probe_require_version_and_urls():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/info":
            return httpx.Response(200, json={"version": "2.0.29", "urls": ["http://x"]})
        if request.url.path == "/api/session":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(404)

    client = _client(handler)
    info = await client.probe()
    await client.aclose()
    assert info.version == "2.0.29"


@pytest.mark.asyncio
async def test_info_without_urls_or_paths_is_unsupported():
    from promptops.opencode.errors import UnsupportedServer

    client = _client(lambda request: httpx.Response(200, json={"version": "1.0"}))
    with pytest.raises(UnsupportedServer):
        await client.info()
    await client.aclose()


@pytest.mark.asyncio
async def test_messages_unwraps_cursor():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [{"id": "msg_1", "type": "user", "payload": {"text": "hi"}}],
                "cursor": {"next": "abc"},
            },
        )

    client = _client(handler)
    page = await client.messages("ses_1", order="asc")
    await client.aclose()
    assert len(page.messages) == 1
    assert page.next_cursor == "abc"
    assert json.loads(json.dumps(page.messages))[0]["id"] == "msg_1"
