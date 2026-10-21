"""Dashboard aggregates (no health probes; failures come from actual Runs)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from promptops.api.serialize import endpoint_dict, run_list_item
from promptops.repositories import endpoints as endpoint_repo
from promptops.repositories import runs as run_repo
from promptops.repositories import tasks as task_repo
from promptops.timeutil import iso

THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000


async def build_dashboard(session: AsyncSession, *, now_ms: int) -> dict[str, object]:
    endpoint_total = await endpoint_repo.count(session)
    endpoint_enabled = await endpoint_repo.count(session, enabled=True)
    default_endpoint = await endpoint_repo.get_default(session)
    task_counts = await task_repo.count(session)
    status_counts = await run_repo.status_counts(session)
    since = now_ms - THIRTY_DAYS_MS

    endpoint_items, _ = await endpoint_repo.list_page(
        session, enabled=None, offset=0, limit=1000
    )
    counts = await endpoint_repo.task_counts(session)

    upcoming = await task_repo.upcoming(session, limit=5)
    recent = await run_repo.recent(session, limit=10)
    failures = await run_repo.recent_failures(session, limit=10)

    return {
        "endpoints": {
            "total": endpoint_total,
            "enabled": endpoint_enabled,
            "disabled": endpoint_total - endpoint_enabled,
            "default": endpoint_dict(default_endpoint, task_count=0) if default_endpoint else None,
            "items": [endpoint_dict(item, task_count=counts.get(item.id, 0)) for item in endpoint_items],
        },
        "tasks": {
            "total": sum(task_counts.values()),
            "enabled": task_counts.get("enabled", 0),
            "disabled": task_counts.get("disabled", 0),
            "archived": task_counts.get("archived", 0),
        },
        "runs": {
            "queued": status_counts.get("queued", 0),
            "preparing": status_counts.get("preparing", 0),
            "submitting": status_counts.get("submitting", 0),
            "running": status_counts.get("running", 0),
            "waiting": status_counts.get("waiting", 0),
            "cancelling": status_counts.get("cancelling", 0),
            "failed_30d": await run_repo.count_finished_since(session, "failed", since),
            "completed_30d": await run_repo.count_finished_since(session, "completed", since),
        },
        "upcoming": [
            {
                "task_id": task.id,
                "task_name": task.name,
                "endpoint_id": task.endpoint_id,
                "next_run_at": iso(task.next_run_at),
                "schedule_summary": _summary(task),
            }
            for task in upcoming
        ],
        "recent_runs": [run_list_item(run) for run in recent],
        "recent_failures": [run_list_item(run) for run in failures],
    }


def _summary(task) -> str:  # noqa: ANN001 - ORM Task
    if task.schedule_type == "cron":
        return f"Cron {task.cron_expression}"
    if task.schedule_type == "once":
        return "Once"
    if task.schedule_type == "interval":
        return f"Every {task.interval_seconds}s"
    return "Manual only"
