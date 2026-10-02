# ADR 0003: 受信 Runner 控制面与一次性隔离任务容器

- 状态：已接受
- 日期：2026-10-02
- 决策人：项目协调者（用户于本次集成修复中确认直接采用该方案）
- 关联：ADR 0001、ADR 0002、Wave 1 Task 3/Task 5

## 背景

ADR 0002 要求不可信仓颉代码在无网络、只读根文件系统、非 root、资源受限的隔离环境中运行。现有实现把整个 `runner` 服务设为 `network_mode: none`，同时 API 通过 `http://runner:8080` 调用它；容器既没有 HTTP 控制面，也因无网络而不可达。这一拓扑无法把 Task 5 与隔离执行器集成。

把长驻 Runner 容器直接连入应用网络并在其中执行学生代码，会让学生进程继承网络命名空间；把整个 Runner 断网，又会让控制面不可达。因此控制面与数据面必须拆分。

## 决策

采用“受信控制面 + 每任务一次性 sandbox”模型：

1. `runner-controller` 是受信服务，只接收结构化 `RunnerRequest`，不在自身进程或网络命名空间内编译、运行学生代码。
2. 控制面只允许启动固定镜像、固定入口和固定安全参数；请求不能覆盖镜像、命令、输出路径、挂载、网络或资源限制。
3. 每个请求创建一次性任务容器。任务容器使用 `--network none`、只读根文件系统、非 root 用户、`no-new-privileges`、全部 capability 丢弃、PID/内存/CPU 限制和受限 tmpfs；完成后强制删除。
4. 源文件只通过标准输入中的 JSON 传入任务容器，任务目录由 worker 创建；不把宿主项目目录或任意用户路径挂载进 sandbox。
5. 控制面通过 Docker Engine Unix socket 创建和管理任务容器。该 socket 只挂载给控制面，不挂载给 API 或 sandbox。控制面因此属于高信任边界，必须保持极小接口、固定参数和内部网络可达性。
6. `RunnerResult` 明确区分 `compile_failed`、`run_failed`、`timed_out`、`resource_exhausted`、`runner_unavailable` 和 `internal_error`；不可用结果标记 `retryable=true`，不得伪造成编译或运行结果。
7. 诊断从未截断的编译器 stderr 增量解析后再限制对外文本；结果携带规范化诊断、命令摘要、工具链版本、资源限制和截断标记，供 Task 5 稳定持久化。

## 安全约束

- 只有 `/health` 与 `/v2/execute` 两个控制面端点。
- 输入限制：最多 32 个文件、单文件 256 KiB、总计 1 MiB；只接受相对 POSIX 路径，拒绝绝对路径、`..`、反斜杠、Windows 盘符、NUL 与符号链接。
- 编译和运行命令由 worker 固定构造并以参数数组执行，禁止 shell。
- 超时必须终止完整进程树；Windows 本地测试即使 `taskkill` 失败也必须有有界等待和最终 `kill`。
- stdout/stderr 分别有字节上限，并返回 `*_truncated`。
- 生产环境必须校验固定 sandbox 镜像摘要；开发环境可使用显式镜像标签，但不得由请求覆盖。

## 备选方案

### 长驻联网 Runner 内执行学生代码

拒绝。控制面可达性会把网络能力同时暴露给学生进程，不满足固定安全边界。

### 长驻无网络 Runner

拒绝。API 无法通过 Compose 网络访问，Task 5 无法集成。

### API 直接访问 Docker socket

拒绝。会把容器管理高权限扩大到业务 API；本决策把它限制在最小受信控制面。

## 后果

- 增加一个受信控制面镜像/进程和一个 sandbox 镜像。
- 本地 Docker Desktop/Linux Engine 均通过容器内 Unix socket 工作；Windows 宿主直接执行 worker 仍仅用于开发测试，不代表容器隔离验证。
- Docker socket 是高价值资产。未来生产部署宜替换为专用调度器或最小权限 socket proxy，但 Wave 1 不把该基础设施扩展作为前置条件。
- Compose 静态配置可验证；若本机 Docker daemon 不可用，不能把单元测试替身结果描述为真实容器安全验证。

## 补充说明（2026-10-02，Wave 1 Gate）

- 决策第 4 条的标准输入 JSON 以单行加换行符分帧。真实 Docker 验证发现 attach 半关闭不会向容器传递 EOF，Docker SDK 7.2.0 也不支持 `stdin_once`，按 EOF 读取会使 worker 永久等待。该补充不改变隔离边界或控制面接口。
- 控制面等待超时在真实 SDK 中表现为包裹 `ReadTimeoutError` 的 `requests.exceptions.ConnectionError`，按决策第 6 条归类为不可重试的 `timed_out`，不得报告为 `runner_unavailable`。
