# Cangjie Runner v2

Task 5 只依赖 `contracts/runner-openapi.yaml` 和 `runner.worker.protocol`，不依赖 Docker、工作目录或编译器原始 JSON 结构。

## 调用

- 内部端点：`POST /v2/execute`
- 请求版本：`protocol_version: "2"`
- 调用方只提交 `submission_id`、最多 32 个 `.cj` 文件、其中一个 `entrypoint` 和 `timeout_ms`。
- 调用方不能提交命令、镜像、输出路径、挂载、网络或资源限制；未知字段直接返回 422。

## Task 5 应持久化的结果

- `status`：`succeeded`、`compile_failed`、`run_failed`、`timed_out`、`resource_exhausted`、`runner_unavailable`、`internal_error`
- `phase`：`compile`、`run`、`control`
- `retryable`：只有基础设施不可用结果为 `true`
- `exit_code`、`signal`、`stdout`、`stderr` 和两个截断标记
- `diagnostics`：已规范化、与 cjc 原始 JSON 字段名解耦的诊断数组
- `command_summary`：不含源码的固定编译摘要
- `limits` 与 `toolchain`：执行时实际采用的限制和 1.2.0 STS cjnative 标识

诊断在 stderr 对外截断前解析，因此 Task 5 必须优先使用 `diagnostics`，不能重新解析截断后的 stderr。收到 HTTP 503 时仍会得到合法 `RunnerResult`，其 `status=runner_unavailable`、`retryable=true`；上层应保留提交并安排重试，不得伪造编译结果。

## 兼容策略

v1 的 `command`、`timeout_seconds`、`timed_out` 和 `resource_limited` 不进入 v2 JSON。Python 内部保留后两个只读兼容属性，但 Task 5 不得持久化或依赖它们。未来不兼容变更必须新增 `/v3` 和新的字面量版本，不能原地改变 v2 枚举或字段语义。

## Compose

`runner-controller` 是受信控制面并位于内部网络；`runner-sandbox` 服务只负责在普通 `docker compose up --build` 中构建固定镜像并成功退出。每次请求由控制面通过 Docker Engine 创建新的、无网络、只读根文件系统、非 root、资源受限的 sandbox，结束后强制删除。

Linux 主机若 Docker socket 的组 ID 不是 0，需要设置 `DOCKER_GID`。生产环境应把 `RUNNER_SANDBOX_IMAGE` 设置为构建后验证过的镜像摘要，而不是可变标签。
