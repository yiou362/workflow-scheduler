"""Trace item repository with idempotent upsert and per-Run sequence."""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promptops.ids import new_id
from promptops.models import TraceItem


async def get(
    session: AsyncSession, run_id: str, kind: str, external_id: str
) -> TraceItem | None:
    return await session.scalar(
        select(TraceItem).where(
            TraceItem.run_id == run_id,
            TraceItem.kind == kind,
            TraceItem.external_id == external_id,
        )
    )


async def upsert(
    session: AsyncSession,
    run_id: str,
    *,
    kind: str,
    external_id: str,
    now: int,
    parent_external_id: str | None = None,
    name: str | None = None,
    status: str | None = None,
    started_at: int | None = None,
    ended_at: int | None = None,
    input_json: str | None = None,
    output_text: str | None = None,
    error_text: str | None = None,
    metadata: dict[str, object] | None = None,
    metadata_json: str | None = None,
) -> TraceItem:
    item = await get(session, run_id, kind, external_id)
    metadata_text = metadata_json
    if metadata_text is None and metadata is not None:
        metadata_text = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    if item is None:
        next_sequence = int(
            await session.scalar(
                select(func.coalesce(func.max(TraceItem.sequence), 0) + 1).where(
                    TraceItem.run_id == run_id
                )
            )
            or 1
        )
        item = TraceItem(
            id=new_id("trace"),
            run_id=run_id,
            kind=kind,
            external_id=external_id,
            parent_external_id=parent_external_id,
            name=name,
            status=status,
            sequence=next_sequence,
            started_at=started_at,
            ended_at=ended_at,
            input_json=input_json,
            output_text=output_text,
            error_text=error_text,
            metadata_json=metadata_text,
            created_at=now,
            updated_at=now,
        )
        session.add(item)
    else:
        if parent_external_id is not None:
            item.parent_external_id = parent_external_id
        if name is not None:
            item.name = name
        if status is not None:
            item.status = status
        if started_at is not None and item.started_at is None:
            item.started_at = started_at
        if ended_at is not None:
            item.ended_at = ended_at
        if input_json is not None:
            item.input_json = input_json
        if output_text is not None:
            item.output_text = output_text
        if error_text is not None:
            item.error_text = error_text
        if metadata_text is not None:
            item.metadata_json = metadata_text
        item.updated_at = now
    if item.started_at is not None and item.ended_at is not None:
        item.duration_ms = max(0, item.ended_at - item.started_at)
    await session.flush()
    return item


async def list_for_run(session: AsyncSession, run_id: str) -> list[TraceItem]:
    return list(
        (
            await session.scalars(
                select(TraceItem)
                .where(TraceItem.run_id == run_id)
                .order_by(
                    func.coalesce(TraceItem.started_at, TraceItem.created_at).asc(),
                    TraceItem.sequence.asc(),
                )
            )
        ).all()
    )


async def count_for_run(session: AsyncSession, run_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(TraceItem).where(TraceItem.run_id == run_id)
        )
        or 0
    )
