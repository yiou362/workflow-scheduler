from __future__ import annotations

import pytest

BASE_ENDPOINT = {
    "name": "Local OpenCode",
    "base_url": "http://127.0.0.1:4096",
    "auth_type": "basic",
    "auth_username": "opencode",
    "password": "s3cret",
}

BASE_TASK = {
    "name": "Monthly Rate Report",
    "tags": ["rates", "monthly"],
    "working_directory": "/workspace/rates-report",
    "provider_id": "lps",
    "model_id": "Qwen/Qwen3.6-35B-A3B-FP8",
    "model_variant": "thinking",
    "prompt": "处理本月的工时数据并生成 Rate Report。\n保留这一行。",
    "status": "enabled",
    "schedule_enabled": True,
    "schedule_type": "cron",
    "cron_expression": "0 9 1 * *",
    "overlap_policy": "queue",
    "missed_policy": "skip",
    "timeout_minutes": 60,
}


async def _create_endpoint(client, **overrides):
    payload = {**BASE_ENDPOINT, **overrides}
    response = await client.post("/api/v1/endpoints", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _create_task(client, endpoint_id, **overrides):
    payload = {**BASE_TASK, "endpoint_id": endpoint_id, **overrides}
    response = await client.post("/api/v1/tasks", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_endpoint_crud_never_returns_password(client):
    endpoint = await _create_endpoint(client)
    assert endpoint["is_default"] is True
    assert endpoint["has_password"] is True
    assert "password" not in endpoint
    assert "s3cret" not in str(endpoint)

    detail = await client.get(f"/api/v1/endpoints/{endpoint['id']}")
    assert detail.status_code == 200
    assert detail.json()["task_count"] == 0

    updated = await client.put(
        f"/api/v1/endpoints/{endpoint['id']}",
        json={"name": "Renamed", "auth_type": "basic", "password": ""},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["has_password"] is True

    disabled = await client.post(f"/api/v1/endpoints/{endpoint['id']}/disable")
    assert disabled.status_code == 409

    second = await _create_endpoint(client, name="Remote", base_url="http://example.test:4096", auth_type="none", password=None)
    default = await client.post(f"/api/v1/endpoints/{second['id']}/default")
    assert default.status_code == 200
    assert default.json()["is_default"] is True

    first = await client.get(f"/api/v1/endpoints/{endpoint['id']}")
    assert first.json()["is_default"] is False

    removed = await client.delete(f"/api/v1/endpoints/{endpoint['id']}")
    assert removed.status_code == 204
    missing = await client.get(f"/api/v1/endpoints/{endpoint['id']}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_default_endpoint_cannot_be_deleted(client):
    endpoint = await _create_endpoint(client)
    response = await client.delete(f"/api/v1/endpoints/{endpoint['id']}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.asyncio
async def test_task_create_validation_and_listing(client):
    endpoint = await _create_endpoint(client)
    task = await _create_task(client, endpoint["id"])
    assert task["endpoint_name"] == "Local OpenCode"
    assert task["schedule_summary"] == "Cron 0 9 1 * *"
    assert task["next_run_at"] is not None
    assert task["prompt"].endswith("保留这一行。")

    listing = await client.get("/api/v1/tasks", params={"tag": "rates"})
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["last_run"] is None

    bad_cron = await client.post(
        "/api/v1/tasks",
        json={**BASE_TASK, "endpoint_id": endpoint["id"], "name": "Bad", "cron_expression": "bad"},
    )
    assert bad_cron.status_code == 422
    assert bad_cron.json()["error"]["code"] == "validation_error"
    assert "cron_expression" in bad_cron.json()["error"]["details"]
    assert (await client.get("/api/v1/tasks")).json()["total"] == 1


@pytest.mark.asyncio
async def test_task_actions_copy_disable_archive(client):
    endpoint = await _create_endpoint(client)
    task = await _create_task(client, endpoint["id"])

    copied = await client.post(f"/api/v1/tasks/{task['id']}/copy")
    assert copied.status_code == 201
    copied_body = copied.json()
    assert copied_body["status"] == "disabled"
    assert copied_body["schedule_enabled"] is False
    assert copied_body["next_run_at"] is None
    assert copied_body["name"].startswith("Copy of ")

    disabled = await client.post(f"/api/v1/tasks/{task['id']}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["next_run_at"] is None

    archived = await client.post(f"/api/v1/tasks/{task['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    run = await client.post(f"/api/v1/tasks/{task['id']}/run")
    assert run.status_code == 403

    restored = await client.post(f"/api/v1/tasks/{task['id']}/restore")
    assert restored.json()["status"] == "disabled"


@pytest.mark.asyncio
async def test_manual_run_and_history(client):
    endpoint = await _create_endpoint(client)
    task = await _create_task(client, endpoint["id"], schedule_enabled=False, schedule_type="none")

    response = await client.post(f"/api/v1/tasks/{task['id']}/run")
    assert response.status_code == 201
    run = response.json()["run"]
    assert run["status"] == "queued"
    assert run["trigger_source"] == "manual"
    assert run["config_snapshot"]["prompt"] == task["prompt"]

    detail = await client.get(f"/api/v1/runs/{run['id']}")
    assert detail.status_code == 200
    assert detail.json()["run"]["id"] == run["id"]
    assert detail.json()["pending_permissions"] == []

    logs = await client.get(f"/api/v1/runs/{run['id']}/logs")
    assert logs.status_code == 200
    assert any(entry["phase"] == "created" for entry in logs.json()["items"])

    history = await client.get("/api/v1/runs", params={"status": "queued"})
    assert history.json()["total"] == 1

    cancelled = await client.post(f"/api/v1/runs/{run['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    missing = await client.get("/api/v1/runs/run_missing")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_schedule_preview(client):
    response = await client.post(
        "/api/v1/schedules/preview",
        json={"type": "cron", "cron": "0 9 * * *", "count": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["occurrences"]) == 5
    assert body["utc_offset"] == "+08:00"
    assert body["occurrences"][0]["local"].endswith("09:00:00")

    invalid = await client.post(
        "/api/v1/schedules/preview", json={"type": "cron", "cron": "nope"}
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_rerun_requires_terminal_run(client):
    endpoint = await _create_endpoint(client)
    task = await _create_task(client, endpoint["id"], schedule_enabled=False, schedule_type="none")
    created = await client.post(f"/api/v1/tasks/{task['id']}/run")
    run_id = created.json()["run"]["id"]
    response = await client.post(f"/api/v1/runs/{run_id}/rerun", json={})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_spa_and_json_404(client):
    health = await client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["db"] == "ok"

    missing = await client.get("/api/v1/does-not-exist")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/json")
    assert missing.json()["error"]["code"] == "not_found"

    root = await client.get("/")
    if root.status_code == 503:
        assert root.json()["error"]["code"] == "frontend_not_built"
    else:
        assert root.status_code == 200
        assert 'id="root"' in root.text

    client_route = await client.get("/tasks/123")
    if client_route.status_code == 503:
        assert client_route.json()["error"]["code"] == "frontend_not_built"
    else:
        assert client_route.status_code == 200
        assert 'id="root"' in client_route.text


@pytest.mark.asyncio
async def test_dashboard_shape(client):
    endpoint = await _create_endpoint(client)
    await _create_task(client, endpoint["id"])
    response = await client.get("/api/v1/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["endpoints"]["total"] == 1
    assert body["tasks"]["total"] == 1
    assert body["tasks"]["enabled"] == 1
    assert len(body["upcoming"]) == 1
    assert body["recent_runs"] == []
