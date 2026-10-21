"""Task repository."""

from __future__ import annotations

import json

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from promptops.models import Run, Task
from promptops.enums import PENDING_OR_ACTIVE_STATUSES


async def get(session: AsyncSession, task_id: str) -> Task | None:
    return await session.get(Task, task_id)


async def count(session: AsyncSession) -> dict[str, int]:
    rows = await session.execute(select(Task.status, func.count()).group_by(Task.status))
    return {status: int(total) for status, total in rows.all()}


def _apply_filters(
    stmt: Select,
    *,
    status: str | None,
    endpoint_id: str | None,
    schedule_type: str | None,
    tag: str | None,
    last_status: str | None,
) -> Select:
    if status:
        stmt = stmt.where(Task.status == status)
    if endpoint_id:
        stmt = stmt.where(Task.endpoint_id == endpoint_id)
    if schedule_type:
        stmt = stmt.where(Task.schedule_type == schedule_type)
    if tag:
        stmt = stmt.where(
            text(
                "EXISTS (SELECT 1 FROM json_each(tasks.tags_json) WHERE json_each.value = :tag_value)"
            ).bindparams(tag_value=tag)
        )
    if last_status:
        latest = (
            select(Run.status)
            .where(Run.task_id == Task.id)
            .order_by(Run.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        stmt = stmt.where(latest == last_status)
    return stmt


async def list_page(
    session: AsyncSession,
    *,
    status: str | None,
    endpoint_id: str | None,
    schedule_type: str | None,
    tag: str | None,
    last_status: str | None,
    offset: int,
    limit: int,
) -> tuple[list[Task], int]:
    base = select(Task)
    count_base = select(func.count()).select_from(Task)
    base = _apply_filters(
        base,
        status=status,
        endpoint_id=endpoint_id,
        schedule_type=schedule_type,
        tag=tag,
        last_status=last_status,
    )
    count_base = _apply_filters(
        count_base,
        status=status,
        endpoint_id=endpoint_id,
        schedule_type=schedule_type,
        tag=tag,
        last_status=last_status,
    )
    base = base.order_by(Task.created_at.desc()).offset(offset).limit(limit)
    items = list((await session.scalars(base)).all())
    total = int(await session.scalar(count_base) or 0)
    return items, total


async def latest_runs(session: AsyncSession, task_ids: list[str]) -> dict[str, Run]:
    if not task_ids:
        return {}
    runs = list(
        (
            await session.scalars(
                select(Run).where(Run.task_id.in_(task_ids)).order_by(Run.created_at.desc())
            )
        ).all()
    )
    result: dict[str, Run] = {}
    for run in runs:
        result.setdefault(run.task_id, run)
    return result


async def tasks_due(session: AsyncSession, now_ms: int) -> list[str]:
    rows = await session.scalars(
        select(Task.id)
        .where(
            Task.status == "enabled",
            Task.schedule_enabled.is_(True),
            Task.next_run_at.is_not(None),
            Task.next_run_at <= now_ms,
        )
        .order_by(Task.next_run_at.asc())
    )
    return list(rows.all())


async def upcoming(session: AsyncSession, limit: int = 5) -> list[Task]:
    return list(
        (
            await session.scalars(
                select(Task)
                .where(
                    Task.status == "enabled",
                    Task.schedule_enabled.is_(True),
                    Task.next_run_at.is_not(None),
                )
                .order_by(Task.next_run_at.asc())
                .limit(limit)
            )
        ).all()
    )


async def has_pending_or_active_run(session: AsyncSession, task_id: str) -> Run | None:
    return await session.scalar(
        select(Run)
        .where(
            Run.task_id == task_id,
            Run.status.in_(sorted(PENDING_OR_ACTIVE_STATUSES)),
        )
        .order_by(Run.created_at.asc())
        .limit(1)
    )


async def pending_or_active_runs(session: AsyncSession, task_id: str) -> list[Run]:
    return list(
        (
            await session.scalars(
                select(Run)
                .where(Run.task_id == task_id, Run.status.in_(sorted(PENDING_OR_ACTIVE_STATUSES)))
                .order_by(Run.created_at.asc())
            )
        ).all()
    )


async def create(session: AsyncSession, task: Task) -> Task:
    session.add(task)
    await session.flush()
    return task


async def delete(session: AsyncSession, task: Task) -> None:
    await session.delete(task)
    await session.flush()


def tags_of(task: Task) -> list[str]:
    try:
        value = json.loads(task.tags_json or "[]")
    except ValueError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []
