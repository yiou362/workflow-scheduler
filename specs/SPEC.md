# SPEC — PromptOps Console 技术实现方案

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 文档状态 | MVP 已实现并通过自动化与真实 v2 冒烟验收（见第 19 节） |
| 对应需求 | [PromptOps_Console_PRD_v1.0.md](./PromptOps_Console_PRD_v1.0.md) |
| 对应计划 | [PLAN.md](./PLAN.md) |
| 目标范围 | MVP（PRD 第 10.1 节） |
| 实测协议 | OpenCode v2.0.29，`opencode serve` 的 v2 HTTP API |
| 最后更新 | 2026-10-19 |

本文档把 PRD 的产品要求翻译成可实施的技术方案：技术架构、技术选型、数据模型、状态机、核心流程、接口与页面、测试策略、实施任务拆分。**产品行为以 PRD 为准**；本文档只规定“如何实现”，不新增业务规则。凡是 PRD 未定义、但实现必须做选择的地方，均在文中标注为“设计决定”，并在第 17 节汇总为待确认项。

> 定位说明：按仓库的 spec-driven 约定，`SPEC.md` 通常只写 WHAT、`PLAN.md` 写 HOW；本文档是应本次需求交付的**技术实现方案**，内容偏 PLAN。产品 WHAT 仍以 PRD 为准。实施开始时，应把本文第 11 节的文件落点整理进 `PLAN.md`，并按已拆分的 `TASKS.md` 执行。

## 目录

- 0 设计原则
- 1 设计摘要
- 2 技术选型
- 3 总体架构
- 4 关键技术决策（ADR）
- 5 领域模型与状态机
- 6 数据模型
- 7 OpenCode v2 适配层
- 8 核心功能实现设计
- 9 Web API 设计
- 10 React 前端设计
- 11 目录结构与代码组织
- 12 配置与环境变量
- 13 安全、可靠性与运维
- 14 测试策略
- 15 实施计划与任务拆分（任务见 [TASKS.md](./TASKS.md)）
- 16 PRD 需求追踪矩阵
- 17 风险、限制与待确认项
- 18 验收标准（技术）
- 附录 A OpenCode v2.0.29 实测协议样本
- 附录 B 错误分类与用户可见行为
- 附录 C 术语表
- 附录 D 实现检查清单

---

## 0. 设计原则

1. **Run 是唯一执行事实。** Task 是可复用模板；Run 创建时冻结完整配置快照。之后 Task 或 Endpoint 怎么改，都不影响已创建的 Run。
2. **只展示观察到的轨迹。** 不根据 Prompt、Tool 名称或业务常识推断 Skill 调用、文件变化或执行结果。拿不到就标“不完整/无轨迹”，不补故事。
3. **不做隐式补救。** 不自动切换 Endpoint，不自动重发状态不明的 Prompt，不自动审批权限，不自动判定业务正确性。所有补救动作由用户显式发起。
4. **先持久化，再行动。** 每次状态迁移先落库；长 HTTP/SSE 等待期间不持有数据库事务。进程崩溃后能靠数据库恢复。
5. **单进程、少依赖、可运维。** MVP 是单用户内部工具，不做分布式调度、消息队列和多租户。一个 Python 进程 + SQLite 足够，部署和排障成本最低。
6. **协议隔离。** OpenCode v2 API 仍标注为 experimental。所有协议细节收敛在 `opencode/` 适配层，业务层只依赖领域对象和规范化后的轨迹条目。
7. **安全默认。** 默认只监听 `127.0.0.1`；Endpoint 密码加密存储；日志和页面永不回显密码；模型输出按不可信文本渲染。
8. **时区简化为全局 UTC+08:00。** 数据库统一存 UTC epoch 毫秒；所有调度规则按全局东八区（`+08:00`）解释，展示也统一用 `UTC+08:00`；不按 Task 配置时区，不做 DST/浏览器本地双时区。

---

## 1. 设计摘要

### 1.1 一句话架构

```text
React 18 + Ant Design 5 SPA（Vite 构建）
        │ JSON /api/v1
        ▼
FastAPI 单进程（API + Scheduler + Dispatcher + Executor + SSE Supervisor）
        │
        ├── SQLite（WAL）：Endpoint / Task / Run / RunLog / TraceItem
        ├── frontend/dist：SPA 静态资源（FastAPI 同源提供）
        │
        └── OpenCode v2 HTTP API（每个 Endpoint 一条 SSE 流）
```

### 1.2 关键结论

| 结论 | 说明 |
|---|---|
| 只支持 OpenCode v2 HTTP API | 通过 `GET /api/info` 探测并返回 `version`；v1 的 `/global/health`、`/session/:id/prompt_async` 不实现，测试连接时明确报告“v1 服务不受支持” |
| 调度器自研，不用 APScheduler | PRD 的 overlap / missed / queue / recovery 语义需要精确控制；自研 tick + `croniter` 更小、更可测、行为可解释 |
| 单进程异步执行，不引入 Celery/Redis | 单个 Uvicorn 进程内跑调度器与执行器；SQLite 唯一约束保证同一计划时刻最多一个 Run |
| 时区简化为全局 UTC+08:00 | 默认东八区，所有 cron/once/interval 和页面展示统一按 `+08:00`；不提供 per-task 时区、DST 处理或浏览器本地双时区 |
| UI 用 React + Ant Design SPA | Vite 构建、FastAPI 提供 `/api/v1` JSON API 与 `frontend/dist` 静态资源；实时轨迹用 TanStack Query 2 秒轮询，关闭页面不影响后台执行 |
| Run 配置快照是权威 | 快照 JSON + 冗余查询列；历史展示永远读 Run，不读 Task 当前值 |
| 权限不自动批准 | OpenCode 请求权限时 Run 进入 `Waiting`，在 Run 详情页由用户 Allow once / Always / Reject；超时策略仍生效 |
| 轨迹“原始事件 → 规范化条目” | SSE 事件实时落 `trace_items`；结束时用 `/message` 与 `/diff` 对账；明确标记轨迹完整性 |
| 状态不明的 Prompt 不重发 | `POST /prompt` 网络异常后先查用户消息对账；确认不了就 `Unknown`，由用户决定是否 Rerun |

### 1.3 明确不做（MVP）

- 不做 Endpoint 定时健康监控、自动故障转移、自动重试。
- 不做 Skill/Tool/MCP 管理、Skill 编辑器、DAG 编排。
- 不做多用户、登录、RBAC、审计合规。
- 不做分布式调度、多实例高可用、消息队列。
- 不生成执行总结，不验证报表/文件/外部系统的业务正确性。
- 不展示模型未公开的推理过程；v2 的 `session.reasoning.*` 与 assistant reasoning 内容不进入 UI。
- 不实现通用 form/question 表单的渲染与回复；只处理权限请求（见 7.9）。
- 不做 per-task 时区与 DST；全局固定 UTC+08:00（见 17.2）。

### 1.4 与现有 `workflow-runner` 的关系

`app/workflow-runner` 是已有的单 Endpoint、固定顺序、无 UI 的顺序执行守护进程；本系统是独立的新应用，**不复用其代码、数据库或 `workflows.json`**。

- 两者可以并存（不同 Endpoint / 不同 Task 范围），但不要让它们同时调度同一批 Prompt，否则会产生重复执行。
- 如需把 `workflows.json` 迁移为 Task，写一次性导入脚本即可；导入不属于 MVP，且导入后的 Task 默认 `disabled`，由用户确认后再启用。
- 本系统不读取、不修改 `workflow-runner` 的 `state.db`；排障时不要把两套 Run 记录混在一起看。

---

## 2. 技术选型

### 2.1 选型总表

| 领域 | 选型 | 版本/形态 | 选择理由 | 未采用及原因 |
|---|---|---|---|---|
| 语言 | Python | 3.12+（本机解释器 3.14；依赖安装后需再跑冒烟） | 与仓库现有 OpenCode 工具链、pytest、venv 一致；`asyncio`/`datetime` 标准库足够 | Go/Node：团队与仓库生态不匹配 |
| Web 框架 | FastAPI + Uvicorn | FastAPI ≥ 0.115，Uvicorn ≥ 0.30 | 类型化 JSON API；单进程即可承载 API + 后台任务；自动 OpenAPI 便于前端联调 | Flask：异步 SSE/HTTP 并发不如 FastAPI 自然；Django：对本项目过重 |
| 前端框架 | React 18 + TypeScript | React ≥ 18.3，TypeScript ≥ 5.6 | 用户指定 React；组件化适合轨迹查看、表单和运行详情；类型化 API 客户端 | Vue/Svelte：用户指定 React；原生 JS：复杂交互难以维护 |
| UI 组件库 | Ant Design 5 | `antd` ≥ 5.22，`@ant-design/icons` ≥ 5.5 | 企业级表格/表单/弹窗/时间线/描述列表开箱可用；中文 locale 完整 | Pico/手写 CSS：重复造轮子；Tailwind：与 AntD 主题体系重叠 |
| 前端构建 | Vite + `@vitejs/plugin-react` | Vite ≥ 5.4，Node ≥ 20 | 开发 HMR、生产静态构建；配置简单；与 FastAPI 同源部署 | Next.js：不需要 SSR；CRA：已过时；Webpack 手配：更重 |
| 路由与数据 | React Router 6 + TanStack Query 5 + 原生 `fetch` | 无 Redux | 页面路由、请求缓存、轮询/失效重取都由成熟库处理；`fetch` 足够，避免 axios | Redux：MVP 不需要全局 store；SWR：也可，但 TanStack Query 的 mutation/失效语义更完整 |
| 时间展示 | dayjs + `utc` 插件 + `utcOffset` | AntD 已依赖 dayjs | 统一按 UTC+08:00 展示；与 AntD DatePicker 一致；不需要 timezone 插件 | 原生 `Intl`：也能做，但和 AntD 组件配合不如 dayjs 顺 |
| 数据库 | SQLite（WAL） | 文件型 | 单用户、单进程、数据量小；备份/迁移简单；无需运维 | PostgreSQL：MVP 无并发/多实例需求；引入即增加部署成本 |
| ORM/迁移 | SQLAlchemy 2 async + Alembic | SQLAlchemy ≥ 2.0.30，aiosqlite | 异步会话与 FastAPI 一致；迁移可版本化 | 纯 `sqlite3`：查询多、迁移和 JSON 处理重复代码多；SQLModel：抽象层更厚 |
| 调度 | 自研 tick + `croniter` | `croniter` ≥ 2.0 | 精确实现 exactly-once、overlap、missed、queue；逻辑集中可测 | APScheduler：misfire/coalesce 语义与 PRD 不完全一致，反而要绕开其默认行为 |
| HTTP 客户端 | `httpx` | ≥ 0.27 | 同步/异步统一；支持 Basic Auth、超时、流式 SSE | `requests`：无原生 async；`aiohttp`：也可，但 httpx 的 API 与测试替身更简单 |
| 数据校验 | Pydantic v2 | FastAPI 自带 | JSON 请求/响应校验、序列化一致；422 错误可映射到 AntD Form | 手写校验：错误信息与类型转换重复 |
| 密码加密 | `cryptography` Fernet | ≥ 42 | 对称加密、API 简单、密钥可轮换 | 明文：不可接受；哈希：密码需要还原后发给 Endpoint，不能哈希 |
| 时区 | 固定 UTC 偏移（`datetime.timezone`） | 默认 `+08:00`（东八区） | 中国无 DST；全局统一偏移，调度/展示逻辑最简单 | IANA/zoneinfo：per-task 时区与 DST 复杂度高，MVP 不需要 |
| 后端测试 | pytest + pytest-asyncio + httpx MockTransport/ASGI | 与仓库一致 | 单测不依赖外部服务；可模拟 OpenCode v2 与 SSE | 只做手工测试：调度与恢复逻辑无法可靠回归 |
| 前端测试 | Vitest + Testing Library + jsdom | 轻量 | 测 API client、关键表单/状态组件；不引入浏览器 E2E 作为默认门禁 | 只靠手工点页面：表单/轮询回归不可靠 |
| 日志 | 标准库 `logging` + 自定义 JSON formatter | 无额外依赖 | 结构化、可 grep、可接 journald/Docker | 第三方日志库：收益不足以新增依赖 |
| 部署 | 单 Uvicorn 进程；`pnpm build` 产出 `frontend/dist`；systemd/supervisord 二选一 | 跨 Linux/Windows | 与仓库现有 supervisord 习惯一致；Windows 可直接 `python -m promptops` | Docker 多容器：MVP 不需要；多 worker：会重复调度 |

### 2.2 依赖清单

`requirements.txt`：

```text
fastapi>=0.115
uvicorn[standard]>=0.30
sqlalchemy[asyncio]>=2.0.30
aiosqlite>=0.20
alembic>=1.13
httpx>=0.27
croniter>=2.0
cryptography>=42
pydantic-settings>=2.3
python-dotenv>=1.0
```

`frontend/package.json`（npm/pnpm 依赖，不是 Python 依赖）：

```json
{
  "dependencies": {
    "antd": "^5.22.0",
    "@ant-design/icons": "^5.5.0",
    "@tanstack/react-query": "^5.62.0",
    "dayjs": "^1.11.13",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.28.0"
  },
  "devDependencies": {
    "@testing-library/dom": "^10.4.0",
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.0.0",
    "@types/node": "^22.0.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "jsdom": "^25.0.0",
    "typescript": "^5.6.0",
    "vite": "^5.4.0",
    "vitest": "^2.1.0"
  }
}
```

> 以上只列依赖；完整的 `package.json`（name/scripts/engines）由 T0.6 生成。

`requirements-dev.txt`：

```text
-r requirements.txt
pytest>=8
pytest-asyncio>=0.23
```

不引入：Redis、Celery、APScheduler、SQLModel、Jinja2、HTMX、Pico.css、Tailwind、Bootstrap、jQuery、Redux、axios、markdown 渲染库（MVP 用 `<pre>` 原样展示）。前端构建只引入 Vite/React/AntD/TanStack Query 这一套。

### 2.3 版本与兼容性

- **后端**：Python 3.12+；不使用 3.13/3.14 独有语法。
- **时区**：全局固定 UTC 偏移，默认 `+08:00`（东八区）；所有调度/展示按此偏移，不做 per-task 时区与 DST。部署在非东八区时通过 `PROMPTOPS_UTC_OFFSET` 统一调整。
- **前端**：Node 20+（本机 Node 24 可用）、pnpm 9+；React 18.3、Ant Design 5.x、Vite 5.4、TypeScript 5.6+。不要用 React 19 + AntD 5 的组合（需要额外兼容补丁），MVP 固定 React 18；Vite 5.4 + Vitest 2.1 是常用兼容组合，以 T0.6 安装冒烟为准。
- **浏览器**：最近两个版本的 Chrome/Edge/Firefox/Safari；不支持 IE。
- Windows 与 Linux 都必须可运行：路径用 `pathlib`；不硬编码 `/tmp`；不依赖 POSIX shell。
- SQLite ≥ 3.38（JSON1、部分索引）；Python 自带 SQLite 满足。若目标环境更旧，启动时检查并报错。
- OpenCode 目标版本：v2.0.29 实测。v2 API 版本升级可能改变事件字段；适配层必须把未知事件降级为“忽略并记录”，不能让未知事件导致 Run 崩溃。

---

## 3. 总体架构

### 3.1 组件图

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Browser                                                             │
│  React 18 + Ant Design 5 SPA（Vite + TypeScript）                    │
│  React Router / TanStack Query / fetch                              │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ JSON /api/v1 + 静态资源
┌───────────────────────────────▼─────────────────────────────────────┐
│ FastAPI 单进程（Uvicorn，workers=1）                                 │
│                                                                     │
│  api/            JSON 路由、请求/响应 schema、错误与分页             │
│  web/spa.py      提供 frontend/dist、SPA fallback、缓存头            │
│  services/       EndpointService / TaskService / DashboardService    │
│  scheduler/      SchedulerEngine（每 1s tick）                       │
│  dispatcher/     RunDispatcher（N 个 worker 协程）                   │
│  executor/       RunExecutor（单个 Run 的状态机）                    │
│  recovery/       RecoveryService（启动时对账）                       │
│  trace/          TraceIngestor（事件 → trace_items）                 │
│  opencode/       OpenCodeV2Client + EventStreamSupervisor            │
│  persistence/    SQLAlchemy async models / repositories              │
└───────────────┬─────────────────────────────────┬───────────────────┘
                │                                 │
                ▼                                 ▼
┌───────────────────────────────┐   ┌─────────────────────────────────┐
│ SQLite (WAL)                  │   │ OpenCode v2 Endpoint(s)         │
│ endpoints / tasks / runs      │   │  GET  /api/info                 │
│ run_logs / trace_items        │   │  POST /api/session              │
│ alembic_version               │   │  POST /api/session/{id}/prompt  │
└───────────────────────────────┘   │  GET  /api/session/{id}/message │
                                    │  GET  /api/session/{id}/diff    │
                                    │  POST /api/session/{id}/interrupt│
                                    │  POST .../permission/{rid}/reply│
                                    │  GET  /api/event (SSE)          │
                                    └─────────────────────────────────┘
```

### 3.2 模块职责

| 模块 | 职责 | 不做什么 |
|---|---|---|
| `frontend/` | React 页面、AntD 组件、API client、路由、查询缓存、轮询 | 不直接访问数据库/OpenCode；不渲染未转义 HTML |
| `api/` | `/api/v1` 路由、Pydantic 请求/响应、错误映射、分页、权限校验（MVP 无登录） | 不直接拼 SQL、不直接调 OpenCode |
| `web/spa.py` | 提供 `frontend/dist`、SPA fallback、静态资源缓存头 | 不处理业务 API |
| `services/endpoints.py` | Endpoint CRUD、默认端点、启停、删除约束、连接测试 | 不执行 Run |
| `services/tasks.py` | Task CRUD、复制、归档、校验、调度预览、模型发现 | 不产生 Run |
| `services/dashboard.py` | Dashboard 统计、最近执行、最近失败 | 不做实时健康探测 |
| `scheduler/engine.py` | 到点产生 Run、推进 `next_run_at`、重叠/错过策略 | 不执行 Run |
| `dispatcher/pool.py` | 领取 Queued Run、保证同一 Task 串行、并发上限 | 不关心 OpenCode 协议细节 |
| `executor/run_executor.py` | 单个 Run 的完整生命周期：连接、建会话、提交、等待、取消、超时、收尾 | 不推进调度时间、不修改 Task |
| `opencode/client.py` | v2 HTTP 调用、认证、超时、错误分类、响应解析 | 不写业务状态 |
| `opencode/stream.py` | 每个 Endpoint 一条 SSE 流、重连、事件分发 | 不直接改 Run 终态（交给 executor/ingestor） |
| `trace/ingestor.py` | 事件规范化、幂等 upsert、轨迹完整性标记 | 不根据 Prompt 推断事件 |
| `recovery/service.py` | 启动时恢复非终态 Run、对账 Session | 不重发 Prompt |
| `persistence/` | ORM 模型、仓储查询、事务边界 | 不含业务规则 |

### 3.3 启动与关闭顺序

**启动（FastAPI lifespan）**

1. 读取配置、初始化日志。
2. 确保 `data/`、`data/logs/` 存在；检查 SQLite 版本。
3. 执行 Alembic 迁移（`PROMPTOPS_AUTO_MIGRATE=true` 时）。
4. 加载/生成 Fernet 密钥（若未配置）。
5. 若数据库无 Endpoint 且提供了 `PROMPTOPS_DEFAULT_ENDPOINT_*`，创建默认 Endpoint。
6. 运行 `RecoveryService.recover_on_startup()`：处理非终态 Run，见 8.4.9。
7. 启动 `SchedulerEngine`。
8. 启动 `RunDispatcher` worker 协程。
9. 检查 `frontend/dist/index.html`：存在则挂载 SPA 静态资源；不存在时 API 仍可用，`/` 返回 503 + 构建提示（开发时由 Vite dev server 提供页面）。
10. 开始接受 HTTP 请求。

**关闭**

1. 停止 Scheduler tick，不再产生新 Run。
2. Dispatcher 停止领取新 Run。
3. 等待正在执行的 Run 至多 `PROMPTOPS_SHUTDOWN_GRACE_SECONDS`（默认 20s）。
4. 取消 SSE 流、关闭 httpx 客户端。
5. 关闭数据库引擎。

未完成的 Run **不标记失败**，保持 `Running` / `Waiting` / `Submitting`；下次启动由 Recovery 对账。这样避免“服务重启 = 任务失败”的假象。

### 3.4 并发模型

- 单事件循环；所有 HTTP、SSE、DB 调用都是 async。
- `SchedulerEngine` 每 1 秒 tick 一次；tick 之间用 `asyncio.Lock` 防止重入。
- `RunDispatcher` 默认 2 个 worker（`PROMPTOPS_MAX_CONCURRENT_RUNS`），每个 worker 循环“领取一个 Run → 执行 → 再领取”。
- 同一 Task 同时最多一个**执行中** Run；Queued Run 按 `created_at` FIFO。
- 每个 Endpoint 最多一条 SSE 流；由 `EventStreamSupervisor` 懒启动（该 Endpoint 第一次有活动 Run 时），无活动 Run 后 5 分钟关闭。
- 全局 `claim_lock` 保护“领取 Run”与“创建 Run”的临界区。单进程下这足够；多实例部署不在 MVP 内。

### 3.5 定时执行数据流

```text
Scheduler tick
  → 选出 status=enabled, schedule_enabled=1, next_run_at<=now 的 Task
  → 事务内：创建 Run(Queued) + 计算并写入 next_run_at
  → Dispatcher 领取该 Run
  → Executor: Preparing（连接/探测/建 Session）
  → Executor: Submitting（POST Prompt）
  → Executor: Running（等待 SSE / 轮询）
  → SSE Supervisor / TraceIngestor 持续写 trace_items
  → 终态事件
  → Executor: Finalizing（GET session/message/diff）
  → Run = Completed / Failed / Cancelled / Timeout / Unknown
  → UI 通过 TanStack Query 2s 轮询 `/api/v1/runs/{id}` 与 `/api/v1/runs/{id}/trace` 看到变化
```

---

## 4. 关键技术决策（ADR）

### ADR-01：只实现 OpenCode v2 API，v1 明确不支持

**决定**：以 `GET /api/info` 返回 `{version, pid, urls, ...}` 作为“受支持服务”的判据。所有会话、消息、事件、权限、中断都走 `/api/*`。不实现 v1 的 `/global/health`、`/session/:id/prompt_async`、`/event`。

**理由**：

- 目标环境的 `opencode serve` 为 v2.0.29（`opencode serve --help` 明确写着 “Start the v2 API and web server”）。
- v1 与 v2 的 API 形态差异很大（v2 是 `{data: ...}` 信封、session 创建时带 location/model、消息是投影消息、事件是 `session.execution.*`），强行兼容会显著放大适配层。
- PRD 要求“目标服务不是受支持的 OpenCode Serve”可被识别；明确报“v1 不支持”比半兼容更安全。

**后果**：如果实际部署的是 v1，需要在 `opencode/` 下新增 `V1Adapter` 并扩展 Endpoint 探测。该工作不在 MVP。

**拒绝的方案**：运行时同时探测 v1/v2 并双实现。MVP 无此需求，且双实现的事件模型难以统一。

### ADR-02：自研调度器，`croniter` 只负责“下一次时间”

**决定**：不用 APScheduler 的 job store、misfire、coalesce、executor。调度器是一个 1 秒 tick 的纯函数式循环；`croniter` 只计算 cron 的下一次发生时间。所有“是否该执行、是否跳过、是否排队、错过怎么办”由本系统显式实现。

**理由**：

- PRD 的 overlap `queue/skip`、missed `skip/run_once`、one-off 执行后自动结束、endpoint 停用产生 Skipped 记录，这些都需要在“创建 Run”这一刻做统一决策。
- APScheduler 的 misfire grace、coalesce、max_instances 语义与 PRD 不完全一致；绕开它反而更难解释。
- 自研逻辑可以用纯函数单测覆盖，不依赖时钟和后台线程。

**后果**：需要自己实现 tick、固定 UTC 偏移换算、exactly-once 约束；这些在本文 8.3 与 14.1 中定义。时区简化为全局 `+08:00`，不做 DST 分支。

### ADR-03：React + Ant Design SPA，FastAPI 只提供 JSON API

**决定**：前端用 React 18 + Ant Design 5 + TypeScript + Vite；React Router 负责页面路由，TanStack Query 负责请求缓存/失效/轮询，原生 `fetch` 封装 API client。FastAPI 只提供 `/api/v1` JSON API，并在生产环境同源提供 `frontend/dist` 静态资源。运行中的 Run 详情每 2 秒轮询摘要、轨迹和日志。

**理由**：

- 用户明确要求 React + AntD；AntD 的 Table/Form/Select/DatePicker/Descriptions/Timeline/Modal 能覆盖本系统 90% 的界面，减少自写组件。
- Execution Trace Explorer 是核心界面，需要层级/时间线切换、Tool 输入输出折叠、权限弹窗、实时刷新；SPA 的组件状态和请求缓存比服务端局部刷新更自然。
- API-first 便于后续接入其他客户端、做契约测试和前端独立开发。
- React 18 + AntD 5 是稳定组合；不引入 React 19，避免 AntD 兼容补丁。

**后果**：

- 部署需要 Node/pnpm 构建步骤（`pnpm install && pnpm build`），产物 `frontend/dist` 由 FastAPI 或反向代理提供；后端不再是唯一运行时。
- 必须维护 JSON API 契约（`/api/v1`）与前端 TypeScript 类型；接口变更要同步前后端。
- 开发时需要 Vite dev server + FastAPI 两个进程（Vite 代理 `/api` 与 `/healthz`）；生产同源部署。
- 关闭/刷新页面仍不影响后台执行；后台调度与执行完全不依赖浏览器。
- 不做 SSR/Next.js：管理后台不需要 SEO 与服务端渲染，SSR 会增加部署与状态同步复杂度。

**拒绝的方案**：Jinja2 + HTMX（交互与实时轨迹不足，且用户要求 React）；纯 React + 手写 CSS（重复实现 AntD 已有的表格/表单/弹窗）；Next.js（SSR 无收益）。

### ADR-04：SQLite + WAL，单实例

**决定**：SQLite 文件数据库，开启 WAL、`foreign_keys=ON`、`busy_timeout=5000`。数据库放在本地磁盘，不放网络共享。应用强制单进程（Uvicorn `workers=1`）。

**理由**：单用户、低并发、数据量小；SQLite 的备份、迁移、排障最简单。WAL 允许读写并发，足以支撑 Web + 调度 + 执行。

**后果**：不支持多实例水平扩展；如果误开多个 Uvicorn worker，会出现重复调度/领取。启动时检测 `WEB_CONCURRENCY`/`--workers` 无法可靠获知，改为在 README 和启动脚本中固定 `--workers 1`。未来需要多实例时，迁移到 PostgreSQL，并把 claim 改为 `SELECT ... FOR UPDATE SKIP LOCKED`。

### ADR-05：单进程内异步执行，不引入任务队列

**决定**：Scheduler、Dispatcher、Executor 都是同一事件循环里的协程。没有 Celery、RQ、Redis、外部 worker。

**理由**：MVP 的并发量是个位数；长任务是 I/O 等待（HTTP/SSE），不是 CPU 密集。异步足够。引入队列会增加部署组件、序列化边界和故障面。

**后果**：进程重启会中断执行中的 Run；靠 Recovery 对账，不重发 Prompt。CPU 密集型处理不应放进本进程（本系统也不做）。

### ADR-06：Run 配置快照是权威

**决定**：创建 Run 时把 Task、Endpoint 的执行配置完整写入 `runs.config_snapshot_json`，并冗余到 `runs` 的查询列。执行、详情、Rerun 都读快照；只有“重新执行”时按快照 + 当前 Endpoint 解析连接信息。

**理由**：PRD 8.2 明确要求 Run 与 Task 当前配置隔离。历史页面不能因为 Task 被编辑而改变。

**后果**：修改 Task 不会改已有 Run；修改 Endpoint 的地址/认证只影响之后发起的执行，以及 Recovery 时重新解析的连接配置。快照中不存密码。

### ADR-07：轨迹“规范化条目”而非原始事件仓库

**决定**：SSE 事件在内存中规范化后 upsert 到 `trace_items`；不长期保存原始 SSE JSON。`trace_items.payload_json` 保留展示所需字段。Run 结束用 `/message` 和 `/diff` 对账补齐。

**理由**：原始事件与消息投影大量重复；Tool 输出可能很大，双份存储浪费。规范化条目足够支撑时间线、层级、Tool 输入输出、文件变化与完整性标记。

**后果**：如果未来需要协议级回放，需要新增 `trace_events` 原始表；当前不做。

### ADR-08：权限不自动批准，Run 可进入 Waiting

**决定**：收到 `permission.asked` 时，Run 置 `Waiting`，在 Run 详情页展示待审批项；用户选择 Allow once / Always / Reject 后调用 OpenCode 回复接口。没有全局自动批准开关。

**理由**：PRD 把 `Waiting` 列为用户可见状态，但没有授权系统替用户做安全决策。自动化任务若自动批准所有工具，风险不可控。

**后果**：无人值守的定时任务可能停在 `Waiting` 直到超时。这是显式行为，Dashboard 会显示 Waiting 数量。未来可增加 Task 级 `permission_mode`，但不在 MVP。

### ADR-09：Endpoint 密码加密存储，应用本身不做登录

**决定**：Endpoint 的 Basic Auth 密码用 Fernet 加密后入库；密钥来自 `PROMPTOPS_SECRET_KEY`，未配置时生成 `data/secret.key`（权限尽量 0600）。应用默认绑定 `127.0.0.1`，MVP 不做登录/RBAC；远程访问应放在带认证的反向代理后。

**理由**：密码需要还原后发给 OpenCode，不能哈希；明文入库不可接受。多用户/RBAC 在 PRD 10.2 中明确排除。

**后果**：能访问本机端口的人就能操作本系统；这是内部工具的信任边界。部署文档必须写明。

### ADR-10：状态不明的 Prompt 不自动重发

**决定**：`POST /api/session/{id}/prompt` 发生连接中断/超时/5xx 时，不重试；先查该 Session 的用户消息，判断 Prompt 是否已被接收。能确认 → 继续 `Running`；不能确认 → `Unknown`，保留错误说明，等待用户 Rerun。

**理由**：PRD 8.7 明确要求避免重复文件、重复消息、重复外部操作。Prompt 可能已经产生副作用。

**后果**：`Unknown` 需要人工判断；UI 必须清楚展示“为什么不确定”和“可以重新执行”。

---

## 5. 领域模型与状态机

### 5.1 实体关系

```text
Endpoint 1 ──── * Task 1 ──── * Run 1 ──── * TraceItem
                                  │
                                  └────── * RunLog

Run 的快照字段（task_name / endpoint_name / prompt / model / policy ...）
不依赖 Task / Endpoint 的当前值。
```

| 实体 | 说明 | 关键不变量 |
|---|---|---|
| Endpoint | 一个 OpenCode Serve 连接目标 | 系统恰好一个默认 Endpoint；默认 Endpoint 必须启用；密码只写不读 |
| Task | 可重复执行的 Prompt 模板 + 执行目标 + 调度 + 策略 | Task 不绑定 Skill；Prompt 原样保存；编辑不影响已创建 Run |
| Schedule | Task 的内嵌配置 | 使用全局 UTC+08:00；`next_run_at` 是下一次待触发时刻（UTC） |
| Run | 一次具体执行 | 创建即冻结快照；每个计划时刻最多一个 Scheduled/Recovery Run；终态不可逆 |
| TraceItem | Run 中观察到的一个消息/Tool/Skill/文件/权限/错误 | 只来自 OpenCode 返回的数据；幂等 upsert；不推断 |
| RunLog | Run 生命周期日志 | 追加写；不修改历史日志 |

### 5.2 Run 状态

| 状态 | 分类 | 含义 | 允许的下一状态 |
|---|---|---|---|
| `Queued` | 非活动（待执行） | 已创建，等待 worker 或同 Task 串行 | `Preparing`, `Cancelled`, `Skipped` |
| `Preparing` | 活动 | 已领取；解析 Endpoint、探测、创建 Session | `Submitting`, `Failed`, `Skipped`, `Cancelling`, `Cancelled`, `Timeout` |
| `Submitting` | 活动 | Prompt POST 正在途中 | `Running`, `Failed`, `Unknown`, `Cancelling`, `Cancelled`, `Timeout` |
| `Running` | 活动 | Prompt 已接收，OpenCode 正在处理 | `Waiting`, `Completed`, `Failed`, `Cancelling`, `Unknown` |
| `Waiting` | 活动 | OpenCode 正在等待权限或其他输入 | `Running`, `Completed`, `Failed`, `Cancelling`, `Unknown` |
| `Cancelling` | 活动（过渡） | 已请求停止，等待确认 | `Cancelled`, `Timeout`, `Completed`, `Failed`, `Unknown` |
| `Completed` | 终态 | Session 正常结束；不代表业务正确 | — |
| `Failed` | 终态 | 有明确错误（连接、认证、协议、Session 失败） | — |
| `Cancelled` | 终态 | 已确认因用户取消而停止 | — |
| `Timeout` | 终态 | 已确认因超时而停止 | — |
| `Skipped` | 终态 | 因重叠、Endpoint 停用、错过计划等未执行 | — |
| `Unknown` | 终态 | 无法确认执行是否停止/是否已接收 | — |

**活动集合**（用于“同 Task 串行”）：`Preparing, Submitting, Running, Waiting, Cancelling`。

**待执行/活动集合**（用于重叠判断）：`Queued` + 活动集合。理由是：Queue 策略下，队列中已有 Run 时，再来触发也应视为“上一次尚未结束”，否则队列会无限膨胀；Skip 策略下也应跳过。

**终态集合**：`Completed, Failed, Cancelled, Timeout, Skipped, Unknown`。

### 5.3 状态机

```text
                    ┌──────────────┐
                    │    Queued    │
                    └──┬────┬───┬──┘
             claim     │    │   │ cancel
                       ▼    │   └──────────────► Cancelled
              ┌────────────┐│
              │ Preparing  ││ endpoint disabled / pre-session failure
              └──┬──────┬──┘│
        session  │      └───────────────► Failed / Skipped
        created  ▼
              ┌────────────┐
              │ Submitting │
              └──┬──────┬──┘
        prompt   │      └───────────────► Failed / Unknown
        admitted ▼
              ┌────────────┐   permission asked   ┌───────────┐
              │  Running   │◄────────────────────►│  Waiting  │
              └──┬──┬──┬───┘   permission replied └─────┬─────┘
                 │  │  │                               │
      succeeded  │  │  └───────────────► Cancelling ◄─┘
                 │  │                        │
                 ▼  ▼                        ├── confirmed ──► Cancelled / Timeout
           Completed Failed                 └── unconfirmed ─► Unknown

任何活动状态 --取消/超时请求--> Cancelling
```

> 上图省略了 `Preparing/Submitting` 的取消分支（未提交 Prompt 时可直接 `Cancelled`）；完整规则以 5.2 表与 5.4 表为准。

**终态保护**：所有状态更新使用条件更新（`WHERE status = :expected`）。终态一旦写入，不再被迟到事件覆盖。迟到事件只记 RunLog，不改变状态。

### 5.4 状态迁移规则

| 触发 | 前置 | 结果 | 附带动作 |
|---|---|---|---|
| Scheduler 创建 | Task 可调度 | `Queued` | 写快照、写 `run_logs.created` |
| 用户手动执行 | Task 非归档 | `Queued` | 来源 `Manual`、写快照 |
| 历史重新执行 | 原 Run 存在 | `Queued` | 来源 `Rerun`、`rerun_of_run_id`、写快照 |
| 恢复补触发 | 启动时发现错过 | `Queued` | 来源 `Recovery`、`scheduled_for=最新错过时刻` |
| 重叠且 Skip | 存在待执行/活动 Run | `Skipped` | `error_type=overlap`，日志说明 |
| Endpoint 停用 | 触发时或领取时 | `Skipped` | `error_type=endpoint_disabled` |
| 错过且 Skip | 启动时超过 grace | `Skipped` | `error_type=missed_schedule`，记录错过次数 |
| Worker 领取 | `Queued` | `Preparing` | `started_at`、`last_heartbeat_at` |
| 连接/建会话成功 | `Preparing` | `Submitting` | 记录 `opencode_session_id` |
| Prompt 200 | `Submitting` | `Running` | `running_at`、记录用户消息 ID |
| Prompt 明确 4xx | `Submitting` | `Failed` | `error_phase=prompt`、不重发 |
| Prompt 网络异常且对账失败 | `Submitting` | `Unknown` | 不重发，提示人工判断 |
| 权限请求 | `Running` | `Waiting` | 记录 permission 条目 |
| 权限全部处理 | `Waiting` | `Running` | 记录回复 |
| Session 正常结束 | `Running/Waiting` | `Completed` | 收尾、拉消息/ diff、写 final response |
| Session 失败 | `Running/Waiting` | `Failed` | 记录结构化错误 |
| 用户取消 | `Queued` | `Cancelled` | 不需要外部中断 |
| 用户取消 | `Preparing/Submitting` 且未提交 Prompt | `Cancelled` | 无外部执行；写 `cancel_confirmed_at` |
| 超时 | `Preparing/Submitting` 且未提交 Prompt | `Timeout` | `error_type=timeout_before_prompt`；无外部执行 |
| 用户取消 | `Running/Waiting` | `Cancelling` | 设置 `cancel_requested_at`、调 interrupt |
| 取消确认 | `Cancelling` | `Cancelled` | 写 `cancel_confirmed_at` |
| 超时确认 | `Cancelling` | `Timeout` | `cancel_reason=timeout` |
| 取消/超时未确认 | `Cancelling` | `Unknown` | 先对账 Session；仍无 outcome 才 Unknown；不显示 Cancelled/Timeout |
| 远程中断 | `Running/Waiting` | `Failed` | `error_type=remote_interrupted` |
| Session 404（执行中） | 活动状态 | `Unknown` | 不重发 |

### 5.5 Task 状态与调度类型

| Task `status` | 含义 | 自动调度 | 手动执行 | 历史 |
|---|---|---|---|---|
| `enabled` | 正常 | 看 `schedule_enabled` 与 `schedule_type` | 允许 | 保留 |
| `disabled` | 停用 | 不产生新 Run | 允许（PRD 7.2.7） | 保留 |
| `archived` | 归档 | 不产生 | 禁止 | 保留 |

| `schedule_type` | 配置 | 行为 |
|---|---|---|
| `none` | 无 | 只允许手动执行 |
| `cron` | `cron_expression` | 按 cron 周期；按全局 UTC+08:00 解释 |
| `once` | `run_at`（UTC） | 执行一次；按全局 UTC+08:00 解释；触发后 `schedule_enabled=false`，Task 保留 |
| `interval` | `interval_seconds` | 固定间隔；以 `next_run_at` 为节拍推进 |

`schedule_enabled=false` 时保留调度配置，只是不触发。这样“临时停用自动调度”不会丢失 cron。

| `overlap_policy` | 触发时存在待执行/活动 Run | 行为 |
|---|---|---|
| `queue` | 是 | 创建 `Queued` Run，等待前一个结束；FIFO |
| `skip` | 是 | 创建 `Skipped` Run，`error_type=overlap`，写日志；不静默丢弃 |

| `missed_policy` | 启动时发现错过 | 行为 |
|---|---|---|
| `skip` | 是 | 创建一条 `Skipped` Run（汇总错过次数），推进到未来；不补跑 |
| `run_once` | 是 | 创建一条 `Recovery` Run（最新错过时刻），推进到未来；只补一次 |

### 5.6 核心不变量

1. `runs.config_snapshot_json` 创建后不可变；任何更新接口不得修改它。
2. 同一 `(task_id, occurrence_key)` 最多一条 Run；`occurrence_key` 为 `occ:<utc_epoch_ms>`，手动/Rerun 为 `NULL`。
3. 同一 Task 同时最多一条活动 Run（由 Dispatcher 的领取查询与全局锁保证）。
4. 终态 Run 不再改变状态；迟到事件只写日志。
5. 任何 Run 的 `Completed` 只表示 OpenCode Session 正常结束；UI 不得出现“业务成功”字样。
6. 没有 `opencode_session_id` 的 Run 不允许进入 `Running`。
7. 没有确认执行停止时，不得显示 `Cancelled` 或 `Timeout`；例外是 `Queued` / `Preparing` 且已确认尚未提交 Prompt 的取消/超时（没有外部执行需要停止）。
8. Endpoint 密码、`Authorization` 头、`PROMPTOPS_SECRET_KEY` 不得出现在日志、页面、错误消息中。
9. Task 的 Prompt 原样发送；不允许追加隐藏前后缀。
10. 轨迹条目必须能追溯到 OpenCode 返回的 `event.id` 或 message/part ID；不得由 Prompt 文本推断。

---

## 6. 数据模型

### 6.1 约定

- **主键**：字符串，带前缀的 UUID：`ep_`、`tsk_`、`run_`、`log_`、`trc_`。便于日志辨认。
- **时间**：所有 `*_at` 字段为 UTC epoch 毫秒（`INTEGER`）。API/模板层转换为 ISO 8601 展示。
- **布尔**：`INTEGER` 0/1。
- **枚举**：`TEXT` + `CHECK` 约束，不用 SQLite 原生 ENUM。
- **JSON**：`TEXT` 存 JSON；需要查询的标签用 JSON1 `json_each`。
- **外键**：开启 `PRAGMA foreign_keys=ON`。
- **字符串长度**：应用层限制；DB 不强制长度（SQLite 忽略 `VARCHAR(n)`）。
- **软删除**：Endpoint 物理删除（受约束）；Task 只归档，不删除。

### 6.2 `endpoints`

| 列 | 类型 | 约束/说明 |
|---|---|---|
| `id` | TEXT PK | `ep_...` |
| `name` | TEXT NOT NULL | 展示名，≤120 字符；唯一 |
| `description` | TEXT | 可空 |
| `base_url` | TEXT NOT NULL | `http://` 或 `https://`；无 query/fragment；末尾 `/` 归一化去掉 |
| `auth_type` | TEXT NOT NULL | `none` / `basic` |
| `auth_username` | TEXT | Basic 用户名，默认 `opencode` |
| `secret_ciphertext` | TEXT | Fernet 密文；`none` 时为 NULL |
| `is_default` | INTEGER NOT NULL | 0/1 |
| `enabled` | INTEGER NOT NULL | 0/1 |
| `last_test_at` | INTEGER | 最近一次测试时间 |
| `last_test_result` | TEXT | `success` / `unreachable` / `auth_failed` / `unsupported` / `service_error` / `timeout` |
| `last_test_message` | TEXT | 人类可读结果；不含密码 |
| `last_test_version` | TEXT | 成功时的 OpenCode 版本 |
| `created_at` | INTEGER NOT NULL | UTC ms |
| `updated_at` | INTEGER NOT NULL | UTC ms |

索引/约束：

```sql
CREATE UNIQUE INDEX ux_endpoints_name ON endpoints(name COLLATE NOCASE);
CREATE UNIQUE INDEX ux_endpoints_default ON endpoints(is_default) WHERE is_default = 1;
CREATE INDEX ix_endpoints_enabled ON endpoints(enabled);
```

`is_default` 的部分唯一索引保证最多一个默认；应用层保证至少一个（首次创建或 seed 时设置）。删除默认、停用默认由应用层拒绝。

### 6.3 `tasks`

| 列 | 类型 | 约束/说明 |
|---|---|---|
| `id` | TEXT PK | `tsk_...` |
| `name` | TEXT NOT NULL | ≤120 字符；不要求唯一 |
| `description` | TEXT | 可空 |
| `tags_json` | TEXT NOT NULL | JSON 数组，默认 `[]` |
| `endpoint_id` | TEXT NOT NULL FK → endpoints(id) | `ON DELETE RESTRICT` |
| `working_directory` | TEXT NOT NULL | 原样传给 OpenCode；不要求本机存在 |
| `provider_id` | TEXT NOT NULL | 如 `opencode`、`lps` |
| `model_id` | TEXT NOT NULL | 如 `Qwen/Qwen3.6-35B-A3B-FP8` |
| `model_variant` | TEXT | 可空，如 `thinking`、`no_thinking` |
| `agent` | TEXT | 可空；空表示服务端默认 |
| `prompt` | TEXT NOT NULL | 原样保存、原样发送 |
| `status` | TEXT NOT NULL | `enabled` / `disabled` / `archived` |
| `schedule_enabled` | INTEGER NOT NULL | 0/1 |
| `schedule_type` | TEXT NOT NULL | `none` / `cron` / `once` / `interval` |
| `cron_expression` | TEXT | cron 类型必填；5 字段 |
| `run_at` | INTEGER | once 类型必填；UTC ms |
| `interval_seconds` | INTEGER | interval 类型必填；≥60 |
| `overlap_policy` | TEXT NOT NULL | `queue` / `skip` |
| `missed_policy` | TEXT NOT NULL | `skip` / `run_once` |
| `timeout_minutes` | INTEGER NOT NULL | 1..10080；默认 60 |
| `next_run_at` | INTEGER | 下一次待触发 UTC ms；不可调度时为 NULL |
| `created_at` | INTEGER NOT NULL | |
| `updated_at` | INTEGER NOT NULL | |
| `archived_at` | INTEGER | |

PRD 7.2.3 的 Task 示例到字段的映射：

| PRD 示例字段 | 本方案字段 | 说明 |
|---|---|---|
| `name` | `tasks.name` | |
| `description` | `tasks.description` | |
| `status` | `tasks.status` | `enabled/disabled/archived` |
| `endpoint` | `tasks.endpoint_id` | 示例里是名称；系统存 ID，展示时取名称 |
| `execution.working_directory` | `tasks.working_directory` | 原样传递 |
| `execution.provider` | `tasks.provider_id` | |
| `execution.model` | `tasks.model_id` | |
| `execution.agent` | `tasks.agent` | 可空 |
| `prompt` | `tasks.prompt` | 原样保存/发送 |
| `schedule.enabled` | `tasks.schedule_enabled` | |
| `schedule.type` | `tasks.schedule_type` | |
| `schedule.cron` | `tasks.cron_expression` | |
| `schedule.timezone` | —（移除） | MVP 简化为全局 `PROMPTOPS_UTC_OFFSET`，默认 `+08:00` |
| `execution_policy.overlap` | `tasks.overlap_policy` | |
| `execution_policy.timeout_minutes` | `tasks.timeout_minutes` | |
| （PRD 7.3.4 要求） | `tasks.missed_policy` | 示例未列出，但调度规则需要；默认 `skip` |

> **时区简化**：Task 不存 `timezone`；所有规则统一按全局 `PROMPTOPS_UTC_OFFSET`（默认 `+08:00`）解释。Run 创建时把当时的偏移写入快照，历史展示不随全局配置变化。

索引：

```sql
CREATE INDEX ix_tasks_schedulable ON tasks(status, schedule_enabled, next_run_at);
CREATE INDEX ix_tasks_endpoint ON tasks(endpoint_id);
CREATE INDEX ix_tasks_status ON tasks(status);
```

标签筛选：

```sql
EXISTS (SELECT 1 FROM json_each(tasks.tags_json) WHERE json_each.value = :tag)
```

### 6.4 `runs`

| 列 | 类型 | 约束/说明 |
|---|---|---|
| `id` | TEXT PK | `run_...` |
| `task_id` | TEXT NOT NULL FK → tasks(id) | `ON DELETE RESTRICT` |
| `trigger_source` | TEXT NOT NULL | `scheduled` / `manual` / `rerun` / `recovery` |
| `status` | TEXT NOT NULL | 5.2 的 12 个状态 |
| `occurrence_key` | TEXT | `occ:<utc_ms>`；手动/Rerun 为 NULL |
| `scheduled_for` | INTEGER | 计划触发时刻；手动/Rerun 为 NULL |
| `created_at` | INTEGER NOT NULL | |
| `queued_at` | INTEGER | |
| `started_at` | INTEGER | 被 worker 领取 |
| `submitting_at` | INTEGER | |
| `running_at` | INTEGER | |
| `finished_at` | INTEGER | 终态时间 |
| `deadline_at` | INTEGER | `started_at + timeout_minutes*60_000` |
| `cancel_requested_at` | INTEGER | |
| `cancel_confirmed_at` | INTEGER | |
| `cancel_reason` | TEXT | `user` / `timeout` |
| `last_heartbeat_at` | INTEGER | 活动期间每 10s 更新 |
| `task_name_snapshot` | TEXT NOT NULL | |
| `endpoint_id` | TEXT FK → endpoints(id) | `ON DELETE SET NULL`；历史快照仍保留 |
| `endpoint_name_snapshot` | TEXT NOT NULL | |
| `endpoint_url_snapshot` | TEXT NOT NULL | 创建时的 URL；仅展示 |
| `endpoint_auth_type_snapshot` | TEXT NOT NULL | `none` / `basic`；不含密码 |
| `working_directory` | TEXT NOT NULL | |
| `provider_id` | TEXT NOT NULL | |
| `model_id` | TEXT NOT NULL | |
| `model_variant` | TEXT | |
| `agent` | TEXT | |
| `prompt` | TEXT NOT NULL | 本次实际发送的 Prompt |
| `utc_offset` | TEXT NOT NULL | 创建时的全局偏移快照，如 `+08:00` |
| `schedule_summary` | TEXT NOT NULL | 人类可读，如 `Cron 0 9 * * * (UTC+08:00)` |
| `overlap_policy` | TEXT NOT NULL | |
| `missed_policy` | TEXT NOT NULL | |
| `timeout_minutes` | INTEGER NOT NULL | |
| `opencode_session_id` | TEXT | 唯一（非空时） |
| `opencode_session_title` | TEXT | |
| `final_response` | TEXT | 最后一条 assistant 文本；无则 NULL |
| `final_response_truncated` | INTEGER NOT NULL | 0/1 |
| `error_phase` | TEXT | `connect` / `session` / `prompt` / `stream` / `finalize` / `cancel` / `timeout` / `scheduler` |
| `error_type` | TEXT | 见附录 B |
| `error_message` | TEXT | 人类可读；不含密码/Authorization |
| `trace_integrity` | TEXT | `complete` / `gap` / `incomplete` / `none` |
| `trace_gap_count` | INTEGER NOT NULL | SSE 断连次数 |
| `input_tokens` | INTEGER | 未返回则 NULL |
| `output_tokens` | INTEGER | |
| `reasoning_tokens` | INTEGER | |
| `cache_read_tokens` | INTEGER | |
| `cache_write_tokens` | INTEGER | |
| `cost_usd` | REAL | 未返回则 NULL |
| `rerun_of_run_id` | TEXT FK → runs(id) | `ON DELETE SET NULL` |
| `config_snapshot_json` | TEXT NOT NULL | 权威快照 |
| `updated_at` | INTEGER NOT NULL | |

索引/约束：

```sql
CREATE UNIQUE INDEX ux_runs_task_occurrence
  ON runs(task_id, occurrence_key) WHERE occurrence_key IS NOT NULL;
CREATE UNIQUE INDEX ux_runs_session
  ON runs(opencode_session_id) WHERE opencode_session_id IS NOT NULL;
CREATE INDEX ix_runs_task_created ON runs(task_id, created_at DESC);
CREATE INDEX ix_runs_status_created ON runs(status, created_at DESC);
CREATE INDEX ix_runs_endpoint_created ON runs(endpoint_id, created_at DESC);
CREATE INDEX ix_runs_scheduled_for ON runs(scheduled_for);
```

`runs.prompt` 与 `config_snapshot_json.prompt` 由同一份数据在创建时写入，均不可变；详情页展示用 `runs.prompt`，完整回放/调试用快照。任何编辑接口都不得更新它们。

`config_snapshot_json` 至少包含：

```json
{
  "task": {"id": "...", "name": "...", "description": "...", "tags": []},
  "endpoint": {"id": "...", "name": "...", "base_url": "...", "auth_type": "basic", "username": "opencode"},
  "execution": {
    "working_directory": "/workspace/rates-report",
    "provider_id": "lps",
    "model_id": "Qwen/Qwen3.6-35B-A3B-FP8",
    "model_variant": "thinking",
    "agent": null
  },
  "prompt": "原样 Prompt",
  "schedule": {
    "type": "cron",
    "cron": "0 9 1 * *",
    "utc_offset": "+08:00",
    "summary": "Cron 0 9 1 * * (UTC+08:00)"
  },
  "policy": {"overlap": "queue", "missed": "skip", "timeout_minutes": 60},
  "trigger": {"source": "scheduled", "scheduled_for": 1792400000000}
}
```

### 6.5 `run_logs`

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | `log_...` |
| `run_id` | TEXT NOT NULL FK → runs(id) | `ON DELETE CASCADE` |
| `at` | INTEGER NOT NULL | UTC ms |
| `level` | TEXT NOT NULL | `info` / `warn` / `error` |
| `phase` | TEXT NOT NULL | 见 8.4.2 |
| `message` | TEXT NOT NULL | 人类可读，已脱敏 |
| `details_json` | TEXT | 可选结构化字段 |

索引：`CREATE INDEX ix_run_logs_run_at ON run_logs(run_id, at);`

### 6.6 `trace_items`

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | `trc_...` |
| `run_id` | TEXT NOT NULL FK → runs(id) | `ON DELETE CASCADE` |
| `kind` | TEXT NOT NULL | `user_message` / `assistant_message` / `tool` / `skill` / `file` / `permission` / `error` / `system` |
| `external_id` | TEXT NOT NULL | 事件 ID / message ID / part ID / call ID / 文件路径 / permission ID |
| `parent_external_id` | TEXT | 父条目 external_id；未知则 NULL |
| `name` | TEXT | Tool 名 / Skill 名 / 文件名 / 权限 action |
| `status` | TEXT | `pending` / `running` / `completed` / `failed` / `rejected` / `info` |
| `sequence` | INTEGER NOT NULL | Run 内单调递增；用于稳定排序 |
| `started_at` | INTEGER | |
| `ended_at` | INTEGER | |
| `duration_ms` | INTEGER | 由应用计算；两者都有才写 |
| `input_json` | TEXT | Tool 输入 / 权限资源等 |
| `output_text` | TEXT | Tool 输出 / 消息文本 / patch / 说明 |
| `error_text` | TEXT | 错误 |
| `metadata_json` | TEXT | 文件 additions/deletions、truncated、source event id 等 |
| `created_at` | INTEGER NOT NULL | |
| `updated_at` | INTEGER NOT NULL | |

索引/约束：

```sql
CREATE UNIQUE INDEX ux_trace_run_kind_external
  ON trace_items(run_id, kind, external_id);
CREATE INDEX ix_trace_run_sequence ON trace_items(run_id, sequence);
CREATE INDEX ix_trace_run_started ON trace_items(run_id, started_at);
```

**文本上限**：单个 `output_text` / `error_text` / `input_json` 超过 `PROMPTOPS_MAX_TRACE_TEXT_BYTES`（默认 262144）时截断，并在 `metadata_json` 写 `{"truncated": true, "original_bytes": N}`。UI 明确显示“已截断”。

### 6.7 迁移与初始化

- Alembic 管理 schema；`alembic/versions/` 按顺序提交。
- 启动时若 `PROMPTOPS_AUTO_MIGRATE=true`，执行 `alembic upgrade head`；失败则拒绝启动（不带着旧 schema 运行）。
- SQLite PRAGMA 在每次连接建立时设置：

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
PRAGMA synchronous=NORMAL;
```

- `data/` 目录：`promptops.db`、`secret.key`、`logs/app.log`；`.gitignore` 排除。

---

## 7. OpenCode v2 适配层

### 7.1 受支持的服务判定

`GET /api/info`：

```json
{
  "version": "2.0.29",
  "pid": 29320,
  "urls": ["http://127.0.0.1:41999"],
  "paths": {"tmp": "..."},
  "capabilities": {"persistentPty": false}
}
```

判定：

- HTTP 200 + JSON 含非空 `version`，且含 `urls` 或 `paths` → 受支持。
- HTTP 200 + JSON 只有 `version`、没有 `urls`/`paths` → 不足以确认是 OpenCode v2，按“不受支持”处理（避免把任意返回 version 的服务当 OpenCode）。
- HTTP 401/403 → 认证失败。
- 连接拒绝/超时 → 地址不可访问。
- 200 但返回 HTML/非 JSON、或 JSON 无 `version` → 不是受支持的 v2 服务。
- 404 且 `GET /global/health` 返回 `{healthy: true, version: ...}` → 明确报告“该服务是 v1，不受支持”。
- 其他 4xx/5xx → 服务返回异常。
- v2.0.29 实测 `/api/info` 也受 Basic Auth 保护；仍用 `GET /api/session?limit=1` 做一次认证 + API 可用性双重确认（防止反向代理只保护部分路由）。401/403 → 认证失败。

### 7.2 认证

OpenCode v2 使用 **HTTP Basic Auth**：

```text
Authorization: Basic base64(<username>:<password>)
```

- `OPENCODE_SERVER_PASSWORD` 设置密码；用户名默认 `opencode`，可用 `OPENCODE_SERVER_USERNAME` 覆盖。
- 本系统 Endpoint 保存 `auth_type`、`auth_username`、加密后的密码。
- 不使用 Bearer Token（v1 时代的做法）；如果目标服务只接受 Bearer，视为不受支持。
- 不在 URL 中放用户名/密码；httpx 使用 `BasicAuth`。
- v2 在未设置 `OPENCODE_SERVER_PASSWORD` 时会**自动生成随机密码并打印到启动日志**。如果 Endpoint 配 `auth_type=none` 但服务端有密码，会得到 401；测试连接会明确报认证失败。部署文档要求显式设置服务端密码，或确认服务端确实无密码。

### 7.3 适配层接口

```python
class OpenCodeV2Client:
    async def info(self) -> ServerInfo: ...
    async def sessions(self, *, limit: int = 50,
                       parent_id: str | None = None) -> list[SessionInfo]: ...
    async def create_session(self, *, title: str, directory: str,
                             model: ModelRef | None, agent: str | None) -> SessionInfo: ...
    async def prompt(self, session_id: str, text: str) -> UserMessage: ...
    async def session(self, session_id: str) -> SessionInfo: ...
    async def messages(self, session_id: str, *, order: str = "asc",
                       limit: int = 100, cursor: str | None = None) -> MessagePage: ...
    async def diff(self, session_id: str, *, from_message: str | None = None,
                   to_message: str | None = None) -> list[FileDiff]: ...
    async def interrupt(self, session_id: str) -> bool: ...
    async def reply_permission(self, session_id: str, request_id: str,
                               decision: str, message: str | None = None) -> None: ...
    async def models(self, directory: str) -> list[ModelOption]: ...
    async def agents(self, directory: str) -> list[AgentOption]: ...
    async def event_stream(self) -> AsyncIterator[RawEvent]: ...
```

错误统一为 `OpenCodeError` 子类：`ConnectionFailed`、`AuthFailed`、`UnsupportedServer`、`HttpError(status, body)`、`Timeout`、`ProtocolError`、`SessionNotFound`。业务层只捕获这些类型，不解析底层异常字符串。

### 7.4 实际使用的 API

| 方法 | 路径 | 用途 | 关键请求/响应 |
|---|---|---|---|
| GET | `/api/info` | 健康/版本探测 | 200 `{version, ...}`；v2.0.29 实测受 Basic Auth 保护 |
| GET | `/api/session?limit=1` | 认证探测/连接测试 | 200 `{data:[Session.Info]}`；401 → 认证失败 |
| POST | `/api/session` | 创建 Session | body `{title?, location:{directory}, model?, agent?}`；200 `{data: Session.Info}` |
| POST | `/api/session/{id}/prompt` | 提交 Prompt | body `{text}`；200 `{data: Session.Inbox.User}`；异步执行 |
| GET | `/api/session/{id}` | Session 状态/用量 | 200 `{data: Session.Info}`；`outcome` 为 `succeeded/failed/interrupted`，活动时无 `outcome` |
| GET | `/api/session/{id}/message` | 消息投影 | `?order=asc&limit=100[&cursor=]`；`{data:[...], cursor:{next,previous}}` |
| GET | `/api/session/{id}/diff` | 文件变化 | 200 `{data:[FileDiff.Info]}`；`status=added/modified/deleted`，含 `patch/additions/deletions` |
| POST | `/api/session/{id}/interrupt` | 取消/超时 | 200 `{interrupted: true 或 false}` |
| POST | `/api/session/{id}/permission/{requestID}/reply` | 权限回复 | body `{decision: once / always / reject, message?}`；204 |
| GET | `/api/event` | SSE 事件流 | `data: {id,type,created,data,...}` |
| GET | `/api/model` | 模型发现 | `?location[directory]=<wd>`；`{location, data:[...]}` |
| GET | `/api/agent` | Agent 发现 | `?location[directory]=<wd>`；`{location, data:[...]}` |
| GET | `/api/session?parentID=<sid>` | 子 Session（可选） | `{data:[Session.Info]}` |

**响应信封**：除 SSE 外，v2 成功响应统一为 `{ "data": ... }`（`/api/info` 除外）。适配层负责解包；业务层不直接看 `data`。

### 7.5 Session 创建映射

```json
POST /api/session
{
  "title": "PromptOps · Monthly Rate Report · run_ab12",
  "location": {"directory": "/workspace/rates-report"},
  "model": {
    "id": "Qwen/Qwen3.6-35B-A3B-FP8",
    "providerID": "lps",
    "variant": "thinking"
  },
  "agent": "build"
}
```

- `title`：可读标识，≤80 字符；不作为业务字段。
- `location.directory`：Task 的 `working_directory` 原样传入；必须是 OpenCode 主机上的路径。本系统不校验其存在性，因为 Endpoint 可能在另一台机器/另一个 OS。
- `model`：Task 的 `provider_id` / `model_id` / `model_variant`。如果 Task 未配置模型，不传 `model`，由服务端默认；MVP 表单要求配置，避免“跑错模型”。
- `agent`：Task 的 `agent`；空则不传。
- 返回的 `data.id` 存 `runs.opencode_session_id`。

### 7.6 Prompt 提交与不确定性

```json
POST /api/session/{session_id}/prompt
{"text": "<Task.prompt 原样>"}
```

- **不追加任何内容**：不加 system、不包 wrapper、不加“请输出 STATUS_JSON”。PRD 7.2.2 明确“保存时不得自动添加用户不可见的任务内容”。
- v2 的 prompt 是**异步接收**：200 表示已持久化入队，不表示执行完成。
- 200 后：`Submitting → Running`，记录返回的 `data.id` 为 `user_message_external_id`。
- 4xx（400/404/409）：明确拒绝，`Failed`，`error_phase=prompt`；不重试。
- 连接错误/读超时/5xx：结果不确定。执行对账：
  1. 等 1 秒；
  2. `GET /api/session/{id}/message?type=user&order=desc&limit=5`；
  3. 找到 `text` 与本次 Prompt 完全一致、且 `time.created >= submit_started_at` 的消息 → 视为已接收，转 `Running`；
  4. 找不到 → `Unknown`，`error_type=prompt_admission_unknown`；**不重发**。
- 对账本身失败（Session 404/连接失败）→ `Unknown`。

### 7.7 消息读取与分页

- 默认 `order=desc`（最新在前）；本系统统一用 `order=asc` 拉完整时间线。
- 每页 `limit=100`；若 `cursor.next` 非空，继续请求 `?cursor=<next>&order=asc&limit=100`，直到没有 `next`。
- 最多翻 `PROMPTOPS_MAX_MESSAGE_PAGES`（默认 20）页；超过则停止并在 `trace_integrity=incomplete` 的说明中写“消息过多，未完整拉取”。
- 消息类型（v2）：`user`、`assistant`、`skill`、`system`、`synthetic`、`shell`、`compaction`、`idle`，以及 `agent-switched` / `model-switched` / `location-switched`。MVP 只投影 `user`、`assistant`、`skill`、`shell`；其余忽略。
- assistant `content` 是数组，元素类型 `text` / `reasoning` / `tool`：
  - `text` → `assistant_message` 的文本；
  - `tool` → `tool` 条目，`external_id = content.id`（call ID）；
  - `reasoning` → **忽略，不展示**。

### 7.8 文件变化

- 以 `GET /api/session/{id}/diff` 为权威；`session.step.ended.data.files` 只作为“有文件变化”的提示，不用来推断新增/修改/删除。
- `FileDiff.Info`：`{file, patch, additions, deletions, status}`，`status` 为 `added/modified/deleted`。
- 每个文件一条 `trace_items(kind=file, external_id=file)`；`metadata_json` 存 `additions/deletions/status/truncated`；`output_text` 存 patch（受 6.6 文本上限约束）。
- 如果 diff 拉取失败但 `files` 非空：创建 `kind=file, status=info` 的占位条目，`error_text` 说明“未能获取差异”。不猜测内容。

### 7.9 权限

- 事件 `permission.asked` 的 `data` 是 `Permission.Request`（或包含 `request` 字段；适配层两种都接受）。字段：`id`、`sessionID`、`action`、`resources`、`save`、`metadata`、`source`、`message`。
- 处理：
  1. upsert `kind=permission, external_id=request.id, status=pending`，`name=action`，`input_json={resources, save, metadata, source}`；
  2. Run `Running → Waiting`；
  3. UI 展示 action/resources/source/message；
  4. 用户选择后 `POST /api/session/{sid}/permission/{rid}/reply`，body `{decision, message?}`；
  5. 204 后 upsert 该条目 `status=approved/rejected`（`once`/`always` → approved，`reject` → rejected）；
  6. 若该 Run 没有其他 pending 权限，`Waiting → Running`。
- 事件 `permission.replied` 作为对账补充；以 reply 成功的 204 为准。
- **不自动回复**。超时/取消仍然有效：`Waiting` 的 Run 到 deadline 后走 `Cancelling`。
- **其它输入**：v2 还存在 form/question 类输入（`/api/session/{id}/form`）。MVP 只实现权限回复；如果识别到 form/question 事件，Run 置 `Waiting`，UI 提示“请在 OpenCode 中处理，或在控制台取消”，不自动回答；未识别到时按 `Running`/超时处理。通用表单渲染与回复不在 MVP。

### 7.10 取消与中断

```json
POST /api/session/{id}/interrupt
→ {"interrupted": true}
```

- `interrupted=true`：已中断活动执行；仍要等 `session.execution.interrupted` 或 `GET /api/session/{id}` 的 `outcome=interrupted` 来确认，再写 `Cancelled/Timeout`。
- `interrupted=false`：当前没有活动执行（可能刚好完成）。立即对账：
  - `outcome=succeeded` → `Completed`（取消来晚了，日志记录）；
  - `outcome=failed` → `Failed`；
  - 无 `outcome`（仍在跑）→ 继续等，超时后 `Unknown`。
- 用户取消 `Queued` Run：直接 `Cancelled`，不调用 OpenCode。
- 取消/超时确认窗口：`PROMPTOPS_CANCEL_CONFIRM_SECONDS`（默认 30s）。窗口内没有确认时，先 `GET /api/session` 对账；有 `outcome` 按 8.4.4 映射，仍无 outcome 才 `Unknown`，`error_type=cancel_unconfirmed` / `timeout_unconfirmed`，保留说明；UI 不得显示 `Cancelled`/`Timeout`。

### 7.11 SSE 事件

实际事件信封（v2.0.29）：

```json
{
  "id": "evt_...",
  "created": 1792400404038,
  "type": "session.execution.started",
  "location": {"directory": "..."},
  "data": {"sessionID": "ses_...", ...},
  "durable": {"aggregateID": "ses_...", "seq": 2, "version": 1}
}
```

- 首事件 `server.connected`；之后是各领域事件；注释行 `: heartbeat` 忽略。
- 过滤：只处理 `data.sessionID` 属于本系统 Run 的事件（按 `runs.opencode_session_id` 查库，不只看内存 handle）；其他忽略（同一 Endpoint 可能有用户手工会话）。
- `id` 用于去重：同一 Run 内重复 `id` 只处理一次；没有 `id` 的事件用 `type + created + data.sessionID` 生成去重键。
- `durable.seq` 可作为同一 Session 的顺序参考；没有 `durable` 的事件用 `created` + 接收顺序。
- 未知事件类型：计数并记 debug 日志，不报错、不改变 Run 状态。

**实测到的事件**（v2.0.29）：`server.connected`、`session.created`、`session.inbox.enqueued`、`session.inbox.delivered`、`session.execution.started`、`session.step.started/streamed/ended`、`session.text.started/delta/ended`、`session.tool.input.started/ended`、`session.tool.called`、`session.tool.success`、`session.usage.updated`、`session.execution.succeeded/failed/interrupted`。下表中 `session.tool.progress`、`session.tool.failed`、`session.skill.activated`、`permission.asked/replied`、`session.error`、`session.idle`、`file.edited` 来自 v2 二进制字符串/事件命名推断，未全部在本次探测中触发；实现必须以实测为准，并把未知事件降级为忽略。

**事件映射表**

| 事件类型 | 关键 data 字段 | Run 状态影响 | Trace 影响 |
|---|---|---|---|
| `server.connected` | — | 无 | 标记流已连接 |
| `session.created` | `sessionID`, `title`, `model` | 无（本系统创建时已知） | 可更新 session title |
| `session.inbox.enqueued` | `inboxID`, `sessionID`, `item` | 无 | 记录用户 Prompt 已入队（可选） |
| `session.inbox.delivered` | `inboxID`, `sessionID` | `Submitting → Running`（若尚未转） | 记录已投递 |
| `session.execution.started` | `sessionID` | `Running` | 记录执行开始 |
| `session.step.started` | `assistantMessageID`, `started`, `snapshot` | 无 | 记录 assistant step 开始 |
| `session.step.streamed` | `assistantMessageID` | 无 | 标记该 step 已流式输出 |
| `session.step.ended` | `assistantMessageID`, `finish`, `tokens`, `cost`, `files` | 无（终态看 execution.*） | 更新用量、文件提示 |
| `session.text.started` | `assistantMessageID`, `ordinal` | 无 | 创建/更新 assistant message 条目 |
| `session.text.delta` | `assistantMessageID`, `ordinal`, `delta` | 无 | 追加实时文本（仅内存/节流写库） |
| `session.text.ended` | `assistantMessageID`, `ordinal`, `text` | 无 | 写入最终文本 |
| `session.tool.input.started` | `assistantMessageID`, `id`, `name` | 无 | upsert tool `pending` |
| `session.tool.input.ended` | `id`, `text` | 无 | 写 `input_json`（解析 JSON，失败存原文） |
| `session.tool.called` | `id`, `name`, `input`, `executed` | 无 | tool `running`，写输入、开始时间 |
| `session.tool.progress` | `id`, 进度字段 | 无 | 更新 `output_text`/metadata（可选） |
| `session.tool.success` | `id`, `content`, `metadata` | 无 | tool `completed`，写输出、结束时间 |
| `session.tool.failed` | `id`, `error`, `content` | 无（不直接判 Run 失败） | tool `failed`，写错误 |
| `session.skill.activated` | `sessionID`, skill 信息 | 无 | upsert `kind=skill` |
| `permission.asked` | `Permission.Request` | `Running → Waiting` | upsert permission `pending` |
| `permission.replied` | request/reply | 无 pending 时 `Waiting → Running` | 更新 permission 状态 |
| `session.usage.updated` | `cost`, `tokens` | 无 | 更新 Run 用量 |
| `session.execution.succeeded` | `sessionID` | 终态事件 → 收尾 | 标记成功（仍需拉消息/diff） |
| `session.execution.failed` | `sessionID` | 终态事件 → 收尾 | 标记失败 |
| `session.execution.interrupted` | `sessionID` | 终态事件 → 收尾 | 标记中断 |
| `session.error` | 错误结构 | 不直接改终态 | 存 `kind=error` 条目 |
| `session.idle` | `outcome`（若存在） | 终态兜底；拉 session 对账 | 可忽略 |
| `file.edited` | 文件路径 | 无 | 可记录提示；权威仍用 diff |

> 观察到的 v2.0.29 终态事件是 `session.execution.succeeded/failed/interrupted`；没有观察到 v1 的 `session.idle` 事件。`session.idle` 作为兼容兜底处理，不能作为唯一依据。

**状态迁移竞争**：SSE ingestor 与 executor 可能同时尝试同一迁移（例如 `Submitting → Running`）。所有迁移必须用条件更新（`WHERE status = :expected`），迁移失败视为“别人已推进”，只记 debug 日志。`permission.asked` 只在 Run 已是 `Running/Waiting` 时置 `Waiting`；如果仍在 `Submitting`，先把状态推进到 `Running`（执行已经发生），再置 `Waiting`。

### 7.12 断线重连与对账

- SSE 的 httpx 客户端必须使用 **读超时 `None`**（长连接），连接超时 5s；不要复用普通请求的 30s 读超时，否则健康流会被周期性掐断。
- SSE 断开：所有该 Endpoint 上的活动 Run 记 `trace_gap_count += 1`；`trace_integrity` 至少为 `gap`。
- 重连：指数退避 1s → 2s → 4s ... 上限 30s；加 ±20% 抖动，避免多 Endpoint 同时重连。
- 重连成功后不假设事件完整：对每个活动 Run 执行一次消息对账（7.7）与 Session 状态查询。
- 若某 Run 超过 `PROMPTOPS_SSE_STALE_SECONDS`（默认 10s）没有收到任何事件，且 Run 处于 `Running/Waiting`，启动**轮询兜底**：每 5s `GET /api/session/{id}`，有 `outcome` 就收尾；每 15s 拉一次消息增量。
- 轮询兜底不替代 SSE；SSE 恢复后停止高频轮询。
- `Last-Event-ID`：重连时尝试带最后收到的 `event.id`；服务端是否支持重放未知，因此仍以消息对账为准。

### 7.13 子 Session（可选/MVP-stretch）

- 运行结束时，可调用 `GET /api/session?parentID=<run.session_id>&limit=50` 获取子 Session。
- 展示为 Run 详情中的“子 Session”列表（ID、标题、创建时间、outcome）。
- 子 Session 的轨迹**不合并**到父 Run 的时间线；避免层级混乱。用户可看到子 Session 存在，但完整轨迹不在 MVP 中展开。
- 如果接口失败，忽略，不影响 Run 终态。

### 7.14 协议兼容与降级

| 情况 | 行为 |
|---|---|
| `/api/info` 成功，但缺少某事件 | 忽略未知事件；靠消息对账补 |
| `/api/session` 返回字段缺失 | 适配层给默认值；缺 `id` 视为 `ProtocolError` |
| `/prompt` 返回 200 但无 `data.id` | 仍转 `Running`；用户消息对账时再补 |
| `/message` 分页 cursor 失效（400） | 停止翻页，标记 `trace_integrity=incomplete` |
| `/diff` 404/500 | 文件轨迹标 `info`/`incomplete`；不影响 Run 终态 |
| `/interrupt` 404（Session 已消失） | 视为无法确认 → `Unknown` |
| SSE 返回 401 | 该 Endpoint 所有活动 Run 的轨迹标 `gap`；轮询兜底；Run 连接层可能已失败 |
| OpenCode 版本升级导致事件名变化 | 未知事件忽略；终态仍可由 `/api/session` 的 `outcome` 判断；记录 `protocol_warning` |

---

## 8. 核心功能实现设计

### 8.1 Endpoint 管理

#### 8.1.1 创建

表单字段：名称、描述、服务地址、认证方式、用户名（Basic）、密码（Basic）、是否启用。

校验：

- 名称：非空，≤120 字符，唯一（大小写不敏感比较由应用层做；DB 唯一索引兜底）。
- 服务地址：必须 `http://` 或 `https://`；不能带 query/fragment；去掉末尾 `/`；不能包含用户名/密码。
- `auth_type=none`：清空用户名/密码。
- `auth_type=basic`：用户名默认 `opencode`；密码必填（新建时）。密码只写不读。
- 是否启用：默认启用。
- 第一个 Endpoint 自动成为默认 Endpoint（否则系统没有默认，违反 PRD 8.3），并**强制启用**；表单在“无其他 Endpoint”时禁用停用选项，避免创建出“唯一但停用”的端点。

创建后写 `last_test_* = NULL`；不自动测试连接（PRD 只要求用户主动测试）。

#### 8.1.2 测试连接

路由：`POST /api/v1/endpoints/test`，接受当前值（可未保存）或 `endpoint_id`。

服务端逻辑：

1. 构造临时 Endpoint 配置；如果表单密码为空且是编辑已保存 Endpoint，使用已存密码。
2. `GET {base_url}/api/info`，Basic Auth，连接超时 5s、读超时 10s。
3. **认证探测**：`GET {base_url}/api/session?limit=1`，Basic Auth。v2.0.29 实测 `/api/info` 也受 Basic Auth 保护；再做一次 `/api/session` 确认认证与 API 可用性（防止反向代理只保护部分路由）。该请求只读、无副作用。
4. 分类：

| 观察 | `last_test_result` | 用户文案 |
|---|---|---|
| `/api/info` 200 + `version` + `urls`/`paths`，且 `/api/session?limit=1` 200 | `success` | 连接成功，OpenCode {version} |
| 任一请求 401 / 403 | `auth_failed` | 认证失败：请检查用户名和密码 |
| `ConnectError` / `ConnectTimeout` | `unreachable` | 地址不可访问：连接被拒绝或超时 |
| `ReadTimeout` | `timeout` | 服务响应超时 |
| 404，且 `/global/health` 返回 `{healthy:true,version}` | `unsupported` | 该服务是 OpenCode v1；本系统仅支持 v2 |
| `/api/info` 200 但 `/api/session?limit=1` 404 | `unsupported` | 目标 OpenCode v2 API 不完整或版本不匹配 |
| 200 但非 JSON / HTML / 无 `version` / 只有 `version` 无 `urls`/`paths` | `unsupported` | 目标不是受支持的 OpenCode v2 服务 |
| 其他 4xx / 5xx | `service_error` | 服务返回异常：HTTP {status} |
| 无法解析 JSON | `unsupported` | 服务返回了无法识别的响应 |

5. 如果是已保存 Endpoint 的测试，更新 `last_test_at/result/message/version`。
6. 返回 JSON `{result, message, version, tested_at}`；前端用 AntD `Alert` 展示，不返回密码。

测试是**一次性**的，不启动后台健康检查。Endpoint 列表不展示在线/离线。停用的 Endpoint 仍允许手动测试连接（测试是显式动作，不是健康监控）。

#### 8.1.3 默认 Endpoint

- 系统必须恰好一个默认 Endpoint。
- 新建 Task 时自动选中默认 Endpoint。
- 设置默认：事务内 `UPDATE endpoints SET is_default=0 WHERE is_default=1; UPDATE endpoints SET is_default=1 WHERE id=?`。
- 新默认只影响之后创建的 Task；不修改已有 Task 的 `endpoint_id`。
- 默认 Endpoint 必须启用。要停用默认 Endpoint，必须先设置另一个默认。
- 默认 Endpoint 不能删除。

#### 8.1.4 编辑

- 允许修改名称、描述、地址、认证方式、认证信息、是否启用。
- 地址/认证修改只影响之后发起的执行；已有 Run 的快照不变。
- 正在执行的 Run：适配层在 Run 开始时解析连接配置并持有客户端；不会因为 Endpoint 被编辑而中途切换。进程重启后的 Recovery 会重新解析当前配置，并在 RunLog 记录“Endpoint 配置已变化”。
- 认证方式从 basic 改成 none 时清空密文；从 none 改成 basic 时必须提供密码（或显式保留旧密码，若旧密文存在）。
- 密码字段在编辑页始终为空，placeholder 显示“已配置，留空保持不变”；提供“清除密码”复选框（仅 `auth_type=none` 时可用/自动）。

#### 8.1.5 停用

- 停用后：Task 继续引用；不能用该 Endpoint 创建新 Task；定时触发不再发送 Prompt。
- 停用时：
  - 该 Endpoint 上 `Queued` 状态的 Run 统一置 `Skipped`，`error_type=endpoint_disabled`；
  - `Running/Waiting/Submitting` 的 Run 继续（已经发送），不强行中断；
  - 写入 RunLog 说明。
- 调度器在触发时再次检查 Endpoint 启用状态；停用期间到点的 Task 创建 `Skipped` Run（`error_type=endpoint_disabled`），保证“有可查询记录”。

#### 8.1.6 删除

只有同时满足才允许：

1. 不是默认 Endpoint；
2. 没有任何 Task 引用（包括 enabled/disabled/archived）；
3. 没有 `Queued/Preparing/Submitting/Running/Waiting/Cancelling` 的 Run 依赖它。

删除后：

- `runs.endpoint_id` 置 NULL（`ON DELETE SET NULL`），但 `endpoint_name_snapshot` / `endpoint_url_snapshot` / `config_snapshot_json` 保留；历史 Run 不丢信息。
- 已删除 Endpoint 不能被 Rerun 直接复用；Rerun 时要求选择可用 Endpoint，并在新 Run 快照中记录调整。

#### 8.1.7 列表

列：名称、服务地址、认证方式、默认标记、启用、被多少 Task 使用、最近测试结果（可选）。

- “被多少 Task 使用”统计所有引用该 Endpoint 的 Task，包括归档 Task。
- 不展示实时在线/离线；最近测试结果标注时间，避免被误读为当前状态。

### 8.2 Task 管理

#### 8.2.1 创建/编辑字段

| 分组 | 字段 | 规则 |
|---|---|---|
| 基础 | 名称 | 非空，≤120 字符 |
| 基础 | 描述 | 可空，≤2000 字符 |
| 基础 | 标签 | 0..20 个；每个 ≤32 字符；trim、去重、保留顺序 |
| 执行目标 | Endpoint | 新建必须选启用 Endpoint；默认选中默认 Endpoint |
| 执行目标 | 工作目录 | 非空；原样保存；提示“必须是 OpenCode 主机上的绝对路径” |
| 执行目标 | Provider | 非空；可由模型发现自动填，也可手输 |
| 执行目标 | 模型 | 非空；可由模型发现选择，也可手输 |
| 执行目标 | 模型 Variant | 可空；由模型发现提供候选 |
| 执行目标 | Agent | 可空；由 Agent 发现提供候选，也可手输 |
| Prompt | Prompt | 非空；原样保存、原样发送；不 trim 内部内容、不追加任何文本 |
| 调度 | 启用自动调度 | 布尔；关闭时保留调度配置但不触发 |
| 调度 | 调度类型 | `cron` / `once` / `interval` / `none` |
| 调度 | Cron | 5 字段；仅 cron 类型 |
| 调度 | 执行时间 | UTC+8 日期+时间；仅 once 类型；必须晚于当前时间 |
| 调度 | 间隔 | ≥60 秒；仅 interval 类型 |
| 策略 | 重叠策略 | `queue` / `skip`；默认 `queue` |
| 策略 | 错过策略 | `skip` / `run_once`；默认 `skip` |
| 策略 | 超时分钟 | 1..10080；默认 60 |
| 状态 | 启用/停用/归档 | 新建默认 `enabled`；复制默认 `disabled` |

> 如果系统还没有任何 Endpoint，Task 创建页显示“请先配置 Endpoint”的引导并禁止提交；第一个 Endpoint 创建后自动成为默认，Task 表单即可使用。
>
> **时区不提供选择**：所有 Task 共用全局 `PROMPTOPS_UTC_OFFSET`（默认 `+08:00`）；表单上只显示只读提示“所有时间按 UTC+08:00 解释”。

#### 8.2.2 校验与保存

- 服务端 Pydantic 校验是最终权威；AntD `Form` rules 只做即时提示；422 的 `details` 映射到 `form.setFields`。
- 保存时：
  - 计算 `next_run_at`（见 8.2.6）；
  - 写 `updated_at`；
  - 不修改任何已有 Run；
  - 如果调度从关闭变为开启，从“现在”之后重新计算，不补跑历史。
- 编辑时如果 Task 当前 Endpoint 已停用且用户未改 Endpoint：允许保存，但前端 `Alert` 显示警告，调度触发会产生 `Skipped`；如果用户改了 Endpoint，必须选启用的。
- `schedule_enabled=true` 时 `schedule_type` 不能是 `none`；选择 `none` 时自动把 `schedule_enabled` 置 false，避免“启用但无规则”的歧义。
- Prompt 保存：保留用户输入的所有换行和空格；只校验 `prompt.strip()` 非空。**不做模板替换、不插入系统提示、不加状态行**。

#### 8.2.3 启用/停用

- 启用：`status=enabled`；如果 `schedule_enabled` 且类型非 none，重新计算 `next_run_at`。如果类型是 `once` 且 `run_at <= now`，拒绝启用并提示“一次性执行时间已过，请先修改时间”；Task 保持 disabled。
- 停用：`status=disabled`；`next_run_at=NULL`；保留 `schedule_enabled` 与配置值，便于恢复。
- 不取消已 `Queued` 或执行中的 Run（PRD 7.2.7）。
- 停用后仍允许手动执行（PRD 7.2.7）。

#### 8.2.4 归档/恢复

- 归档：`status=archived`、`schedule_enabled=false`、`next_run_at=NULL`、`archived_at=now`。
- 归档后：不再自动调度；手动执行按钮禁用（服务端也拒绝）；历史 Run 保留。
- 恢复：`status=disabled`（不是 enabled），避免恢复即触发；用户再显式启用。
- 已排队的 Run 不因归档被取消；继续执行（与停用一致）。文档中明确。

#### 8.2.5 复制

- 复制基础信息、Endpoint、工作目录、Provider/模型/Agent、Prompt、调度配置、执行策略。
- 新名称：`Copy of <原名>`；若重名，追加 ` (2)`、` (3)`。
- 新 Task：`status=disabled`、`schedule_enabled=false`、`next_run_at=NULL`；保留调度字段，用户启用时可选择恢复。
- 复制不复制历史 Run。

#### 8.2.6 调度时间计算

统一放在 `domain/schedule.py`，纯函数，输入输出都用 UTC ms：

```python
def next_occurrence(task, after_ms: int) -> int | None:
    if not task.schedule_enabled or task.schedule_type == "none":
        return None
    if task.schedule_type == "once":
        return task.run_at if task.run_at > after_ms else None
    if task.schedule_type == "interval":
        base = task.next_run_at or after_ms
        step = task.interval_seconds * 1000
        nxt = base + step
        while nxt <= after_ms:
            nxt += step
        return nxt
    # cron：固定偏移，不使用 IANA/DST
    tz = timezone(parse_utc_offset(settings.utc_offset))  # 默认 +08:00
    base = datetime.fromtimestamp(after_ms / 1000, tz=tz)
    itr = croniter(task.cron_expression, base)
    nxt = itr.get_next(datetime)
    return int(nxt.timestamp() * 1000)
```

保存 Task 时 `next_run_at = next_occurrence(task, now_ms)`（`once` 若已过期则校验失败）。停用时置 NULL。启用时从 now 重新计算。

- **once**：表单的 UTC+8 日期/时间按全局偏移解释，服务端转换为 UTC 毫秒后存入 `run_at`；保存/启用时必须严格晚于当前时刻。
- **interval**：保存时先把内存中的 `next_run_at` 视为 NULL，再计算，确保节拍从“现在”起算；编辑间隔等于重置节拍，只影响未来。
- **cron**：保存时以 now 为基准取下一次，不补历史。

**固定偏移处理**：

- `PROMPTOPS_UTC_OFFSET` 只接受 `+HH:MM` / `-HH:MM`，默认 `+08:00`；不读取系统本地时区。
- 东八区没有 DST；MVP 不做春季前进/秋季回拨分支，也不提供 per-task 时区。
- `croniter` 以固定偏移的 aware datetime 为基准；落库仍用 UTC epoch 毫秒。
- 如果未来需要 IANA 时区/DST，属于新的需求，需重新引入 `zoneinfo` 与相应测试。

#### 8.2.7 调度预览

路由：`POST /api/v1/schedules/preview`（JSON）。

输入：调度类型、cron / run_at / interval、数量（默认 5，最多 10）；不传时区。

输出：

- `occurrences: [{utc, local}]`；前端只显示一列“执行时间（UTC+08:00）”。
- `type=none`：返回空数组，前端显示“仅手动执行，无自动计划”。
- 校验失败：422 `validation_error`，`details` 说明具体字段（如 “cron 第 3 段不是合法数字”）；前端映射到表单/预览区域。
- 预览不写数据库。

服务端返回 `local` 已是 UTC+8 墙钟时间；前端不再计算浏览器本地时区。

#### 8.2.8 模型/Agent 发现

- 任务表单的 Endpoint 或工作目录变化时，TanStack Query 请求 `GET /api/v1/options?endpoint_id=...&working_directory=...`。
- 服务端调用：
  - `GET /api/model?location[directory]=<wd>` → `{data:[{modelID, providerID, name, variants, ...}]}`
  - `GET /api/agent?location[directory]=<wd>` → `{data:[{id, name, description, mode}]}`
  - OpenAPI 把 `location` 声明为 deepObject；实测 wire 形式是 **`location[directory]=...`**。
    httpx 使用 `params={"location[directory]": wd}`，不要用 `location.directory`（会被服务端忽略并退回全局配置），
    也不要手拼含特殊字符/反斜杠的 URL。
- 结果缓存 60 秒（内存 dict，key=`endpoint_id|working_directory`）；Endpoint 配置修改时清空该 Endpoint 的缓存。
- 返回 `<option>` / `<datalist>` 片段；模型按 provider 分组，显示 `provider / name (modelID)`。
- 发现失败（连接/认证/超时）时不阻塞保存：显示“无法从 Endpoint 读取模型列表，请手动填写”，保留手输字段。
- 手动输入的 provider/model 不做白名单校验；执行时由 OpenCode 决定是否有效。无效时 Run 在 `session` 或 `prompt` 阶段失败，错误如实展示。

#### 8.2.9 立即执行

- 路由 `POST /api/v1/tasks/{id}/run`。
- 服务端：
  1. Task 必须存在且 `status != archived`；
  2. Endpoint 必须存在且启用，否则 409 并提示；
  3. 按当前 Task 配置构建 Run 快照；
  4. 检查重叠（待执行/活动集合）：
     - `skip` → 创建 `Skipped` Run（`error_type=overlap`），前端 `message.warning` 提示“上一次执行尚未结束，已按策略跳过”；
     - `queue` → 创建 `Queued` Run；
  5. 不修改 `next_run_at`、不修改调度配置。
- 返回 Task 详情或 Run 详情；如果是 Queued，提示“已进入队列”。

#### 8.2.10 历史重新执行

- 路由 `POST /api/v1/runs/{id}/rerun`。
- 只允许对**终态** Run 发起 Rerun；活动/Queued Run 拒绝（要重跑请先取消或等待结束）。
- 默认使用原 Run 的快照：prompt、工作目录、provider/model/agent、timeout、overlap 策略。
- Endpoint 解析：
  - 原 `endpoint_id` 存在且启用 → 使用当前连接配置（地址/认证可能已变），新 Run 快照记录当前 URL；
  - 原 Endpoint 已删除/停用 → 表单必须先选择可用 Endpoint；服务端校验并记录 `config_adjusted=true` 与调整说明；
- 新 Run：`trigger_source=rerun`、`rerun_of_run_id=<原 Run>`、`occurrence_key=NULL`；不覆盖原 Run。
- 仍遵守重叠策略；如果 Skip，创建 `Skipped` Run 并说明。
- 归档 Task 的历史 Run 允许 Rerun（PRD 只禁止“直接手动执行”归档 Task；Rerun 是历史动作）。如果不希望允许，需产品确认；本文按“允许”实现，便于排障。

### 8.3 调度引擎

#### 8.3.1 运行方式

- `SchedulerEngine` 在 FastAPI lifespan 中启动一个协程，每 `PROMPTOPS_SCHEDULER_TICK_SECONDS`（默认 1s）执行一次 `tick(now)`。
- `tick` 用 `asyncio.Lock` 防重入；单次 tick 不应超过 1s（正常只有少量 Task）。
- 单个 tick 的异常必须捕获并记录，不能让调度协程退出；下一 tick 继续。
- 所有时间比较用 UTC ms；`now = int(time.time() * 1000)`。
- 每次 tick 只处理“当前到点”的 Task；没有到点就空转。

#### 8.3.2 tick 伪代码

```python
async def tick(now_ms: int) -> None:
    async with self._tick_lock:
        due = await repo.tasks_due(now_ms)          # status=enabled, schedule_enabled=1, next_run_at<=now
        for task_id in due:
            async with self._claim_lock:
                async with db.transaction():
                    task = await repo.get_task_for_update(task_id)
                    if not is_schedulable(task):
                        continue
                    occurrence = task.next_run_at
                    late = now_ms - occurrence
                    if late > self.missed_grace_ms:
                        await self._handle_missed(task, occurrence, now_ms)
                    else:
                        await self._handle_due(task, occurrence, now_ms)
```

`_handle_due`：

```python
async def _handle_due(task, occurrence, now_ms):
    endpoint = await repo.get_endpoint(task.endpoint_id)
    if endpoint is None or not endpoint.enabled:
        await self._create_run(task, occurrence, "skipped", error="endpoint_disabled")
        await self._advance(task, now_ms)
        return

    if await repo.has_pending_or_active_run(task.id):
        if task.overlap_policy == "skip":
            await self._create_run(task, occurrence, "skipped", error="overlap")
        else:
            await self._create_run(task, occurrence, "queued")
    else:
        await self._create_run(task, occurrence, "queued")

    await self._advance(task, now_ms)
```

`_handle_missed`：

```python
async def _handle_missed(task, first_missed, now_ms):
    latest_due, missed_count = await compute_latest_due(task, first_missed, now_ms)
    endpoint = await repo.get_endpoint(task.endpoint_id)
    if endpoint is None or not endpoint.enabled:
        await self._create_run(task, latest_due, "skipped",
                               error="endpoint_disabled", source="recovery")
        await self._advance(task, now_ms)
        return
    if task.missed_policy == "skip":
        await self._create_run(task, latest_due, "skipped",
                               error="missed_schedule",
                               details={"missed_count": missed_count})
    else:  # run_once
        if await repo.has_pending_or_active_run(task.id):
            if task.overlap_policy == "skip":
                await self._create_run(task, latest_due, "skipped",
                                       error="overlap", source="recovery")
            else:
                await self._create_run(task, latest_due, "queued", source="recovery")
        else:
            await self._create_run(task, latest_due, "queued", source="recovery")
    await self._advance(task, now_ms)
```

`_create_run`：

- `occurrence_key = "occ:" + str(occurrence)`。
- 同一 `(task_id, occurrence_key)` 已存在 → 不重复插入（`INSERT ... ON CONFLICT DO NOTHING`），但仍要推进 `next_run_at`。
- Run 快照从 Task + Endpoint 当前值构建；`scheduled_for=occurrence`；`trigger_source` 为 `scheduled` 或 `recovery`；`status` 为 `queued` 或 `skipped`。
- 写 `run_logs`：`created` / `skipped`（含原因）。
- 如果 `skipped`，`finished_at=now`、`error_phase=scheduler`、`error_type` 为原因。

`_advance`：

- `once`：`schedule_enabled=false`、`next_run_at=NULL`（无论本次是执行、跳过还是 Endpoint 停用，计划时刻已消费）。
- `cron/interval`：`next_run_at = next_occurrence(task, now_ms)`（第一个 **严格大于 now** 的时刻）。这样即使 tick 延迟，也不会一次创建多个 Run；中间错过的时刻由 missed 策略汇总处理。
- 更新 `updated_at`。

#### 8.3.3 exactly-once

三层保证：

1. `ux_runs_task_occurrence` 唯一索引：同一 Task 同一 `occ:<ms>` 最多一条 Run。
2. 创建 Run 与推进 `next_run_at` 在**同一个事务**内提交；崩溃只会导致“两者都没发生”或“两者都发生”。
3. tick 内的 `_claim_lock` 防止同一进程内两个 tick 并发处理同一 Task。

验证用例：

- 同一 occurrence 调用两次 `_create_run` → 只有一条 Run。
- 事务提交后模拟崩溃、重启 → Recovery 不会重建同一 occurrence。
- 两个并发 tick（人为制造）→ 只有一个创建成功。

#### 8.3.4 重叠策略

- 判断集合：`Queued` + `Preparing/Submitting/Running/Waiting/Cancelling`。
- `queue`：创建 `Queued` Run；Dispatcher 的领取查询保证同一 Task 只跑一个，FIFO。
- `skip`：创建 `Skipped` Run，`error_type=overlap`，`finished_at=now`，RunLog 写明“上一次执行尚未结束（run_id=...）”。
- 手动执行与 Rerun 同样走这个判断。
- 队列不设上限（PRD 未要求）；如果用户长期不处理，队列会累积。Dashboard 显示 Queued 数量；文档提示。**设计决定**：不擅自丢弃排队 Run。

#### 8.3.5 错过执行时间

- 启动时由 Recovery/Scheduler 先跑一次“弥补 tick”（`tick(now)` 对 `next_run_at` 远早于 now 的 Task 走 `_handle_missed`）。
- 运行中如果进程被挂起（如笔记本休眠）导致 tick 延迟超过 `PROMPTOPS_MISSED_GRACE_SECONDS`（默认 300s），同样按 missed 处理，而不是补跑所有时刻。
- `run_once`：只创建一条 `Recovery` Run，`scheduled_for=latest_due`；不逐次补跑。
- `skip`：创建一条 `Skipped` Run，`details_json.missed_count` 记录错过次数；不补跑。
- 一次性调度：错过时按同样策略处理；之后 `schedule_enabled=false`。
- `compute_latest_due` 对 cron 逐次前进，最多 10000 次；超过则使用**最后一次已计算出的 due**作为 `latest_due`，停止继续迭代并记录 warning。不要用未来时刻冒充 due；避免恶意 cron（每分钟）长期停机导致死循环。

#### 8.3.6 一次性与固定间隔

**一次性**：

- 保存时 `run_at` 必须 > now；`next_run_at = run_at`。
- 触发（或跳过）后 `schedule_enabled=false`、`next_run_at=NULL`；Task 保留。
- 前端显示“已执行/已结束的一次性调度”，不再显示下一次时间。

**固定间隔**：

- `interval_seconds >= 60`。
- 保存时 `next_run_at = now + interval`（从保存时刻起算）。
- 每次触发后 `next_run_at = next_occurrence(task, now)`，会跳过停机期间错过的多个间隔，只保留一个待执行时刻；错过策略生效。
- 编辑间隔会重置节拍（从 now 起算），只影响未来。

#### 8.3.7 全局 UTC 偏移修改

- 修改 `PROMPTOPS_UTC_OFFSET` 后，只重算**未来**的 `next_run_at`；历史 Run 的 `utc_offset` 快照不变。
- 已有 Queued Run 的 `scheduled_for` 是 UTC instant，不受影响；它的快照保留创建时的偏移，用于展示。
- 下一次预览按新偏移计算。
- MVP 不提供运行中修改偏移的 UI；改 env 后重启生效。

#### 8.3.8 调度边界示例

| 场景 | 配置 | 行为 |
|---|---|---|
| 每天 09:00 | cron `0 9 * * *`，UTC+08:00 | 每天 01:00 UTC 触发；tick 延迟 5s 仍触发当天 |
| 每月 1 日 09:00 | cron `0 9 1 * *` | 每月 1 日；若 1 日 09:00 停机到 2 日，按 missed 策略 |
| 每 30 分钟 | interval 1800 | 08:00、08:30、09:00；停机到 09:10，错过 09:00，按 missed 策略 |
| 一次性 | run_at 2026-11-01 10:00 | 触发一次后自动结束调度 |
| 上一轮未结束 + Queue | overlap=queue | 新触发创建 Queued Run；前一个结束后 FIFO 执行 |
| 上一轮未结束 + Skip | overlap=skip | 创建 Skipped Run，日志说明原因 |
| Endpoint 停用 | scheduled | 创建 Skipped Run，`error_type=endpoint_disabled`；不发送 Prompt |

### 8.4 Run 执行器

#### 8.4.1 领取

```sql
SELECT r.*
FROM runs r
WHERE r.status = 'queued'
  AND NOT EXISTS (
    SELECT 1 FROM runs a
    WHERE a.task_id = r.task_id
      AND a.status IN ('preparing','submitting','running','waiting','cancelling')
  )
ORDER BY r.created_at ASC, r.id ASC
LIMIT 1;
```

在 `claim_lock` + 事务内执行；随后：

```sql
UPDATE runs
SET status='preparing', started_at=:now, deadline_at=:now + timeout_minutes*60000,
    last_heartbeat_at=:now, updated_at=:now
WHERE id=:id AND status='queued';
```

`rowcount == 1` 才算领取成功。领取后写 `run_logs(claimed)`。

#### 8.4.2 阶段与日志

| phase | 时机 | 典型 message |
|---|---|---|
| `created` | Run 创建 | Run created (source=scheduled) |
| `queued` | 进入队列 | Waiting for worker |
| `claimed` | worker 领取 | Claimed by worker |
| `resolving_endpoint` | 解析 Endpoint | Resolving endpoint ep_... |
| `probing` | GET /api/info | Probing OpenCode v2 endpoint |
| `creating_session` | POST /api/session | Creating OpenCode session |
| `session_created` | 建会话成功 | Session ses_... created |
| `submitting` | POST /prompt | Submitting prompt |
| `submitted` | prompt 200 | Prompt admitted (user message msg_...) |
| `tracing` | 开始接收事件 | Tracing session |
| `waiting_permission` | permission.asked | Waiting for permission: <action> |
| `permission_resolved` | 回复成功 | Permission <id> -> once/always/reject |
| `cancelling` | 取消/超时请求 | Cancel requested (reason=user/timeout) |
| `interrupt_sent` | interrupt 返回 | Interrupt acknowledged (interrupted=true/false) |
| `cancel_confirmed` | 确认中断 | Cancellation confirmed |
| `timing_out` | 到 deadline | Deadline reached; requesting interrupt |
| `finalizing` | 拉消息/diff | Finalizing run |
| `finalized` | 终态写入 | Run finished: <status> |
| `failed` | 明确失败 | Failed at <phase>: <type> |
| `unknown` | 无法确认 | Cannot confirm run state: <reason> |
| `skipped` | 未执行 | Skipped: <reason> |

日志 message 不包含密码、Authorization、完整 Prompt（Prompt 本身在 Run 详情可见，但日志不重复）。

#### 8.4.3 执行主流程

```python
async def execute(run_id: str) -> None:
    run = await repo.get_run(run_id)
    # claim 后立即注册 handle（此时还没有 session），UI 的取消请求才能设置取消标志。
    handle = registry.register(run)
    if run.cancel_requested_at:
        await finish_cancelled(run, "user")
        return
    try:
        endpoint = await endpoints.resolve(run.endpoint_id)
        if endpoint is None or not endpoint.enabled:
            await finish_skipped(run, "endpoint_disabled")
            return

        # claim 已把 Run 置为 Preparing，并写入 started_at / deadline_at；
        # 这里不再重复 transition，只写日志并推进后续状态。
        client = client_registry.get(endpoint)

        await log(run, "probing")
        info = await client.info()                 # 失败 -> Failed(connect)
        if await control_check(handle, run):
            return
        await log(run, "creating_session")
        session = await client.create_session(
            title=make_title(run),
            directory=run.working_directory,
            model=run.model_ref,
            agent=run.agent,
        )
        await repo.set_session(run, session.id)
        # session 创建后附加到已注册的 handle，确保事件/终态不会丢。
        handle.attach_session(session.id)
        await log(run, "session_created", session_id=session.id)

        # 控制检查点：已建 Session 但尚未提交 Prompt，可以直接 Cancelled/Timeout（无外部执行）。
        if await control_check(handle, run):
            return

        await transition(run, "submitting", submitting_at=now)
        await log(run, "submitting")
        try:
            user_msg = await client.prompt(session.id, run.prompt)
        except PromptUncertain as exc:
            admitted = await reconcile_prompt_admission(client, session.id, run)
            if not admitted:
                await finish_unknown(run, "prompt_admission_unknown", str(exc))
                return
        await transition(run, "running", running_at=now)
        await log(run, "submitted", user_message_id=...)
        await log(run, "tracing")

        outcome = await wait_for_terminal(handle, deadline=run.deadline_at)
        await finalize(run, outcome)
    except OpenCodeError as exc:
        await finish_error(run, exc)
    except Exception as exc:
        await finish_error(run, unexpected(exc))
    finally:
        registry.unregister(run_id)
```

**控制检查点**：`RunHandle` 在 claim 后立即注册（此时无 session），UI 取消可设置 `cancel_requested`；session 创建后 `attach_session(session_id)`。执行器在每个 await 边界调用：

```python
async def control_check(handle, run) -> bool:
    if handle.timeout_requested:
        await finish_timeout(run, "timeout_before_prompt")
        return True
    if handle.cancel_requested:
        await finish_cancelled(run, "user")
        return True
    return False
```

尚未提交 Prompt 时直接 `Cancelled`/`Timeout`，不调用 interrupt（没有执行可中断）；提交后取消走 8.4.5 的 interrupt 路径。进程重启后，Recovery 重新读取 `runs.cancel_requested_at` 判断取消意图。

`wait_for_terminal`：

- 等待 `handle.terminal_event`，超时到 `deadline_at`。
- 终态事件可能早于 `wait_for_terminal` 到达：`RunHandle` 必须锁存结果（`set()` 后再 `wait()` 立即返回），不能丢事件。
- 进入 `wait_for_terminal` 时若 `handle.timeout_requested` / `handle.cancel_requested` 已置，立即走 8.4.6 / 8.4.5 的取消路径，不要先等事件。
- 同时每 5s 检查 `handle.cancel_requested` / `timeout_requested`，由中央 sweeper 设置。
- 如果 SSE 断开超过 10s，启动轮询兜底。
- 返回 `TerminalOutcome(kind, raw)`，`kind` 为 `succeeded/failed/interrupted`。

#### 8.4.4 终态映射

| 观察 | 条件 | Run 终态 | error_type |
|---|---|---|---|
| `execution.succeeded` 或 `session.outcome=succeeded` | 无取消/超时请求 | `Completed` | — |
| 同上 | 取消请求已发，但成功先到 | `Completed` | 日志注明 cancel too late |
| 同上 | 超时请求已发，但成功先到 | `Completed` | 日志注明 timeout too late |
| `execution.failed` 或 `session.outcome=failed` | — | `Failed` | `session_failed` / 结构化错误类型 |
| `execution.interrupted` / `outcome=interrupted` | `cancel_reason=user` | `Cancelled` | — |
| 同上 | `cancel_reason=timeout` | `Timeout` | — |
| 同上 | 无 cancel_reason | `Failed` | `remote_interrupted` |
| 无法确认（Session 404/网络中断/取消未确认） | — | `Unknown` | 见附录 B |

`Completed` 只表示 Session 正常结束；`final_response` 可能为空。UI 不得写“执行成功/业务成功”，只写“已完成（Completed）”。

#### 8.4.5 取消

**Queued**：

- 条件更新 `Queued → Cancelled`；写 `cancel_requested_at/cancel_confirmed_at=now`、`cancel_reason=user`；不需要 OpenCode。

**Preparing（尚未创建 Session）**：

- 设置取消标志；在下一个 await 检查点停止；`Cancelled`（没有外部副作用）。如果已创建 Session 但尚未提交 Prompt，调用 interrupt 或直接结束；`Cancelled` 仍准确，因为没有 Prompt 被接收。RunLog 写明。

**Submitting（Prompt POST 在途）**：

- 设置 `cancel_requested_at`，进入 `Cancelling`；等待 POST 结果：
  - 200 → 调 interrupt；转 `Cancelled` 需确认 `interrupted`；
  - 明确 4xx → `Cancelled`（没有执行）；
  - 不确定 → 对账；确认 Prompt 已接收 → 调 interrupt；否则 `Cancelled`（未接收）；
  - 仍不确定 → `Unknown`。

**Running / Waiting**：

- 条件更新为 `Cancelling`；`cancel_requested_at=now`；`cancel_reason=user`；调 `POST /interrupt`。
- 收到 `session.execution.interrupted` 或 `session.outcome=interrupted` → `Cancelled`，写 `cancel_confirmed_at`。
- 如果 `interrupted=false` 且 Session 已成功 → `Completed`（取消太晚）；失败 → `Failed`；仍活动 → 继续等。
- 超过确认窗口 → `Unknown`，`error_type=cancel_unconfirmed`。
- UI 提示：取消不能撤销已经发生的文件修改、消息发送、外部调用。

#### 8.4.6 超时

- `deadline_at = started_at + timeout_minutes*60000`（从领取时刻算，包含连接/建会话/提交）。
- 如果超时在 Prompt 提交前到达，直接 `Timeout`（`timeout_before_prompt`），不调用 interrupt；因为没有外部执行需要停止。
- 中央 sweeper 每 5s 扫描活动 Run；`deadline_at <= now` 且未取消：
  - 置 `cancel_reason=timeout`；`Cancelling`；写 `timing_out`；调 interrupt。
  - 确认中断 → `Timeout`；成功先到 → `Completed`。
  - 窗口内未确认时，先做一次 `GET /api/session` 最终对账：有 `outcome` 就按 8.4.4 映射（succeeded→Completed、failed→Failed、interrupted→Timeout）；仍无 outcome 才 `Unknown`，`error_type=timeout_unconfirmed`。
- 超时不会删除 OpenCode Session；保留轨迹供排查。
- 超时后不自动重试。

#### 8.4.7 心跳与中央 sweeper

- 执行器每 `PROMPTOPS_RUN_HEARTBEAT_SECONDS`（10s）更新 `last_heartbeat_at`；SSE 事件到达也更新。
- sweeper 每 5s：
  1. 超时检查（8.4.6）；
  2. `Cancelling` 超过确认窗口：先对账 Session；有 outcome 按 8.4.4 映射，仍无 outcome 才 `Unknown`；
  3. 活动 Run 心跳超过 `PROMPTOPS_STALE_RUN_SECONDS`（默认 300s）→ 写 warning；如果无 Session → `Unknown`；有 Session → 触发一次对账（不直接判死）。
- sweeper 不重发 Prompt。

#### 8.4.8 最终收尾（finalize）

顺序：

1. `GET /api/session/{id}` 取 `outcome/cost/tokens`；事件已给出 outcome 时以事件为准，Session info 只作补充（可能短暂没有 `outcome`）。失败不改变已确认的终态，只记 `trace_integrity=incomplete`。
2. 分页拉取全部消息（`order=asc`），投影为 trace items。
3. `GET /api/session/{id}/diff`，投影 file items。
4. 计算 `final_response`：取最后一条 assistant 消息；它含非空 `text` 才按 content 顺序拼接 text parts，否则 NULL（与 8.5.3 一致，不向前回退）。
5. 更新 `runs`：终态、`finished_at`、用量、`final_response`、`trace_integrity`、`error_*`。
6. 写 `run_logs(finalized)`。
7. 释放 RunHandle；SSE supervisor 若该 Endpoint 无活动 Run，开始 5 分钟空闲计时。

**消息滞后**：终态事件到达时，先等 500ms 让同一批 SSE 事件落库，再开始收尾。消息投影可能还没完全落库；若事件为 `succeeded` 但最后一条 assistant 没有 text、或消息列表为空，重试消息拉取 3 次（间隔 1s）；仍无则 `final_response=NULL`。diff 失败重试 1 次，仍失败则文件轨迹标 `incomplete`。

**收尾幂等**：`finalize` 可能因重连/恢复被调用多次；用 `WHERE status IN (active)` 条件更新，已终态则只补 trace，不改状态。**`finalize` 的异常不能让 Run 停在活动状态**：已有确认终态则保留；没有确认终态则写 `Unknown`，`error_phase=finalize`，并保留 `error_message`。

#### 8.4.9 启动恢复

启动时在 Scheduler/Dispatcher 之前执行：

```text
for run in runs where status in (preparing, submitting, running, waiting, cancelling):
    if run.opencode_session_id is null:
        if status == preparing: Failed(process_restarted_before_prompt)
        elif status == submitting: Unknown(recovery_prompt_may_be_admitted)
        elif status == cancelling: Cancelled(no_session)
        else: Unknown
        continue
    try:
        session = GET /api/session/{sid}
    except 404:
        Unknown(session_not_found)
    except connection/auth:
        Unknown(server_unreachable_during_recovery)
    else:
        if session.outcome:
            finalize(run, outcome)       # 不重发
        else:
            handle = registry.register(run)
            handle.attach_session(session.id)
            spawn resume_run(run, handle)   # 复用 wait_for_terminal + finalize
            if deadline_at <= now: request_timeout(run)
            else: log(recovered_active)
```

- `resume_run` 是 Recovery 自己持有的协程，**不经过 Dispatcher 的领取流程**（再次领取会重复执行）；它只等待终态、对账、收尾。
- 恢复过程不创建新 Session、不重发 Prompt。
- 恢复完成后才启动 Scheduler，避免“恢复中又被调度”。
- 每个 Run 的恢复独立处理；单个 Run 对账失败不阻塞其他 Run。数据库/迁移不可用则拒绝启动。
- 所有恢复动作写 RunLog（`recovered_*`）。

#### 8.4.10 并发与有序性

- 同一 Task 的活动 Run 至多一个；Queued Run 按创建时间 FIFO。
- 不同 Task 可以并行，受 `PROMPTOPS_MAX_CONCURRENT_RUNS` 限制。
- 同一 Endpoint 可以被多个 Run 并发使用；OpenCode Session 本身隔离。
- 同一 Endpoint 只有一条 SSE 流；事件按 `sessionID` 分发。
- 数据库写入短事务；不在 HTTP 调用期间持有事务。
- 每个 worker 对单个 Run 的异常做捕获和记录，然后继续领取下一个；不能让一个 Run 的异常杀死整个 worker 循环。

### 8.5 轨迹采集与展示

#### 8.5.1 规范化条目

| 来源 | kind | external_id | parent | 关键字段 |
|---|---|---|---|---|
| 用户消息 | `user_message` | message.id | NULL | output_text=text |
| Assistant 消息 | `assistant_message` | message.id | NULL | output_text=拼接 text parts |
| Assistant tool part | `tool` | content.id (call ID) | assistant message id | name, status, input, output, error, times |
| Skill 消息 | `skill` | message.id | NULL | name=skill name, output_text=text, status=info |
| Shell 消息 | `tool` | message.id | NULL | name=shell, input/output 按 content |
| 权限请求 | `permission` | request.id | NULL | name=action, input_json=resources/source, status |
| 错误 | `error` | event.id | 相关 message/call（若知） | error_text, metadata |
| 文件 diff | `file` | file path | NULL | name=file, status, patch, additions/deletions |
| 子 Session（可选） | `system` | child session id | NULL | output_text=title |

**状态映射**：

| OpenCode | trace_items.status |
|---|---|
| `streaming` | `pending` |
| `running` | `running` |
| `completed` | `completed` |
| `error` | `failed` |
| permission `once/always` | `completed`（metadata 记 decision） |
| permission `reject` | `rejected` |
| 文件/信息 | `info` |

**去重**：`unique(run_id, kind, external_id)`；同一条目重复事件执行 upsert，只更新状态/输出/时间，不新增。

**顺序**：`sequence` 在 Run 内单调递增；分配时在写事务内执行 `SELECT COALESCE(MAX(sequence),0)+1`，同一 Run 的并发写由 SQLite 写锁串行化。实时事件按到达顺序；最终对账时，已存在的条目保留原 sequence，新条目追加。时间线展示用 `COALESCE(started_at, created_at)` 排序，`sequence` 作为 tie-breaker。

**层级**：

```text
Run
└── OpenCode Session
    ├── Prompt (user_message)
    ├── Assistant message
    │   └── Tool call
    ├── Skill (skill)
    ├── Tool call（无法确定父消息时）
    ├── Permission
    ├── File change
    └── Final response (assistant_message)
```

- Tool 的父级是包含它的 assistant message（v2 事件提供 `assistantMessageID`），这是真实关系，不是推断。
- Skill 与 Tool 没有可靠父子关系时，都挂在 Session 下；**不强行把 Tool 归到某个 Skill**。
- 未知父级 → 挂 Session，不丢条目。

#### 8.5.2 实时更新

- `TraceIngestor` 收到 `session.text.delta` 时，为了避免每字一条 DB 写，采用节流：
  - 内存维护每个 assistant message 的当前文本；
  - 最多每 500ms 或每 4KB 写一次 `output_text`；
  - `session.text.ended` 强制写最终文本。
- Tool 事件是低频的，逐条 upsert。
- **事件分发不依赖内存 handle**：SSE supervisor 先按 `sessionID` 查 `runs.opencode_session_id` 找到 Run，再写 trace/用量；如果该 Run 有注册的 `RunHandle`，才唤醒等待者。恢复窗口内没有 handle 时，事件仍要落库，避免丢轨迹；终态事件到达但无 handle 时，supervisor 把它放入“待收尾”异步队列并调用 `finalize`。若进程在收尾前崩溃，Recovery 会重新对账。
- Run 详情页用 TanStack Query 每 2s 轮询 `/api/v1/runs/{id}/trace`（以及摘要/日志），读取 DB；关闭页面不影响后台采集。

#### 8.5.3 最终回复

- `final_response` 只来自 assistant 消息的 `text` 内容。
- 选择规则：按消息时间顺序取**最后一条 assistant 消息**；如果它至少有一个非空 `text` part，按 content 顺序拼接所有 text parts，用 `\n` 连接；如果它只有 tool 调用、没有 text，则 `final_response=NULL`。
- **不向前回退**找更早的 assistant 文本：更早的文本很可能是过程说明，不是最终回复；回退会把“没有最终回复”误报成“有”。
- OpenCode v2 没有单独的 final 标记；UI 在“最终结果”旁标注“来源：最后一条 Assistant 文本”，避免读者误以为是业务结论。
- `final_response` 同样受 `PROMPTOPS_MAX_TRACE_TEXT_BYTES` 约束；超长截断并置 `final_response_truncated=1`，UI 显示“已截断”。
- UI 无 final response 时显示精确文案：**本次执行没有可用的最终回复。**
- 不调用模型生成总结，不判断业务正确性。

#### 8.5.4 用量

- Session 的 `tokens` / `cost` 是首选；assistant 消息的 `tokens/cost` 作为补充。
- 字段：`input_tokens`、`output_tokens`、`reasoning_tokens`、`cache_read_tokens`、`cache_write_tokens`、`cost_usd`。
- 任何一个缺失 → 存 NULL，UI 显示“未返回”，**不估算**。
- 展示位置：Run 详情“消耗信息”；不参与业务判断。

#### 8.5.5 轨迹完整性

| 值 | 判定 | UI 文案 |
|---|---|---|
| `complete` | SSE 全程连接，最终消息/diff 拉取成功 | 轨迹完整 |
| `gap` | SSE 至少断连一次，但对账成功补齐 | 轨迹有缺口，已用最终消息补齐 |
| `incomplete` | 对账失败、分页失败、Session 不可达、部分事件缺失 | 轨迹不完整，仅供参考 |
| `none` | 没有条目，也没有消息 | 无可用轨迹 |

- 运行中显示“采集中”，终态后写最终值。
- `trace_gap_count` 显示断连次数；`last_event_at` 可用于排障（可存在 RunLog metadata，不必单独列）。
- 不把推理内容、未公开的内部过程描述为完整思考轨迹。

#### 8.5.6 权限条目展示

- 在 Run 详情顶部（摘要下方）显示“待处理权限”区块，优先于轨迹。
- 每条：action、resources、source、message、请求时间；按钮 Allow once / Always / Reject；Reject 可填原因。
- 提交后局部刷新；如果 Run 已终态，按钮禁用并说明。
- 没有待处理权限时不显示该区块。
- 不自动批准；不提供“全部批准”按钮（MVP）。

### 8.6 Run 详情、历史与 Dashboard

#### 8.6.1 Run 详情区域

| 区域 | 内容 | 数据来源 |
|---|---|---|
| 摘要 | Task 名称、Run 状态、来源、Endpoint（快照）、工作目录、Provider/模型/Agent、开始/结束、总耗时、队列等待 | `runs` |
| 操作 | 取消（活动/Queued）、重新执行（终态） | 状态判断 |
| Prompt | 本次实际发送的完整 Prompt | `runs.prompt` |
| 实时轨迹 | 时间线/层级、Tool 输入输出、Skill、文件、错误、权限 | `trace_items` |
| 最终结果 | 最后 assistant 文本；无则固定文案 | `runs.final_response` |
| 错误信息 | 失败阶段、类型、消息、相关 Session/Tool、是否可 Rerun | `runs.error_*` + 失败 trace item |
| 消耗信息 | tokens/cost/cache；缺失显示“未返回” | `runs` |
| 配置快照 | 可折叠 JSON/表格 | `runs.config_snapshot_json` |
| Run 日志 | 时间、级别、阶段、消息 | `run_logs` |
| 子 Session | 可选列表 | `/api/session?parentID=` |

“总耗时”= `finished_at - started_at`；未开始则 NULL。“队列等待”= `started_at - queued_at`。

#### 8.6.2 历史列表

列：Task、Run 状态、Endpoint（快照）、来源、开始时间、结束时间、耗时、轨迹完整性。

筛选：Task、Endpoint、Run 状态、来源、时间范围（from/to）、模型。

分页：offset/limit（默认 50，最大 200）；按 `created_at DESC`。显示总数。

操作：查看详情、查看轨迹、查看快照、Rerun、取消（活动）。

#### 8.6.3 Dashboard 统计

| 区块 | 指标 | 定义 |
|---|---|---|
| Endpoint 概览 | 总数、默认、启用、停用 | `endpoints` 计数 |
| Task 概览 | 总数、启用、停用、归档 | `tasks.status` 计数 |
| Run 概览 | Queued、Running、Waiting | 当前状态计数 |
| Run 概览 | Failed、Completed | 最近 30 天计数，标签注明“近 30 天” |
| 即将执行 | Task 名称、下一次时间、Endpoint | `tasks` where enabled + schedule_enabled + next_run_at not null，升序，limit 5 |
| 最近执行 | Task、Endpoint、状态、来源、开始时间、详情链接 | `runs` 按 created_at desc，limit 10 |
| 最近失败 | Task、Endpoint、状态、错误类型、开始时间、详情链接 | `runs` where status in (failed, timeout, unknown) 最近 10 条 |

- Endpoint 连接失败会以 Failed Run 出现在“最近失败”，不需要健康监控。
- 不展示基于定时探测的在线/离线。

---

## 9. Web API 设计

### 9.1 原则

- 前端是独立 SPA，后端只提供 **JSON API**；不再有服务端 HTML 模板、HTMX partial 或表单重定向。
- 所有业务 API 挂在 `/api/v1` 下；`/healthz` 保留为运维探针；生产环境由 FastAPI 同源提供 `frontend/dist`。
- API 版本前缀固定为 `/api/v1`；破坏性变更升 `/api/v2`，不在同一版本内改变字段语义。
- 请求/响应使用 JSON；时间统一 ISO 8601 UTC（`2026-10-19T08:00:00Z`），前端用 dayjs 按全局 `UTC+08:00` 展示；不传本地时区。
- 枚举值使用小写字符串（`queued`、`running`、`scheduled`），前端负责中文标签映射。
- 列表分页统一 `page`（1-based）+ `page_size`（默认 20，最大 200）；响应 `{items, total, page, page_size}`。
- 认证沿用 SPEC 13.1：应用本身无登录，默认只监听 `127.0.0.1`；远程部署由反向代理认证。API 不使用 Cookie，因此不需要 CSRF token。

### 9.2 响应与错误约定

成功响应直接返回对象或分页对象：

```json
{"items": [], "total": 0, "page": 1, "page_size": 20}
```

错误响应统一：

```json
{
  "error": {
    "code": "validation_error",
    "message": "cron 表达式不合法",
    "details": {"cron": "第 3 段不是合法数字"}
  }
}
```

| HTTP | `error.code` | 场景 |
|---|---|---|
| 400 | `bad_request` | 请求语义错误 |
| 401 | `unauthorized` | 保留；MVP 应用无登录，通常不返回 |
| 403 | `forbidden` | 操作不被允许（如归档 Task 手动执行） |
| 404 | `not_found` | Endpoint/Task/Run/Permission 不存在 |
| 409 | `conflict` | 默认 Endpoint 删除、Endpoint 停用、Run 非终态 Rerun、重叠策略拒绝等 |
| 422 | `validation_error` | Pydantic/AntD 字段校验失败；`details` 为字段 → 错误信息 |
| 502 | `opencode_error` | 上游 OpenCode 返回不可用/协议错误 |
| 500 | `internal_error` | 未预期错误；不返回堆栈/密码 |

前端 `ApiError` 保留 `status/code/message/details`；表单提交收到 422 时把 `details` 映射到 AntD `form.setFields`。

### 9.3 路由总表

**Meta / 运维**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | `{status, version, db, frontend_built}` |
| GET | `/api/v1/meta` | `{version, server_time, utc_offset, utc_offset_label, frontend_version}` |
| GET | `/api/docs` | FastAPI OpenAPI 文档（`docs_url="/api/docs"`；内部工具可保留，生产可关闭） |

**Dashboard**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/dashboard` | Endpoint/Task/Run 统计、即将执行、最近执行、最近失败 |

**Endpoint**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/endpoints` | 列表；`?enabled=&page=&page_size=` |
| POST | `/api/v1/endpoints` | 创建 |
| GET | `/api/v1/endpoints/{id}` | 详情 |
| PUT | `/api/v1/endpoints/{id}` | 更新 |
| DELETE | `/api/v1/endpoints/{id}` | 删除（受约束） |
| POST | `/api/v1/endpoints/{id}/default` | 设为默认 |
| POST | `/api/v1/endpoints/{id}/enable` | 启用 |
| POST | `/api/v1/endpoints/{id}/disable` | 停用 |
| POST | `/api/v1/endpoints/test` | 测试连接；可传 `endpoint_id` 或未保存的连接配置 |

**Task**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/tasks` | 列表；支持 `status/endpoint_id/schedule_type/last_status/tag/page/page_size` |
| POST | `/api/v1/tasks` | 创建 |
| GET | `/api/v1/tasks/{id}` | 详情（含最近 Run 摘要） |
| PUT | `/api/v1/tasks/{id}` | 更新 |
| POST | `/api/v1/tasks/{id}/copy` | 复制（默认停用、关闭调度） |
| POST | `/api/v1/tasks/{id}/enable` | 启用 |
| POST | `/api/v1/tasks/{id}/disable` | 停用 |
| POST | `/api/v1/tasks/{id}/archive` | 归档 |
| POST | `/api/v1/tasks/{id}/restore` | 恢复为停用 |
| POST | `/api/v1/tasks/{id}/run` | 立即执行 |
| POST | `/api/v1/schedules/preview` | 调度预览，不落库 |
| GET | `/api/v1/options` | 模型/Agent 候选；`?endpoint_id=&working_directory=` |

**Run**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/runs` | 历史列表；支持 `task_id/endpoint_id/status/source/from/to/model/page/page_size` |
| GET | `/api/v1/runs/{id}` | Run 摘要、快照、错误、用量、待处理权限 |
| GET | `/api/v1/runs/{id}/trace` | 轨迹条目 + 完整性；`?view=timeline` 或 `?view=hierarchy` |
| GET | `/api/v1/runs/{id}/logs` | RunLog；`?after_at=&limit=` |
| POST | `/api/v1/runs/{id}/cancel` | 取消 |
| POST | `/api/v1/runs/{id}/rerun` | 重新执行；可带 `endpoint_id` |
| POST | `/api/v1/runs/{id}/permissions/{request_id}/reply` | 权限回复 |

> 路由注册顺序：`/api/v1/endpoints/test`、`/api/v1/schedules/preview`、`/api/v1/options` 必须在对应的动态 `/{id}` 路由之前注册，否则会被 `{id}` 捕获。

列表响应补充字段：

- Endpoint 列表/详情返回 `task_count`（含归档 Task）与 `has_password`；永不返回密码。
- Task 列表返回 `last_run` 摘要（`status/started_at/finished_at`），避免前端为每行再查一次。
- Run 列表返回 `trace_integrity`、`duration_ms`、`endpoint_name`（快照）、`utc_offset`（快照），便于直接渲染表格并按历史偏移展示时间。

### 9.4 关键请求/响应

**测试连接**

```json
POST /api/v1/endpoints/test
{
  "endpoint_id": "ep_123",
  "base_url": "http://127.0.0.1:4096",
  "auth_type": "basic",
  "username": "opencode",
  "password": ""
}
→ 200
{
  "result": "success",
  "message": "连接成功，OpenCode 2.0.29",
  "version": "2.0.29",
  "tested_at": "2026-10-19T08:00:00Z"
}
```

- `password` 为空且提供了 `endpoint_id` 时，服务端使用已存密码；未保存的新 Endpoint 必须提供密码。
- 结果 `result` 取值：`success/unreachable/auth_failed/unsupported/service_error/timeout`。
- 响应永不返回密码或 Authorization。

**调度预览**

```json
POST /api/v1/schedules/preview
{"type": "cron", "cron": "0 9 * * *", "count": 5}
→ 200
{
  "occurrences": [
    {"utc": "2026-10-20T01:00:00Z", "local": "2026-10-20 09:00:00"}
  ]
}
```

- `local` 是 `UTC+08:00` 墙钟时间；前端只显示这一列，不再计算浏览器本地时区。
- 预览响应可带 `utc_offset: "+08:00"` 供 UI 标注，但不需要客户端做换算。

**模型/Agent 候选**

```json
GET /api/v1/options?endpoint_id=ep_123&working_directory=/workspace/rates
→ 200
{
  "models": [{"provider_id": "lps", "model_id": "Qwen/Qwen3.6-35B-A3B-FP8", "name": "Qwen3.6 35B A3B", "variants": ["thinking", "no_thinking"]}],
  "agents": [{"id": "build", "name": "Build"}],
  "warning": null
}
```

- 发现失败时仍返回 200，`models/agents` 为空，`warning` 说明原因；前端保留手输 provider/model。
- 结果按 `endpoint_id + working_directory` 缓存 60 秒。

**Run 摘要**

```json
GET /api/v1/runs/run_123
→ 200
{
  "run": {
    "id": "run_123", "task_name": "Monthly Rate Report", "status": "running",
    "trigger_source": "scheduled", "scheduled_for": "2026-10-19T01:00:00Z",
    "created_at": "...", "started_at": "...", "finished_at": null,
    "utc_offset": "+08:00",
    "endpoint": {"id": "ep_123", "name": "Local OpenCode", "base_url": "..."},
    "working_directory": "/workspace/rates-report",
    "provider_id": "lps", "model_id": "...", "model_variant": null, "agent": null,
    "prompt": "...", "final_response": null, "error": null,
    "usage": {"input_tokens": null, "output_tokens": null, "cost_usd": null},
    "trace_integrity": "none", "config_snapshot": {}
  },
  "pending_permissions": []
}
```

**轨迹**

```json
GET /api/v1/runs/run_123/trace
→ 200
{
  "items": [
    {"id": "trc_1", "kind": "tool", "name": "read", "status": "completed",
     "parent_external_id": "msg_1", "started_at": "...", "ended_at": "...",
     "duration_ms": 21, "input": {"path": "..."}, "output": "Read file ...",
     "error": null, "metadata": {"truncated": false}}
  ],
  "integrity": "gap",
  "gap_count": 1
}
```

**权限回复**

```json
POST /api/v1/runs/run_123/permissions/per_1/reply
{"decision": "once", "message": null}
→ 204
```

`decision` 为 `once` / `always` / `reject`；后端调用 OpenCode 后返回 204。

### 9.5 筛选与分页

Task 列表：

```text
/api/v1/tasks?status=enabled&endpoint_id=ep_x&schedule_type=cron&last_status=failed&tag=rates&page=1&page_size=20
```

Run 历史：

```text
/api/v1/runs?task_id=tsk_x&endpoint_id=ep_x&status=failed&source=scheduled&from=2026-10-01&to=2026-10-31&model=...&page=1&page_size=50
```

- `from` / `to` 是日期（`YYYY-MM-DD`），按全局 `PROMPTOPS_UTC_OFFSET`（默认 `+08:00`）解释，包含首尾两天；后端转 UTC 查询。
- 所有筛选参数为空时忽略；未知参数不报错，但记录 debug 日志。

### 9.6 SPA 静态资源与 fallback

- 生产：FastAPI 挂载 `/assets` 到 `frontend/dist/assets`；`GET /` 返回 `index.html`；客户端路由（`/tasks/123`）fallback 到 `index.html`。
- `/api/*` 与 `/healthz` 不参与 fallback：未知 API 返回 JSON 404，不能返回 HTML。
- 静态资源带 `Cache-Control: public, max-age=31536000, immutable`（文件名带 hash）；`index.html` 使用 `no-cache`。
- `frontend/dist` 不存在时：`/` 返回 503 + “请先执行 pnpm build”的 JSON/HTML 提示；API 仍可用。

### 9.7 开发与跨域

- 开发：Vite dev server `http://localhost:5173`，`vite.config.ts` 代理 `/api` 与 `/healthz` 到 `http://127.0.0.1:8787`；浏览器同源，不需要 CORS。
- 如前端独立域名部署，配置 `PROMPTOPS_CORS_ORIGINS`（逗号分隔）启用 FastAPI CORSMiddleware；默认空，不开放跨域。
- 生产同源部署，不启用 CORS。

## 10. React 前端设计

### 10.1 技术栈与页面地图

```text
React 18.3 + TypeScript 5.6
Ant Design 5（antd + @ant-design/icons）
Vite 5.4（构建/开发服务器）
React Router 6（页面路由）
TanStack Query 5（请求缓存、失效、轮询）
dayjs + utc 插件 + utcOffset（统一按 UTC+08:00 展示）
原生 fetch（封装为 src/api/client.ts）
```

| 路由 | 页面 | 主要组件 |
|---|---|---|
| `/` | Dashboard | `Statistic` 卡片、`Table` 最近执行/失败、`List` 即将执行 |
| `/endpoints` | Endpoint 列表 | `Table`、`Tag`、`Space`、操作按钮 |
| `/endpoints/new` | 新建 Endpoint | `Form`、`Input`、`Select`、`Input.Password`、测试连接 |
| `/endpoints/:id` | Endpoint 详情 | `Descriptions`、最近测试结果、关联 Task |
| `/endpoints/:id/edit` | 编辑 Endpoint | 同新建表单 |
| `/tasks` | Task 列表 | `Table`、筛选栏、状态/调度摘要、下一次执行 |
| `/tasks/new` | 新建 Task | 分组 `Form`、`ScheduleForm`、`ModelSelect`、预览 |
| `/tasks/:id` | Task 详情 | `Descriptions`、最近 Run、操作按钮 |
| `/tasks/:id/edit` | 编辑 Task | 同新建表单 |
| `/runs` | 执行历史 | `Table`、筛选栏、分页 |
| `/runs/:id` | Run 详情 | 摘要、Prompt、`TraceView`、最终结果、错误、用量、快照、日志、权限 |
| `*` | 404 | AntD `Result` |

### 10.2 目录结构

```text
frontend/
├── package.json
├── pnpm-lock.yaml
├── vite.config.ts
├── tsconfig.json
├── index.html
├── src/
│   ├── main.tsx                 # ConfigProvider(zhCN) + QueryClientProvider + Router
│   ├── App.tsx                  # Layout、Sider/Menu、路由出口
│   ├── api/
│   │   ├── client.ts            # fetch 封装、ApiError、AbortSignal
│   │   ├── types.ts             # 与后端 Pydantic schema 对齐的 TS 类型
│   │   └── endpoints.ts         # 各资源 API 函数
│   ├── hooks/
│   │   ├── useMeta.ts
│   │   ├── useDashboard.ts
│   │   ├── useEndpoints.ts
│   │   ├── useTasks.ts
│   │   └── useRuns.ts
│   ├── pages/
│   │   ├── DashboardPage.tsx
│   │   ├── EndpointsPage.tsx
│   │   ├── EndpointFormPage.tsx
│   │   ├── EndpointDetailPage.tsx
│   │   ├── TasksPage.tsx
│   │   ├── TaskFormPage.tsx
│   │   ├── TaskDetailPage.tsx
│   │   ├── RunsPage.tsx
│   │   └── RunDetailPage.tsx
│   ├── components/
│   │   ├── StatusTag.tsx
│   │   ├── ScheduleForm.tsx
│   │   ├── SchedulePreview.tsx
│   │   ├── ModelSelect.tsx
│   │   ├── EndpointTestAlert.tsx
│   │   ├── RunSummary.tsx
│   │   ├── TraceView.tsx
│   │   ├── TraceItem.tsx
│   │   ├── DiffView.tsx
│   │   ├── LogsPanel.tsx
│   │   ├── PermissionModal.tsx
│   │   ├── ConfigSnapshot.tsx
│   │   ├── TimeText.tsx
│   │   └── ErrorState.tsx
│   ├── utils/
│   │   ├── time.ts              # dayjs utc/utcOffset、UTC+8 格式化
│   │   └── format.ts            # JSON 缩进、duration、状态标签
│   └── styles.css               # AntD theme 之外的少量布局样式
└── dist/                        # pnpm build 产物，gitignored
```

### 10.3 布局与主题

- `ConfigProvider`：`locale={zhCN}`、`theme={{token:{colorPrimary:'#1677ff', borderRadius:8}}}`。
- `Layout`：左侧 `Sider`（Dashboard / Endpoints / Tasks / Runs），顶部 `Header` 显示默认 Endpoint、当前版本；内容区 `Content`。
- `Breadcrumb` 根据路由生成；`Menu` 选中项与路由同步。
- 状态色：
  - 活动：Queued 默认灰、Preparing/Submitting/Running 蓝、Waiting 橙、Cancelling 紫。
  - 成功：Completed 绿。
  - 失败：Failed/Timeout/Unknown 红。
  - 取消/跳过：Cancelled/Skipped 灰。
- 状态标签始终带中文文字，颜色不是唯一信息。
- 不使用 AntD 之外的 UI 框架；图表暂不做（Dashboard 用 `Statistic`/`Table`）。

### 10.4 页面设计

**Dashboard**

- `Row/Col` + `Card` + `Statistic`：Endpoint 总数/默认/启用、Task 总数/启用/归档、Run Queued/Running/Waiting/Failed(30d)/Completed(30d)。
- `Table`：即将执行（Task/Endpoint/下一次时间）、最近执行、最近失败；行点击跳 Run 详情。
- 全部数据来自 `GET /api/v1/dashboard`；不单独请求健康状态。

**Endpoint**

- 列表：`Table` 列名称、地址、认证方式、默认 `Tag`、启用 `Switch`/`Tag`、Task 数、最近测试结果、操作。
- 表单：`Form` 分组基础/连接；`auth_type` 切换时显示/隐藏 username/password；编辑时密码留空表示保持；`Input.Password` 不显示已存值。
- 测试连接：按钮触发 `POST /api/v1/endpoints/test`，结果用 `Alert`（success/error/warning）展示；不阻塞保存。
- 删除/设默认：`Modal.confirm`；删除失败展示后端 `error.message`。

**Task**

- 列表：`Table` + 筛选栏（状态/Endpoint/调度类型/最近执行状态/标签）；列名称、Endpoint、工作目录、模型、调度摘要、下一次执行、最近 Run。
- 表单：`Card` 分组基础/执行目标/Prompt/调度/策略；`Form.Item` 规则：
  - 名称必填、Prompt 必填（只校验 `trim()` 非空，提交原文）。
  - Endpoint 必选（新建只列启用项）；工作目录必填。
  - Provider/Model 必填；`ModelSelect` 优先用 `/options`，失败时 `Input` 手输。
  - 调度类型 `cron/once/interval/none`；切换时显示对应字段；**不显示时区选择**，只读提示“所有时间按 UTC+08:00 解释”。
  - `once` 用 `DatePicker` + `TimePicker`，按 UTC+8 解释后提交 ISO；`interval` 最小 60 秒；`timeout` 1..10080。
  - 保存前 `SchedulePreview` 展示未来 5 次；服务端校验失败把 `details` 映射到字段。
- 详情：摘要、调度、最近 Run、复制/启用/停用/归档/立即执行按钮；归档后立即执行禁用。

**Run 历史**

- `Table` + 筛选栏：Task、Endpoint、状态、来源、时间范围（`RangePicker`）、模型；服务端分页。
- 列：Task、状态、Endpoint、来源、开始/结束、耗时、轨迹完整性、详情。
- 行点击进入 `/runs/:id`。

**Run 详情**

- 顶部 `RunSummary`：`Descriptions` 展示 Task/状态/来源/Endpoint/工作目录/Provider/模型/Agent/开始/结束/总耗时/队列等待；操作按钮取消/重新执行。
- `Alert`：错误摘要（失败阶段/类型/消息/是否可 Rerun）或轨迹完整性提示。
- Prompt：`Input.TextArea` 只读或 `<pre>`，展示 `run.prompt`（快照）。
- 权限：`PermissionModal` 或顶部 `Alert` + 按钮；有待处理权限时置顶。
- `TraceView`：时间线/层级切换、分页、Tool 输入输出、Skill、文件、错误。
- 最终结果：`<pre>` 展示 `final_response`；为空显示精确文案“本次执行没有可用的最终回复。”；标注“来源：最后一条 Assistant 文本”。
- 消耗：`Descriptions` 展示 tokens/cost/cache；缺失显示“未返回”。
- 配置快照：`Collapse` + `<pre>{JSON.stringify(snapshot,null,2)}</pre>`。
- 日志：`LogsPanel` 表格/列表，运行中 2s 刷新，终态停止。
- 子 Session：可选 `Collapse` 列表（若后端返回）。

### 10.5 数据获取与缓存

- `QueryClient` 默认：`retry: 1`、`refetchOnWindowFocus: false`、`staleTime: 5000`。
- Query key 规范：
  - `['meta']`
  - `['dashboard']`
  - `['endpoints', filters]` / `['endpoint', id]`
  - `['tasks', filters]` / `['task', id]`
  - `['runs', filters]` / `['run', id]` / `['run', id, 'trace']` / `['run', id, 'logs']`
  - `['options', endpointId, workingDirectory]`
- 运行中的 Run 详情：
  - `useQuery({queryKey:['run', id], queryFn, refetchInterval: (q) => isActive(q.state.data?.run.status) ? 2000 : false})`
  - 同样对 `trace` / `logs` 设置 2s；终态自动停止。
  - `refetchIntervalInBackground` 默认 false，浏览器标签页隐藏时暂停轮询。
- Mutation 成功后 `queryClient.invalidateQueries` 对应列表/详情；删除/归档后跳转或关闭弹窗。
- API client：
  - `fetch` + `AbortController`；`Content-Type: application/json`。
  - 非 2xx 解析 `{error}` 抛 `ApiError(status, code, message, details)`。
  - 422 `details` 由表单 `setFields` 使用；其他错误 `message.error` / `notification.error`。
- 不做全局 Redux；服务端状态归 TanStack Query，UI 状态用组件 state。

### 10.6 表单与校验

- AntD `Form` + `rules`；提交前 `form.validateFields()`。
- 服务端是最终校验权威；前端规则只做即时提示，不复制业务规则。
- Prompt：`Input.TextArea` 保留换行/空格；提交前不 `trim`；仅校验 `trim()` 非空。
- 密码：`Input.Password`；编辑时空白表示保持，`has_password` 控制 placeholder；不把密码写入任何前端状态持久化。
- 时间：`DatePicker`/`TimePicker` 返回 dayjs；按全局 UTC+8 组装带 `+08:00` 的 ISO 字符串提交；不使用浏览器本地时区。
- 危险操作：`Modal.confirm`；按钮 loading 防重复提交。
- 失败：字段级 `details` → `form.setFields`；顶部 `Alert` 展示 `message`。

### 10.7 时间展示（固定 UTC+8）

- `dayjs.extend(utc)`；`dayjs.locale('zh-cn')`；**不引入 timezone 插件**。
- `TimeText` 组件接收 ISO 与偏移（Run 用 `run.utc_offset` 快照，其他用 `meta.utc_offset`）：
  - 文本：`dayjs.utc(iso).utcOffset(offset).format('YYYY-MM-DD HH:mm:ss')`；
  - 标签：显示对应偏移，如 `UTC+08:00`；
  - `title` 显示 UTC ISO。
- 不再显示“你的本地时间”，也不做浏览器时区换算；所有人看到同一时间。
- 调度预览只有一列“执行时间（UTC+08:00）”。
- Run 列表、Run 详情、日志时间全部按 UTC+8 展示。

### 10.8 轨迹渲染

- `TraceView` 支持 `Segmented` 切换“时间线/层级”：
  - 时间线：AntD `Timeline`，按 `started_at || created_at` 排序。
  - 层级：`Collapse`/嵌套列表，Session → message → tool；Skill 与无法确定父级的 Tool 挂在 Session 下，不强行归类。
- `TraceItem`：
  - `Tag` 显示状态（pending/running/completed/failed/rejected/info）。
  - `Descriptions` 显示时间、耗时、Tool 名称、父消息。
  - 输入/输出/错误用 `<pre>` + `Collapse` 展开；JSON 用 `JSON.stringify(..., null, 2)`。
  - 文件：状态 `added/modified/deleted`、additions/deletions、`DiffView`。
  - 权限：action/resources/source/message + 回复按钮。
- `DiffView`：按行拆分 patch，`+` 绿、`-` 红、上下文灰；`<pre>` 渲染，不注入 HTML。
- 分页：前端每页 100 条（`Pagination`），避免一次渲染 500+ 条目；实时轮询只刷新当前页数据。
- **安全**：不使用 `dangerouslySetInnerHTML`；不渲染 Markdown/HTML；模型输出、Tool 输出、Prompt、错误全部按文本渲染。
- 不展示 reasoning/thinking；不根据 Prompt 推断 Skill/文件。

### 10.9 运行中刷新

- Run 详情页的 `run` / `trace` / `logs` 查询在 Run 活动时 2s 轮询，终态停止。
- 页面隐藏时暂停（TanStack Query 默认 `refetchIntervalInBackground:false`）；重新可见时立即刷新一次。
- 轮询失败：保留上次数据，显示 `Alert`/`message`；不把 UI 状态改成 Run 失败。
- 关闭/刷新页面不影响后台执行；重新打开从 API 读取最新状态。

### 10.10 权限交互

- 有待处理权限时，Run 详情顶部显示 `Alert` + “处理权限”按钮，打开 `PermissionModal`。
- Modal 展示 action/resources/source/message；按钮 Allow once / Always / Reject；Reject 可填原因。
- 提交调用 `POST /api/v1/runs/{id}/permissions/{request_id}/reply`；成功后 invalidate `['run', id]`、`['run',id,'trace']`；失败显示后端错误。
- 不自动批准；不提供“一键全部批准”。

### 10.11 安全与可访问性

- React 默认转义；禁止 `dangerouslySetInnerHTML`；所有动态文本用 `{}` 插值或 `<pre>`。
- AntD `Form.Item` 有 `label`；按钮有可读文字/`aria-label`；键盘可操作 Modal/Dropdown。
- 状态/错误不只靠颜色；`Tag`/`Alert` 带文字。
- 不在 localStorage/sessionStorage 存密码、Prompt、Token；只存无敏感 UI 偏好（可选）。
- 前端不直接请求 OpenCode；所有请求经 `/api/v1` 后端代理。

### 10.12 前端测试与构建

- `pnpm typecheck`（`tsc --noEmit`）必须通过。
- `pnpm build` 必须产出 `dist/index.html` 与带 hash 的 assets。
- `pnpm test`（Vitest + Testing Library）覆盖：
  - `api/client.ts` 错误解析/422 details；
  - `utils/time.ts` UTC → UTC+8 格式化；
  - `StatusTag`、`TraceView` 空/有数据/失败状态；
  - `ScheduleForm` 类型切换与校验。
- 可选 Playwright E2E 不纳入默认门禁；真实后端联调时手工冒烟。
- AntD 按 ES module 引入，确保 tree-shaking；不引入 `moment`（用 dayjs）。

## 11. 目录结构与代码组织

```text
app/workflow-scheduler/
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini                        # asyncio_mode=auto, testpaths=tests
├── .env.example
├── .gitignore                        # data/, __pycache__, .venv, frontend/node_modules, frontend/dist
├── README.md
├── specs/
│   ├── PromptOps_Console_PRD_v1.0.md
│   ├── SPEC.md                     # 本文档
│   └── TASKS.md                    # 47 个实施任务
├── promptops/
│   ├── __init__.py
│   ├── __main__.py                 # python -m promptops serve
│   ├── main.py                     # FastAPI app + lifespan
│   ├── config.py                   # pydantic-settings
│   ├── logging.py                  # JSON formatter / redaction
│   ├── db.py                       # engine, session factory, PRAGMA
│   ├── models.py                   # SQLAlchemy ORM
│   ├── enums.py                    # 状态/枚举常量
│   ├── security.py                 # Fernet secret box
│   ├── timeutil.py                 # UTC ms / UTC+8 offset / formatting
│   ├── domain/
│   │   ├── schedule.py             # next_occurrence / preview / fixed offset
│   │   ├── state_machine.py        # Run 状态迁移
│   │   ├── snapshots.py            # Run 快照构建
│   │   └── trace.py                # 规范化条目数据结构
│   ├── repositories/
│   │   ├── endpoints.py
│   │   ├── tasks.py
│   │   ├── runs.py
│   │   ├── logs.py
│   │   └── trace.py
│   ├── services/
│   │   ├── endpoint_service.py
│   │   ├── task_service.py
│   │   ├── run_service.py          # 手动执行/取消/Rerun/权限回复
│   │   ├── dashboard_service.py
│   │   └── recovery_service.py
│   ├── opencode/
│   │   ├── client.py               # OpenCodeV2Client
│   │   ├── errors.py
│   │   ├── sse.py                  # SSE 解析
│   │   ├── events.py               # 事件 → 规范化动作
│   │   └── stream.py               # EventStreamSupervisor
│   ├── scheduler/
│   │   └── engine.py
│   ├── dispatcher/
│   │   └── pool.py
│   ├── executor/
│   │   ├── run_executor.py
│   │   ├── handles.py              # RunHandle registry
│   │   ├── finalizer.py
│   │   └── sweeper.py
│   ├── trace/
│   │   └── ingestor.py
│   ├── api/
│   │   ├── routes_meta.py
│   │   ├── routes_dashboard.py
│   │   ├── routes_endpoints.py
│   │   ├── routes_tasks.py
│   │   ├── routes_runs.py
│   │   ├── schemas.py              # Pydantic 请求/响应
│   │   ├── errors.py               # 错误 envelope / 异常映射
│   │   └── dependencies.py
│   └── web/
│       └── spa.py                  # frontend/dist + SPA fallback
├── frontend/
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── api/
│   │   │   ├── client.ts
│   │   │   ├── types.ts
│   │   │   └── endpoints.ts
│   │   ├── hooks/
│   │   ├── pages/
│   │   ├── components/
│   │   ├── utils/
│   │   └── styles.css
│   └── dist/                       # pnpm build 产物，gitignored
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
├── tests/
│   ├── conftest.py
│   ├── unit/
│   ├── integration/
│   └── functional/
└── data/                            # gitignored
    ├── promptops.db
    ├── secret.key
    └── logs/
```

**依赖方向**：`api → services → repositories/domain`；`executor/scheduler → opencode + repositories + domain`；`opencode` 不依赖 `api`；`domain` 不依赖 ORM/FastAPI；`web/spa.py` 只依赖静态文件路径与设置。前端 `frontend/` 只通过 HTTP 访问 `/api/v1`，不 import 后端代码。禁止反向 import。

**命名**：状态/枚举用大写常量（`RunStatus.RUNNING`），DB 存小写；所有时间字段以 `_at` 结尾；所有外部 ID 字段以 `_id` 结尾。

---

## 12. 配置与环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `PROMPTOPS_HOST` | `127.0.0.1` | 监听地址；除非在受信网络，不要改 `0.0.0.0` |
| `PROMPTOPS_PORT` | `8787` | 监听端口 |
| `PROMPTOPS_DATA_DIR` | `./data` | 数据目录 |
| `PROMPTOPS_DATABASE_URL` | `sqlite+aiosqlite:///./data/promptops.db` | 默认按 data dir 解析 |
| `PROMPTOPS_SECRET_KEY` | 空 | Fernet key（urlsafe base64 32 bytes）；空则生成 `data/secret.key` |
| `PROMPTOPS_AUTO_MIGRATE` | `true` | 启动时执行 Alembic |
| `PROMPTOPS_UTC_OFFSET` | `+08:00` | 全局固定偏移；所有调度/展示按此解释；格式 `±HH:MM`；默认东八区 |
| `PROMPTOPS_MAX_CONCURRENT_RUNS` | `2` | 并发执行 Run 数 |
| `PROMPTOPS_SCHEDULER_TICK_SECONDS` | `1` | 调度 tick |
| `PROMPTOPS_MISSED_GRACE_SECONDS` | `300` | 超过该延迟按 missed 策略 |
| `PROMPTOPS_CANCEL_CONFIRM_SECONDS` | `30` | 取消/超时确认窗口 |
| `PROMPTOPS_RUN_HEARTBEAT_SECONDS` | `10` | 活动 Run 心跳 |
| `PROMPTOPS_STALE_RUN_SECONDS` | `300` | 心跳丢失警戒 |
| `PROMPTOPS_SSE_STALE_SECONDS` | `10` | 无事件后启动轮询兜底 |
| `PROMPTOPS_SSE_RECONNECT_BASE_MS` | `1000` | SSE 重连基数 |
| `PROMPTOPS_SSE_RECONNECT_MAX_MS` | `30000` | SSE 重连上限 |
| `PROMPTOPS_HTTP_CONNECT_TIMEOUT_SECONDS` | `5` | 连接超时 |
| `PROMPTOPS_HTTP_READ_TIMEOUT_SECONDS` | `30` | 普通请求读超时 |
| `PROMPTOPS_PROMPT_READ_TIMEOUT_SECONDS` | `60` | Prompt POST 读超时 |
| `PROMPTOPS_MAX_TRACE_TEXT_BYTES` | `262144` | 单条文本上限 |
| `PROMPTOPS_MAX_MESSAGE_PAGES` | `20` | 消息分页上限 |
| `PROMPTOPS_SHUTDOWN_GRACE_SECONDS` | `20` | 优雅关闭等待 |
| `PROMPTOPS_LOG_LEVEL` | `INFO` | 日志级别 |
| `PROMPTOPS_LOG_DIR` | `data/logs` | 日志目录 |
| `PROMPTOPS_FRONTEND_DIST` | `./frontend/dist` | SPA 构建产物目录；不存在时 `/` 返回构建提示，API 仍可用 |
| `PROMPTOPS_CORS_ORIGINS` | 空 | 逗号分隔的允许来源；仅前后端分离开发/部署时设置，生产同源默认空 |
| `PROMPTOPS_DEFAULT_ENDPOINT_NAME` | 空 | 首次启动 seed 默认 Endpoint 的名称 |
| `PROMPTOPS_DEFAULT_ENDPOINT_URL` | 空 | seed 地址 |
| `PROMPTOPS_DEFAULT_ENDPOINT_USERNAME` | `opencode` | seed Basic 用户名 |
| `PROMPTOPS_DEFAULT_ENDPOINT_PASSWORD` | 空 | seed Basic 密码；不写入日志 |

seed 规则：数据库没有任何 Endpoint 且 `PROMPTOPS_DEFAULT_ENDPOINT_URL` 非空时，创建默认 Endpoint。若已有 Endpoint，忽略 seed。

时区规则：不提供 per-task 时区；`PROMPTOPS_UTC_OFFSET` 只接受 `+HH:MM` / `-HH:MM`，默认 `+08:00`。修改后重启生效，只影响未来 `next_run_at`；历史 Run 使用 `runs.utc_offset` 快照。

`.env.example` 只放占位符，不放真实密码；文档说明生产环境用环境变量或密钥管理注入。

---

## 13. 安全、可靠性与运维

### 13.1 安全

| 事项 | 措施 |
|---|---|
| Endpoint 密码 | Fernet 加密；API/UI 不回显；编辑留空保持不变；日志脱敏 |
| 密钥 | `PROMPTOPS_SECRET_KEY` 或 `data/secret.key`；文件权限尽量 0600；不提交仓库 |
| 认证头 | 只在 httpx 请求中构造；不写日志；异常消息中不含 header |
| 应用访问 | MVP 无登录；默认 `127.0.0.1`；远程部署放在带认证的反向代理后；README 警告 |
| XSS | React 默认转义；模型/Prompt/Tool 输出用 `<pre>`/文本节点；禁止 `dangerouslySetInnerHTML`；不渲染 Markdown/HTML |
| SQL 注入 | SQLAlchemy 参数化；标签筛选用绑定参数 |
| SSRF | Endpoint 地址由管理员配置；本系统不抓取任意 URL；只访问配置的 Endpoint |
| 路径 | 不读取本地/远程文件；`working_directory` 只传递给 OpenCode |
| CSRF | API 不使用 Cookie；生产同源；开发用 Vite proxy；如独立域名部署，只允许 `PROMPTOPS_CORS_ORIGINS` 中的来源 |
| CORS | 默认关闭；仅开发/独立前端域名时按白名单开启，不使用 `*` |
| 静态资源 | `dist/assets` 带 hash 长缓存；`index.html` no-cache；`/api/*` 不参与 SPA fallback |
| 依赖 | 固定最低版本；定期升级；不引入不必要的依赖 |
| 审计 | RunLog + trace_items 保留执行事实；不记录密码 |

### 13.2 可靠性

- SQLite WAL + `busy_timeout`；单写者，写事务短。
- 每个状态迁移先落库；HTTP 调用不持有事务。
- 唯一约束 + 条件更新保证 exactly-once 与终态不可逆。
- 启动 Recovery 对账，不重发 Prompt。
- SSE 断线重连 + 轮询兜底 + 消息对账。
- 取消/超时确认窗口，未确认不谎报 Cancelled/Timeout。
- 优雅关闭不把活动 Run 标失败。
- 时钟：依赖系统 NTP；调度用 UTC；时钟回拨时 missed 策略处理。
- 磁盘：trace 文本有上限；无自动清理（MVP）；文档建议定期备份/归档。

### 13.3 日志

- 应用日志 JSON 行：`ts`、`level`、`logger`、`message`、`run_id`、`task_id`、`endpoint_id`、`phase`。
- 输出到 stdout 和 `data/logs/app.log`（RotatingFileHandler，10MB × 5）。
- 脱敏规则：`password`、`secret`、`authorization`、`token`、`api_key` 字段一律替换为 `***`；URL 中的 userinfo 去掉。
- RunLog 是人类可读的执行日志；与结构化应用日志分开。
- 不记录完整 Prompt 到应用日志；Prompt 在 Run 详情按设计展示。

### 13.4 备份与迁移

- SQLite 备份：`sqlite3 data/promptops.db ".backup 'backup.db'"` 或 `VACUUM INTO`；不要直接复制正在写的 WAL 文件。
- 长期运行后可在低峰期执行 `VACUUM` 回收空间；不要在高频写入/执行高峰执行。
- 升级前备份；Alembic 迁移失败则拒绝启动。
- `data/secret.key` 必须与数据库一起备份；丢失则 Endpoint 密码无法解密，需要重新输入。
- `frontend/dist` 可由源码 + lockfile 重建，不需要备份；发布时记录前端版本/commit。
- 密钥轮换不在 MVP；如需轮换，必须提供离线迁移脚本：解密所有 Endpoint 密码 → 用新密钥重新加密。不要直接替换密钥文件。
- 迁移到 PostgreSQL 不在 MVP；数据模型已避免 SQLite 特有类型（除部分索引/JSON1）。

### 13.5 部署

**构建前端（部署/升级前必须执行）**

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm typecheck
pnpm build              # 产出 frontend/dist
```

FastAPI 启动时检查 `frontend/dist/index.html`；缺失时 `/` 返回构建提示，但 `/api/v1` 仍可用。生产环境把 `frontend/dist` 与后端一起发布；不要在生产机跑 `vite dev`。

**Linux（systemd 示例）**

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

**Windows**

```powershell
python -m promptops serve
```

或用 `nssm`/任务计划程序注册为服务。必须单实例；不要开多个进程。开发时不要用 `uvicorn --reload` 跑真实任务：reload 会重启进程并中断正在执行的 Run；恢复机制能兜底，但会打断执行。生产固定 `workers=1`。

**开发模式**：

```bash
# 终端 1：后端
python -m promptops serve

# 终端 2：前端
cd frontend && pnpm dev   # Vite 5173，代理 /api、/healthz 到 127.0.0.1:8787
```

**反向代理**：如需局域网访问，Nginx/Caddy 终止 TLS 并加 Basic Auth/OIDC；应用仍绑定 `127.0.0.1`。可以让 Nginx 直接服务 `frontend/dist` 并把 `/api`、`/healthz` 代理到 FastAPI；也可以全部由 FastAPI 同源提供，二选一，不要两边各配一套。

---

## 14. 测试策略

### 14.1 单元测试（不依赖外部服务）

| 文件 | 覆盖 |
|---|---|
| `tests/unit/test_schedule.py` | 固定 UTC+8 偏移、cron 下一次、interval、once、预览、非法 cron、过期 once |
| `tests/unit/test_state_machine.py` | 允许/禁止迁移；终态不可逆；Cancelling 确认规则 |
| `tests/unit/test_scheduler_exactly_once.py` | 同一 occurrence 两次 tick 只有一条 Run；唯一冲突；next_run_at 推进 |
| `tests/unit/test_scheduler_overlap.py` | queue/skip；手动/Rerun；FIFO |
| `tests/unit/test_scheduler_missed.py` | skip/run_once；missed_count；one-off 消费；Endpoint 停用 |
| `tests/unit/test_snapshots.py` | 快照字段完整；Task 修改不改 Run；Endpoint 修改不改历史 |
| `tests/unit/test_terminal_mapping.py` | succeeded/failed/interrupted + cancel/timeout → 状态 |
| `tests/unit/test_endpoint_test.py` | 成功/401/连接失败/404 v1/HTML/5xx/超时 分类 |
| `tests/unit/test_trace_normalization.py` | 事件 → 条目；Tool 状态；Skill；权限；文件；去重；截断 |
| `tests/unit/test_final_response.py` | 最后 assistant 文本；只有 tool；无文本 → NULL |
| `tests/unit/test_security.py` | Fernet 加解密；日志脱敏；API/UI 不回显密码 |
| `tests/unit/test_sse_parser.py` | 多行 data、`event:` 行、heartbeat、注释、半包、非法 JSON |
| `tests/unit/test_recovery.py` | 无 session/有 session/404/成功/失败/中断；不重发 |

### 14.2 集成测试（Fake OpenCode v2）

用 FastAPI 写一个 `FakeOpenCodeServer`，通过 `httpx.MockTransport` 或 ASGI transport 接入：

| 端点 | 行为 |
|---|---|
| `GET /api/info` | 返回 `{version:"2.0.29"}`；可配置 401/500/HTML |
| `POST /api/session` | 返回 `{data:{id:"ses_fake", ...}}`；可延迟 |
| `POST /api/session/{id}/prompt` | 返回 200；可配置连接中断/超时/409 |
| `GET /api/session/{id}` | 按脚本返回活动/成功/失败/中断 |
| `GET /api/session/{id}/message` | 返回分页消息（user/assistant/tool/skill/idle） |
| `GET /api/session/{id}/diff` | 返回 `{data:[FileDiff]}` |
| `POST /api/session/{id}/interrupt` | 返回 `{interrupted:true/false}` |
| `POST .../permission/{rid}/reply` | 204；记录 decision |
| `GET /api/event` | 流式发送预置事件序列；可模拟断开 |
| `GET /api/model` / `/api/agent` | 返回候选 |

集成用例：

1. 调度 → 执行 → Completed：Run 快照、Session 关联、trace items、final response、tokens/cost。
2. Prompt 连接中断 → 对账找到用户消息 → 继续 Running；找不到 → Unknown。
3. Endpoint 401 → Failed(auth_failed)，不切换。
4. SSE 断开 → gap；重连/轮询 → Completed；trace_integrity=gap。
5. 权限请求 → Waiting → reply once → Running → Completed；条目状态正确。
6. 取消 Running → Cancelling → interrupted → Cancelled；未确认 → Unknown。
7. 超时 → Cancelling → interrupted → Timeout。
8. 进程重启恢复：预置 Running + fake session outcome → 启动后 Completed；无 session → Failed/Unknown。
9. 重叠 queue：两个 scheduled 触发 → 两个 Run，第二个等第一个结束。
10. 重叠 skip：第二个 Skipped，error_type=overlap。
11. 一次性触发后 schedule_enabled=false，next_run_at=NULL。
12. Endpoint 停用 → 定时触发 Skipped(endpoint_disabled)。

### 14.3 API 契约测试与前端测试

**后端 API 契约**（pytest + `httpx.ASGITransport` + 临时 SQLite）：

- 每个 `/api/v1` 资源至少覆盖：列表分页、详情 404、创建/更新 422、冲突 409、成功响应字段。
- 断言错误 envelope 的 `error.code/message/details`；422 的 `details` 可直接映射到 AntD Form。
- 断言 Endpoint 密码/Authorization 不出现在任何响应；`has_password` 正确。
- 断言 Run 详情/轨迹/日志的 JSON 字段与 `frontend/src/api/types.ts` 对齐（可用 Pydantic schema 导出 JSON Schema 做快照）。
- 断言 SPA fallback：`GET /tasks/123` 返回 `index.html`；`GET /api/v1/unknown` 返回 JSON 404；`/healthz` 返回 JSON。
- 可选 Playwright E2E 不纳入默认 CI；需要真实浏览器时单独标记 `@pytest.mark.e2e`。

**前端**（Vitest + Testing Library + jsdom）：

- `pnpm typecheck` 必须通过；`pnpm build` 必须成功。
- `src/api/client.ts`：2xx 解析、错误 envelope、网络错误、AbortSignal。
- `src/utils/time.ts`：UTC → UTC+8 格式化；偏移解析。
- `StatusTag`：12 个 Run 状态都有中文标签与颜色。
- `TraceView`：空轨迹、Tool 失败、权限条目、文件 diff、完整性提示。
- `ScheduleForm`：类型切换、cron/once/interval 校验、预览请求参数。
- 前端测试 mock `fetch`，不依赖真实后端；不把密码写进测试快照。

### 14.4 测试数据与清理

- 每个测试用独立临时 SQLite 文件；`tmp_path` fixture。
- 时间用可注入的 `Clock`（`now_ms()`）避免 `sleep`。
- Fake server 的状态用脚本队列；测试结束关闭所有任务。
- 不访问真实 OpenCode、不发送真实 Prompt；live 测试单独标记 `@pytest.mark.live`，默认跳过。

### 14.5 验收前必须通过

- `pytest tests/unit tests/integration` 全绿。
- `cd frontend && pnpm typecheck && pnpm build && pnpm test` 全绿。
- 至少一个“重启恢复”集成用例。
- 至少一个“exactly-once 并发”用例。
- 至少一个“取消未确认 → Unknown”用例。
- 手动冒烟：真实 OpenCode v2 Endpoint 建 Task、手动执行、看轨迹、取消、Rerun；前端 dev proxy 与生产 `dist` 两种模式都能打开。

---

## 15. 实施计划与任务拆分

完整任务清单已拆分为独立文件：[TASKS.md](./TASKS.md)。任务依赖、验收标准、勾选状态和 Definition of Done 均以 TASKS.md 为准；本节只保留阶段总览，避免 SPEC 与 TASKS 双份维护。

| Phase | 目标 | 任务 |
|---|---|---|
| 0 | 工程骨架 | T0.1–T0.6 |
| 1 | 领域基础 | T1.1–T1.5 |
| 2 | Endpoint 管理 | T2.1–T2.4 |
| 3 | Task 管理 | T3.1–T3.6 |
| 4 | 调度引擎 | T4.1–T4.5 |
| 5 | OpenCode 适配与执行 | T5.1–T5.9 |
| 6 | React UI 与查询 | T6.1–T6.6 |
| 7 | 加固与验收 | T7.1–T7.6 |

> 实施时同步维护 `PLAN.md`（文件落点/架构决策）与 `TASKS.md`（勾选进度）。按仓库约定，三件套必须一致；任务细节以 TASKS.md 为准。

---

## 16. PRD 需求追踪矩阵

下表把 PRD 要求映射到设计章节与任务 ID；任务详情、依赖和完成状态见 [TASKS.md](./TASKS.md)。

| PRD 章节 | 关键要求 | 本方案落点 | 任务 |
|---|---|---|---|
| 7.1.1 | Endpoint 列表字段、Task 计数、不展示实时状态 | 8.1.7 | T2.3 |
| 7.1.2 | 创建 Endpoint、无认证/Basic | 8.1.1、7.2 | T2.1/T2.3 |
| 7.1.3 | 测试连接分类 | 8.1.2、7.3 | T2.2 |
| 7.1.4 | 默认 Endpoint、新建 Task 自动选中 | 8.1.3 | T2.1/T3.5 |
| 7.1.5 | 编辑只影响之后执行 | 8.1.4、ADR-06 | T2.1 |
| 7.1.6 | 停用约束、定时触发记录 | 8.1.5、8.3.2 | T2.1/T4.1 |
| 7.1.7 | 删除约束、历史不丢 | 8.1.6 | T2.1 |
| 7.2.1 | Task 列表字段与筛选 | 8.2、9.5、10.4 | T3.5 |
| 7.2.2 | 创建 Task 的完整配置 | 8.2.1 | T3.1/T3.5 |
| 7.2.3 | Task 示例对应的字段 | 6.3、6.4 | T1.3 |
| 7.2.4 | 四种调度类型 | 5.5、8.3.6 | T1.2/T4.4 |
| 7.2.5 | 调度预览、UTC+8 展示 | 8.2.7、10.7 | T3.3 |
| 7.2.6 | 编辑只影响新 Run | ADR-06、6.4 | T3.1 |
| 7.2.7 | 启用/停用行为 | 8.2.3 | T3.2 |
| 7.2.8 | 归档/恢复 | 8.2.4 | T3.2 |
| 7.2.9 | 复制默认不启用调度 | 8.2.5 | T3.2 |
| 7.2.10 | 立即执行、不改下次时间、遵守重叠 | 8.2.9、8.3.4 | T3.2/T4.2 |
| 7.3.1 | 自动触发、每个时刻最多一个 Run | 8.3.2、8.3.3 | T4.1/T4.5 |
| 7.3.2 | per-task 时区（MVP 简化为全局 UTC+8） | 8.3.7、8.2.6、17.2 | T1.2/T4.5 |
| 7.3.3 | Queue/Skip 重叠、不得静默丢弃 | 8.3.4 | T4.2 |
| 7.3.4 | 错过 Skip/Run once | 8.3.5 | T4.3 |
| 7.3.5 | Endpoint 不可用 Failed、不切换 | 8.4.3、8.1.5、ADR-01 | T5.5 |
| 7.4.1 | Run 来源四种 | 5.2、6.4 | T4.1/T3.2 |
| 7.4.2 | 12 个用户可见状态 | 5.2、5.3 | T1.1 |
| 7.4.3 | Run 配置快照 | ADR-06、6.4、8.4.8 | T1.3/T3.1 |
| 7.4.4 | Run 日志阶段 | 8.4.2 | T5.5 |
| 7.4.5 | 取消三态、不能提前显示 Cancelled | 8.4.5、7.10 | T5.7 |
| 7.4.6 | 超时、确认后 Timeout/Unknown | 8.4.6 | T5.7 |
| 7.4.7 | 历史重新执行、Endpoint 不可用改选 | 8.2.10 | T3.2 |
| 7.5.1 | 轨迹内容 | 8.5.1 | T5.3 |
| 7.5.2 | Tool 字段与状态 | 8.5.1、7.11 | T5.3 |
| 7.5.3 | 只在明确调用时显示 Skill | 8.5.1、7.11 | T5.3 |
| 7.5.4 | 文件变化、不按 Tool 名推断 | 7.8、8.5.1 | T5.3 |
| 7.5.5 | 轨迹完整性四态 | 8.5.5 | T5.3/T5.6 |
| 7.5.6 | 时间线视图 | 8.5.1、10.8 | T6.2 |
| 7.5.7 | 调用层级视图、不强行归类 | 8.5.1 | T6.2 |
| 7.6.1 | 执行摘要 | 8.6.1 | T6.1 |
| 7.6.2 | 实际 Prompt | 8.6.1 | T6.1 |
| 7.6.3 | 实时轨迹、关页不影响后台 | 8.5.2、10.9 | T6.2 |
| 7.6.4 | 最终结果、固定空文案 | 8.5.3 | T5.6/T6.1 |
| 7.6.5 | 错误信息 | 8.4.4、附录 B | T5.5/T6.1 |
| 7.6.6 | 消耗信息、不估算 | 8.5.4 | T5.6/T6.1 |
| 7.7.1 | 历史列表字段 | 8.6.2 | T6.4 |
| 7.7.2 | 历史筛选 | 9.5、8.6.2、10.4 | T6.4 |
| 7.7.3 | 历史操作 | 8.6.1、8.2.10 | T6.3 |
| 7.8.1 | Endpoint 概览 | 8.6.3 | T6.5 |
| 7.8.2 | Task 概览 | 8.6.3 | T6.5 |
| 7.8.3 | Run 概览 | 8.6.3 | T6.5 |
| 7.8.4 | 最近执行 | 8.6.3 | T6.5 |
| 7.8.5 | 最近失败（含端点连接失败） | 8.6.3 | T6.5 |
| 8.1 | Task 不绑定 Skill | 8.2.1、ADR-01 | T3.1 |
| 8.2 | Run 与 Task 当前配置隔离 | ADR-06、5.6 | T1.3/T3.1 |
| 8.3 | 默认 Endpoint 规则 | 8.1.3 | T2.1 |
| 8.4 | Endpoint 失败不自动转移 | 8.4.3、ADR-01 | T5.5 |
| 8.5 | 执行结束不等于业务正确 | 5.6、8.4.4、8.5.3 | T5.6/T6.1 |
| 8.6 | Tool 成功不等于 Run 完成 | 8.4.4、8.5.1 | T5.6 |
| 8.7 | 不自动重发状态不明 Prompt | ADR-10、7.6 | T5.5 |
| 10.1 | MVP 必须包含 | 全文 | 全部 |
| 10.2 | MVP 不包含 | 1.3、17 | — |
| 11.1-11.7 | 验收场景 | 14.2、T7.5 | T7.5 |
| 12.1-12.15 | 成功标准 | 18 | T7.5 |

---

## 17. 风险、限制与待确认项

### 17.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| OpenCode v2 API 标注 experimental，字段可能变化 | 适配层解析失败、轨迹缺失 | 适配层隔离；未知事件忽略；终态用 `/api/session` 的 `outcome` 兜底；锁定实测版本；升级前跑集成测试 |
| 目标环境实际是 v1 | 无法连接 | 测试连接明确报“v1 不支持”；实施前确认部署版本；v1 适配器不在 MVP |
| 定时任务停在 Waiting 直到超时 | 自动化中断 | Dashboard 显示 Waiting；Run 详情可审批；文档明确不自动批准；未来可加 Task 级策略 |
| 远程工作目录不存在/无权限 | Run 在 Session/Prompt 阶段失败 | 错误如实展示；不猜测路径；文档要求填写 OpenCode 主机路径 |
| 固定偏移不支持 DST/跨时区 | 非东八区或 DST 地区时间不准确 | 全局 `+08:00` 是明确限制；如未来需要 IANA/DST，再引入 `zoneinfo` 并单独立项 |
| SQLite 单写者/误开多 worker | 重复调度/锁等待 | 强制 `workers=1`；WAL + busy_timeout；唯一约束兜底；未来迁 PostgreSQL |
| 无应用登录 | 本机/内网可操作 | 默认 `127.0.0.1`；远程加反向代理认证；文档警告 |
| Queue 队列无限增长 | 磁盘/执行堆积 | Dashboard 显示 Queued；文档提示；未来可加最大队列深度（需产品确认） |
| SSE 不保证重放 | 轨迹缺口 | 断线对账消息；`trace_integrity=gap/incomplete`；不谎报完整 |
| Trace 文本过大 | DB 膨胀/React 页面卡顿 | 单条上限 + 截断标记；列表只展示摘要；前端分页；未来加保留策略 |
| 时钟漂移/回拨 | 调度偏移 | NTP；UTC 存储；missed 策略；不依赖本地时区 |
| 模型发现依赖 Endpoint 可达 | 表单无法选择模型 | 保留手输 provider/model；发现失败不阻塞保存 |
| 前端构建/发布遗漏 | 页面打不开/旧版本 | 部署清单强制 `pnpm build`；启动检查 `dist/index.html`；`/healthz` 返回 `frontend_built` |
| API 契约漂移（Pydantic vs TS） | 前端运行时字段错误 | `frontend/src/api/types.ts` 与 Pydantic schema 对齐；契约测试覆盖关键响应；变更同一 PR 更新两端 |
| AntD/React 版本不兼容 | 构建失败或组件异常 | 固定 React 18 + AntD 5；锁定 lockfile；不使用 React 19 兼容补丁 |
| SPA fallback 吞掉 API 404 | API 错误被 HTML 响应掩盖 | `/api/*`、`/healthz` 先注册；契约测试断言 JSON 404；static 只挂 `/assets` |
| 前端包体积过大 | 首屏慢 | AntD ES module + tree-shaking；不用 moment/全量图标；按需引入组件 |

### 17.2 设计决定（需要产品确认）

以下不是 PRD 明文规定，而是实现必须选择的点；本文已给出默认行为：

1. **默认 Endpoint 不能停用**，必须先设另一个默认。理由：否则“新建 Task 自动选中默认”会选中一个不可用端点。
2. **归档 Task 允许 Rerun 历史 Run**。理由：归档只禁止“直接手动执行”和自动调度；历史排障仍应可重放。
3. **停用 Endpoint 时，该 Endpoint 上 Queued Run 置 Skipped**；执行中的 Run 继续。理由：PRD 7.1.6 “不应继续发送 Prompt”，Queued 尚未发送。
4. **手动执行遇到重叠且策略 Skip 时，创建 Skipped Run**，而不是只弹错误。理由：历史可追溯，不静默。
5. **一次性调度被跳过/Endpoint 停用后也算“已消费”**，不再重试。理由：一次性计划的时刻已经过去；避免恢复后意外执行。
6. **超时从 worker 领取时刻开始计算**（包含连接/建会话/提交），不是从 Prompt 200 开始。理由：用户配置的是“单次执行允许持续多长时间”，领取即开始占用执行资源。
7. **`Completed` 的 UI 文案统一为“已完成（Completed）”**，不使用“成功”；避免与业务正确性混淆。
8. **子 Session 只展示列表，不合并轨迹**（MVP）。理由：父子轨迹合并的归属规则不可靠，容易误导。
9. **不展示 reasoning/thinking 内容**。理由：PRD 不要求，且容易把模型内部过程误呈现为完整思考轨迹。
10. **应用不做登录**。理由：PRD 10.2 排除多用户/权限体系；默认只监听本机。
11. **MVP 只处理权限请求，不渲染通用 form/question 表单**。识别到表单输入时置 `Waiting` 并提示到 OpenCode 处理或取消；通用表单回复留待后续。
12. **前端固定 React 18 + Ant Design 5，不做 SSR**。理由：稳定组合、避免 React 19 兼容补丁；管理后台不需要 SSR。
13. **API 统一 `/api/v1`，生产同源提供 SPA**。开发用 Vite proxy；如独立域名部署，只按白名单开 CORS。
14. **MVP 使用全局固定 UTC+08:00，不做 per-task 时区/DST**。PRD 7.3.2 的 per-task 时区暂缓；所有 Task 共用 `PROMPTOPS_UTC_OFFSET`（默认 `+08:00`）。理由：东八区无 DST，简化调度、展示和测试；跨时区/DST 需求另立。

### 17.3 待确认问题

| # | 问题 | 当前默认 | 影响 |
|---|---|---|---|
| Q1 | 目标 OpenCode 是否统一为 v2？是否存在必须支持的 v1 实例？ | 只支持 v2 | 若存在 v1，需要新增适配器与任务 |
| Q2 | Endpoint 是否可能使用自签名 HTTPS 证书？ | 使用系统 CA；不支持跳过校验 | 内网自签名会导致连接失败 |
| Q3 | 定时任务遇到权限请求，是否接受“停在 Waiting 直到人工处理/超时”？ | 接受，不自动批准 | 无人值守场景可能频繁超时 |
| Q4 | 是否需要 Run/Trace 自动保留期限（如 90 天）？ | 不自动清理 | 长期运行 DB 会增长 |
| Q5 | 是否需要“取消后立即把 OpenCode Session 标记为终止”之外的清理动作？ | 不做 | 已产生的副作用无法回滚（PRD 也明确） |
| Q6 | Queue 策略是否需要最大排队数？ | 不限制 | 长期不处理会堆积 |
| Q7 | 是否需要通知（邮件/IM）失败/Waiting？ | 不做 | 用户需主动看 Dashboard |
| Q8 | 是否需要 Task 标签的层级/颜色？ | 纯文本标签 | 筛选够用，UI 简单 |
| Q9 | 是否需要跨时区/DST 支持？ | 不提供；全局 `+08:00` | 若需要，需引入 `zoneinfo`、per-task 时区与 DST 测试 |

---

## 18. 验收标准（技术）

### 18.1 功能验收

- [ ] 可以创建、编辑、停用、删除 Endpoint；第一个 Endpoint 自动成为默认；默认唯一；默认不可删除/停用。
- [ ] “测试连接”能区分成功、地址不可达、认证失败、v1 不支持、非 OpenCode 服务、服务异常、超时。
- [ ] 可以创建/编辑/复制/停用/归档/恢复 Task；复制默认不启用调度。
- [ ] 新建 Task 自动选中默认 Endpoint；可以选择其他启用 Endpoint；停用 Endpoint 不能被新 Task 选择。
- [ ] Task 保存前可以看到未来 5 次执行时间，统一按 UTC+08:00 展示；不出现浏览器本地双时区列。
- [ ] cron、once、interval、none 四种调度行为符合 8.3；one-off 触发后自动结束调度。
- [ ] 到点只产生一条 Scheduled Run；重复 tick/重启不会重复创建。
- [ ] 上一轮未结束时，Queue 产生排队 Run，Skip 产生 Skipped Run 且日志说明原因。
- [ ] 停机超过 grace 后，Skip 不补跑，Run once 只补一次；都有记录。
- [ ] Endpoint 停用时，定时触发不发送 Prompt，产生 Skipped 记录。
- [ ] 每个 Run 保存完整配置快照；修改 Task/Endpoint 后，历史 Run 展示不变。
- [ ] Run 状态覆盖 12 种；终态不可逆；`Completed` 不写成“业务成功”。
- [ ] Run 日志包含创建、排队、领取、连接、建 Session、提交、轨迹、错误、取消、结束等阶段。
- [ ] 可以在 Run 详情看到实际 Prompt、最终回复、错误、消耗、配置快照、日志。
- [ ] 可以看到真实的 Tool 名称、状态、时间、耗时、输入、输出、错误。
- [ ] 只有 OpenCode 明确返回 Skill 消息/事件时才显示 Skill；不根据 Prompt 推断。
- [ ] 文件变化来自 `/diff`，不根据 Tool 名称推断；无 diff 时明确说明。
- [ ] 轨迹完整性可以区分完整/缺口/不完整/无轨迹。
- [ ] 权限请求使 Run 进入 Waiting；用户可 Allow once / Always / Reject；不自动批准。
- [ ] 取消 Queued 立即 Cancelled；取消 Running 只有确认后才 Cancelled；未确认显示 Unknown。
- [ ] 超时请求停止；执行中确认后 Timeout；未确认 Unknown；未提交 Prompt 的超时直接 Timeout。
- [ ] 进程重启后，活动 Run 会被对账；不会重发 Prompt；不重复创建同一计划时刻。
- [ ] 历史列表支持 Task/Endpoint/状态/来源/时间/模型筛选，并可 Rerun/取消。
- [ ] Dashboard 显示 Endpoint/Task/Run 统计、即将执行、最近执行、最近失败。
- [ ] 端点连接失败出现在“最近失败”，不需要健康监控。
- [ ] React SPA 可以直接打开 `/runs/{id}`、`/tasks/{id}`（刷新不 404）；`/api/v1/*` 未知路径返回 JSON 404。
- [ ] AntD 表单的 422 字段错误能映射到对应 `Form.Item`；危险操作有 `Modal.confirm`。
- [ ] Run 详情在运行中 2s 刷新，终态后停止轮询；页面隐藏时暂停。

### 18.2 非功能验收

- [ ] 默认只监听 `127.0.0.1`；API/UI/日志无密码、Authorization、密钥。
- [ ] Endpoint 密码加密存储；密钥丢失时有明确错误，不静默使用空密钥。
- [ ] 模型/Prompt/Tool 输出用 React 文本节点/`<pre>` 渲染，无 `dangerouslySetInnerHTML`，无 XSS。
- [ ] SQLite WAL、外键、busy_timeout 生效。
- [ ] 单进程运行；README 明确 `workers=1`。
- [ ] 1000 条 Run 历史、500 条轨迹条目在 React 页面本机 1s 内可打开；2s 轮询不导致明显 CPU 上升。
- [ ] `frontend` 的 `pnpm typecheck`、`pnpm build`、`pnpm test` 全绿；`dist/index.html` 与带 hash 的 assets 正确生成。
- [ ] 目标后端单测/集成测试全绿；关键恢复/取消/超时用例有自动化覆盖。
- [ ] API 契约测试覆盖成功/422/404/409/错误 envelope；错误 `details` 可被 AntD 表单消费。
- [ ] 按 README 在全新环境可以安装依赖、构建前端、启动、迁移、创建 Endpoint 并跑通一次手动执行。

### 18.3 PRD 验收场景映射

| PRD 场景 | 技术验证 |
|---|---|
| 场景一：创建定时任务 | React Task 表单 + 默认 Endpoint + UTC+8 调度预览 + 列表下一次时间（T3.3/T3.5） |
| 场景二：按时自动执行 | Fake/真实 Endpoint 下 Scheduler→Executor→Completed + 轨迹（T4.5/T5.9/T7.5） |
| 场景三：端点连接失败 | Endpoint 关闭/错误地址 → Failed + 日志 + Dashboard 最近失败（T5.9/T6.5） |
| 场景四：查看 Skill/Tool 轨迹 | 预置 skill/tool 事件 → React `TraceView` 展示（T5.3/T6.2） |
| 场景五：修改 Task 后看历史 | 修改 Task 前后两个 Run，旧 Run 快照不变（T1.3/T3.1） |
| 场景六：上一轮未结束 | Queue/Skip 两个用例（T4.5） |
| 场景七：重新执行历史 | Rerun 生成新 Run，原 Run 不变，来源 Rerun（T3.2/T6.3） |

---

## 19. 实施状态与验证记录（v1.0）

本节记录 SPEC 落地后的实际结构、实现决定和验收结果；实现细节以 [PLAN.md](./PLAN.md) 和
[docs/acceptance.md](../docs/acceptance.md) 为准。

### 19.1 已完成范围

- Phase 0–7 全部 47 个任务完成（见 [TASKS.md](./TASKS.md)）。
- 后端：`promptops/` 下实现 API、领域纯函数、SQLAlchemy ORM/Alembic、Endpoint/Task/Run/
  Dashboard/Options/Recovery 服务、自研调度器、Dispatcher、RunExecutor、Finalizer、Sweeper、
  OpenCode v2 客户端与 SSE 监管、TraceIngestor、SPA 静态资源。
- 前端：React 18 + AntD 5 的 Endpoint/Task/Run/Dashboard 页面、TraceView、权限、取消/Rerun、
  调度预览、模型发现、UTC+8 时间展示；`pnpm typecheck`/`test`/`build` 全绿。
- 测试：108 个后端测试（unit+integration）+ 16 个前端测试；真实 OpenCode v2.0.29 上完成
  PRD 11 章 7 个场景及取消/超时附加场景（证据见 acceptance 文档）。
- 性能冒烟：1000 Runs / 500 trace items 下，分页列表 12.5 ms、Dashboard 45.1 ms、
  500 条轨迹 102.3 ms（本机临时 SQLite）。

### 19.2 实际文件落点（相对 SPEC 11 节的补充）

| 文件 | 说明 |
|---|---|
| `promptops/runtime.py` | Runtime 容器：client 工厂、RunHandle 注册、终态事件转发、启停顺序 |
| `promptops/api/serialize.py` | ORM → JSON 的唯一出口（时间 ISO、快照、密码排除） |
| `promptops/api/dependencies.py` | Runtime / AsyncSession 依赖注入与事务边界 |
| `promptops/services/client_factory.py` | 从 Endpoint 构造带认证的 OpenCode 客户端 |
| `promptops/services/options_service.py` | 模型/Agent 发现与 60s 缓存 |
| `scripts/perf_smoke.py` | 1000 Runs / 500 trace 条目性能冒烟 |
| `tests/integration/fake_opencode.py` | 可脚本化的 OpenCode 适配层替身（含空 SSE 流） |

### 19.3 实现中对设计基线的技术性修正

1. **Alembic 日志隔离**：程序内迁移通过 `Config.attributes["skip_logging_config"]` 跳过
   `fileConfig`；否则 Alembic 会用自身配置覆盖应用的 JSON 日志与 `RotatingFileHandler`。
2. **SQLite 数据目录**：Alembic CLI 与程序内迁移都先确保 `data/` 存在，否则空环境首次
   `upgrade head` 会报 `unable to open database file`。
3. **SSE 断线保护**：SSE 断开时对每个活动 Run 递增 `trace_gap_count` 并置
   `trace_integrity=gap`，但已确认终态不被覆盖。
4. **Provider 失败详情**：OpenCode 将 provider 错误放在消息投影的 `idle.error` 中；finalizer
   从该字段提取 `error_type/error_message`，使 Run 详情能显示 `provider.no-route` 等真实原因。
5. **模型 variants 解析**：v2 的 variants 可能是 `[{id, settings}]` 对象数组；适配层统一投影为
   `id` 字符串列表，前端只展示可选 id。
6. **调度边界**：到期判断使用 `next_run_at <= now`；错过折叠使用严格 `>`；一次性在触发/跳过/
   Endpoint 停用后都视为已消费，避免恢复后重放。
7. **模型/Agent 发现的 location 编码**：v2 的 `location` 是 deepObject，实际 wire 形式为
   `location[directory]=...`。使用 `location.directory` 会被服务端静默忽略并退回全局配置
   （表现为项目 `opencode.json` 中的 provider/模型不出现）。已修正客户端并增加回归测试。
8. **工作目录语义**：Task 的 `working_directory` 原样作为 Session 的 `location.directory` 传给
   OpenCode；OpenCode 以该目录加载项目 `opencode.json`、`AGENTS.md` 与 Skill。必须是 OpenCode
   主机上的绝对路径（本系统不校验存在性）。

以上不改变 PRD 的产品行为，只补齐实现的边界条件。第 17.2 节的产品待确认项仍保持原默认行为。

---

## 附录 A：OpenCode v2.0.29 实测协议样本

以下是设计时在本机 `opencode serve` 上实际观察到的形状，供适配层实现参考。字段可能随版本变化，代码必须以 `openapi.json` 和容错解析为准。

### A.1 创建 Session

```json
POST /api/session
{
  "title": "spec-probe",
  "location": {"directory": "C:\\...\\workflow-scheduler"},
  "model": {"id": "deepseek-v4.1-flash-free", "providerID": "opencode"}
}
→ 200
{"data": {
  "id": "ses_eac9c6351ffenBQwj6xpZWrq1w",
  "projectID": "...",
  "model": {"id": "deepseek-v4.1-flash-free", "providerID": "opencode", "variant": "default"},
  "cost": 0,
  "tokens": {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}},
  "time": {"created": 1792400400618, "updated": 1792400400618},
  "title": "spec-probe",
  "subpath": "app/workflow-scheduler",
  "location": {"directory": "C:\\...\\workflow-scheduler"}
}}
```

### A.2 提交 Prompt

```json
POST /api/session/{id}/prompt
{"text": "Reply with exactly the word OK."}
→ 200
{"data": {
  "id": "msg_...",
  "sessionID": "ses_...",
  "time": {"created": 1792400404038},
  "type": "user",
  "payload": {"text": "Reply with exactly the word OK."},
  "delivery": "steer"
}}
```

### A.3 消息投影

`GET /api/session/{id}/message` 默认最新在前；`order=asc` 可 oldest first。样本：

```json
{"data": [
  {"id": "msg_idle", "time": {"created": 1792400447808}, "type": "idle", "outcome": "succeeded"},
  {"id": "msg_asst", "time": {"created": 1792400441243, "streamed": 1792400443851, "completed": 1792400447804},
   "type": "assistant", "agent": "build",
   "model": {"id": "deepseek-v4.1-flash-free", "providerID": "opencode", "variant": "default"},
   "content": [{"type": "text", "text": "# OpenCode 调度追踪系统需求文档"}],
   "snapshot": {"start": "...", "end": "...", "files": ["app/workflow-scheduler/specs/x.txt"]},
   "finish": "stop", "rawFinish": "stop", "cost": 0,
   "tokens": {"input": 12494, "output": 10, "reasoning": 0, "cache": {"read": 9984, "write": 0}}},
  {"id": "msg_tool", "type": "assistant", "agent": "build",
   "content": [{
     "type": "tool", "id": "call_...", "name": "read", "executed": false,
     "state": {"status": "completed",
               "input": {"path": "specs/PromptOps_Console_PRD_v1.0.md"},
               "content": [{"type": "text", "text": "Read file ..."}],
               "metadata": {"truncated": false}},
     "time": {"created": 1792400437122, "ran": 1792400437137, "completed": 1792400437158}
   }]}
]}
```

### A.4 SSE 事件样本

```text
data: {"id":"evt_...","type":"server.connected","data":{}}

data: {"id":"evt_...","created":1792400404044,"type":"session.execution.started",
       "data":{"sessionID":"ses_..."},
       "durable":{"aggregateID":"ses_...","seq":2,"version":1}}

data: {"id":"evt_...","created":1792400437122,"type":"session.tool.input.started",
       "data":{"sessionID":"ses_...","assistantMessageID":"msg_...","id":"call_...","name":"read"}}
data: {"id":"evt_...","created":1792400437133,"type":"session.tool.input.ended",
       "data":{"sessionID":"ses_...","assistantMessageID":"msg_...","id":"call_...",
               "text":"{\"path\": \"specs/...\"}"}}
data: {"id":"evt_...","created":1792400437137,"type":"session.tool.called",
       "data":{"sessionID":"ses_...","assistantMessageID":"msg_...","id":"call_...",
               "input":{"path":"specs/..."},"executed":false}}
data: {"id":"evt_...","created":1792400437158,"type":"session.tool.success",
       "data":{"sessionID":"ses_...","assistantMessageID":"msg_...","id":"call_...",
               "content":[{"type":"text","text":"Read file ..."}],
               "metadata":{"truncated":false},"executed":false}}

data: {"id":"evt_...","created":1792400447808,"type":"session.execution.succeeded",
       "data":{"sessionID":"ses_..."}}
```

### A.5 Diff

```json
GET /api/session/{id}/diff
→ 200
{"data": [
  {"file": "app/workflow-scheduler/specs/x.txt",
   "patch": "@@ ...",
   "additions": 28,
   "deletions": 0,
   "status": "modified"}
]}
```

### A.6 中断

```json
POST /api/session/{id}/interrupt
→ 200
{"interrupted": true}
```

### A.7 权限回复

```json
POST /api/session/{id}/permission/{requestID}/reply
{"decision": "once"}
→ 204
```

---

## 附录 B：错误分类与用户可见行为

| `error_type` | `error_phase` | Run 终态 | 可 Rerun | 用户提示/处理 |
|---|---|---|---|---|
| `connect_unreachable` | `connect` | Failed | 是 | 地址不可访问；检查 Endpoint 地址/网络 |
| `connect_auth_failed` | `connect` | Failed | 是 | 认证失败；检查用户名/密码 |
| `connect_unsupported` | `connect` | Failed | 否（先修 Endpoint） | 非受支持 OpenCode v2 服务 |
| `connect_timeout` | `connect` | Failed | 是 | 连接/读超时；稍后重试 |
| `connect_service_error` | `connect` | Failed | 是 | Endpoint 返回 HTTP 错误 |
| `session_create_failed` | `session` | Failed | 是 | 创建 Session 失败；查看错误详情 |
| `session_failed` | `session` | Failed | 是 | OpenCode Session 以 failed 结束；查看错误详情 |
| `session_not_found` | `session`/`finalize` | Unknown | 是 | OpenCode 中找不到 Session，无法确认是否执行 |
| `prompt_rejected` | `prompt` | Failed | 是 | Prompt 被 OpenCode 拒绝（4xx） |
| `prompt_admission_unknown` | `prompt` | Unknown | 是 | 无法确认 Prompt 是否被接收；请人工判断后 Rerun |
| `stream_disconnected` | `stream` | 取决于最终对账 | 是 | 轨迹有缺口；最终状态以 Session 为准 |
| `stream_auth_failed` | `stream` | 取决于最终对账 | 是 | SSE 认证失败；检查 Endpoint 凭据 |
| `finalize_failed` | `finalize` | 保持已确认终态 | 是 | 收尾数据不完整；轨迹可能不完整 |
| `cancel_unconfirmed` | `cancel` | Unknown | 是 | 已请求取消但无法确认停止；请检查 OpenCode |
| `timeout_unconfirmed` | `timeout` | Unknown | 是 | 已请求超时停止但无法确认；请检查 OpenCode |
| `timeout_before_prompt` | `timeout` | Timeout | 是 | 超时发生在 Prompt 提交前；无外部执行 |
| `remote_interrupted` | `session` | Failed | 是 | Session 被外部中断，非本系统发起 |
| `overlap` | `scheduler` | Skipped | 是（等前一个结束） | 上一次执行尚未结束 |
| `endpoint_disabled` | `scheduler`/`connect` | Skipped | 是（启用后） | Endpoint 已停用，未发送 Prompt |
| `missed_schedule` | `scheduler` | Skipped | 是（手动） | 已错过计划时间，按策略未补跑 |
| `process_restarted_before_prompt` | `session` | Failed | 是 | 服务重启时尚未提交 Prompt；无外部副作用 |
| `recovery_prompt_may_be_admitted` | `session` | Unknown | 是 | 服务重启时 Prompt 可能已提交；请人工确认 |
| `unexpected` | 任意 | Failed/Unknown | 是 | 未预期错误；查看 Run 日志 |

**通用规则**：

- `Failed` / `Timeout` / `Unknown` 都允许 Rerun（除非 Endpoint 不可用需要先选择）。
- `Skipped` 不是错误；Dashboard “最近失败”只统计 `failed/timeout/unknown`，不包含 Skipped。
- 任何错误信息不得包含密码、Authorization、完整 Prompt（Prompt 可在详情查看）。

---

## 附录 C：术语表

| 术语 | 含义 |
|---|---|
| Endpoint | 一个 OpenCode Serve 连接目标（v2 HTTP API） |
| Task | Prompt 模板 + 执行目标 + 调度 + 策略 |
| Schedule | Task 内嵌的调度配置：cron/once/interval/none；统一按全局 UTC+08:00 |
| Run | Task 的一次执行；创建即冻结配置快照 |
| Session | OpenCode 侧的会话 ID（`ses_...`）；一个 Run 对应一个主 Session |
| Execution Trace | Run 中实际观察到的消息、Tool、Skill、文件、权限、错误 |
| TraceItem | 规范化后的轨迹条目 |
| Snapshot | Run 创建时冻结的配置 JSON + 冗余列 |
| Overlap | 同一 Task 上一次 Run 尚未结束又到触发时间 |
| Missed | 进程不可用期间错过的计划时刻 |
| Waiting | OpenCode 正在等待权限或其他输入 |
| Unknown | 系统无法确认执行是否停止/是否接收；不是“失败”的同义词 |
| exactly-once | 同一 Task 同一计划时刻最多创建一个 Run（不保证业务只执行一次） |
| SSE | Server-Sent Events，`GET /api/event` |
| v2 API | OpenCode `opencode serve` 的 `/api/*` HTTP API；以 `/api/info` 探测 |

---

## 附录 D：实现检查清单（提交前）

- [ ] 所有新增/修改的 Python 文件有类型标注；公共函数有 docstring。
- [ ] 所有 DB 写入在事务中；长 HTTP 调用不持有事务。
- [ ] 所有状态迁移走 `state_machine`，没有散落的 `UPDATE status=`。
- [ ] 所有时间写入用 `timeutil.now_ms()` / `to_utc_ms()`，没有裸 `datetime.now()`。
- [ ] 所有外部文本（Prompt、Tool 输出、错误、标题）用 React 文本节点/`<pre>` 渲染，无 `dangerouslySetInnerHTML`。
- [ ] 所有日志调用经过脱敏 helper；没有 f-string 拼密码。
- [ ] 新增配置项同时更新 `.env.example` 和 README。
- [ ] 新增表/列同时有 Alembic migration 和索引说明。
- [ ] 新增 API 路由有 Pydantic schema，`frontend/src/api/types.ts` 同步更新。
- [ ] 新增页面有加载/空/错误状态；运行中轮询终态会停止。
- [ ] 新增调度/状态/恢复逻辑有单测；新增协议逻辑有 fake server 集成测试。
- [ ] 前端 `pnpm typecheck` / `pnpm build` / `pnpm test` 通过；`frontend/dist` 未提交。
- [ ] 界面文案全英文：`frontend/src` 与 `promptops` 中会渲染到界面的字符串无中文字符
      （`grep -rnP '[\x{4e00}-\x{9fff}]' frontend/src promptops --include=*.py` 无输出）；
      用户数据（Prompt、模型输出、日志详情）按原样展示，不做翻译或过滤。见 [AGENTS.md](../AGENTS.md)。
- [ ] `SPEC.md` / `PLAN.md` / `TASKS.md` 与实现一致（按仓库约定）。


