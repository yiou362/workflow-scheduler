# AGENTS.md — PromptOps Console (`app/workflow-scheduler`)

Guidance for agents working in this subsystem. Read this before touching the frontend or any
user-facing message. It supplements the repository-level `AGENTS.md` at `bo/AGENTS.md`.

## Mandatory rule: the UI is English-only

**All text rendered in the web UI must be English.** This is a hard constraint, not a style
preference. It applies to every layer that can reach a screen.

Scope — every one of these must be English:

| Surface | Where |
|---|---|
| Frontend labels, buttons, table headers, placeholders, form validation messages, empty states, `message.*` toasts, `modal.confirm` copy | `frontend/src/**/*.tsx`, `frontend/src/**/*.ts` |
| Label dictionaries and enum-to-text maps | `frontend/src/utils/format.ts` |
| Client-side error strings | `frontend/src/api/client.ts` |
| antd component locale | `ConfigProvider locale` in `frontend/src/main.tsx` (`enUS`) |
| Date/time widget locale | dayjs locale in `frontend/src/utils/time.ts` (`en`) |
| Document language | `<html lang="en">` in `frontend/index.html` |
| API error `message` / `details` values | `promptops/api/errors.py`, `promptops/services/*.py` |
| Messages returned in response bodies and shown as toasts | `promptops/services/*.py`, `promptops/api/routes_*.py` |
| Persisted strings rendered in the UI (`error_message`, `last_test_message`, `config_snapshot` notes) | `promptops/scheduler/*.py`, `promptops/executor/*.py`, `promptops/services/*.py`, `promptops/opencode/client.py`, `promptops/trace/*.py` |
| Schedule summaries | `promptops/domain/schedule.py`, `promptops/api/serialize.py`, `promptops/services/dashboard_service.py` |

Why the backend is in scope: `ErrorState`, `EndpointTestAlert`, and every `message.*` call
render `err.message` or `response.message` verbatim. A Chinese string produced by the backend
is still Chinese text on the screen, so translating only `frontend/src` does not satisfy the
rule.

Not in scope: user data. Task prompts, `data/` contents, model output, trace payloads, and
log details are stored and displayed verbatim and may be in any language. Do not translate
them, and do not add filtering that would alter them.

### Verify before declaring the work done

```bash
# 1) Frontend source and build inputs must contain no CJK characters.
cd app/workflow-scheduler/frontend
grep -rnP '[\x{4e00}-\x{9fff}]' src index.html && echo "VIOLATION: CJK in frontend source"

# 2) Backend user-facing layers must contain no CJK characters.
cd ..
grep -rnP '[\x{4e00}-\x{9fff}]' promptops --include=*.py && echo "VIOLATION: CJK in backend"
```

Both commands must print nothing. Test fixtures that assert on Chinese *prompt content*
(`tests/helpers.py`, `tests/integration/fake_opencode.py`) are intentional — they prove
non-ASCII user data round-trips correctly. Do not "fix" them.

When adding a new string, add it in English directly. Do not introduce an i18n framework or a
parallel translation table for this rule; the product is English-only by contract.

## Subsystem conventions

- **Single process.** Scheduler, run claiming, and SSE supervision are in-process. Keep
  `workers=1` and never parallelise runs without redesigning run claiming. See `README.md`.
- **Fixed global time zone.** `PROMPTOPS_UTC_OFFSET` (default `+08:00`) applies to scheduling
  and display; there is no per-task zone and no DST handling. Render times through
  `formatTime` / `TimeText` so the offset stays consistent.
- **Prompts are verbatim.** A task's prompt is stored and sent unchanged; never append hidden
  instructions, preambles, or skill hints.
- **Never echo credentials.** Endpoint passwords are Fernet-encrypted and write-only.
  API responses, logs, and UI must not contain passwords or `Authorization` headers.
- **Never auto-approve permissions.** Runs may sit in `waiting` until a human replies; do not
  add auto-approval shortcuts to make demos flow better.
- **`frontend/dist` is committed.** The backend serves the SPA from it. After any frontend
  change run `pnpm typecheck && pnpm build` and commit the rebuilt `dist/`.
- **Spec trio.** Changes to behaviour update `specs/SPEC.md`, `specs/PLAN.md`, and
  `specs/TASKS.md` in place (never a nested new trio), with `- [ ]` / `- [x]` checkboxes.
- **Do not invent business rules.** If a threshold, policy, or field mapping is undefined,
  surface it as a clarification instead of picking a silent default.

## Commands

```bash
# Backend
.venv/Scripts/python.exe -m pytest tests/unit -q
.venv/Scripts/python.exe -m pytest tests/integration -q

# Frontend
cd frontend && pnpm typecheck && pnpm test && pnpm build
```

Environment note: DB-backed backend tests require `aiosqlite`. On Python 3.14 + Windows in some
sandboxes `aiosqlite` aborts the process with a fatal exception (`0xc0000096`) inside its
connection worker thread, which kills the whole pytest session. If that happens, the failure is
environmental — verify it with a two-line `aiosqlite.connect(":memory:")` probe before blaming
the code, and run the DB-free suites (`tests/unit/test_schedule.py`) to confirm the rest is
healthy.
