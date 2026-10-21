# 团队公告：workflow-scheduler（PromptOps Console v1.0）

> 用途：Teams 群组公布。以下正文可直接粘贴。

---

## 正文

**【团队公告】workflow-scheduler（PromptOps Console）v1.0 已完成**

一句话：把"每周要跑的那条 Prompt"变成自动触发、随时可查、失败可定位的定时任务。

### 核心功能

1. **端点管理** —— 登记多个 OpenCode Serve（本地机 / 服务器 / 项目专用），可设默认端点，一键"测试连接"验活。
2. **任务配置** —— 一次配齐：目标端点 + 工作目录 + Provider/模型 + 完整 Prompt + 调度规则 + 异常策略 + 超时。调度支持 cron / 一次性 / 固定间隔。
3. **调度预览** —— 保存前先看未来 5 次触发时间，不用猜 cron 对不对。
4. **自动执行** —— 到点自动投递 Prompt；也可手动"立即执行"。
5. **全过程留痕** —— 每次执行记录：真实发出的 Prompt、消息与 Tool 调用轨迹、最终回复、耗时、Token 与成本、配置快照。
6. **失败可定位** —— 区分失败阶段（连接 / 会话 / 提交 / 流式 / 收尾）与错误类型，端点不通、认证错、模型不可用一眼分得清。
7. **历史与重跑** —— 按任务 / 端点 / 状态 / 触发来源 / 时间 / 模型筛选；失败的原地重跑，旧记录不被覆盖。
8. **实时看板** —— 端点 / 任务 / 运行统计，外加"即将执行""最近执行""最近失败"。

> 三条关键设计：① Task 是模板、Run 是事实——Run 创建时冻结配置快照，改 Task 不影响历史；② 端点失败不自动切换、不换机器重跑；③ "执行结束"≠"业务正确"，系统只如实呈现发生了什么。

### 如何启动

代码在 `app/workflow-scheduler`：

```bash
# 1) 后端依赖
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # Windows
# .venv/bin/python -m pip install -r requirements-dev.txt          # Linux/macOS

# 2) 前端构建
cd frontend && pnpm install && pnpm build && cd ..

# 3) 启动（必须单进程，workers=1）
.venv\Scripts\python.exe -m promptops serve
```

打开 <http://127.0.0.1:8787>。

> 必须 `workers=1`：调度、Run 领取和 SSE 监管都在进程内，多 worker 会重复调度。

### 如何配置

**① 配端点**（`Endpoints` → 新建）

- URL：OpenCode Serve 地址，如 `http://127.0.0.1:4096`
- 认证：Basic Authentication，用户名 `opencode`，密码为 OpenCode 启动时的 `OPENCODE_SERVER_PASSWORD`（未显式设置时为随机密码，存在 `~/.local/state/opencode/service.json`）
- 点"测试连接"应显示 `连接成功，OpenCode <version>`；第一个端点自动成为默认端点

**② 配任务**（`Tasks` → 新建）

- **工作目录**：填 OpenCode 主机上的**绝对路径**，指向含 `opencode.json` 的项目目录（如 `...\bo\opencode`），不要填文件本身
- **Provider / 模型**：随该目录的 `opencode.json` 加载，选择该目录下可见的模型
- **Prompt**：要发送的完整内容。不绑定 Skill，OpenCode 依 Prompt 与目录配置自行决定调用什么
- **调度**：Cron / 一次性 / 固定间隔；重叠选"排队"或"跳过"，错过选"跳过"或"补跑一次"；可设超时分钟数
- 保存前看调度预览，确认无误后保存启用

**③ 看结果**（`执行历史`）

Dashboard 看总体与"即将执行"；执行历史里点开任一次 Run，看状态、实际 Prompt、轨迹时间线、最终回复、错误详情；失败的点"重新执行"。

### 已知限制

- 只支持 OpenCode v2（v2.0.29 实测），v1 明确报不支持
- 单进程 + SQLite（必须单 worker），无高可用
- 无登录与权限体系，默认只监听 `127.0.0.1`；团队共享访问需自行加反向代理与认证
- 全局固定 UTC+08:00，不支持 per-task 时区
- 不做端点健康巡检与自动故障转移；权限请求不自动批准
- 与既有 `app/workflow-runner` 完全独立，**不要让两者同时调度同一批 Prompt**

有疑问或新场景想接进来，群里找我。
