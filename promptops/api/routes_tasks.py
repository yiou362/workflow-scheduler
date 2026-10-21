"""Task API, schedule preview and model/agent discovery."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from promptops.api.dependencies import get_runtime, get_session
from promptops.api.schemas import (
    SchedulePreviewRequest,
    TaskCreate,
    TaskUpdate,
)
from promptops.api.serialize import run_dict, task_dict
from promptops.repositories import endpoints as endpoint_repo
from promptops.repositories import tasks as task_repo
from promptops.runtime import Runtime
from promptops.services import options_service, run_service, task_service

router = APIRouter(prefix="/api/v1", tags=["tasks"])


async def _endpoint_names(session: AsyncSession) -> dict[str, str]:
    items, _ = await endpoint_repo.list_page(session, enabled=None, offset=0, limit=1000)
    return {item.id: item.name for item in items}


@router.get("/tasks")
async def list_tasks(
    status_filter: str | None = Query(default=None, alias="status"),
    endpoint_id: str | None = None,
    schedule_type: str | None = None,
    last_status: str | None = None,
    tag: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    items, total = await task_repo.list_page(
        session,
        status=status_filter,
        endpoint_id=endpoint_id,
        schedule_type=schedule_type,
        tag=tag,
        last_status=last_status,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    last_runs = await task_repo.latest_runs(session, [item.id for item in items])
    names = await _endpoint_names(session)
    return {
        "items": [
            task_dict(
                item,
                last_run=last_runs.get(item.id),
                endpoint_name=names.get(item.endpoint_id),
            )
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    task = await task_service.create_task(
        session, payload, settings=runtime.settings, now_ms=runtime.clock.now_ms()
    )
    names = await _endpoint_names(session)
    return task_dict(task, endpoint_name=names.get(task.endpoint_id))


@router.post("/schedules/preview")
async def preview_schedule(
    payload: SchedulePreviewRequest,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    return task_service.preview_schedule(
        payload, runtime.settings, runtime.clock.now_ms()
    )


@router.get("/options")
async def options(
    endpoint_id: str,
    working_directory: str,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    return await options_service.get_options(
        session,
        endpoint_id=endpoint_id,
        working_directory=working_directory,
        settings=runtime.settings,
        box=runtime.secret_box,
        now_ms=runtime.clock.now_ms(),
    )


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    task = await task_service.get_or_404(session, task_id)
    last_runs = await task_repo.latest_runs(session, [task.id])
    names = await _endpoint_names(session)
    return task_dict(
        task, last_run=last_runs.get(task.id), endpoint_name=names.get(task.endpoint_id)
    )


@router.put("/tasks/{task_id}")
async def update_task(
    task_id: str,
    payload: TaskUpdate,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    task = await task_service.update_task(
        session, task_id, payload, settings=runtime.settings, now_ms=runtime.clock.now_ms()
    )
    names = await _endpoint_names(session)
    return task_dict(task, endpoint_name=names.get(task.endpoint_id))


@router.post("/tasks/{task_id}/copy", status_code=status.HTTP_201_CREATED)
async def copy_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    task = await task_service.copy_task(
        session, task_id, now_ms=runtime.clock.now_ms()
    )
    names = await _endpoint_names(session)
    return task_dict(task, endpoint_name=names.get(task.endpoint_id))


@router.post("/tasks/{task_id}/enable")
async def enable_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    task = await task_service.set_enabled(
        session,
        task_id,
        enabled=True,
        settings=runtime.settings,
        now_ms=runtime.clock.now_ms(),
    )
    names = await _endpoint_names(session)
    return task_dict(task, endpoint_name=names.get(task.endpoint_id))


@router.post("/tasks/{task_id}/disable")
async def disable_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    task = await task_service.set_enabled(
        session,
        task_id,
        enabled=False,
        settings=runtime.settings,
        now_ms=runtime.clock.now_ms(),
    )
    names = await _endpoint_names(session)
    return task_dict(task, endpoint_name=names.get(task.endpoint_id))


@router.post("/tasks/{task_id}/archive")
async def archive_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    task = await task_service.archive_task(
        session, task_id, now_ms=runtime.clock.now_ms()
    )
    names = await _endpoint_names(session)
    return task_dict(task, endpoint_name=names.get(task.endpoint_id))


@router.post("/tasks/{task_id}/restore")
async def restore_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    task = await task_service.restore_task(
        session, task_id, settings=runtime.settings, now_ms=runtime.clock.now_ms()
    )
    names = await _endpoint_names(session)
    return task_dict(task, endpoint_name=names.get(task.endpoint_id))


@router.post("/tasks/{task_id}/run", status_code=status.HTTP_201_CREATED)
async def run_task_now(
    task_id: str,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    run = await run_service.manual_run(
        session, task_id, settings=runtime.settings, now_ms=runtime.clock.now_ms()
    )
    if run.status == "queued":
        message = "Queued"
    elif run.status == "skipped":
        message = run.error_message or "Skipped by the overlap policy"
    else:
        message = "Run created"
    return {"run": run_dict(run), "message": message}
