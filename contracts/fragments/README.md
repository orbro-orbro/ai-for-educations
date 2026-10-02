# OpenAPI fragments

并行工作 Agent 只能在本目录提交以任务编号命名的 API 片段，例如 `task-2-auth-courses.yaml`。协调 Agent 在波次门禁中审查并合并片段到 `contracts/openapi.yaml`；工作 Agent 不直接修改共享契约。

Wave 1 已于 2026-10-02 完成 Task 2/Task 4 合并。`contracts/openapi.yaml` 是前端和生成工具的唯一规范；片段保留为任务来源记录，共享的 `Role`、`bearerAuth` 和基础错误封装由主契约提供。片段中的同名 `CourseId`/`ErrorResponse` 必须与主契约逐字同义，后续不得独立演化。
