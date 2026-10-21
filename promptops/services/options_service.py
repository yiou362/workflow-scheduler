"""Model / Agent discovery with a short-lived in-memory cache."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from promptops.config import Settings
from promptops.repositories import endpoints as endpoint_repo
from promptops.security import SecretBox
from promptops.services.client_factory import client_for_endpoint

_CACHE_TTL_MS = 60_000
_cache: dict[str, tuple[int, dict[str, object]]] = {}


def invalidate_endpoint(endpoint_id: str) -> None:
    for key in [key for key in _cache if key.startswith(f"{endpoint_id}|")]:
        _cache.pop(key, None)


def clear_cache() -> None:
    _cache.clear()


async def get_options(
    session: AsyncSession,
    *,
    endpoint_id: str,
    working_directory: str,
    settings: Settings,
    box: SecretBox,
    now_ms: int,
) -> dict[str, object]:
    key = f"{endpoint_id}|{working_directory}"
    cached = _cache.get(key)
    if cached is not None and cached[0] > now_ms:
        return cached[1]

    endpoint = await endpoint_repo.get(session, endpoint_id)
    if endpoint is None:
        return {"models": [], "agents": [], "warning": "Endpoint not found"}
    if not endpoint.enabled:
        return {"models": [], "agents": [], "warning": "Endpoint is disabled"}
    if not working_directory:
        return {"models": [], "agents": [], "warning": "working directory is missing"}

    client = client_for_endpoint(endpoint, settings, box)
    models: list[dict[str, object]] = []
    agents: list[dict[str, object]] = []
    warnings: list[str] = []
    try:
        model_result, agent_result = await asyncio.gather(
            client.models(working_directory),
            client.agents(working_directory),
            return_exceptions=True,
        )
        if isinstance(model_result, Exception):
            warnings.append(f"could not read the model list: {model_result}")
        else:
            models = [
                {
                    "provider_id": item.provider_id,
                    "model_id": item.model_id,
                    "name": item.name,
                    "variants": item.variants,
                }
                for item in model_result
            ]
        if isinstance(agent_result, Exception):
            warnings.append(f"could not read the agent list: {agent_result}")
        else:
            agents = [
                {
                    "id": item.id,
                    "name": item.name,
                    "description": item.description,
                    "mode": item.mode,
                }
                for item in agent_result
            ]
    finally:
        await client.aclose()

    payload: dict[str, object] = {
        "models": models,
        "agents": agents,
        "warning": "；".join(warnings) if warnings else None,
    }
    _cache[key] = (now_ms + _CACHE_TTL_MS, payload)
    return payload
