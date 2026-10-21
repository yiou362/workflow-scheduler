"""Local performance smoke: 1000 Runs, 500 trace items.

Run:  .venv/Scripts/python.exe scripts/perf_smoke.py
It builds a temporary database, seeds data, and times the hot API reads.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path

import httpx

from promptops.config import Settings
from promptops.ids import new_id
from promptops.main import create_app
from promptops.models import Endpoint, Run, Task, TraceItem
from promptops.timeutil import now_ms

RUNS = 1000
TRACE_ITEMS = 500


async def main() -> None:
    data_dir = Path(tempfile.mkdtemp(prefix="promptops-perf-"))
    settings = Settings(data_dir=data_dir, auto_migrate=True, log_level="ERROR")
    app = create_app(settings, start_background=False)
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        now = now_ms()
        async with runtime.session_factory() as session:
            endpoint = Endpoint(
                id=new_id("endpoint"),
                name="Perf Endpoint",
                base_url="http://127.0.0.1:4096",
                auth_type="none",
                is_default=True,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
            session.add(endpoint)
            task = Task(
                id=new_id("task"),
                name="Perf Task",
                tags_json=json.dumps(["perf"]),
                endpoint_id=endpoint.id,
                working_directory="/workspace",
                provider_id="lps",
                model_id="m",
                prompt="hello",
                status="enabled",
                schedule_enabled=False,
                schedule_type="none",
                overlap_policy="queue",
                missed_policy="skip",
                timeout_minutes=60,
                created_at=now,
                updated_at=now,
            )
            session.add(task)
            await session.flush()
            runs: list[Run] = []
            for index in range(RUNS):
                run = Run(
                    id=new_id("run"),
                    task_id=task.id,
                    trigger_source="manual",
                    status="completed" if index % 3 else "failed",
                    created_at=now - index,
                    started_at=now - index,
                    finished_at=now - index + 100,
                    task_name_snapshot="Perf Task",
                    endpoint_id=endpoint.id,
                    endpoint_name_snapshot="Perf Endpoint",
                    endpoint_url_snapshot="http://127.0.0.1:4096",
                    endpoint_auth_type_snapshot="none",
                    working_directory="/workspace",
                    provider_id="lps",
                    model_id="m",
                    prompt="hello",
                    utc_offset="+08:00",
                    schedule_summary="仅手动执行",
                    overlap_policy="queue",
                    missed_policy="skip",
                    timeout_minutes=60,
                    trace_integrity="complete",
                    trace_gap_count=0,
                    final_response="done",
                    config_snapshot_json="{}",
                    updated_at=now,
                )
                runs.append(run)
            session.add_all(runs)
            trace_run = runs[0]
            for index in range(TRACE_ITEMS):
                session.add(
                    TraceItem(
                        id=new_id("trace"),
                        run_id=trace_run.id,
                        kind="tool",
                        external_id=f"call_{index}",
                        name="read",
                        status="completed",
                        sequence=index + 1,
                        started_at=now,
                        ended_at=now + 10,
                        duration_ms=10,
                        output_text="x" * 200,
                        created_at=now,
                        updated_at=now,
                    )
                )
            await session.commit()
            trace_run_id = trace_run.id

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://perf") as client:
            async def timed(label: str, path: str) -> None:
                started = time.perf_counter()
                response = await client.get(path)
                elapsed = (time.perf_counter() - started) * 1000
                print(f"{label:28s} {response.status_code} {elapsed:8.1f} ms")
                assert response.status_code == 200

            await timed("runs list (50)", "/api/v1/runs?page_size=50")
            await timed("runs list page 10", "/api/v1/runs?page=10&page_size=50")
            await timed("dashboard", "/api/v1/dashboard")
            await timed("run trace (500 items)", f"/api/v1/runs/{trace_run_id}/trace")

        db_path = data_dir / "promptops.db"
        print(f"database size: {db_path.stat().st_size / 1024 / 1024:.2f} MiB")


if __name__ == "__main__":
    asyncio.run(main())
