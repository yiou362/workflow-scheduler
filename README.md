# PromptOps Console

Turn a prompt into a task, send it on a schedule to a designated OpenCode Serve instance
(v2 HTTP API), and record the status, logs, real trace, and final response of every execution.

- Backend: single-process FastAPI + SQLite (WAL) + a purpose-built scheduler/executor
- Frontend: React 18 + Ant Design 5 + TypeScript + Vite
- Scheduling/display time zone: globally fixed at `UTC+08:00` (default; adjustable with
  `PROMPTOPS_UTC_OFFSET`; no per-task time zone or DST handling)
- OpenCode v2 only (`GET /api/info` returns `version` + `urls`/`paths`); v1 is reported
  explicitly as unsupported

Requirements and design:

- [PRD](specs/PromptOps_Console_PRD_v1.0.md)
- [SPEC](specs/SPEC.md)
- [PLAN](specs/PLAN.md)
- [TASKS](specs/TASKS.md)
- [Implementation and acceptance record](docs/acceptance.md)

## Setup

Prerequisites: Python 3.12+, Node 20+, pnpm 10+ (validated with 12.3.4 on this machine;
`pnpm-workspace.yaml` already allows the esbuild build script). `frontend/dist` is already
built in this repository; rebuild it after changing the frontend.

```bash
# 1) Backend dependencies
python -m venv .venv
# Windows
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
# Linux/macOS
# .venv/bin/python -m pip install -r requirements-dev.txt

# 2) Frontend dependencies and build
cd frontend
pnpm install
pnpm typecheck
pnpm build
cd ..

# 3) Configuration
copy .env.example .env    # Windows
# cp .env.example .env    # Linux/macOS

# 4) Start (single process)
.venv\Scripts\python.exe -m promptops serve
# Linux: .venv/bin/python -m promptops serve
```

Open <http://127.0.0.1:8787>. Or run it directly:

```bash
uvicorn promptops.main:app --host 127.0.0.1 --port 8787 --workers 1
```

> **`workers=1` is mandatory.** Scheduling, run claiming, and SSE supervision all live
> inside the process; multiple workers would schedule the same run more than once.
> Do not use `--reload` while running real tasks in development: reload restarts the
> process. The recovery mechanism can reconcile state, but the execution is interrupted.

### Development mode

```bash
# Terminal 1
python -m promptops serve

# Terminal 2
cd frontend && pnpm dev   # http://localhost:5173, proxies /api and /healthz to 127.0.0.1:8787
```

### First run

1. `Endpoints → New endpoint`, then fill in the OpenCode Serve address (for example
   `http://127.0.0.1:4096`) and Basic Auth credentials.
2. Click "Test connection"; it should report `Connected successfully, OpenCode <version>`.
3. The first endpoint automatically becomes the default; the default can be switched
   from the list afterwards.
4. `Tasks → New task`, then fill in the prompt, working directory, provider/model, and
   schedule rule.
5. Preview the next 5 run times before saving; after saving you can use "Run now" and open
   the run details to inspect the trace.

### Task working directory and skills

- Enter an **absolute path on the OpenCode host** pointing at the project directory that
  contains `opencode.json`, for example
  `C:\Users\<user>\Documents\internal-ai-project\bo\opencode`.
- Do not enter the `opencode.json` file itself, and do not enter the PromptOps directory.
  The system passes the string verbatim as the session's `location.directory` to OpenCode;
  it is never read or validated here.
- Relative paths are resolved by the OpenCode process itself. The working directory of
  `opencode serve --service` is not controllable, so always use absolute paths.
- OpenCode loads the project `opencode.json`, `AGENTS.md`, and skills from that directory.
  Tasks are not bound to a skill; whether one is invoked depends on the prompt and the
  configuration at that directory. When a specific skill is required, name it in the prompt.
- Skill execution is further constrained by `permission.skill` in `opencode.json`. The
  current repository's `bo/opencode/opencode.json` sets `"*": "deny"` and only allows
  `ironman_timesheet_reminder`, `mspo_contract_validation`, `mspo_project_governance`, and
  `sharepoint_excel_update`; every other skill is rejected even when loaded.
- The provider/model from that directory is loaded together with `opencode.json`. For
  example, `lps/Qwen/Qwen3.6-35B-A3B-FP8` is only visible under `bo/opencode`, and is not
  visible from the repository root.

### "Test connection" reports `auth_failed`

- Being able to open `http://127.0.0.1:<port>/` in a browser does not mean the API is
  unauthenticated: OpenCode v2 protects `/api/*` with Basic Auth, while the root path serves
  the web UI.
- When OpenCode is started without an explicit password it generates a random one. The
  password for `opencode serve --service` is stored in the `password` field of
  `~/.local/state/opencode/service.json` (older versions may use
  `~/.config/opencode/service.json`); the `url` field holds the actual port.
- Choose **Basic Authentication** for the endpoint, use `opencode` as the username and the
  password above as the password; never put the password in the URL.
- To use a custom password, set `OPENCODE_SERVER_PASSWORD` before starting OpenCode.

## Configuration

Environment variables are prefixed with `PROMPTOPS_`; the full list lives in
`promptops/config.py` and `.env.example`. Commonly used settings:

| Variable | Default | Description |
|---|---|---|
| `PROMPTOPS_HOST` / `PROMPTOPS_PORT` | `127.0.0.1` / `8787` | Bind address/port; loopback only by default |
| `PROMPTOPS_DATA_DIR` | `./data` | SQLite, key, and log directory |
| `PROMPTOPS_UTC_OFFSET` | `+08:00` | Global fixed offset; takes effect after restart and only affects future runs |
| `PROMPTOPS_MAX_CONCURRENT_RUNS` | `2` | Number of runs executed concurrently |
| `PROMPTOPS_SECRET_KEY` | empty | Fernet key; generated into `data/secret.key` when empty |
| `PROMPTOPS_AUTO_MIGRATE` | `true` | Run Alembic on startup |
| `PROMPTOPS_DEFAULT_ENDPOINT_URL` | empty | Seeds a default endpoint when the database is empty |
| `PROMPTOPS_FRONTEND_DIST` | `./frontend/dist` | SPA build output directory |

## Security

- The application has **no login or RBAC** and only listens on `127.0.0.1` by default. For
  LAN access, place it behind an authenticating reverse proxy.
- Endpoint passwords are encrypted with Fernet. The API, UI, logs, and error messages never
  echo passwords or the `Authorization` header.
- Model output, prompts, and tool input/output are all rendered as plain text; the frontend
  never uses `dangerouslySetInnerHTML`.
- `data/secret.key` must be backed up together with the database; once lost, stored endpoint
  passwords cannot be decrypted and must be re-entered.
- OpenCode permission requests are never approved automatically; a scheduled task can remain
  in `Waiting` until a human acts on it or it times out.

## Testing

```bash
# Backend (per repository convention, run only the affected tests; all tests use a temporary SQLite database)
.venv/Scripts/python.exe -m pytest tests/unit -q
.venv/Scripts/python.exe -m pytest tests/integration -q

# Frontend
cd frontend
pnpm typecheck
pnpm test
pnpm build

# Performance smoke test (1000 runs / 500 trace entries, temporary database)
PYTHONPATH=. .venv/Scripts/python.exe scripts/perf_smoke.py
```

## Deployment

### Linux (systemd)

```ini
[Unit]
Description=PromptOps Console
After=network.target

[Service]
WorkingDirectory=/opt/promptops/app/workflow-scheduler
EnvironmentFile=/opt/promptops/.env
ExecStart=/opt/promptops/.venv/bin/python -m promptops serve
Restart=on-failure
RestartSec=5
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
```

### Windows

```powershell
python -m promptops serve
```

Alternatively register it as a service with `nssm` or Task Scheduler. Keep a single instance.

### Release checklist

1. `cd frontend && pnpm install --frozen-lockfile && pnpm typecheck && pnpm build`
2. Back up `data/promptops.db` and `data/secret.key`
3. Restart the process; Alembic runs on startup and refuses to start if a migration fails
4. Open `/healthz` and confirm `db=ok` and `frontend_built=true`

### Backup and restore

```bash
sqlite3 data/promptops.db ".backup 'backup.db'"
# or: sqlite3 data/promptops.db "VACUUM INTO 'backup.db'"
```

Do not copy WAL files while writes are in flight. Back up the database and the key before
upgrading; `frontend/dist` can be rebuilt from source and does not need a backup.

### Reverse proxy

Nginx or Caddy terminates TLS and adds authentication, proxying `/`, `/api`, and `/healthz`
to FastAPI (same-origin deployment). Do not let Nginx serve `frontend/dist` directly while
FastAPI also serves the SPA; pick one.

## Layout

```text
promptops/            FastAPI app, domain layer, scheduler, executor, OpenCode adapter, API
frontend/             React + AntD SPA (build output in frontend/dist)
alembic/              Database migrations
tests/unit/           Pure unit tests (temporary SQLite, injectable clock)
tests/integration/    Fake OpenCode / API contract / recovery and cancellation
scripts/perf_smoke.py Performance smoke test
specs/                PRD, SPEC, PLAN, TASKS
data/                 Runtime data (gitignored)
```
