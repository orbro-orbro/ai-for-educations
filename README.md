# 知界·仓颉学伴

知界·仓颉学伴是面向《仓颉语言设计》的可信概念误区诊断智能体。首版仅包含学生和教师两类角色，目标是打通代码提交、真实编译反馈、误区诊断、递进式提示、学生可控学习记忆与教师匿名分析闭环。

## 当前状态

Wave 1 集成基线：身份/课程权限、教师知识图谱、PostgreSQL 迁移、Runner v2 协议以及“受信控制面 + 每任务一次性 sandbox”已接入。课程种子默认全部为 `pending_review`，在课程教师明确审批前不会进入生产诊断证据。

## 本地依赖

- Python 3.11 或更高版本
- Node.js 20 或更高版本
- Docker Desktop 或兼容的 Docker Compose 环境
- 仓颉工具链统一固定为最新正式版 1.2.0 STS（cjnative），不使用 Nightly 构建

## 本地验证

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests runner\tests -q
cd frontend
npm test
npm run build
```

Docker 可用时再运行：

```powershell
docker compose -f infra\compose\docker-compose.yml config
docker compose -f infra\compose\docker-compose.yml up --build
```

普通 `up --build` 会先构建 `runner-sandbox` 镜像并让构建辅助容器成功退出，再启动受信 `runner-controller`。Linux 主机按 Docker socket 的实际组 ID设置 `DOCKER_GID`。

开发环境会幂等创建《仓颉语言设计》课程、全部待审知识种子以及两个本地账号：`teacher / teacher-change-me`、`student / student-change-me`。教师对种子做出的审核或修改不会在重启时被覆盖。

开发默认值只用于本机。`APP_ENV=production` 时必须同时设置：

- 长随机值 `AUTH_TOKEN_SECRET`，不能使用 `development-only-token-secret`；
- 非默认的 `BOOTSTRAP_TEACHER_PASSWORD` 和 `BOOTSTRAP_STUDENT_PASSWORD`；
- 带 `@sha256:<64 hex>` 的不可变 `RUNNER_SANDBOX_IMAGE`；
- 非默认 PostgreSQL 凭据。

公开 API 契约位于 `contracts/openapi.yaml`，内部 Runner v2 契约位于 `contracts/runner-openapi.yaml`；Task 5 的消费说明见 `runner/README.md`。

项目设计、实现计划和 Agent 约束分别位于 `docs/superpowers/specs/`、`docs/superpowers/plans/` 和 `AGENTS.md`。
