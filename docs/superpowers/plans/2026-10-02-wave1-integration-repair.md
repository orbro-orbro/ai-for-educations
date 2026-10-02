# Wave 1 Integration Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 修复 Wave 1 Task 2/3/4 的阻塞级集成缺陷，使完整应用、知识审批证据、Runner 协议、持久化契约和 Compose 拓扑能够进入 Gate 验证并为 Task 5 提供稳定输入。

**Architecture:** FastAPI 应用通过单一应用工厂组合 Authenticator、CourseService、KnowledgeRepository 与共享错误中间件；知识证据按整条引用闭包审批。Runner 使用 ADR 0003 的受信控制面和每任务一次性无网络 sandbox，并以版本化协议返回结构化结果。PostgreSQL 迁移定义持久化约束，运行时仓储保留协议接口以支持单元测试。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、PostgreSQL 16、Alembic/SQLAlchemy 2、PyYAML、Docker Compose、cjc/cjpm 1.2.0 STS cjnative

**Spec:** `docs/superpowers/specs/2026-10-01-knowbound-cangjie-design.md`

## Global Constraints

- 角色只能是 `student`、`teacher`。
- 未知资源与无权资源统一为 `404 RESOURCE_NOT_AVAILABLE`，不能泄露存在性。
- 教师身份只能来自已验证 bearer token；课程资源必须服务端校验课程归属或显式授权。
- 只有完整引用闭包均为 `approved` 的知识/误区可进入生产诊断证据。
- 不可信仓颉代码只能进入 ADR 0003 sandbox；工具链固定为 `1.2.0 STS cjnative`。
- 不把测试替身或模拟结果描述为真实容器/试点结果。
- 按用户要求在当前工作区内联执行，不创建 Agent、不提交或推送 Git。

## Review Focus

- 缺失、伪造、过期 bearer token 必须是统一 401；有效但越权的所有课程知识路径必须是不泄露的统一 404。
- approved 误区引用 pending/rejected 根概念、关联概念或解释边时必须从证据查询中排除。
- Runner 编译失败、运行失败、超时、资源耗尽与控制面不可用必须可稳定区分且不可用可重试。
- Windows 终止辅助命令失败时不得无限等待；Linux sandbox 必须终止完整进程树。
- 重复 seed 导入必须幂等，跨课程相同业务 ID 必须隔离，迁移必须有组合唯一键和外键。

---

### Task 1: 应用组合、认证与知识权限

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/auth.py`
- Modify: `backend/app/api/courses.py`
- Modify: `backend/app/api/knowledge.py`
- Create: `backend/app/api/errors.py`
- Create: `backend/tests/integration/test_app_permissions.py`

**Interfaces:**
- Consumes: `Authenticator.authenticate_header(str | None) -> Actor`、`CourseService.assert_teacher_access(Actor, str)`。
- Produces: `create_app(...) -> FastAPI`，真实 bearer → Actor → CourseService → knowledge router；所有错误含同一个 `request_id`。

- [x] 写集成失败测试：登录后课程 owner 可访问知识；学生、外课程教师、未知课程均为相同 404；缺 token 为 401；响应 request id 与 header 一致。
- [x] 运行 `python -m pytest backend/tests/integration/test_app_permissions.py -q` 并确认因主应用未挂载/默认拒绝而失败。
- [x] 实现 request-id 中间件、统一错误响应和应用工厂；知识授权依赖从请求容器取得 Authenticator/CourseService，禁止请求参数提供身份。
- [x] 给所有 Pydantic 请求模型设置 `extra="forbid"`，注册验证异常处理器并保持 401/404/409/422 语义。
- [x] 运行 Task 1 集成测试和既有 auth/course/knowledge 测试。

### Task 2: 审批证据闭包与安全种子

**Files:**
- Modify: `backend/app/knowledge/repository.py`
- Modify: `backend/app/knowledge/seed.py`
- Modify: `backend/tests/knowledge/test_graph.py`
- Modify: `backend/tests/knowledge/test_seed.py`
- Modify: `data/course_seed/cangjie_concepts.yaml`
- Modify: `data/course_seed/cangjie_misconceptions.yaml`

**Interfaces:**
- Consumes: `KnowledgeGraph.approved_evidence(...)`。
- Produces: 仅在误区、根概念、全部关联概念以及相关 `explains_error` 边均获批时生成 `ApprovedEvidence`；seed 初始为 `pending_review`。

- [x] 写失败测试覆盖 pending/rejected 关联概念、未审批解释边、重复 seed 导入。
- [x] 运行目标测试并确认当前错误返回证据/重复冲突。
- [x] 给边增加审核字段或明确从审批闭包排除未审核边；实现幂等 upsert 语义，内容冲突必须报错。
- [x] 把种子中未经教师确认的 approved 状态重置为 pending_review，并更新统计断言。
- [x] 运行知识图谱、种子及 API 测试。

### Task 3: Runner v2 协议、诊断与有界终止

**Files:**
- Modify: `runner/worker/protocol.py`
- Modify: `runner/worker/parser.py`
- Modify: `runner/worker/executor.py`
- Modify: `runner/tests/test_protocol.py`
- Modify: `runner/tests/test_parser.py`
- Modify: `runner/tests/test_executor.py`

**Interfaces:**
- Produces: `RunnerRequest(protocol_version="2", files, entrypoint, timeout_ms)`；`RunnerResult(status, phase, retryable, exit_code, signal, stdout, stderr, diagnostics, command_summary, limits, toolchain, *_truncated)`。
- Status: `succeeded|compile_failed|run_failed|timed_out|resource_exhausted|runner_unavailable|internal_error`。

- [x] 写失败测试覆盖所有状态、JSON 诊断、截断后诊断保留、输入大小/路径限制、Windows taskkill 失败有界退出。
- [x] 运行协议/parser/executor 目标测试并观察失败。
- [x] 实现版本化模型、先解析后截断、限制元数据和平台无关进程树终止；命令仅使用参数数组和固定输出名。
- [x] 用本机 cjc/cjpm 1.2.0 运行最小编译诊断验证；运行 Runner 单测，悬挂上限 90 秒。

### Task 4: 受信 Runner 控制面和一次性 sandbox

**Files:**
- Create: `runner/controller/app.py`
- Create: `runner/controller/docker_engine.py`
- Create: `runner/worker/cli.py`
- Create: `runner/tests/test_controller.py`
- Create: `runner/tests/test_docker_engine.py`
- Modify: `runner/Dockerfile`
- Create: `runner/controller.Dockerfile`
- Modify: `runner/requirements.txt`
- Modify: `runner/compose.fragment.yaml`

**Interfaces:**
- Consumes: Task 3 JSON `RunnerRequest`/`RunnerResult`。
- Produces: `GET /health`、`POST /v2/execute`；固定 Docker create/start/wait/logs/delete 调用和 ADR 0003 全部安全参数。

- [x] 写失败测试断言控制面不可执行本地命令、不可覆盖镜像/命令/网络/挂载，Docker 请求含全部安全参数，Engine 不可用映射为 retryable。
- [x] 运行控制面测试并确认模块/端点尚不存在。
- [x] 用标准库 Unix-socket HTTP client 实现最小 Docker Engine adapter；控制面只调用固定 launcher。
- [x] 添加 worker JSON stdin/stdout 入口，sandbox 镜像默认运行 worker；控制面镜像只运行 uvicorn。
- [x] 运行 controller/protocol/executor 测试；若 daemon 可用再运行真实容器 smoke test，否则明确记录未验证。

### Task 5: PostgreSQL 模型、迁移和幂等种子

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/alembic.ini`
- Create: `backend/migrations/env.py`
- Create: `backend/migrations/versions/0001_identity_courses.py`
- Create: `backend/migrations/versions/0002_knowledge_graph.py`
- Create: `backend/app/persistence/models.py`
- Create: `backend/tests/persistence/test_migration_contract.py`

**Interfaces:**
- Produces: users/courses/enrollments/exercises 与 concepts/concept_edges/misconception_patterns 表；所有知识主键/外键带 `course_id`，审核者引用 users，状态/角色有 check constraint，常用课程查询有索引。

- [x] 写静态失败测试，解析迁移并断言表、组合唯一键、级联策略、外键、索引和审核字段存在。
- [x] 运行测试并确认迁移缺失。
- [x] 添加 SQLAlchemy/Alembic/PyYAML/psycopg 生产依赖与模型/迁移；课程删除级联知识，业务 ID 不可原地修改，审核状态变化保留引用完整性。
- [x] 运行迁移契约测试；若 PostgreSQL/Docker 可用，执行 upgrade/downgrade/upgrade smoke test，否则记录为 Gate 环境验证项。

### Task 6: 单一 OpenAPI、完整 Compose 与 Gate 回归

**Files:**
- Modify: `contracts/openapi.yaml`
- Modify: `contracts/fragments/task-2-auth-courses.yaml`
- Modify: `contracts/fragments/task-4-knowledge.yaml`
- Modify: `infra/compose/docker-compose.yml`
- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`
- Create: `backend/tests/contracts/test_openapi_runtime.py`

**Interfaces:**
- Consumes: Task 1 应用路由、Task 3 Runner v2、Task 4 控制面、Task 5 数据库配置。
- Produces: 无重复公共组件、引用有效且与运行时路由一致的 OpenAPI；可构建的 api/frontend/runner-controller/runner-sandbox/postgres Compose。

- [x] 写失败测试检查 operationId 唯一、引用可解析、所有受保护路由有 bearerAuth 与 401/404、运行时路径/状态码和契约一致。
- [x] 运行测试并确认现有片段/主契约不一致。
- [x] 合并公共 `CourseId`/`Role`/`Actor`/`ErrorResponse`，补全 401/404/409/422，并记录 Runner v2 内部契约；片段只保留任务专属定义或引用共享组件。
- [x] 增加缺失 Dockerfile，Compose 合并 controller 与 sandbox 安全配置，API 只连接 controller 内部地址。
- [x] 运行全部 backend/runner 测试（90 秒悬挂策略）、OpenAPI 测试、seed check、Compose config 和前端测试/构建。

## 自审记录

- 规格覆盖：权限、证据审批、Runner 分类/隔离、持久化、OpenAPI、Compose 与 Gate 交叉测试均有归属。
- 接口一致性：Task 1 产出真实授权链供 Task 6 契约验证；Task 3 协议同时被 Task 4 和 Task 6 消费；Task 2/5 共享审批字段。
- 范围裁决：不实现 Task 5 的提交/诊断业务，只稳定其输入契约；不实现 Wave 2 私人记忆功能。
- 执行方式：用户明确要求当前会话直接修复，使用 `superpowers:executing-plans`，不等待再次确认。
