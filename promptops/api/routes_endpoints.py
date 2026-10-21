"""Endpoint API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from promptops.api.dependencies import get_runtime, get_session
from promptops.api.schemas import EndpointCreate, EndpointTestRequest, EndpointUpdate
from promptops.api.serialize import endpoint_dict
from promptops.runtime import Runtime
from promptops.services import endpoint_service
from promptops.services import options_service

router = APIRouter(prefix="/api/v1/endpoints", tags=["endpoints"])


@router.get("")
async def list_endpoints(
    enabled: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    rows, total = await endpoint_service.list_endpoints(
        session, enabled=enabled, page=page, page_size=page_size
    )
    return {
        "items": [endpoint_dict(item, task_count=count) for item, count in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    payload: EndpointCreate,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    endpoint = await endpoint_service.create_endpoint(
        session, payload, box=runtime.secret_box, now=runtime.clock.now_ms()
    )
    return endpoint_dict(endpoint)


@router.post("/test")
async def test_endpoint(
    payload: EndpointTestRequest,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    return await endpoint_service.test_connection(
        session,
        payload,
        settings=runtime.settings,
        box=runtime.secret_box,
        now=runtime.clock.now_ms(),
        transport=runtime.transport,
    )


@router.get("/{endpoint_id}")
async def get_endpoint(
    endpoint_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    endpoint = await endpoint_service.get_or_404(session, endpoint_id)
    from promptops.repositories import endpoints as endpoint_repo

    count = await endpoint_repo.task_count_for(session, endpoint.id)
    return endpoint_dict(endpoint, task_count=count)


@router.put("/{endpoint_id}")
async def update_endpoint(
    endpoint_id: str,
    payload: EndpointUpdate,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    endpoint = await endpoint_service.update_endpoint(
        session, endpoint_id, payload, box=runtime.secret_box, now=runtime.clock.now_ms()
    )
    options_service.invalidate_endpoint(endpoint_id)
    from promptops.repositories import endpoints as endpoint_repo

    count = await endpoint_repo.task_count_for(session, endpoint.id)
    return endpoint_dict(endpoint, task_count=count)


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    endpoint_id: str,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> Response:
    await endpoint_service.delete_endpoint(
        session, endpoint_id, now=runtime.clock.now_ms()
    )
    options_service.invalidate_endpoint(endpoint_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{endpoint_id}/default")
async def set_default(
    endpoint_id: str,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    endpoint = await endpoint_service.set_default(
        session, endpoint_id, now=runtime.clock.now_ms()
    )
    from promptops.repositories import endpoints as endpoint_repo

    count = await endpoint_repo.task_count_for(session, endpoint.id)
    return endpoint_dict(endpoint, task_count=count)


@router.post("/{endpoint_id}/enable")
async def enable_endpoint(
    endpoint_id: str,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    endpoint = await endpoint_service.set_enabled(
        session, endpoint_id, enabled=True, now=runtime.clock.now_ms()
    )
    options_service.invalidate_endpoint(endpoint_id)
    from promptops.repositories import endpoints as endpoint_repo

    count = await endpoint_repo.task_count_for(session, endpoint.id)
    return endpoint_dict(endpoint, task_count=count)


@router.post("/{endpoint_id}/disable")
async def disable_endpoint(
    endpoint_id: str,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    endpoint = await endpoint_service.set_enabled(
        session, endpoint_id, enabled=False, now=runtime.clock.now_ms()
    )
    options_service.invalidate_endpoint(endpoint_id)
    from promptops.repositories import endpoints as endpoint_repo

    count = await endpoint_repo.task_count_for(session, endpoint.id)
    return endpoint_dict(endpoint, task_count=count)
