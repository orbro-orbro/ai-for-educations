# ADR 0005：本地预览 CORS 白名单

- 状态：接受
- 日期：2026-10-07

## 背景

前端开发服务器运行在 `localhost:5173` 或 `127.0.0.1:5173`，API 运行在
`localhost:8000`。浏览器会把登录和后续 JSON 请求视为跨来源请求，并在正式
请求前发送 OPTIONS 预检。API 未处理预检时返回 405，导致前端无法登录。

## 决策

- 开发和测试环境默认只允许 `http://localhost:5173` 与
  `http://127.0.0.1:5173`。
- 其他环境默认不允许跨来源访问，部署方可通过逗号分隔的
  `CORS_ALLOWED_ORIGINS` 显式配置来源。
- 禁止 `*` 通配来源，不启用跨来源凭证。
- 仅允许前端需要的 GET、POST、PATCH、DELETE 方法，以及 Authorization、
  Content-Type、Idempotency-Key、X-Request-ID 请求头；向前端暴露
  X-Request-ID 响应头。

## 影响

- 浏览器可从本地 Vite 开发服务器调用 API，登录预检不再返回 405。
- OpenAPI 路径、数据库和角色权限不变；CORS 只控制浏览器是否可以读取响应，
  不替代服务端认证和授权。
- 新增前端部署来源时必须显式更新 `CORS_ALLOWED_ORIGINS`，不能扩大为通配来源。
