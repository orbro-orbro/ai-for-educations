# 知界·仓颉学伴

知界·仓颉学伴是面向《仓颉语言设计》的可信概念误区诊断智能体。首版仅包含学生和教师两类角色，目标是打通代码提交、真实编译反馈、误区诊断、递进式提示、学生可控学习记忆与教师匿名分析闭环。

## 当前状态

Wave 0 工程基线。此阶段提供 API、前端、执行器协议和容器拓扑骨架，不包含业务功能。

## 本地依赖

- Python 3.11 或更高版本
- Node.js 20 或更高版本
- Docker Desktop 或兼容的 Docker Compose 环境
- 后续执行器阶段需要仓颉 1.0.5 cjnative 工具链

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
```

项目设计、实现计划和 Agent 约束分别位于 `docs/superpowers/specs/`、`docs/superpowers/plans/` 和 `AGENTS.md`。
