"""Run history, detail, trace, logs, cancel, rerun and permission replies."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from promptops.api import errors
from promptops.api.dependencies import get_runtime, get_session
from promptops.api.schemas import PermissionReplyRequest, RerunRequest
from promptops.api.serialize import log_dict, run_dict, run_list_item, trace_dict
from promptops.repositories import logs as log_repo
from promptops.repositories import runs as run_repo
from promptops.repositories import trace as trace_repo
from promptops.runtime import Runtime
from promptops.services import run_service
from promptops.timeutil import local_date_bounds_ms, parse_iso

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


@router.get("")
async def list_runs(
    task_id: str | None = None,
    endpoint_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    source: str | None = None,
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    model: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    try:
        from_ms, to_ms = local_date_bounds_ms(from_date, to_date, runtime.settings.utc_offset)
    except ValueError as exc:
        raise errors.validation_error("invalid time range format", {"from": str(exc)}) from exc
    items, total = await run_repo.list_page(
        session,
        task_id=task_id,
        endpoint_id=endpoint_id,
        status=status_filter,
        source=source,
        from_ms=from_ms,
        to_ms=to_ms,
        model=model,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return {
        "items": [run_list_item(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{run_id}")
async def get_run(
    run_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    run = await run_repo.get(session, run_id)
    if run is None:
        raise errors.not_found("Run not found")
    return {
        "run": run_dict(run),
        "pending_permissions": await run_service.pending_permissions(session, run_id),
    }


@router.get("/{run_id}/trace")
async def get_trace(
    run_id: str,
    view: str = Query(default="timeline"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    run = await run_repo.get(session, run_id)
    if run is None:
        raise errors.not_found("Run not found")
    items = await trace_repo.list_for_run(session, run_id)
    return {
        "items": [trace_dict(item) for item in items],
        "integrity": run.trace_integrity,
        "gap_count": run.trace_gap_count,
        "view": view,
    }


@router.get("/{run_id}/logs")
async def get_logs(
    run_id: str,
    after_at: str | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    run = await run_repo.get(session, run_id)
    if run is None:
        raise errors.not_found("Run not found")
    try:
        after_ms = parse_iso(after_at) if after_at else None
    except ValueError as exc:
        raise errors.validation_error("after_at must be an ISO timestamp", {"after_at": str(exc)}) from exc
    entries = await log_repo.list_for_run(session, run_id, after_at=after_ms, limit=limit)
    return {"items": [log_dict(entry) for entry in entries]}


@router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    return await run_service.request_cancel(
        session, run_id, registry=runtime.registry, now_ms=runtime.clock.now_ms()
    )


@router.post("/{run_id}/rerun", status_code=status.HTTP_201_CREATED)
async def rerun(
    run_id: str,
    payload: RerunRequest,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    run = await run_service.rerun(
        session,
        run_id,
        endpoint_id=payload.endpoint_id,
        settings=runtime.settings,
        now_ms=runtime.clock.now_ms(),
    )
    return {"run": run_dict(run), "message": "New run created"}


@router.post("/{run_id}/permissions/{request_id}/reply", status_code=status.HTTP_204_NO_CONTENT)
async def reply_permission(
    run_id: str,
    request_id: str,
    payload: PermissionReplyRequest,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> Response:
    await run_service.reply_permission(
        session,
        run_id,
        request_id,
        decision=payload.decision,
        message=payload.message,
        runtime=runtime,
        now_ms=runtime.clock.now_ms(),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
