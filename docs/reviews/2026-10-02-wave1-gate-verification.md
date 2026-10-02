# Wave 1 Gate 真实环境验证记录

- 日期：2026-10-02；分支：`codex/wave1-gate-closure`（基线 `2a82b18`）
- 环境：Windows 11 + WSL2，Docker Desktop 29.8.1，Compose v5.5.1，cgroup v2
- Compose project：`knowbound-wave1-gate`（隔离项目，验证结束后仅清理该项目资源）
- 工具链：sandbox 镜像内 `cjc 1.2.0 (cjnative)`（Linux x64 SDK，SHA256 `8c5fd944…998f` 校验通过）；主机 `cjc`/`cjpm 1.2.0`
- 数据性质：以下均为工程验证结果；未包含任何真实学生数据或试点成效。知识种子仍全部为 `pending_review`。

## 启动

```powershell
docker compose -p knowbound-wave1-gate -f infra/compose/docker-compose.yml --env-file .env.example up -d --build
```

postgres、runner-controller 健康；runner-sandbox 构建后以 0 退出；宿主机只暴露 8000（API）和 5173（Web），runner-controller 只在内部网络可达。

## PostgreSQL（真实数据库）

| 项目 | 结果 |
|---|---|
| 迁移 | 新库 `0001 → 0002`；`alembic_version=0002_knowledge_graph`；10 张表、复合主键/外键、CHECK 与索引齐全 |
| 降级 | 在一次性库 `knowbound_gate_downgrade_probe` 上 `upgrade head → downgrade 0001 → downgrade base → upgrade head` 成功；主库未操作 |
| bootstrap 幂等 | 连续两次执行后用户 2、课程 1、概念 48、误区 29、边 72 不变 |
| 重启持久 | `restart` 及 `down`（保留卷）+ `up` 后数据、审核者、课程归属不变 |
| 课程隔离 | 合成课程中可创建与种子课程相同的局部 ID，两者互不影响；跨课程外键引用被拒绝 |
| 引用完整性 | 删除被误区引用的概念被 RESTRICT 拒绝；删除普通概念级联删除其边且无悬空引用；第三角色、未知审核状态、错误边类型被 CHECK 拒绝 |
| 已知限制 | 课程删除会被 RESTRICT 阻止（数据不丢失、不悬空）。当前无课程删除接口 |

## API 权限（真实 HTTP + 真实数据库）

学生访问教师端、学生审核、教师访问未知课程/未知概念、学生访问未选课程/未知课程，响应完全一致：
`404 {"code":"RESOURCE_NOT_AVAILABLE","message":"Resource is not available.","request_id":…}`。
无令牌/伪造 `alg=none` 令牌返回 401；请求体注入 `reviewed_by` 返回 422。
在合成课程中审核记录 `reviewed_by=bootstrap-teacher`（来自 Bearer 身份），编辑后回到 `pending_review`。种子课程未做任何审核操作。

## Runner（真实 Docker sandbox）

| 场景 | 结果 |
|---|---|
| hello world / 多文件 | `succeeded`，输出正确 |
| 语法错误 | `compile_failed`，诊断 `main.cj:1:22` |
| `NoneValueException` | `run_failed`，exit 1 |
| 死循环（2s） | `timed_out`，不可重试，2.4s 返回 |
| 无限输出 | stdout 截断到 65536，`stdout_truncated=true` |
| 1.6 GB 数组 | 仓颉运行时 `Out of memory`，`run_failed` |
| worker 挂起（控制面截止） | `timed_out`/`control`，不可重试 |
| 无 Docker Engine | HTTP 503，`runner_unavailable`，`retryable=true` |
| 路径穿越、绝对路径、反斜杠、覆盖镜像/命令、超长超时 | HTTP 422 |
| 生产环境可变标签 | 控制面启动失败；摘要形式可启动 |

运行中 sandbox 的 `docker inspect` 与容器内核探测：用户 `10001:10001`，仅 `lo` 网卡且外连 `Network is unreachable`，根文件系统只读（仅 `/work` tmpfs 可写），无挂载、无 Docker socket，`CapEff=0`、`NoNewPrivs=1`，cgroup `pids.max=64`、`memory.max=512MiB`、`cpu.max=1 核`，探测进程派生 63 个子进程（合计 64）后再派生被内核以 `EAGAIN` 拒绝。每个场景结束后不存在残留的 `knowbound.component=cangjie-sandbox` 容器。API 容器无 Docker socket，可访问控制面；宿主机不可访问控制面。

在 sandbox 镜像内以 uid 10001 运行 `runner/tests`：41 通过、0 跳过（含 Windows 跳过的符号链接逃逸测试）。

## 本次修复的缺陷

1. API 镜像缺少课程种子，bootstrap 报 `FileNotFoundError`：Compose `additional_contexts` + Dockerfile 复制。
2. sandbox 永久等待 stdin EOF，所有执行返回 `runner_unavailable`：请求改为单行 JSON + 换行分帧。
3. 控制面等待超时被误报为可重试的 `runner_unavailable`：识别真实 SDK 的 `ReadTimeoutError` 包裹异常。
4. `.env.example` 中 `DATABASE_URL` 密码与 `POSTGRES_PASSWORD` 不一致、缺少 Runner/Bootstrap 变量。

## 未覆盖

- 容器级 OOM（退出码 137 → `resource_exhausted`）只有单元测试；本次内存场景由仓颉运行时先行报错。
- 需要派生进程的仓颉 PID 耗尽程序未编写（本机未安装 `cangjie-coding` 技能）；PID 上限由内核探测验证。
- 教师审核：见 `2026-10-02-wave1-knowledge-review-checklist.md`，尚无教师确认。
