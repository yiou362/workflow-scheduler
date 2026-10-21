# PLAN — PromptOps Console 实现方案（HOW）

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 对应需求 | [PromptOps_Console_PRD_v1.0.md](./PromptOps_Console_PRD_v1.0.md) |
| 对应设计 | [SPEC.md](./SPEC.md) |
| 工作清单 | [TASKS.md](./TASKS.md) |
| 最后更新 | 2026-10-19 |

本文档把 SPEC 的架构落到实际文件与运行时组件，并记录实施中做出的工程决定。产品行为以 PRD 为准，技术细节以 SPEC 为准；本文件解释“代码放在哪里、怎么协作”。

## 1. 运行时拓扑

```text
Browser (React SPA)
   │ fetch /api/v1 (JSON) + 静态资源
   ▼
FastAPI 单进程 (Uvicorn workers=1)
   ├── api/             路由、Pydantic 请求、错误 envelope、序列化
   ├── services/        Endpoint/Task/Run/Dashboard/Recovery/Options
   ├── scheduler/       1s tick：到期 Task → Run（exactly-once）
   ├── dispatcher/      N worker：领取 Queued Run，保证同 Task 串行
   ├── executor/        Run 状态机、finalizer、sweeper、RunHandle
   ├── opencode/        v2 HTTP client、SSE parser、Endpoint 流监管
   ├── trace/           SSE/消息 → trace_items
   ├── persistence      repositories + SQLAlchemy ORM
   └── web/spa.py       frontend/dist + SPA fallback
   │
   ├── SQLite (WAL)     endpoints/tasks/runs/run_logs/trace_items
   └── OpenCode v2      /api/info, /api/session, /api/event (SSE), ...
```

`Runtime`（`promptops/runtime.py`）是唯一把上述协作者装在一起的容器：构造 client、注册
RunHandle、把终态事件转给 finalizer、管理启动/关闭顺序。所有 API 通过
`app.state.runtime` 访问它，便于测试替换 `make_client` 或注入 `FixedClock`。

## 2. 文件落点

| 关注点 | 文件 |
|---|---|
| 配置/日志/密钥/时间 | `promptops/config.py`, `logging.py`, `security.py`, `timeutil.py`, `ids.py` |
| 领域纯函数 | `promptops/domain/state_machine.py`, `schedule.py`, `snapshots.py`, `trace.py` |
| 持久化 | `promptops/models.py`, `db.py`, `repositories/{endpoints,tasks,runs,logs,trace}.py` |
| 业务服务 | `promptops/services/{endpoint,task,run,dashboard,recovery,options}_service.py`, `client_factory.py` |
| OpenCode 适配 | `promptops/opencode/{client,errors,sse,stream}.py` |
| 调度/执行 | `promptops/scheduler/engine.py`, `dispatcher/pool.py`, `executor/{run_executor,finalizer,sweeper,handles}.py` |
| 轨迹 | `promptops/trace/ingestor.py` |
| HTTP API | `promptops/api/{routes_meta,routes_dashboard,routes_endpoints,routes_tasks,routes_runs}.py`, `schemas.py`, `serialize.py`, `errors.py`, `dependencies.py` |
| SPA | `promptops/web/spa.py` |
| 应用入口 | `promptops/main.py`, `__main__.py` |
| 迁移 | `alembic/versions/0001_initial.py` |
| 前端 | `frontend/src/{api,pages,components,hooks,utils}` |
| 测试 | `tests/unit`, `tests/integration` |

依赖方向：`api → services → repositories/domain`；`scheduler/dispatcher/executor → opencode + repositories + domain`；
`opencode` 不依赖 `api`；`domain` 不依赖 ORM/FastAPI。`api/serialize.py` 是唯一的 ORM → JSON 出口。

## 3. 关键实现决定

1. **Run 快照唯一事实**：`run_service.create_run()` 与 `_create_rerun_run()` 一次性写入
   `config_snapshot_json` 和冗余列；之后没有任何更新路径修改它们。
2. **状态迁移条件更新**：`repositories/runs.transition()` 使用 `WHERE id=? AND status IN (...)`
   （`rowcount==1` 才成功）。终态不可逆；迟到事件只写 RunLog。
3. **exactly-once 三层**：`ux_runs_task_occurrence` 唯一索引、创建 Run 与推进 `next_run_at`
   同一事务、`SchedulerEngine._lock`。tick 内单个 Task 异常不影响其他 Task。
4. **同 Task 串行**：领取查询排除“同 Task 存在活动 Run”的 Queued Run；`_claim_lock` 串行化
   领取事务；同一 Task 的 Queued Run 按 `created_at, id` FIFO。
5. **取消/超时不谎报**：`RunHandle` 负责唤醒（terminal/cancel/timeout）；执行器调用
   `/interrupt` 后等待确认窗口，未确认先查 `/api/session` 的 `outcome`，仍无才写 `Unknown`。
   取消/超时确认后才写 `cancel_confirmed_at` 并显示 `Cancelled`/`Timeout`。
6. **不重发 Prompt**：Prompt POST 的不确定结果先对账 `/message`（文本完全一致且时间满足）；
   对不上写 `Unknown(prompt_admission_unknown)`，绝不自动重试。
7. **轨迹只来自观察**：SSE 事件与 `/message`、`/diff` 生成 `trace_items`；Skill 只在
   `session.skill.activated` 或 skill 消息出现时记录；reasoning 内容丢弃；文件以 `/diff` 为准。
8. **全局 UTC+08:00**：`PROMPTOPS_UTC_OFFSET` 解析为固定 `datetime.timezone`；croniter 以
   aware datetime 计算；DB 只存 UTC epoch ms；Run 快照保存当时的偏移用于历史展示。
9. **Alembic 日志隔离**：程序内迁移通过 `Config.attributes["skip_logging_config"]` 跳过
   `fileConfig`，避免 Alembic 覆盖应用的 JSON 日志与文件 handler。
10. **前端轮询**：Run 详情在活动状态 2s 轮询 `run/trace/logs`，终态自动停止；页面隐藏时
    TanStack Query 默认暂停。关闭页面不影响后台执行。
11. **错误 envelope**：`{error:{code,message,details}}`；422 的 `details` 为字段 → 文案，前端
    直接 `form.setFields`。
12. **测试替身**：`tests/integration/fake_opencode.py` 实现适配层接口（含空 SSE 流），通过
    `runtime.make_client` 注入；不访问真实服务。
13. **location 使用 deepObject 编码**：模型/Agent 发现调用 `/api/model`、`/api/agent` 时必须发送
    `location[directory]=<wd>`；`location.directory` 会被 OpenCode 忽略并退回全局配置。客户端
    已有回归测试（`tests/unit/test_opencode_client.py`），前端只看返回的候选列表。
14. **工作目录是 OpenCode 侧路径**：Task 保存的 `working_directory` 原样传给 Session 的
    `location.directory`，用于加载该目录的 `opencode.json` / Skill；系统不读取它，也不校验存在性。
15. **界面语言唯一（英文）**：前端不引入 i18n 框架，文案以英文直接落笔；`ConfigProvider`
    固定 `enUS`、dayjs 固定 `en`、`<html lang="en">`。由于 `ErrorState` / `EndpointTestAlert` /
    所有 `message.*` 直接渲染 `err.message` 与 `response.message`，后端会出现在界面上的
    字符串（`api/errors.py`、`services/*.py` 的 message/details、持久化的 `error_message` 与
    `last_test_message`、`schedule_summary`）同样必须是英文。硬约束与验收命令写入
    [AGENTS.md](../AGENTS.md)。

## 4. 启动/关闭

启动（`main.lifespan`）：目录 → 日志 → engine/PRAGMA → SQLite 版本 → Alembic →
SecretBox → seed Endpoint → Runtime → Recovery（对账活动 Run）→ Scheduler → Dispatcher →
Sweeper → 接受请求。

关闭：停 Scheduler → 停 Dispatcher → 取消 SSE 流 → 停 Sweeper/Recovery → 等待 finalize
（`SHUTDOWN_GRACE_SECONDS`）→ 关闭 engine。活动 Run **不标失败**，下次启动 Recovery 对账。

## 5. 测试与验收

- 单元：状态机、调度纯函数、密钥/脱敏、SSE parser、轨迹规范化、快照、finalizer 响应、
  Endpoint 分类、Task 校验、exactly-once/overlap/missed/once/interval、Dispatcher 领取、
  SSE 断线 gap。
- 集成：Fake OpenCode 下的执行成功、Prompt 不确定、连接失败、取消确认/未确认、超时前/后、
  重启恢复、权限回复；API 契约（Endpoint/Task/Run/Preview/SPA/404）。
- 前端：client 错误解析、UTC+8 时间工具、StatusTag 12 状态、TraceView、ScheduleForm。
- 真实 v2 验收记录见 [docs/acceptance.md](../docs/acceptance.md)。

## 6. 与 SPEC 的差异

- 新增 `promptops/runtime.py` 作为运行时容器（SPEC 目录清单未列，但避免全局单例）。
- 新增 `promptops/api/{serialize,dependencies}.py`（SPEC 的 schemas/errors 之外的序列化与依赖注入）。
- 新增 `scripts/perf_smoke.py` 与 `tests/integration/fake_opencode.py`。
- `frontend/src/components` 使用 `AutoComplete` 实现“模型可手输”的 Select 语义；字段与 API 契约不变。
- 未实现 SPEC 1.3 明确排除的项（v1 适配、健康监控、自动审批、多用户、分布式、图表等）。
