# 知界·仓颉学伴 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个面向《仓颉语言设计》的双角色 Web 应用，完成仓颉代码安全执行、概念误区诊断、递进式提示、学生可控学习记忆和教师匿名班级分析闭环。

**Architecture:** React 前端只通过 OpenAPI 调用 FastAPI；PostgreSQL/pgvector 保存课程、概念图谱、诊断和受控记忆；不可信仓颉代码由独立 Docker 执行器编译运行。权限、记忆过滤、模型网关和教师聚合彼此隔离，所有跨边界数据都通过明确契约传递。

**Tech Stack:** React、TypeScript、Vite、FastAPI、Python、PostgreSQL、pgvector、SQLAlchemy、Alembic、Docker Compose、仓颉 1.0.5 cjnative、pytest、Vitest、Playwright。

**Spec:** `docs/superpowers/specs/2026-10-01-knowbound-cangjie-design.md`

## Global Constraints

- 只有教师和学生两类角色，不创建助教端。
- 首个试点课程固定为《仓颉语言设计》，首版按仓颉语法与编程实践组织。
- 教师默认不能读取学生私人对话或完整个人记忆。
- 模型只能创建记忆建议，不能直接写入长期记忆。
- 不可信仓颉代码只能在无外网、非 root、有限资源的独立执行器中运行。
- 教师统计仅在分组样本数不少于 5 时展示。
- 课程概念、典型误区和低置信度诊断必须支持教师审核。
- 目标值、模拟数据和真实试点结果必须明确区分。
- 所有仓颉语义以当前 `cjc`/`cjpm` 和 `cangjie-coding` 技能知识库为准。
- 任何框架、数据库、角色、隐私边界或执行器隔离策略变更必须先写 ADR 并获得用户确认。

## Review Focus

- 越权 ID：学生提交另一个学生的资源 ID 时，服务端返回统一拒绝且不暴露资源是否存在；Task 2 和 Task 10 覆盖。
- 执行器不可用：API 不得让模型伪造编译结果，必须保存提交并返回明确可重试状态；Task 3 和 Task 6 覆盖。
- 无证据或低置信度诊断：不得写入长期记忆，必须追问或进入教师复核；Task 6 覆盖。
- 删除不完整：删除期间记忆立即停止检索，后台补偿清理数据库、向量和缓存；Task 7 覆盖。
- 小样本统计：任意过滤组合导致样本数小于 5 时均不得返回明细；Task 8 和 Task 10 覆盖。

---

## 0. Agent 编排规则

### 推荐配置

- **协调 Agent**：常驻，负责契约、共享文件、任务派发、集成、全量验证和最终交付；原则上不与工作 Agent 同时修改同一文件。
- **工作 Agent 1—3**：每个任务使用一个新鲜上下文，只处理一个明确领域。
- **复核 Agent**：每个任务完成后使用新鲜上下文审查；可复用空出的工作槽位，不与实现 Agent 同时审查未完成代码。

同一时刻最多运行三个工作 Agent。不要让两个 Agent 同时修改以下高冲突文件：

- `backend/alembic/versions/*`
- `contracts/openapi.yaml`
- `infra/compose/docker-compose.yml`
- `.env.example`
- 根目录依赖和格式化配置

工作 Agent 不直接修改上述高冲突文件。各任务把 API 变化写入 `contracts/fragments/task-<n>.yaml`，把数据库变化写入自己的 SQLAlchemy 模型和测试。每个波次结束后由协调 Agent 串行合并 OpenAPI，并按固定顺序生成迁移：`0001_identity_courses.py`、`0002_knowledge_graph.py`、`0003_submissions_diagnostics.py`、`0004_memories_audit.py`。

### 执行波次

```text
Wave 0（协调 Agent 串行）
  Task 1 契约与工程基线

Wave 1（三 Agent 并行）
  Task 2 身份、课程与权限
  Task 3 仓颉隔离执行器
  Task 4 概念图谱与课程种子

Wave 1 Gate（协调 Agent 串行）
  合并 Task 2/4 API 片段和 Task 3 Compose 片段
  生成并验证 0001_identity_courses.py、0002_knowledge_graph.py

Wave 2A（串行，等待 Wave 1）
  Task 5 提交管线与确定性映射
  协调 Agent 合并契约并生成 0003_submissions_diagnostics.py

Wave 2B（串行，等待 Task 5）
  Task 6 AI 诊断与提示阶梯
  协调 Agent 合并诊断契约

Wave 2C（串行，等待 Task 6）
  Task 7 学习记忆、授权与删除
  协调 Agent 合并契约并生成 0004_memories_audit.py
  协调 Agent 补全并冻结供 Wave 3 使用的教师分析 OpenAPI

Wave 3（三 Agent 并行，等待 Wave 2 契约稳定）
  Task 8 教师匿名分析
  Task 9 学生端与教师端 UI
  Task 10 安全、端到端与评测框架

Wave 4（协调 Agent 串行）
  Task 11 全量集成与比赛交付基线
```

## 1. Planned File Structure

```text
/
├─ AGENTS.md
├─ README.md
├─ .env.example
├─ contracts/
│  ├─ openapi.yaml
│  └─ fragments/
├─ frontend/
│  ├─ package.json
│  ├─ src/api/
│  ├─ src/auth/
│  ├─ src/student/
│  ├─ src/teacher/
│  └─ tests/
├─ backend/
│  ├─ pyproject.toml
│  ├─ alembic/
│  ├─ app/api/
│  ├─ app/auth/
│  ├─ app/courses/
│  ├─ app/submissions/
│  ├─ app/knowledge/
│  ├─ app/diagnostics/
│  ├─ app/memories/
│  ├─ app/analytics/
│  ├─ app/audit/
│  └─ tests/
├─ runner/
│  ├─ Dockerfile
│  ├─ worker/
│  └─ tests/
├─ data/
│  ├─ course_seed/
│  └─ evaluation/
├─ infra/compose/
│  └─ docker-compose.yml
└─ docs/
   ├─ adr/
   ├─ experiments/
   └─ superpowers/
```

### Task 1: 工程基线与共享契约

**Owner:** 协调 Agent，串行执行。

**Files:**
- Create: `README.md`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `contracts/openapi.yaml`
- Create: `backend/pyproject.toml`
- Create: `backend/app/main.py`
- Create: `backend/tests/test_health.py`
- Create: `frontend/package.json`
- Create: `frontend/src/main.tsx`
- Create: `runner/worker/protocol.py`
- Create: `infra/compose/docker-compose.yml`
- Create: `docs/adr/0001-system-boundaries.md`
- Create: `contracts/fragments/README.md`

**Interfaces:**
- Consumes: 设计规格中的模块、数据对象和 API 边界。
- Produces: `GET /health`、OpenAPI 基线、`RunnerRequest`/`RunnerResult` 类型、数据库连接环境变量和可启动的 Compose 拓扑。

- [ ] **Step 1: 初始化版本控制和目录**

Run:

```powershell
git init
New-Item -ItemType Directory -Force contracts,frontend,backend,runner,data,infra,docs\adr
```

Expected: `git status --short --branch` 显示初始化分支，目录存在。

- [ ] **Step 2: 写健康检查失败测试**

Create `backend/tests/test_health.py`:

```python
from fastapi.testclient import TestClient
from app.main import app


def test_health_reports_service_ready() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "knowbound-api"}
```

- [ ] **Step 3: 运行测试并确认失败**

Run: `cd backend; python -m pytest tests/test_health.py -q`

Expected: FAIL，因为 `app.main` 尚不存在。

- [ ] **Step 4: 实现最小 API**

Create `backend/app/main.py`:

```python
from fastapi import FastAPI

app = FastAPI(title="KnowBound-CJ", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "knowbound-api"}
```

- [ ] **Step 5: 定义执行器协议**

Create `runner/worker/protocol.py` with immutable request/result models containing `submission_id`, `source_files`, `command`, `timeout_seconds`, `exit_code`, `stdout`, `stderr`, `timed_out`, and `resource_limited`. Set output limits and reject absolute paths in model validation tests.

- [ ] **Step 6: 固化 OpenAPI 与 Compose 边界**

Define `api`, `web`, `postgres`, and `runner` services. `runner` must have no public port and an internal-only network. `openapi.yaml` must include `/health`, authentication scheme, role enum `student|teacher`, and error envelope `{code,message,request_id}`.

- [ ] **Step 7: 验证基线**

Run:

```powershell
cd backend
python -m pytest -q
cd ..
docker compose -f infra/compose/docker-compose.yml config
```

Expected: pytest PASS；Compose 配置解析成功。

- [ ] **Step 8: Commit**

```powershell
git add .
git commit -m "chore: establish project contracts and service skeleton"
```

### Task 2: 身份、课程与服务端权限

**Owner:** Wave 1 Agent A。

**Files:**
- Create: `backend/app/auth/models.py`
- Create: `backend/app/auth/policy.py`
- Create: `backend/app/courses/models.py`
- Create: `backend/app/courses/service.py`
- Create: `backend/app/api/auth.py`
- Create: `backend/app/api/courses.py`
- Create: `backend/tests/auth/test_policy.py`
- Create: `backend/tests/courses/test_course_access.py`
- Create: `contracts/fragments/task-2-auth-courses.yaml`

**Interfaces:**
- Consumes: Task 1 error envelope and role enum。
- Produces: `Actor(user_id, role)`, `authorize(actor, action, resource)`, course/enrollment repositories, login and course APIs used by Tasks 5、7、8、9。

- [ ] **Step 1: 写跨学生资源拒绝测试**

```python
def test_student_cannot_read_another_students_resource(policy, student_a, student_b_resource):
    decision = policy.authorize(student_a, "read", student_b_resource)
    assert decision.allowed is False
    assert decision.public_error_code == "RESOURCE_NOT_AVAILABLE"
```

- [ ] **Step 2: 写教师私人记忆拒绝测试**

```python
def test_teacher_cannot_read_private_memory_without_grant(policy, teacher, private_memory):
    decision = policy.authorize(teacher, "read_private_memory", private_memory)
    assert decision.allowed is False
```

- [ ] **Step 3: 运行测试并确认失败**

Run: `cd backend; python -m pytest tests/auth tests/courses -q`

Expected: FAIL because policy and models are missing.

- [ ] **Step 4: 实现最小角色和课程策略**

Implement deny-by-default policy. Course membership must be checked server-side on every resource. Authentication for MVP may use seeded demo accounts and signed tokens, but passwords must be hashed and secrets loaded from environment variables.

- [ ] **Step 5: 输出契约片段**

Write login, course list, exercise list, teacher course creation and enrollment endpoints to `contracts/fragments/task-2-auth-courses.yaml`. Verify unknown IDs and forbidden IDs return the same public error code. Do not edit the shared OpenAPI file or migration directory.

- [ ] **Step 6: 验证并提交**

Run: `cd backend; python -m pytest tests/auth tests/courses -q`

Expected: PASS.

Commit: `feat: add course-scoped identity and authorization`

### Task 3: 仓颉隔离执行器

**Owner:** Wave 1 Agent B。

**Files:**
- Create: `runner/Dockerfile`
- Create: `runner/worker/executor.py`
- Create: `runner/worker/parser.py`
- Create: `runner/tests/test_executor.py`
- Create: `runner/tests/test_parser.py`
- Create: `runner/tests/fixtures/hello_world.cj`
- Create: `runner/tests/fixtures/infinite_loop.cj`
- Create: `docs/adr/0002-cangjie-runner-isolation.md`
- Create: `runner/compose.fragment.yaml`

**Interfaces:**
- Consumes: Task 1 `RunnerRequest` and `RunnerResult`。
- Produces: `execute(request: RunnerRequest) -> RunnerResult` and normalized compiler diagnostics consumed by Task 5。

- [ ] **Step 1: 验证工具链前置条件**

Run:

```powershell
cjc -v
cjpm -v
docker version
```

Expected: record exact versions. If Cangjie is unavailable, stop this task and report the missing prerequisite; do not emulate successful compilation.

- [ ] **Step 2: 写成功编译、超时和路径逃逸测试**

Tests must assert: a minimal program returns exit code 0; an infinite loop is terminated at the configured timeout; source file names containing `..` or absolute paths are rejected before execution.

- [ ] **Step 3: 运行测试并确认失败**

Run: `python -m pytest runner/tests -q`

Expected: FAIL because executor is missing.

- [ ] **Step 4: 实现最小执行器**

Use a fresh temporary directory per job, invoke only allowlisted `cjc`/`cjpm` command forms, cap stdout/stderr, and return structured results. Container runs non-root, has no network, read-only root filesystem, process limit, memory limit and timeout.

- [ ] **Step 5: 测试恶意输入**

Add cases for shell metacharacters, excessive output, recursive process creation and symlink escape. Inputs must be passed as argument arrays, never interpolated into a shell command.

- [ ] **Step 6: 验证并提交**

Run: `python -m pytest runner/tests -q`

Expected: PASS including timeout and escape tests.

Write the runner service hardening and internal-network changes to `runner/compose.fragment.yaml`; do not edit shared Compose directly.

Commit: `feat: add isolated cangjie compilation runner`

### Task 4: 仓颉概念图谱与课程种子

**Owner:** Wave 1 Agent C。

**Files:**
- Create: `backend/app/knowledge/models.py`
- Create: `backend/app/knowledge/repository.py`
- Create: `backend/app/knowledge/seed.py`
- Create: `backend/app/api/knowledge.py`
- Create: `backend/tests/knowledge/test_graph.py`
- Create: `backend/tests/knowledge/test_seed.py`
- Create: `data/course_seed/cangjie_concepts.yaml`
- Create: `data/course_seed/cangjie_misconceptions.yaml`
- Create: `data/course_seed/README.md`
- Create: `contracts/fragments/task-4-knowledge.yaml`

**Interfaces:**
- Consumes: Task 2 course ownership and teacher authorization。
- Produces: `Concept`, `ConceptEdge`, `MisconceptionPattern`, graph traversal and approved-evidence lookup used by Tasks 5、6、8。

- [ ] **Step 1: 用 cangjie-coding 技能验证首批概念**

Batch-query class/struct、match、Option、interface/extension、generic where、spawn/Future and cjpm. Record only verified summaries and current toolchain version in seed metadata.

- [ ] **Step 2: 写图谱一致性失败测试**

Tests must reject duplicate IDs, edges to missing nodes, cycles in strict prerequisite edges, unreviewed misconceptions used as approved evidence, and seed records without source metadata.

- [ ] **Step 3: 运行测试并确认失败**

Run: `cd backend; python -m pytest tests/knowledge -q`

- [ ] **Step 4: 实现模型、仓储和导入器**

Use stable IDs such as `cj.pattern-match.exhaustiveness`. Separate edge types `prerequisite`, `confusable_with`, `used_by`, and `explains_error`. Only `review_status=approved` items may feed production diagnosis.

- [ ] **Step 5: 导入最小课程数据**

Seed at least 30 concepts and 20 reviewed misconception patterns across the nine course topics. Each misconception must include trigger evidence, root concept, explanation, hint ladder outline and source metadata.

- [ ] **Step 6: 输出教师知识管理契约**

Write teacher-authorized concept and misconception create/update/review endpoints to `contracts/fragments/task-4-knowledge.yaml`. Create `backend/app/api/knowledge.py` against that fragment; do not edit shared OpenAPI or migrations.

- [ ] **Step 7: 验证并提交**

Run: `cd backend; python -m pytest tests/knowledge -q`

Commit: `feat: add reviewed cangjie concept graph seed`

### Task 5: 提交管线与确定性误区映射

**Owner:** Wave 2A 独立 Agent。

**Files:**
- Create: `backend/app/submissions/models.py`
- Create: `backend/app/submissions/service.py`
- Create: `backend/app/submissions/runner_client.py`
- Create: `backend/app/diagnostics/rules.py`
- Create: `backend/app/api/submissions.py`
- Create: `backend/tests/submissions/test_pipeline.py`
- Create: `backend/tests/diagnostics/test_rules.py`
- Create: `contracts/fragments/task-5-submissions.yaml`

**Interfaces:**
- Consumes: Task 2 actor/course policy, Task 3 runner protocol, Task 4 approved misconception lookup。
- Produces: `Submission`, `ExecutionResult`, deterministic `RuleMatch` and submission APIs used by Task 6 and Task 9。

- [ ] **Step 1: 写正常提交与执行器失败测试**

Assert successful submission persists source and real execution result. When runner is unavailable, status becomes `execution_unavailable`, the source remains saved, and no fabricated compiler diagnostics are created.

- [ ] **Step 2: 写确定性映射测试**

Given a known compiler diagnostic fixture, `match_rules` must return only approved misconception IDs with evidence references; unknown diagnostics return an empty match list.

- [ ] **Step 3: 运行失败测试**

Run: `cd backend; python -m pytest tests/submissions tests/diagnostics/test_rules.py -q`

- [ ] **Step 4: 实现提交状态机和 runner client**

States: `received`, `executing`, `executed`, `execution_unavailable`, `diagnosing`, `diagnosed`, `needs_review`. Persist every transition timestamp and request ID.

- [ ] **Step 5: 实现规则映射和 API**

Rule matches supplement AI diagnosis; they never silently rewrite code. Write submit, status and execution-result schemas to `contracts/fragments/task-5-submissions.yaml`; do not edit shared OpenAPI or migrations.

- [ ] **Step 6: 验证并提交**

Run: `cd backend; python -m pytest tests/submissions tests/diagnostics/test_rules.py -q`

Commit: `feat: add submission and compiler evidence pipeline`

### Task 6: AI 诊断、置信度与提示阶梯

**Owner:** Wave 2B 独立 Agent；必须等待 Task 5 集成完成。

**Files:**
- Create: `backend/app/model_gateway/base.py`
- Create: `backend/app/model_gateway/mock.py`
- Create: `backend/app/diagnostics/schema.py`
- Create: `backend/app/diagnostics/service.py`
- Create: `backend/app/diagnostics/hints.py`
- Create: `backend/app/diagnostics/leakage.py`
- Create: `backend/app/api/diagnostics.py`
- Create: `backend/tests/diagnostics/test_schema.py`
- Create: `backend/tests/diagnostics/test_service.py`
- Create: `backend/tests/diagnostics/test_hints.py`
- Create: `contracts/fragments/task-6-diagnostics.yaml`

**Interfaces:**
- Consumes: Task 4 approved knowledge and Task 5 submission/evidence。
- Produces: validated `Diagnosis`, four-level `HintEvent`, explanation-check result and review-queue event consumed by Tasks 7、8、9。

- [ ] **Step 1: 写结构校验测试**

Reject missing evidence, unknown concept IDs, confidence outside `[0,1]`, invalid line ranges, and free-text categories. Accept only `conceptual|strategic|procedural|expression`.

- [ ] **Step 2: 写低置信度与无编译结果测试**

Low confidence must set `requires_teacher_review=true` and cannot request memory writing. Missing execution evidence must be explicit; the model cannot invent compiler output.

- [ ] **Step 3: 写提示泄露测试**

Level 1 and 2 responses containing a complete replacement program must be rejected and regenerated with less information.

- [ ] **Step 4: 运行失败测试**

Run: `cd backend; python -m pytest tests/diagnostics -q`

- [ ] **Step 5: 实现 provider abstraction and deterministic mock**

Production provider receives redacted, authorized context. Tests use fixture-driven mock responses so CI never requires network or paid API calls.

- [ ] **Step 6: 实现诊断与四级提示状态机**

Students cannot skip policy-defined hint gates by changing request payload. Every hint upgrade stores reason and previous attempt count.

Write diagnosis, next-hint and explanation-check endpoint schemas to `contracts/fragments/task-6-diagnostics.yaml`; do not edit shared OpenAPI.

- [ ] **Step 7: 验证并提交**

Run: `cd backend; python -m pytest tests/diagnostics -q`

Commit: `feat: add evidence-bound diagnosis and hint ladder`

### Task 7: 学习记忆、授权与可验证删除

**Owner:** Wave 2C 独立 Agent；必须等待 Task 6 集成完成。

**Files:**
- Create: `backend/app/memories/models.py`
- Create: `backend/app/memories/policy.py`
- Create: `backend/app/memories/service.py`
- Create: `backend/app/memories/deletion.py`
- Create: `backend/app/audit/service.py`
- Create: `backend/app/api/memories.py`
- Create: `backend/tests/memories/test_lifecycle.py`
- Create: `backend/tests/memories/test_isolation.py`
- Create: `backend/tests/memories/test_deletion.py`
- Create: `contracts/fragments/task-7-memories.yaml`

**Interfaces:**
- Consumes: Task 2 policy and Task 6 validated high-confidence diagnoses。
- Produces: `MemoryProposal`, `LearningMemory`, `ShareGrant`, deletion receipt and authorized retrieval function used by Tasks 8、9、10。

- [ ] **Step 1: 写“模型不能直接写记忆”测试**

Only an authenticated student accepting a proposal can create an active memory. Teacher, model callback and another student must all be rejected.

- [ ] **Step 2: 写课程与所有者双重隔离测试**

Retrieval must filter by owner and course before vector search and re-check authorization after retrieval.

- [ ] **Step 3: 写删除补偿测试**

Simulate vector deletion failure. The memory must immediately become non-retrievable, be marked `deletion_pending`, and succeed after retry; the deletion receipt must not contain original text.

- [ ] **Step 4: 运行失败测试**

Run: `cd backend; python -m pytest tests/memories -q`

- [ ] **Step 5: 实现生命周期和审计**

Implement proposal, accept, reject, correct, expire, share, revoke and delete. Audit sensitive access without logging private content.

Write memory proposal, lifecycle, share-grant and deletion receipt schemas to `contracts/fragments/task-7-memories.yaml`; do not edit shared OpenAPI or migrations.

- [ ] **Step 6: 验证并提交**

Run: `cd backend; python -m pytest tests/memories -q`

Commit: `feat: add student-controlled isolated learning memory`

### Task 8: 教师匿名分析与复核队列

**Owner:** Wave 3 Agent A。

**Files:**
- Create: `backend/app/analytics/service.py`
- Create: `backend/app/analytics/schemas.py`
- Create: `backend/app/api/teacher.py`
- Create: `backend/tests/analytics/test_threshold.py`
- Create: `backend/tests/analytics/test_review_queue.py`

**Interfaces:**
- Consumes: Task 4 concepts, Task 6 diagnoses, Task 7 privacy rules。
- Produces: anonymized heatmap/trend DTOs and review queue APIs consumed by Task 9。

- [ ] **Step 1: 写所有过滤组合的小样本测试**

Course-wide, concept, exercise, time-range and combined filters must all suppress groups smaller than 5. Responses must not contain user IDs or raw submissions.

- [ ] **Step 2: 写教师复核权限测试**

Teacher can review low-confidence diagnosis for their course but cannot open the student's unrelated private conversation or memory.

- [ ] **Step 3: 运行失败测试**

Run: `cd backend; python -m pytest tests/analytics -q`

- [ ] **Step 4: 实现聚合与复核 API**

Precompute only de-identified events needed for charts. Teacher review records the decision, reason and reviewer without changing the student's private memory automatically.

Implement the frozen analytics and review-queue schemas already present in `contracts/openapi.yaml`. If implementation reveals a contract flaw, report it to the coordinator instead of changing the shared contract directly.

- [ ] **Step 5: 验证并提交**

Run: `cd backend; python -m pytest tests/analytics -q`

Commit: `feat: add privacy-preserving teacher analytics`

### Task 9: 学生端与教师端 UI

**Owner:** Wave 3 Agent B。

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/auth/session.ts`
- Create: `frontend/src/student/ExercisePage.tsx`
- Create: `frontend/src/student/DiagnosisPanel.tsx`
- Create: `frontend/src/student/MemoryCenter.tsx`
- Create: `frontend/src/teacher/CourseDashboard.tsx`
- Create: `frontend/src/teacher/ReviewQueue.tsx`
- Create: `frontend/tests/student-flow.test.tsx`
- Create: `frontend/tests/teacher-privacy.test.tsx`
- Create: `frontend/e2e/learning-loop.spec.ts`

**Interfaces:**
- Consumes: frozen OpenAPI from Tasks 2、5、6、7、8。
- Produces: complete student learning loop and teacher dashboard, with no direct database or model calls。

- [ ] **Step 1: 生成或手写类型安全 API client**

Client must preserve error envelope and request ID. Role guards improve navigation only; backend remains authoritative.

- [ ] **Step 2: 写学生闭环失败测试**

Test submit, execution unavailable state, diagnosis, hint upgrade, explanation check, memory proposal accept/reject and deletion confirmation.

- [ ] **Step 3: 写教师隐私失败测试**

Teacher dashboard must render aggregate cells and “样本不足”, and contain no UI route or client call for full private memory.

- [ ] **Step 4: 运行测试并确认失败**

Run: `cd frontend; npm test -- --run`

- [ ] **Step 5: 实现最小页面与状态**

Include loading, empty, retry, low-confidence, execution unavailable, denied access and deletion-pending states. Do not add rich IDE features beyond a code editor/text area needed for the demo.

- [ ] **Step 6: 验证并提交**

Run:

```powershell
cd frontend
npm test -- --run
npm run build
```

Commit: `feat: add student learning loop and teacher dashboard`

### Task 10: 安全、端到端和评测框架

**Owner:** Wave 3 Agent C。

**Files:**
- Create: `backend/tests/security/test_idor.py`
- Create: `backend/tests/security/test_prompt_injection.py`
- Create: `backend/tests/security/test_cross_course_memory.py`
- Create: `frontend/e2e/security.spec.ts`
- Create: `data/evaluation/cases.schema.json`
- Create: `data/evaluation/security_cases.yaml`
- Create: `data/evaluation/diagnosis_cases.yaml`
- Create: `docs/experiments/protocol.md`
- Create: `docs/experiments/results-template.md`

**Interfaces:**
- Consumes: complete backend and UI contracts。
- Produces: repeatable attack suite, diagnosis evaluation schema and non-fabricated experiment protocol。

- [ ] **Step 1: 建立评测数据 schema**

Each case records case ID, course version, input, expected concept IDs, teacher annotators, evidence, privacy classification and dataset split. Real student identifiers are forbidden.

- [ ] **Step 2: 写 IDOR、跨课程和提示注入测试**

Use at least two students, one teacher and two courses. Assert identical public denial for nonexistent and unauthorized resources; assert no sensitive text reaches mock model request capture.

- [ ] **Step 3: 写删除后检索与小样本测试**

Run deletion, retry the original semantic query, and assert no result. Apply multiple analytics filters and assert all groups below 5 remain suppressed.

- [ ] **Step 4: 写实验协议**

Define three groups: generic LLM, compiler explanation only, full KnowBound. Pre-register diagnosis accuracy, independent repair, recurrence, transfer accuracy, answer leakage and security success metrics. Clearly label target values.

- [ ] **Step 5: 验证并提交**

Run:

```powershell
cd backend
python -m pytest tests/security -q
cd ..\frontend
npx playwright test
```

Commit: `test: add security and education evaluation harness`

### Task 11: 全量集成与比赛交付基线

**Owner:** 协调 Agent，串行执行，随后由新鲜复核 Agent 进行全项目审查。

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `infra/compose/docker-compose.yml`
- Create: `docs/demo-script.md`
- Create: `docs/operations.md`
- Create: `docs/security-report.md`
- Create: `docs/evaluation-report.md`

**Interfaces:**
- Consumes: Tasks 1—10 的全部交付物。
- Produces: one-command local demo, verified full test suite and evidence package baseline。

- [ ] **Step 1: 检查任务交接和文件冲突**

Review every agent summary, migration order, OpenAPI diff, Compose diff and dependency addition. Reject changes that violate the spec or lack tests.

- [ ] **Step 2: 从干净环境启动**

Run:

```powershell
docker compose -f infra/compose/docker-compose.yml build
docker compose -f infra/compose/docker-compose.yml up -d
docker compose -f infra/compose/docker-compose.yml ps
```

Expected: api, web, postgres and runner healthy; runner has no public port.

- [ ] **Step 3: 运行全部验证**

Run backend, runner, frontend unit tests, Playwright, migration-upgrade test, security suite and OpenAPI validation. Record exact commands and outputs in `docs/operations.md`.

- [ ] **Step 4: 执行比赛演示彩排**

Demonstrate one Cangjie misconception from submission through repair, memory confirmation, cross-user denial, teacher aggregate display and deletion verification. The path must use live services, not hard-coded screenshots.

- [ ] **Step 5: 完成交付文档但不伪造成效**

Populate reports only with verified results. If the real student pilot has not occurred, leave the actual-results tables structurally empty with the explicit status “尚未开展试点”，而不是复制目标值。

- [ ] **Step 6: 最终复核与提交**

Use a fresh review Agent to compare the repository against every spec section, then fix blocking findings and rerun the full suite.

Commit: `docs: finalize verified demo and competition evidence baseline`

## 2. Copy-Paste Agent Prompt Template

协调 Agent 派发任务时使用以下模板，不要只说“完成某模块”：

```text
你负责 Implementation Plan 的 Task <编号和名称>。

开始前必须完整阅读：
1. AGENTS.md
2. docs/superpowers/specs/2026-10-01-knowbound-cangjie-design.md
3. docs/superpowers/plans/2026-10-01-knowbound-cangjie-implementation.md 中你的 Task
4. 任务依赖产生的接口、测试和 ADR

范围：只修改 Task 的 Files 列表；若必须修改共享文件，先报告原因并等待协调者处理。
要求：测试先行；不得扩大产品范围；不得添加助教角色；不得改变教师隐私边界；仓颉语义必须查询 cangjie-coding 并用当前工具链验证。

完成后返回：
- 完成与未完成内容
- 修改文件
- 验证命令及结果
- 数据库/API/配置变更
- 已知风险和后续依赖
不要自行开始下一个 Task。
```

## 3. Coordinator Review Checklist

每个 Agent 返回后，协调者必须：

- 阅读实现摘要和实际 diff；
- 确认没有越权修改其他任务文件；
- 运行该任务的精确测试；
- 检查 OpenAPI、数据库迁移和类型名称是否一致；
- 让新鲜复核 Agent 进行代码审查；
- 修复审查问题后再次测试；
- 只有当前波次全部通过才派发下一波。

最终不得把多个 Agent 的“各自测试通过”当作系统通过；必须从干净环境执行全量集成验证。
