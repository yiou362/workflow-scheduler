# 实施与验收记录

| 项目 | 内容 |
|---|---|
| 日期 | 2026-10-19 |
| 环境 | Windows 11；Python 3.14.6；Node 24.15.0；pnpm 12.3.4 |
| 真实 OpenCode | `opencode serve` v2.0.29，`http://127.0.0.1:4097`，Basic Auth |
| 后端测试 | 108 passed（`tests/unit` + `tests/integration`，19 个测试文件） |
| 前端测试 | 16 passed（Vitest） |
| 前端门禁 | `pnpm typecheck` / `pnpm test` / `pnpm build` 全绿 |
| 前端产物 | `frontend/dist`，主 JS 1,357.83 kB（gzip 426.20 kB） |

## 1. 自动化覆盖

- 领域：状态机 12 状态迁移、终态不可逆、取消确认规则、固定 UTC+8 cron/interval/once 预览、
  错过折叠、快照不可变、最终回复选择、用量不估算。
- 调度：同一 occurrence 重复 tick 只建一条 Run；overlap queue/skip；手动执行不改 `next_run_at`；
  missed skip/run_once；Endpoint 停用 → Skipped；once 消费；interval 不补历史。
- 执行：Fake OpenCode 下 Completed、最终回复、tokens/cost、trace items、文件 diff；
  Prompt 不确定不重发；连接失败 Failed；取消确认/未确认；超时前/后；重启恢复不重发；权限回复。
- 安全：Fernet 往返、错误密钥、日志脱敏、Endpoint API 不回显密码。
- 持久化：WAL/foreign_keys/busy_timeout、外键约束生效。
- API：Endpoint CRUD/默认/删除约束、Task 校验/复制/归档/停用、Preview、Run 历史/取消/Rerun、
  JSON 404、SPA fallback、Dashboard 形状。
- 前端：API 错误 envelope、UTC+8 格式化、12 状态标签、TraceView 失败/缺口、ScheduleForm 类型切换。
- 协议回归：模型/Agent 发现必须使用 `location[directory]`（deepObject）；`location.directory` 会被
  OpenCode 忽略并退回全局配置。实测工作目录 `bo/opencode` 能加载项目 `opencode.json` 与 25 个 Skill，
  并出现 `lps` provider；工作目录 `bo` 只有全局配置和 7 个 Skill。

## 2. 真实 OpenCode v2 验收（PRD 第 11 章）

| PRD 场景 | 结果 | 证据 |
|---|---|---|
| 场景一：创建定时任务 | 通过 | Task `tsk_a094e62011af4bbc9a653d15`，once 调度，默认 Endpoint 自动选中，保存后 `next_run_at` 正确 |
| 场景二：按时自动执行 | 通过 | 调度器在 15s 后自动创建 `run_7511f0b30e1e42418712b3f1`（source=scheduled），Completed，最终回复 `AUTO-OK`；触发后 `schedule_enabled=false`、`next_run_at=null` |
| 场景三：端点连接失败 | 通过 | 坏 Endpoint `ep_6f1d31a195b741379ea3010f` → `run_85886b7163924063bd582c5d` 为 Failed / `connect_unreachable` / phase=connect；未切换 Endpoint |
| 场景四：查看 Skill 和 Tool 轨迹 | 通过（Tool 实测） | `run_7265c3bcced3436ca8cda6f2` 的 trace 含 `tool: read`（input/path、output、completed）；Skill 条目仅在真实 `session.skill.activated`/skill 消息时出现，由自动测试覆盖，本次验收任务未触发 Skill |
| 场景五：修改 Task 后查看历史 | 通过 | 原 Run `run_68b56768d2354695816e2cb2` 快照保留 `lps`；Task 已改为 `opencode` 模型，旧 Run 不变 |
| 场景六：上一轮尚未结束 | 通过 | Skip：`run_bae82406ed3c4a7c8e9e618b` = Skipped(`overlap`)；Queue：`run_14a95faa7ab94ef5a005668b` 排队后执行，`started_at >=` 前一个 `finished_at` |
| 场景七：重新执行历史任务 | 通过 | `run_b2c1497621bc458299069cc9`（source=rerun, rerun_of=`run_7265c3bcced3436ca8cda6f2`）Completed；原 Run 仍为 Completed |
| 附加：取消 | 通过 | `run_8e3681b5b1964c4d954ac43c`：Running → Cancelling → 确认后 Cancelled，`cancel_confirmed_at` 已写入 |
| 附加：超时 | 通过 | `run_9140aed369fa4ab7aa9dab01`：timeout_minutes=1，执行器 interrupt 后确认 Timeout；未提前显示 |

真实运行使用 `opencode serve` v2.0.29。第一次尝试使用配置中的 `lps` provider 时，上游返回
`provider.no-route: Model unavailable`，Run 如实记录为 Failed（`session_failed`，错误详情来自
idle 消息），这同时验证了“执行结束 ≠ 业务成功”和“错误可定位”。后续验收使用 OpenCode 自带的
免费模型完成。

## 3. 性能冒烟

`PYTHONPATH=. .venv/Scripts/python.exe scripts/perf_smoke.py`（1000 Runs / 500 trace items，临时 SQLite）：

```text
runs list (50)               200    103.6 ms
runs list page 10            200     12.5 ms
dashboard                    200     45.1 ms
run trace (500 items)        200    102.3 ms
database size: 0.12 MiB
```

首次请求包含冷启动开销；分页查询 12.5 ms。前端为单页应用，Run 详情在活动期间 2s 轮询，
终态停止。页面渲染未纳入自动化门禁，按本机构建产物手工冒烟；如需要可后续接入 Playwright E2E。

### 3.1 浏览器冒烟（Playwright CLI，生产构建）

- Dashboard：Endpoint/Task/Run 统计、即将执行、最近执行/失败均渲染，顶部显示 `UTC+08:00`。
- Tasks 列表：筛选栏、调度摘要、下一次执行、最近 Run 状态正常。
- New Task 表单：分组（基础/执行目标/Prompt/调度/策略）、默认 Endpoint 自动选中、
  “仅手动执行，无自动计划”预览、UTC+8 提示正常。
- Run 详情：`已完成（Completed）`、实际 Prompt、时间线中的 `Tool: read`、最终结果
  `# AGENTS.md`、tokens/cost、配置快照、轨迹缺口提示正常。
- 性能：`performance.getEntriesByType('navigation')[0].loadEventEnd = 308.5 ms`（本机，< 1s）。
- 截图：[Dashboard](ui-dashboard.png)、[Run 详情](ui-run-detail.png)、[Task 表单](ui-task-form.png)。

## 4. 已知限制（与 SPEC 一致）

- 只支持 OpenCode v2；v1 会明确报“不支持”。
- 全局固定 UTC+08:00，不做 per-task 时区/DST。
- 不做 Endpoint 健康监控/自动切换；端点问题只在测试连接或 Run 日志中体现。
- 不自动批准权限；无人值守任务可能停在 Waiting 直到超时。
- 不展示 reasoning/thinking；不根据 Prompt 推断 Skill/文件。
- Queue 无上限，长期不处理会堆积；Dashboard 显示 Queued 数量。
- 单进程 `workers=1`；SQLite 单写者，不做多实例。
- 应用无登录，默认仅监听 `127.0.0.1`；远程访问需反向代理认证。

## 5. 复现方式

```bash
# 后端
.venv/Scripts/python.exe -m pytest tests/unit tests/integration -q

# 前端
cd frontend && pnpm typecheck && pnpm test && pnpm build

# 真实 OpenCode（另开终端，设置密码）
cd opencode && $env:OPENCODE_SERVER_PASSWORD="<password>"; opencode serve --port 4097

# 本系统
$env:PROMPTOPS_DATA_DIR="data/_live"; python -m promptops serve
```

> 真实验收数据保留在 `data/_live/`（gitignored），其中包含 Endpoint 密文与 Run 记录；
> 不要提交或把该目录内容复制到公开位置。
