# OpenAPI fragments

并行工作 Agent 只能在本目录提交以任务编号命名的 API 片段，例如 `task-2-auth-courses.yaml`。协调 Agent 在波次门禁中审查并合并片段到 `contracts/openapi.yaml`；工作 Agent 不直接修改共享契约。
