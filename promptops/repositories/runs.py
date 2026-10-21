"""Run repository, including the conditional status transition helper."""

from __future__ import annotations

import json

from sqlalchemy import Select, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from promptops.enums import ACTIVE_RUN_STATUSES, RunStatus
from promptops.models import Run


async def get(session: AsyncSession, run_id: str) -> Run | None:
    return await session.get(Run, run_id)


async def get_by_session(session: AsyncSession, session_id: str) -> Run | None:
    return await session.scalar(select(Run).where(Run.opencode_session_id == session_id))


async def create(session: AsyncSession, run: Run) -> Run:
    session.add(run)
    await session.flush()
    return run


async def transition(
    session: AsyncSession,
    run_id: str,
    target: RunStatus | str,
    *,
    expected: set[RunStatus | str] | RunStatus | str | None = None,
    now: int | None = None,
    **fields: object,
) -> bool:
    """Conditionally move a Run to ``target``; returns ``True`` only when applied.

    Terminal states are protected by the ``expected`` clause: a late event can
    never overwrite a status another writer already committed.
    """

    target_value = target.value if isinstance(target, RunStatus) else str(target)
    stmt = update(Run).where(Run.id == run_id)
    if expected is not None:
        if isinstance(expected, (str, RunStatus)):
            expected_values = [expected.value if isinstance(expected, RunStatus) else str(expected)]
        else:
            expected_values = [item.value if isinstance(item, RunStatus) else str(item) for item in expected]
        stmt = stmt.where(Run.status.in_(expected_values))
    values: dict[str, object] = {"status": target_value}
    if now is not None:
        values["updated_at"] = now
    values.update(fields)
    result = await session.execute(stmt.values(**values))
    return (result.rowcount or 0) == 1


async def transition_run(
    session: AsyncSession,
    run: Run,
    target: RunStatus | str,
    *,
    now: int,
    **fields: object,
) -> bool:
    applied = await transition(session, run.id, target, expected=run.status, now=now, **fields)
    if applied:
        await session.refresh(run)
    return applied


async def update_fields(session: AsyncSession, run_id: str, *, now: int, **fields: object) -> None:
    fields["updated_at"] = now
    await session.execute(update(Run).where(Run.id == run_id).values(**fields))


async def claim_next_queued(session: AsyncSession, now_ms: int) -> Run | None:
    """Claim the oldest Queued Run whose Task has no active Run."""

    alias = aliased(Run)
    active_same_task = exists(
        select(alias.id).where(
            alias.task_id == Run.task_id,
            alias.status.in_([item.value for item in ACTIVE_RUN_STATUSES]),
            alias.id != Run.id,
        )
    )
    candidate_id = await session.scalar(
        select(Run.id)
        .where(Run.status == RunStatus.QUEUED.value, ~active_same_task)
        .order_by(Run.created_at.asc(), Run.id.asc())
        .limit(1)
    )
    if candidate_id is None:
        return None
    claimed = await transition(
        session,
        candidate_id,
        RunStatus.PREPARING,
        expected=RunStatus.QUEUED,
        now=now_ms,
        started_at=now_ms,
        last_heartbeat_at=now_ms,
        deadline_at=now_ms + (await _timeout_ms(session, candidate_id)),
    )
    if not claimed:
        return None
    run = await session.get(Run, candidate_id)
    if run is not None:
        await session.refresh(run)
    return run


async def _timeout_ms(session: AsyncSession, run_id: str) -> int:
    value = await session.scalar(select(Run.timeout_minutes).where(Run.id == run_id))
    return int(value or 60) * 60_000


def _apply_filters(
    stmt: Select,
    *,
    task_id: str | None,
    endpoint_id: str | None,
    status: str | None,
    source: str | None,
    from_ms: int | None,
    to_ms: int | None,
    model: str | None,
) -> Select:
    if task_id:
        stmt = stmt.where(Run.task_id == task_id)
    if endpoint_id:
        stmt = stmt.where(Run.endpoint_id == endpoint_id)
    if status:
        stmt = stmt.where(Run.status == status)
    if source:
        stmt = stmt.where(Run.trigger_source == source)
    if from_ms is not None:
        stmt = stmt.where(Run.created_at >= from_ms)
    if to_ms is not None:
        stmt = stmt.where(Run.created_at <= to_ms)
    if model:
        stmt = stmt.where(Run.model_id == model)
    return stmt


async def list_page(
    session: AsyncSession,
    *,
    task_id: str | None = None,
    endpoint_id: str | None = None,
    status: str | None = None,
    source: str | None = None,
    from_ms: int | None = None,
    to_ms: int | None = None,
    model: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[Run], int]:
    base = _apply_filters(
        select(Run),
        task_id=task_id,
        endpoint_id=endpoint_id,
        status=status,
        source=source,
        from_ms=from_ms,
        to_ms=to_ms,
        model=model,
    )
    count_base = _apply_filters(
        select(func.count()).select_from(Run),
        task_id=task_id,
        endpoint_id=endpoint_id,
        status=status,
        source=source,
        from_ms=from_ms,
        to_ms=to_ms,
        model=model,
    )
    base = base.order_by(Run.created_at.desc(), Run.id.desc()).offset(offset).limit(limit)
    items = list((await session.scalars(base)).all())
    total = int(await session.scalar(count_base) or 0)
    return items, total


async def active_runs(session: AsyncSession) -> list[Run]:
    return list(
        (
            await session.scalars(
                select(Run)
                .where(Run.status.in_([item.value for item in ACTIVE_RUN_STATUSES]))
                .order_by(Run.created_at.asc())
            )
        ).all()
    )


async def active_runs_for_task(session: AsyncSession, task_id: str) -> list[Run]:
    return list(
        (
            await session.scalars(
                select(Run).where(
                    Run.task_id == task_id,
                    Run.status.in_([item.value for item in ACTIVE_RUN_STATUSES]),
                )
            )
        ).all()
    )


async def queued_runs(session: AsyncSession) -> list[Run]:
    return list(
        (await session.scalars(select(Run).where(Run.status == RunStatus.QUEUED.value))).all()
    )


async def queued_runs_for_endpoint(session: AsyncSession, endpoint_id: str) -> list[Run]:
    return list(
        (
            await session.scalars(
                select(Run).where(
                    Run.endpoint_id == endpoint_id, Run.status == RunStatus.QUEUED.value
                )
            )
        ).all()
    )


async def status_counts(session: AsyncSession) -> dict[str, int]:
    rows = await session.execute(select(Run.status, func.count()).group_by(Run.status))
    return {status: int(total) for status, total in rows.all()}


async def recent(session: AsyncSession, limit: int = 10) -> list[Run]:
    return list(
        (await session.scalars(select(Run).order_by(Run.created_at.desc()).limit(limit))).all()
    )


async def recent_failures(session: AsyncSession, limit: int = 10) -> list[Run]:
    return list(
        (
            await session.scalars(
                select(Run)
                .where(Run.status.in_(["failed", "timeout", "unknown"]))
                .order_by(Run.created_at.desc())
                .limit(limit)
            )
        ).all()
    )


async def count_finished_since(session: AsyncSession, status: str, since_ms: int) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.status == status, Run.created_at >= since_ms)
        )
        or 0
    )


async def count_for_status(session: AsyncSession, statuses: list[str]) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(Run).where(Run.status.in_(statuses))
        )
        or 0
    )


async def set_usage(session: AsyncSession, run_id: str, *, usage: dict[str, object]) -> None:
    values = {key: value for key, value in usage.items() if value is not None}
    if values:
        await session.execute(update(Run).where(Run.id == run_id).values(**values))


async def active_runs_for_endpoint(session: AsyncSession, endpoint_id: str) -> list[Run]:
    return list(
        (
            await session.scalars(
                select(Run).where(
                    Run.endpoint_id == endpoint_id,
                    Run.status.in_([item.value for item in ACTIVE_RUN_STATUSES]),
                )
            )
        ).all()
    )


async def all_for_task(session: AsyncSession, task_id: str) -> list[Run]:
    return list(
        (await session.scalars(select(Run).where(Run.task_id == task_id).order_by(Run.created_at))).all()
    )


async def exists_for_endpoint(session: AsyncSession, endpoint_id: str) -> bool:
    return bool(
        await session.scalar(
            select(func.count()).select_from(Run).where(Run.endpoint_id == endpoint_id)
        )
    )


async def snapshot_of(run: Run) -> dict[str, object]:
    try:
        value = json.loads(run.config_snapshot_json or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
