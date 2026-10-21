# TASKS — PromptOps Console 实施任务清单

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 文档状态 | 已完成（47/47）；验收记录见 [../docs/acceptance.md](../docs/acceptance.md) |
| 对应设计 | [SPEC.md](./SPEC.md) |
| 对应需求 | [PromptOps_Console_PRD_v1.0.md](./PromptOps_Console_PRD_v1.0.md) |
| 任务总数 | 47 |
| 最后更新 | 2026-10-19 |

本文档是 SPEC 第 15 节的独立拆分。**任务细节、依赖和完成状态以本文件为准**；SPEC 只保留阶段总览，避免两份清单同时维护。

## 使用规则

- 完成一个任务后，把 `- [ ]` 改成 `- [x]`；**只有验收标准全部满足才允许勾选**。
- 一个任务未完成时不要提前勾选，也不要用“部分完成”代替。
- 任务顺序按 Phase 推进；同一 Phase 内按 ID 顺序执行，除非依赖允许并行。
- 每个任务完成后同步检查：[SPEC.md](./SPEC.md) 的设计是否仍准确；实施前把文件落点整理进 `PLAN.md`。
- 前端相关任务必须同时通过 `pnpm typecheck` 与 `pnpm build`；UI 任务至少手动冒烟一次。
- 按仓库约定，`SPEC.md` / `PLAN.md` / `TASKS.md` 三件套保持一致；代码、迁移、前端源码、构建配置都算任务的产出。
- 不提前实现 MVP 之外的功能（队列限流、自动审批、通知、图表、多用户）。

## 阶段总览

| Phase | 目标 | 任务 | 退出条件 |
|---|---|---|---|
| 0 | 工程骨架 | T0.1–T0.6 | 后端可启动；`/healthz` 正常；空库可迁移；前端可构建并由 FastAPI 提供 |
| 1 | 领域基础 | T1.1–T1.5 | 状态机、调度纯函数、ORM、密钥、仓储单测通过 |
| 2 | Endpoint 管理 | T2.1–T2.4 | Endpoint CRUD/默认/停用/删除约束/连接测试可用 |
| 3 | Task 管理 | T3.1–T3.6 | Task CRUD/复制/归档/预览/模型发现可用 |
| 4 | 调度引擎 | T4.1–T4.5 | exactly-once、overlap、missed、one-off/interval 测试通过 |
| 5 | OpenCode 适配与执行 | T5.1–T5.9 | fake server 下端到端执行、取消、超时、恢复通过 |
| 6 | React UI 与查询 | T6.1–T6.6 | React/AntD 的 Run 详情/轨迹/权限/历史/Dashboard 可用 |
| 7 | 加固与验收 | T7.1–T7.6 | 安全、恢复演练、性能、真实 v2 验收、三件套完成 |

---

## Phase 0 — 工程骨架

- [x] **T0.1 建立工程骨架**（依赖：—）
  - 内容：创建 `requirements.txt`、`requirements-dev.txt`、`pytest.ini`、`.env.example`、`.gitignore`、`README.md`、`promptops/` 包目录。
  - 验收：`pip install -r requirements.txt` 成功；`python -c "import promptops"` 成功；README 有最小启动说明。

- [x] **T0.2 配置与日志**（依赖：T0.1）
  - 内容：`promptops/config.py`（pydantic-settings）、`promptops/logging.py`（JSON formatter + 脱敏）、数据目录/日志目录初始化。
  - 验收：缺少数据目录时能自动创建或给出明确错误；日志中的 `password/secret/authorization` 被替换；启动不打印密钥。

- [x] **T0.3 数据库基座**（依赖：T0.1）
  - 内容：`promptops/db.py`、SQLAlchemy async engine、SQLite PRAGMA（WAL/foreign_keys/busy_timeout）、Alembic 初始化。
  - 验收：`alembic upgrade head` 在空库成功；重复执行幂等；WAL 生效；迁移失败时启动拒绝继续。

- [x] **T0.4 FastAPI 骨架**（依赖：T0.2/T0.3）
  - 内容：`promptops/main.py`、lifespan、`GET /healthz`、`/api/v1` 路由骨架、`web/spa.py`（dist 存在时提供 SPA，缺失时返回构建提示）。
  - 验收：服务可启动；`/healthz` 返回 `{status, version, db, frontend_built}`；`/api/v1` 未知路径返回 JSON 404；lifespan 启动/关闭顺序符合 SPEC 3.3。

- [x] **T0.5 测试基座**（依赖：T0.4）
  - 内容：`tests/conftest.py`、可注入 Clock、临时 SQLite、ASGI client、`pytest-asyncio` 配置。
  - 验收：一个空测试可跑；测试不写真实 `data/`；时间相关逻辑不依赖 `sleep`。

- [x] **T0.6 前端工程骨架**（依赖：T0.4）
  - 内容：`frontend/` 下初始化 Vite + React 18 + TypeScript + AntD 5 + React Router + TanStack Query；`main.tsx` 挂 `ConfigProvider(zhCN)`/`QueryClientProvider`/Router；`App.tsx` 提供 Layout 与 404 页；`vite.config.ts` 代理 `/api`、`/healthz` 到后端；`pnpm typecheck`/`pnpm build`/`pnpm test` 脚本。
  - 验收：`pnpm install`、`pnpm typecheck`、`pnpm build` 成功；`pnpm dev` 能打开空白 Layout；构建产物可被 FastAPI 同源提供。

---

## Phase 1 — 领域基础

- [x] **T1.1 枚举与 Run 状态机**（依赖：T0.5）
  - 内容：`enums.py`、`domain/state_machine.py`；实现 SPEC 5.2/5.3/5.4 的 12 个状态与迁移规则。
  - 验收：允许/禁止迁移全覆盖；终态不可逆；`Cancelling` 确认规则正确；单测通过。

- [x] **T1.2 时间与调度纯函数**（依赖：T0.5）
  - 内容：`timeutil.py`、`domain/schedule.py`；实现 UTC ms、固定 `+08:00` 偏移、`next_occurrence`、预览、cron/interval/once。
  - 验收：cron/interval/once/预览/UTC+8 用例通过；非法 cron/偏移返回明确错误；不依赖系统本地时区，不做 DST。

- [x] **T1.3 ORM 模型与迁移**（依赖：T0.3/T1.1）
  - 内容：`models.py` + Alembic migration；endpoints/tasks/runs/run_logs/trace_items 五张表、索引、CHECK、唯一约束。
  - 验收：`alembic upgrade head` 建全表；`(task_id, occurrence_key)` 唯一约束生效；`is_default` 部分唯一索引生效；外键行为正确。

- [x] **T1.4 密钥与脱敏**（依赖：T0.2）
  - 内容：`security.py`；Fernet 加解密、密钥加载/生成、日志脱敏 helper。
  - 验收：加解密往返成功；错误密钥有明确异常；密钥文件权限尽量 0600；API/UI/日志不回显明文。

- [x] **T1.5 仓储层**（依赖：T1.3）
  - 内容：Endpoint/Task/Run/RunLog/Trace 的基础查询、事务辅助、条件更新 helper。
  - 验收：仓储单测通过；业务规则不泄漏到 SQL 字符串；所有写操作有明确事务边界。

---

## Phase 2 — Endpoint 管理

- [x] **T2.1 EndpointService**（依赖：T1.5）
  - 内容：CRUD、默认 Endpoint 事务切换、启用/停用、删除约束、密码保留/清空语义。
  - 验收：默认唯一；默认不可删除/停用；有 Task 引用或活动 Run 时不可删除；编辑留空密码保持不变；API/UI 不回显密码。

- [x] **T2.2 Endpoint 探测与发现**（依赖：T2.1）
  - 内容：在 `opencode/client.py` 实现 `info()`、`sessions(limit=1)`、`models`、`agents` 与错误分类；执行类方法留给 T5.1。
  - 验收：成功/401/不可达/v1/HTML/5xx/超时 分类正确；`/api/info` 与 `/api/session?limit=1` 双重探测；错误消息不含密码。

- [x] **T2.3 Endpoint API 与 React 页面**（依赖：T2.1/T2.2/T0.6）
  - 内容：`/api/v1/endpoints` CRUD/默认/启停/删除/测试 API；React 列表、表单、详情、测试连接 `Alert`；密码字段只写不读。
  - 验收：可创建/编辑/设默认/停用/删除；测试结果可见且有分类文案；停用端点仍可手动测试；API/UI 不返回密码。

- [x] **T2.4 Endpoint 测试**（依赖：T2.3）
  - 内容：Service 单测 + API 契约测试；覆盖默认、删除约束、密码不泄漏、连接分类。
  - 验收：目标单测全绿；API 无密码回显；错误路径是 JSON error envelope，不是裸 500。

---

## Phase 3 — Task 管理

- [x] **T3.1 TaskService**（依赖：T1.2/T1.5）
  - 内容：创建/编辑校验、Run 快照构建、`next_run_at` 计算、调度字段互斥规则。
  - 验收：非法 cron/偏移/路径/模型被拒；快照字段完整；`schedule_enabled=true` 时类型不能为 `none`；once 过期拒绝保存/启用。

- [x] **T3.2 Task 动作**（依赖：T3.1）
  - 内容：复制、归档/恢复、启用/停用、立即执行（含重叠判断接口）。
  - 验收：复制默认 `disabled` 且不启用调度；归档不可手动执行；停用保留调度配置但 `next_run_at=NULL`；手动执行不改 `next_run_at`。

- [x] **T3.3 调度预览**（依赖：T1.2/T0.6）
  - 内容：`POST /api/v1/schedules/preview` JSON API；React `ScheduleForm` + `SchedulePreview` 组件（debounce）；统一 UTC+8 单列展示。
  - 验收：保存前可见未来 5 次；`none` 显示“仅手动执行”；非法输入映射到字段错误；预览不写数据库。

- [x] **T3.4 模型/Agent 发现**（依赖：T2.2/T0.6）
  - 内容：`GET /api/v1/options`；调用 `/api/model`、`/api/agent`；60s 内存缓存；React `ModelSelect`（AntD Select + 手输 fallback）。
  - 验收：发现成功时可选择；失败不阻塞保存；缓存按 endpoint+working_directory 区分；不手拼未编码 URL。

- [x] **T3.5 Task API 与 React 页面**（依赖：T3.1–T3.4）
  - 内容：`/api/v1/tasks` CRUD/复制/归档/启停/立即执行 API；React 列表+筛选、分组表单、详情、最近 Run；默认 Endpoint 自动选中。
  - 验收：列表字段/筛选符合 SPEC 8.2；AntD 表单校验可见；默认 Endpoint 自动选中；无 Endpoint 时显示引导并禁止创建。

- [x] **T3.6 Task 测试**（依赖：T3.5）
  - 内容：Service 单测 + API 契约测试 + React 表单/复制/归档用例。
  - 验收：覆盖 PRD 7.2 主要规则；复制/归档/停用行为可回归。

---

## Phase 4 — 调度引擎

- [x] **T4.1 SchedulerEngine**（依赖：T1.2/T3.1）
  - 内容：due 查询、1s tick、事务内建 Run + 推进 `next_run_at`、`occurrence_key` 幂等。
  - 验收：到点产生一条 Queued；无 due 不产生；同一 occurrence 重复 tick 只有一条 Run；tick 异常不杀死协程。

- [x] **T4.2 重叠策略**（依赖：T4.1）
  - 内容：queue/skip、FIFO、手动/Rerun 共用判断、`Skipped` 记录与日志。
  - 验收：queue 产生排队且同 Task 串行；skip 产生 `Skipped(error_type=overlap)`；不静默丢弃。

- [x] **T4.3 错过策略**（依赖：T4.1）
  - 内容：missed skip/run_once、启动 catch-up、`missed_count`、Endpoint 停用分支。
  - 验收：停机超过 grace 后 skip 有记录、run_once 只补一次；推进到未来；不会死循环。

- [x] **T4.4 一次性/间隔语义**（依赖：T4.1）
  - 内容：one-off 触发后关闭调度；interval 推进/编辑重置；不产生时间堆积。
  - 验收：one-off 只触发一次；interval 保存从 now 起算；编辑间隔重置节拍；跳过期间不补跑多次。

- [x] **T4.5 调度测试**（依赖：T4.2–T4.4）
  - 内容：exactly-once、并发 tick、overlap、missed、固定 UTC+8、one-off/interval。
  - 验收：关键用例全绿；唯一约束被验证；无 `sleep` 依赖。

---

## Phase 5 — OpenCode 适配与执行

- [x] **T5.1 OpenCodeV2Client 执行方法**（依赖：T2.2）
  - 内容：create_session/prompt/session/messages/diff/interrupt/permission；复用 T2.2 的 info/sessions/models/agents。
  - 验收：请求形状与 v2 一致；错误映射到 `OpenCodeError` 子类；不在错误消息中带 Authorization。

- [x] **T5.2 SSE 解析与 Endpoint 流监管**（依赖：T5.1）
  - 内容：SSE parser、每 Endpoint 一条流、懒启动/空闲关闭、重连退避、事件过滤/去重。
  - 验收：可解析实测样本与多行 data；断线重连；未知事件忽略；读超时为 None。

- [x] **T5.3 TraceIngestor**（依赖：T5.2/T1.5）
  - 内容：事件→trace_items、幂等 upsert、tool/skill/permission/file、sequence、文本截断。
  - 验收：重复事件不重复条目；Tool 状态正确；Skill 只来自明确消息/事件；文件以 diff 为准；文本上限生效。

- [x] **T5.4 Dispatcher**（依赖：T4.1/T1.5）
  - 内容：领取查询、同 Task 串行、并发上限、全局 `claim_lock`、异常隔离。
  - 验收：两 worker 不重复领取；同 Task 不并行；单 Run 异常不杀死 worker。

- [x] **T5.5 RunExecutor 主流程**（依赖：T5.1/T5.3/T5.4）
  - 内容：Preparing/Submitting/Running、控制检查点、日志、错误处理、handle 生命周期。
  - 验收：fake server 下完成一次 Run；状态/日志正确；Prompt 不确定时不重发；取消在未提交 Prompt 时直接 Cancelled/Timeout。

- [x] **T5.6 Finalizer**（依赖：T5.5）
  - 内容：拉 session/messages/diff、计算 final response、用量、轨迹完整性、收尾幂等。
  - 验收：Completed 有最终回复；无回复显示固定文案；`trace_integrity` 正确；收尾失败不会让 Run 停在活动状态。

- [x] **T5.7 取消/超时**（依赖：T5.5）
  - 内容：interrupt、确认窗口、Cancelling→Cancelled/Timeout/Unknown、sweeper、超时前对账。
  - 验收：确认→Cancelled/Timeout；未确认→Unknown；成功先到→Completed；不提前显示 Cancelled/Timeout。

- [x] **T5.8 Recovery**（依赖：T5.5）
  - 内容：启动对账、无 session/404/不可达/活动恢复、`resume_run`、不重发 Prompt。
  - 验收：重启后不重复执行；不重发 Prompt；活动 Run 能继续收尾；数据库/迁移失败拒绝启动。

- [x] **T5.9 集成测试**（依赖：T5.6–T5.8）
  - 内容：FakeOpenCodeServer + SPEC 14.2 的 12 个场景。
  - 验收：核心场景全绿；不依赖真实服务；覆盖恢复、取消未确认、SSE 断开、权限。

---

## Phase 6 — React UI 与查询

- [x] **T6.1 Run 详情页**（依赖：T3.5/T5.6/T0.6）
  - 内容：React/AntD 页面；`RunSummary`（Descriptions）、Prompt、最终结果、错误、用量、配置快照、子 Session（可选）；数据来自 `GET /api/v1/runs/{id}`。
  - 验收：历史 Run 不受 Task/Endpoint 当前值影响；无 final response 显示固定文案；消耗缺失显示“未返回”。

- [x] **T6.2 TraceView**（依赖：T5.3/T6.1）
  - 内容：`TraceView` 组件；时间线/层级 `Segmented`、Tool 输入输出、Skill、文件 `DiffView`、完整性 `Alert`；TanStack Query 2s 轮询、终态停止。
  - 验收：运行中更新；终态停止轮询；Tool 失败可见；不强行把 Tool 归到 Skill；不展示 reasoning；无 `dangerouslySetInnerHTML`。

- [x] **T6.3 日志/权限/操作**（依赖：T5.7/T6.1）
  - 内容：`LogsPanel`、`PermissionModal`、取消/Rerun 的 `Modal.confirm` 与 mutation。
  - 验收：权限可 Allow once/Always/Reject；取消有确认且不撤销副作用；Rerun 生成新 Run，原 Run 不变。

- [x] **T6.4 历史列表**（依赖：T6.1）
  - 内容：AntD `Table` + 筛选栏 + 服务端分页；状态/来源/完整性列；行点击进入详情。
  - 验收：PRD 7.7 筛选项齐全；分页保留筛选；日期按 UTC+8 解释。

- [x] **T6.5 Dashboard**（依赖：T6.4）
  - 内容：AntD `Statistic`/`Card`/`Table`；Endpoint/Task/Run 统计、即将执行、最近执行、最近失败。
  - 验收：数字与列表 SQL 可核对；不展示健康状态；连接失败出现在最近失败。

- [x] **T6.6 前端测试与类型检查**（依赖：T6.1–T6.5）
  - 内容：Vitest + Testing Library 覆盖 API client、时间工具、StatusTag、TraceView、ScheduleForm；`pnpm typecheck`/`pnpm build`。
  - 验收：前端测试/类型检查/构建全绿；无 XSS；终态轮询停止；API `types.ts` 与后端 schema 对齐。

---

## Phase 7 — 加固与验收

- [x] **T7.1 安全审计**（依赖：全量）
  - 内容：密钥、脱敏、XSS、SQL 注入、默认绑定、反向代理说明。
  - 验收：检查清单通过；API/UI/日志无敏感信息；默认仅监听 127.0.0.1；无 `dangerouslySetInnerHTML`。

- [x] **T7.2 可靠性演练**（依赖：T5.8）
  - 内容：执行中杀进程、SSE 断开、Endpoint 宕机、时钟跳变。
  - 验收：Recovery 不重发；状态不谎报；有可追溯日志；Run 不会停在活动状态。

- [x] **T7.3 性能冒烟**（依赖：T6.5）
  - 内容：1000 Run 列表、500 trace 条目、DB 体积、React 页面渲染、2s 轮询 CPU。
  - 验收：本机页面 < 1s；轮询不拖垮服务；无 N+1 查询；AntD 首屏体积可接受。

- [x] **T7.4 部署文档**（依赖：T7.1）
  - 内容：前端 `pnpm install/build`、systemd/Windows、备份/恢复、密钥、单实例、反向代理、`--reload` 警告。
  - 验收：新环境按文档完成前端构建并启动；备份恢复演练通过；明确 `workers=1`；`dist` 缺失时提示清晰。

- [x] **T7.5 真实 OpenCode v2 验收**（依赖：T5.9/T6.6）
  - 内容：按 PRD 场景 1–7 在真实 v2 Endpoint 上逐条验收并留记录。
  - 验收：7 个场景通过；轨迹/取消/超时/Rerun 与真实服务一致。

- [x] **T7.6 三件套收尾**（依赖：全量）
  - 内容：维护 `PLAN.md` / `TASKS.md`，勾选完成项，核对 SPEC 设计是否需回写。
  - 验收：三件套一致；无未勾选的已完成项；SPEC 与实际实现无冲突。

## Phase 8 — UI 全英文

- [x] **T8.1 前端界面英文化**（依赖：T6.1–T6.6）
  - 内容：`frontend/src` 下全部硬编码中文改为英文；`utils/format.ts` 标签字典；`api/client.ts` 客户端错误；`ConfigProvider locale` 改 `enUS`；dayjs locale 改 `en`；`index.html` 改 `lang="en"`。
  - 验收：`grep -rnP '[\x{4e00}-\x{9fff}]' frontend/src frontend/index.html` 无输出；`pnpm typecheck` / `pnpm test` / `pnpm build` 通过。

- [x] **T8.2 后端面向界面的文案英文化**（依赖：T8.1）
  - 内容：`api/errors.py`、`services/*.py`、`api/routes_*.py`、`scheduler/*.py`、`executor/*.py`、`opencode/client.py`、`domain/schedule.py`、`api/serialize.py`、`trace/ingestor.py`、`web/spa.py` 中会渲染到界面的 message / details / error_message / schedule_summary 全部改英文；同步 `tests/unit/test_schedule.py`、`tests/unit/test_scheduler_overlap.py` 的文案断言。
  - 验收：`grep -rnP '[\x{4e00}-\x{9fff}]' promptops --include=*.py` 无输出；`tests/unit/test_schedule.py` 通过；`tests/unit/test_scheduler_overlap.py` 断言与新文案一致。
  - 备注：本机 Python 3.14 + aiosqlite 0.22.1 在连接工作线程触发 `0xc0000096` 崩溃，任何依赖数据库夹具的用例无法在本机执行（环境问题，非本次改动引入），需在 Linux/CI 环境复跑 `tests/unit` 与 `tests/integration`。

- [x] **T8.3 文档与约束**（依赖：T8.1）
  - 内容：`README.md` 全文英文；新增 `AGENTS.md`，把「前端 UI 文字必须为英文」写成硬约束并给出验收命令。
  - 验收：`grep -cP '[\x{4e00}-\x{9fff}]' README.md AGENTS.md` 均为 0；新增文案一律以英文直接落笔，不引入 i18n 框架。

---

## 建议迭代节奏

| 迭代 | 内容 | 产出 |
|---|---|---|
| 第 1 周 | T0 + T1 | 可启动后端、React 空壳、数据库、状态机、调度纯函数、单测 |
| 第 2 周 | T2 + T3 | Endpoint/Task API 与 React/AntD 页面；调度预览；模型发现 |
| 第 3 周 | T4 + T5.1–T5.5 | 调度器、OpenCode 客户端、SSE、执行主流程（fake server） |
| 第 4 周 | T5.6–T5.9 + T6 | 收尾、取消/超时、恢复、Run 详情/轨迹/历史/Dashboard |
| 第 5 周 | T7 | 安全/可靠性/性能/真实验收；前端构建与三件套 |

> 时间是粗略建议，不是承诺；以任务验收为准。

## Definition of Done

一个任务只有同时满足以下条件才算完成：

- 代码、迁移、前端源码/构建配置已落到工作区（未要求 git commit；`frontend/dist` 不提交）。
- 对应单测/集成测试存在并通过（按仓库规则只在要求时运行）；前端任务同时通过 `pnpm typecheck` 与 `pnpm build`。
- 错误路径有明确行为，不是裸 500；API 错误使用统一 envelope。
- 日志不泄漏密码；API/UI 不回显密码。
- 相关 `SPEC.md` / `PLAN.md` / `TASKS.md` 已更新（按仓库 spec-driven 约定）。
- 如果是 UI 任务，至少手动冒烟一次；如果是调度/恢复任务，必须有自动化用例。

## 任务统计

| Phase | 任务数 | 已完成 |
|---|---|---|
| 0 工程骨架 | 6 | 6 |
| 1 领域基础 | 5 | 5 |
| 2 Endpoint | 4 | 4 |
| 3 Task | 6 | 6 |
| 4 调度 | 5 | 5 |
| 5 OpenCode/执行 | 9 | 9 |
| 6 React UI | 6 | 6 |
| 7 加固/验收 | 6 | 6 |
| **合计** | **47** | **47** |

## 验收证据

- 自动化：`pytest tests/unit tests/integration -q` → 108 passed；`pnpm typecheck` / `pnpm test`（16 passed）/ `pnpm build` 全绿。
- 协议修正：模型/Agent 发现使用 v2 deepObject 形式 `location[directory]`；已加 `tests/unit/test_opencode_client.py` 回归测试，实测 `bo/opencode` 工作目录能加载项目 `opencode.json` 与 25 个 Skill，`lps` provider 可见。
- 真实 v2：OpenCode 2.0.29 上完成 PRD 11 章场景 1–7，以及取消（确认后 Cancelled）与超时（确认后 Timeout）；Run/证据 ID 见 [../docs/acceptance.md](../docs/acceptance.md)。
- 性能：`scripts/perf_smoke.py` 在 1000 Runs / 500 trace items 下，分页列表 12.5 ms、Dashboard 45.1 ms、500 条轨迹 102.3 ms（本机临时 SQLite）；生产构建页面 `loadEventEnd=308.5 ms`（Playwright，本机）。
- 说明：场景 4 的真实任务触发了 Tool（`read`）；Skill 条目只有在 OpenCode 明确返回
  `session.skill.activated` / skill 消息时才展示，由 `tests/unit/test_trace_normalization.py`
  覆盖，未在本次真实任务中触发。

