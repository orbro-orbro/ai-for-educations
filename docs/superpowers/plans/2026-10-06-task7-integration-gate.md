# Wave 2C Task 7 Integration Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把提交 `f4ad8d8b13ce340fc0d1085ddec0fc9c95bf185b` 中已经完成的 Task 7 领域实现接入 PostgreSQL、应用组合根和共享 OpenAPI，并用真实 PostgreSQL、真实隔离 Runner 与确定性 Mock Provider 形成可复验的 Gate 结论。

**Architecture:** 领域服务继续只依赖 `MemoryRepository`、`MemorySource`、`RetrievalIndex` 和 `AuditLog` Protocol；新增的 SQL Repository、SQL 审计和 Task 6 来源适配共享同一个 SQLAlchemy Unit of Work，使权威状态与审计在同一事务提交。PostgreSQL 复合外键、唯一约束、部分唯一索引和 `SELECT ... FOR UPDATE` 共同兑现跨课程隔离、单一 active 版本、幂等和单调删除；检索索引仍是可替换派生层，失败后由持久化删除请求恢复补偿。

**Tech Stack:** Python 3.12、FastAPI、Pydantic 2、SQLAlchemy 2、Alembic、PostgreSQL 17/pgvector 镜像、pytest、Docker Compose、仓颉 1.2.0 STS cjnative。

**Spec:** `docs/superpowers/specs/2026-10-01-knowbound-cangjie-design.md`；权限与删除语义以 `docs/adr/0004-learning-memory-authorization-and-deletion.md` 为最终依据。

## Global Constraints

- Gate 分支为 `codex/wave2-task7-gate`，直接建立在 `f4ad8d8b13ce340fc0d1085ddec0fc9c95bf185b`；`main` 保持 `8aa21ab7ee375f04cf6a1f615a9c004c36355c9b`。
- 首个试点课程固定为《仓颉语言设计》，只有 `student` 与 `teacher` 两种角色。
- 模型只能形成 `MemoryProposal`；只有所属学生明确接受后才能形成 active `LearningMemory`。
- 教师默认不能读取 `MemoryProposal`、`LearningMemory` 正文或私人对话；`ShareGrant` 只覆盖一个诊断摘要。
- 所有私人记忆授权同时要求 `owner_user_id` 与 `course_id` 匹配；删除权威事务提交后立即停止全部检索。
- PostgreSQL 是权限和状态的唯一权威事实源；不增加外部向量数据库、消息队列或其他生产基础设施。
- 不实现或挂载 Task 8、Task 9、Task 10 业务；Wave 3 只冻结共享契约。
- 不调用真实或付费模型；测试只使用确定性 Mock Provider。
- 任何改变 ADR 0004 权限、共享范围、删除状态机或隐私边界的发现都立即停止产品修改，先提交 ADR 变更给用户确认。
- 不把 SQLite、测试替身、目标值或模拟数据描述成真实 PostgreSQL、真实向量数据库、真实模型或真实试点结果。

## Review Focus

- 相同幂等键被用于另一资源或另一纠正正文时必须返回稳定 409，不能静默复用第一次结果；Task 3、Task 5 覆盖。
- 接受后的索引发布与删除并发时，迟到的 `upsert` 不能在 tombstone 后复活文档；Task 3、Task 6 覆盖。
- 审计插入失败必须回滚接受、纠正、授权、撤销和删除的全部关系状态；Task 3、Task 6 覆盖。
- 进程重建后仅依靠 PostgreSQL 删除请求即可继续未完成步骤，且 `deleted` 永不倒退；Task 6 覆盖。
- Wave 3 任意分析过滤组合低于 5 个样本时不得返回精确样本量、明细或可推断身份字段；Task 1 覆盖。

---

## 1. 已核对基线与真实代码映射

### 1.1 Git 与环境

- `main`、`origin/main` 当前均为 `8aa21ab7ee375f04cf6a1f615a9c004c36355c9b`。
- `codex/wave2-task7-memories` 与已核对 Task 7 最终提交均为 `f4ad8d8b13ce340fc0d1085ddec0fc9c95bf185b`，且 `8aa21ab` 是其祖先。
- Gate worktree 已创建在 `C:\Users\lenovo\Desktop\cs competition\.worktrees\wave2-task7-gate`，当前分支为 `codex/wave2-task7-gate`。
- 本机 `cjc -v` 返回 `1.2.0 (cjnative)`；当前 `cjpm -v` 因用户目录 `.cjpm` 无法 canonicalize 而失败，必须在真实 Runner 容器内完成 Runner Gate。
- 系统 Python 缺少 pytest；根 `.venv` 指向已不存在的 Miniconda，Task 7 分支 `.venv` 也未安装 pytest。执行阶段先使用声明在 `backend/pyproject.toml` 的 `.[dev]` 建立 Gate 专用虚拟环境，或在隔离 Linux API 测试容器中运行同一命令。
- 当前沙箱连接 Docker Desktop daemon 返回 permission denied。执行阶段先申请 Docker 命令权限；若宿主端口不可达，则使用同一专用 Compose 网络内的测试容器，仍连接真实 PostgreSQL 与真实 Runner。

### 1.2 Task 7 Protocol 到 SQL 实现

| 现有接口 | SQL 实现 | 权威事务/锁 |
|---|---|---|
| `MemoryRepository.transaction()` | `SqlMemoryRepository.transaction()` 委托 `SqlMemoryUnitOfWork.transaction()` | 最外层创建 Session 与事务；嵌套调用复用 ContextVar 中同一 Session |
| `proposal_claim(proposal_id)` | 锁 `memory_proposals.id` | `SELECT ... FOR UPDATE`；接受、拒绝、纠正、过期共用 |
| `memory_claim(logical_memory_id)` | 锁 root 记忆及版本链 | 先锁 root，再按 `version,id` 锁整链；纠正、过期、索引发布、删除、重试共用 |
| `deletion_claim(deletion_id)` | 锁 `memory_deletions.id` | 只在已先锁 logical memory 后取得；重复重试串行化 |
| `grant_claim(grant_id)` | 锁 `share_grants.id` | 撤销、过期、读取复核共用 |
| 提议 CRUD/版本/来源查询 | `memory_proposals` | `explanation_check_id` 唯一；`root_proposal_id + version` 唯一 |
| 记忆 CRUD/版本/候选查询 | `learning_memories` | `source_proposal_id` 唯一；`logical_memory_id + version` 唯一；每条逻辑链最多一个 active |
| 授权 CRUD/资源查询 | `share_grants` | 诊断所有者/课程复合外键；教师管理权每次从 `courses`/`course_authorized_teachers` 重验 |
| 删除 CRUD/逻辑链查询 | `memory_deletions` + `memory_tombstones` | `logical_memory_id` 唯一；状态只允许 pending→deleted |
| 纠正/授权等重放结果 | `memory_idempotency_results` | `(actor_user_id, operation, idempotency_key)` 唯一，并校验资源与请求指纹 |
| `AuditLog.transaction/record` | `SqlAuditLog` + `audit_events` | 与 Memory Repository 共享 Unit of Work；插入失败导致整个权威事务回滚 |
| `MemorySource.proposal_source/diagnosis_summary` | `SqlDiagnosticMemorySource` | 只读 join `explanation_checks`、`diagnoses`、`submissions`、`users`、`enrollments` |

`InMemoryMemoryRepository`、`AuditService` 和 `InMemoryRetrievalIndex` 保留为快速领域测试替身；Gate 结论不依赖它们证明 PostgreSQL 并发或约束。

### 1.3 数据表与约束设计

`0005_memories_audit.py` 只创建以下 Task 7 表，并给 Task 6 表补上供复合外键引用的唯一键：

1. `memory_proposals`
   - 主键 `id`；服务端字段 `owner_user_id`、`course_id`、`diagnosis_id`、`explanation_check_id`。
   - `UNIQUE(explanation_check_id)`：一个 ExplanationCheck 最多一个提议根。
   - `UNIQUE(root_proposal_id, version)`、`UNIQUE(previous_proposal_id)`、`UNIQUE(id, owner_user_id, course_id)`；非空 previous 只能有一个后继，禁止并发纠正分叉。
   - 复合外键 `(diagnosis_id, course_id, owner_user_id)` 指向 `diagnoses`；`(explanation_check_id, diagnosis_id)` 指向 `explanation_checks`；root/previous 自引用同时携带 owner/course，禁止跨学生或跨课程拼链。
   - CHECK：状态仅 `pending|accepted|rejected|superseded|expired`、`version >= 1`、`confidence BETWEEN 0 AND 1`、`expires_at > created_at`。
   - 索引：`(owner_user_id, course_id, status, expires_at)`、`(root_proposal_id, version)`。
2. `learning_memories`
   - 主键 `id`；`logical_memory_id` 固定指向首版本，`previous_version_id` 形成不可变链。
   - `UNIQUE(source_proposal_id)`：一个提议最多激活一个长期记忆。
   - `UNIQUE(logical_memory_id, version)`、`UNIQUE(previous_version_id)`、`UNIQUE(index_document_id)`、`UNIQUE(id, owner_user_id, course_id)`；非空 previous 只能有一个后继。
   - 复合外键到 proposal、diagnosis 与自引用版本链；owner/course 必须全程一致。
   - PostgreSQL 部分唯一索引 `uq_learning_memories_one_active`：`(logical_memory_id) WHERE status='active'`。
   - CHECK：合法状态、`visibility='private'`、`version >= 1`、置信度范围；`deletion_pending|deleted` 时 `content IS NULL`。
   - 索引：`(owner_user_id, course_id, status, expires_at)`、`(logical_memory_id, version)`。
3. `share_grants`
   - 复合外键 `(resource_id, course_id, owner_user_id)` 指向同一诊断；受让人 FK 指向用户。
   - CHECK：`resource_type='diagnosis_summary'`；状态仅 `active|revoked|expired`；撤销时间与状态一致。
   - 唯一键覆盖学生、诊断、教师、幂等结果；读取时仍重验教师当前课程管理权。
4. `memory_deletions`
   - 主键 `id`；`UNIQUE(logical_memory_id)` 保证每条逻辑记忆只有一个权威删除请求。
   - 复合外键把 logical memory、owner、course 绑定在同一链。
   - CHECK：状态仅 `deletion_pending|deleted`、计数非负、完成状态要求 `completed_at`、全部清理布尔值及反向验证为真；pending 不允许倒写 deleted 数据。
5. `memory_tombstones`
   - `logical_memory_id` 与 `deletion_id` 均唯一；只保存 owner/course、建立时间和非敏感删除关联，不保存正文、摘要、哈希、向量或内部索引 ID。
6. `audit_events`
   - 只含 ADR 0004 允许的元数据字段；CHECK 限制 actor role 与结果字段，按 `(course_id, created_at)`、`(target_type,target_id)` 建索引。
7. `memory_idempotency_results`
   - 唯一键 `(actor_user_id, operation, idempotency_key)`；保存资源类型/ID、内部请求指纹、结果类型/ID与时间。
   - 请求指纹只用于检测同键不同 payload，不进入 API、审计、日志或删除凭证。
8. Task 6 补充唯一约束
   - `diagnoses(id, course_id, owner_user_id)`。
   - `explanation_checks(id, diagnosis_id)`。

仅靠约束无法表达“受让教师当前仍管理课程”“状态只能沿特定边转换”“旧快照不得覆盖 tombstone”。这些由复合外键 + 行锁 + 事务内重新读取共同保证，并由真实 PostgreSQL 竞态测试固定。

### 1.4 固定锁顺序与事务边界

所有代码路径使用同一顺序，未涉及的层级跳过：

```text
proposal row
  → logical-memory root and lineage (version,id ascending)
  → deletion row
  → related grant rows (grant_id ascending)
  → idempotency row
  → state writes
  → audit insert
```

- 接受：锁 proposal；同一事务校验并写 memory、proposal accepted、幂等结果、审计；提交后再锁 logical memory，重读 active/tombstone 状态后才发布索引。
- 提议纠正/拒绝/过期：锁 proposal；状态、版本、幂等与审计同事务。
- 记忆纠正/过期：锁 logical chain；废止旧版本、创建新 active、幂等与审计同事务；提交前由部分唯一索引兜底。
- 授权创建/撤销：锁诊断/课程权限事实或 grant；授权、幂等与审计同事务。
- 删除权威阶段：锁 logical chain，再锁已有 deletion 和相关 grant；清空全链正文、置 `deletion_pending`、撤销相关授权、创建/复用 deletion 与 tombstone、写幂等和审计后一次提交。
- 删除补偿：先由 deletion 读出 logical ID，再按 logical memory→deletion 顺序加锁；每一步只在相应布尔值为 false 时执行；成功反查后在同一事务把全链和 receipt 置 `deleted` 并写审计。
- 当前项目没有独立缓存或未完成模型任务存储，因此 `cache_cleared` 与 `model_references_cleared` 由显式的确定性 no-op cleanup ports 验证“无该派生层”后置 true；它们不伪装成外部基础设施。检索索引仍是唯一可能失败并需要跨重启重试的派生步骤。
- `deleted` 更新使用条件式 SQL 或锁后重读；过期、纠正和失败重试若看到 `deletion_pending|deleted` 均不得写回旧状态。
- 派生索引调用不参与权威事务。索引发布在 logical-memory 锁内重读状态；索引删除失败只更新脱敏错误码，关系数据仍保持不可检索。

### 1.5 幂等作用域

API 写操作增加必需的 `Idempotency-Key` header，`X-Request-ID` 继续只承担追踪。领域方法新增 `idempotency_key` 参数，直接服务调用测试必须显式提供。

```python
def claim_idempotency(
    *, actor_user_id: str, operation: str, idempotency_key: str,
    resource_type: str, resource_id: str, request_fingerprint: str,
) -> IdempotencyReplay | None: ...

def remember_idempotency_result(
    *, actor_user_id: str, operation: str, idempotency_key: str,
    resource_type: str, resource_id: str, request_fingerprint: str,
    result_type: str, result_id: str,
) -> None: ...
```

作用域是 `(actor_user_id, operation, idempotency_key)`。相同作用域、资源和请求指纹返回第一次结果；相同键换资源或换纠正正文返回 `IDEMPOTENCY_KEY_REUSED` 409。指纹是服务端 canonical JSON 的 SHA-256，仅存内部表，不返回、不审计、不记录日志。

### 1.6 Task 6 → Task 7 适配与提议触发

`SqlDiagnosticMemorySource.proposal_source(explanation_check_id)` 使用一次 SQL join 验证：check 存在且 eligible/understands；Diagnosis 存在且无需教师复核；Diagnosis、check、Submission 关系一致；owner/course 一致；用户 active、角色 student 且仍有课程 enrollment；check 与 diagnosis 置信度均达到当前 `DIAGNOSIS_CONFIDENCE_THRESHOLD`；check concepts 非空且为 diagnosis concepts 子集。

客户端仍只向 `/diagnoses/{diagnosis_id}/explanation-check` 提交 `{"explanation": "..."}`。`create_diagnostics_router` 接受一个可选的服务端 hook；ExplanationCheck 成功持久化后，hook 对 eligible 结果调用 `MemoryService.create_proposal`。如果提议事务失败，返回脱敏 503；ExplanationCheck 已持久化，使用同一幂等键重试会重放 check 并再次触发 proposal，`UNIQUE(explanation_check_id)` 保证只产生一个根提议。不新增客户端直接创建 LearningMemory 或提交 owner/course/confidence/eligibility 的入口。

### 1.7 Wave 3 冻结 DTO

共享 OpenAPI 增加以下三个路径但不挂载 Router，并在 operation 上写入 `x-contract-status: frozen-for-wave-3`：

```yaml
GET /teacher/courses/{course_id}/analytics
  operationId: getTeacherCourseAnalytics
  query: concept_id?, exercise_id?, start_at?, end_at?
  response: oneOf TeacherAnalyticsAvailable | TeacherAnalyticsSuppressed

GET /teacher/courses/{course_id}/review-queue
  operationId: listTeacherReviewQueue
  query: concept_id?, exercise_id?, start_at?, end_at?
  response: TeacherReviewQueue

POST /teacher/diagnoses/{diagnosis_id}/review
  operationId: reviewTeacherDiagnosis
  request: TeacherDiagnosisReviewRequest
  response: TeacherDiagnosisReview
```

精确 schema：

- `TeacherAnalyticsFilters`：只含 nullable `concept_id`、`exercise_id`、`start_at`、`end_at`。
- `TeacherAnalyticsAvailable`：`status=available`、`course_id`、`filters`、`minimum_sample_size=5`、`sample_size(minimum:5)`、`groups: TeacherAnalyticsGroup[]`。
- `TeacherAnalyticsGroup`：只含 `concept_id`、nullable `exercise_id`、`category`、`sample_size(minimum:5)`、`diagnosis_count`、`independent_repair_count`；不含任何用户或私人字段。
- `TeacherAnalyticsSuppressed`：只含 `status=insufficient_sample`、`course_id`、`filters`、`minimum_sample_size=5`；没有精确样本量、groups 或明细。
- `TeacherReviewQueue`：`course_id`、`filters`、`items`。
- `TeacherReviewQueueItem`：只含 `queue_event_id`、`diagnosis_id`、`submission_id`、`exercise_id`、`category`、`concept_ids`、`root_cause`、`evidence_summaries`、`confidence`、`review_reason`、`queued_at`；不含学生 ID、用户名、邮箱、私人对话、原始代码、完整提交或长期记忆正文。
- `TeacherDiagnosisReviewRequest`：严格对象，`decision` 仅 `confirmed|overturned|insufficient_evidence`，`reason` 必填且 1–2000 字符。
- `TeacherDiagnosisReview`：`diagnosis_id`、`course_id`、服务端只读 `reviewer_user_id`、`decision`、`reason`、`reviewed_at`；描述明确复核不创建、修改或激活 LearningMemory。

所有三个操作要求 Bearer、管理课程的教师权限，并声明 401/404/409/422/503。Task 8 实现只能消费该契约；契约缺陷必须回到 Gate 协调者处理。

### 1.8 高冲突文件与影响

| 文件 | 计划变更 | 影响 |
|---|---|---|
| `backend/app/main.py` | 注入 Memory SQL/内存依赖、挂载 Router、注册 explanation hook 和 app state | 改变组合根，不改变既有 Task 2/4/5/6 路径 |
| `backend/app/api/errors.py` | 注册 Memory persistence 与幂等冲突的稳定错误 | 统一 503/409，响应保持脱敏与 request ID |
| `backend/app/persistence/models.py` | 注册七张 Task 7 表及 Task 6 复合唯一键 | Alembic metadata 与 `alembic check` 的事实源 |
| `backend/app/persistence/repositories.py` | 扩展 `SqlRepositories` 工厂 | 使用 DATABASE_URL 时正式返回 memories/audit/source |
| `backend/migrations/versions/0005_memories_audit.py` | 唯一新迁移，down revision 为 `0004_diagnostics_hints` | 可逆新增 Task 7 schema；不删除 Task 2/4/5/6 数据 |
| `contracts/openapi.yaml` | 语义合并 Task 7，冻结 Wave 3 | 共享 API 版本提升，保留既有路径、schema、response、operation ID |

`infra/compose/docker-compose.yml`、`.env.example` 和根级配置预计不修改。真实 Gate 使用独立 project 名与测试 override/CLI 端口，不增加服务或环境变量；若执行阶段证明现有 Compose 无法完成同网络验证，先把具体阻塞报告给用户，不静默修改基础设施。

---

## Task 1: 先以失败测试冻结 Task 7 与 Wave 3 共享契约

**Files:**
- Create: `backend/tests/contracts/test_task7_openapi.py`
- Create: `backend/tests/contracts/test_wave3_openapi.py`
- Modify: `backend/tests/contracts/test_openapi_runtime.py`
- Modify: `contracts/openapi.yaml`
- Modify: `backend/app/api/memories.py`

**Interfaces:**
- Consumes: `contracts/fragments/task-7-memories.yaml`、现有统一 response 与 Bearer 组件。
- Produces: Task 7 共享路径/DTO、必需 `Idempotency-Key`、Wave 3 冻结 DTO 和 runtime/shared 语义比较器。

- [ ] **Step 1: 写 Task 7 合并 RED 测试**

测试逐项断言 12 个 Task 7 路径存在、operation ID 全局唯一、Bearer、错误状态、严格 request schema、readOnly/writeOnly、删除凭证禁止字段，以及原 Task 2/4/5/6 path/schema/response 集合未减少。

```python
def test_task7_mutations_require_scoped_idempotency_and_stable_errors():
    document = load_contract()
    for path, method in TASK7_MUTATIONS:
        operation = document["paths"][path][method]
        assert {"401", "404", "409", "422", "503"} <= set(operation["responses"])
        assert {p["$ref"] for p in operation["parameters"]} >= {
            "#/components/parameters/IdempotencyKey"
        }
```

- [ ] **Step 2: 写 Wave 3 隐私 RED 测试**

```python
def test_suppressed_analytics_has_no_exact_count_or_details():
    schema = schemas()["TeacherAnalyticsSuppressed"]
    assert set(schema["properties"]) == {
        "status", "course_id", "filters", "minimum_sample_size"
    }
    assert schema["properties"]["status"]["const"] == "insufficient_sample"

def test_teacher_dtos_exclude_private_and_identity_fields():
    forbidden = {"owner_user_id", "username", "email", "source_code",
                 "submission", "conversation", "memory_content"}
    for name in ("TeacherAnalyticsGroup", "TeacherReviewQueueItem"):
        assert forbidden.isdisjoint(schemas()[name]["properties"])
```

- [ ] **Step 3: 运行 RED**

Run: `python -m pytest tests/contracts/test_task7_openapi.py tests/contracts/test_wave3_openapi.py tests/contracts/test_openapi_runtime.py -q`

Expected: FAIL，因为共享契约尚无 Task 7/Wave 3 路径，runtime 尚未声明 Task 7 稳定错误和幂等 header。

- [ ] **Step 4: 语义合并 OpenAPI 并对齐 runtime DTO**

保留共享文档现有 components，复用 `ErrorResponse`、`DiagnosisId`、`CourseId` 和公共 responses；仅为缺失名称增加 Task 7 参数/schema。将 `api/memories.py` 的 Pydantic DTO 命名/标题与共享 schema 对齐，并为每个 endpoint 声明 `_ERROR_RESPONSES` 与 `Idempotency-Key`。

- [ ] **Step 5: 运行 GREEN 与既有契约回归**

Run: `python -m pytest tests/contracts -q`

Expected: PASS；旧 path/component/operationId 未丢失，runtime Task 7 操作在共享契约中逐项一致；三个 Wave 3 path 只存在于 shared contract。

- [ ] **Step 6: Commit**

```powershell
git add contracts/openapi.yaml backend/app/api/memories.py backend/tests/contracts
git commit -m "feat: freeze Task 7 and Wave 3 API contracts"
```

## Task 2: 以失败迁移测试定义 `0005_memories_audit`

**Files:**
- Create: `backend/tests/persistence/test_task7_migration_contract.py`
- Create: `backend/migrations/versions/0005_memories_audit.py`
- Modify: `backend/app/persistence/models.py`

**Interfaces:**
- Consumes: `0004_diagnostics_hints`、`Base.metadata`、Task 6 复合关系。
- Produces: 七张 Task 7 表、复合外键/唯一键/CHECK/索引，以及可逆 0005 schema。

- [ ] **Step 1: 写 migration metadata RED 测试**

断言只有一个新版本、revision/down_revision 精确、表与命名约束完整；对 `LearningMemoryRow` 断言 active 部分唯一索引，对删除/审计表断言无私人字段。

```python
def test_task7_migration_extends_the_real_head_once():
    migration = load_module("0005_memories_audit.py")
    assert migration.revision == "0005_memories_audit"
    assert migration.down_revision == "0004_diagnostics_hints"
    assert not (VERSIONS / "0004_memories_audit.py").exists()
```

- [ ] **Step 2: 运行 RED**

Run: `python -m pytest tests/persistence/test_task7_migration_contract.py -q`

Expected: FAIL，迁移与 ORM rows 尚不存在。

- [ ] **Step 3: 添加 ORM rows 与明确命名约束**

在 `models.py` 增加 `MemoryProposalRow`、`LearningMemoryRow`、`ShareGrantRow`、`MemoryDeletionRow`、`MemoryTombstoneRow`、`AuditEventRow`、`MemoryIdempotencyResultRow`。所有时间列使用 `DateTime(timezone=True)`；JSON tuple 字段在 adapter 边界转 list/tuple。

- [ ] **Step 4: 实现升级与降级**

升级先给 Task 6 表增加复合唯一键，再按 proposal→memory→grant→deletion→tombstone→idempotency→audit 顺序建表/索引。降级严格反序删除 Task 7 表/索引，再移除新增 Task 6 唯一键，不改动或清空 Task 2/4/5/6 行。

- [ ] **Step 5: 运行 GREEN 与 metadata 回归**

Run: `python -m pytest tests/persistence/test_task7_migration_contract.py tests/persistence/test_migration_contract.py -q`

Expected: PASS。

- [ ] **Step 6: Commit**

```powershell
git add backend/app/persistence/models.py backend/migrations/versions/0005_memories_audit.py backend/tests/persistence
git commit -m "feat: add Task 7 memory and audit schema"
```

## Task 3: SQL Unit of Work、Repository、审计与 Task 6 来源适配

**Files:**
- Create: `backend/app/memories/persistence.py`
- Create: `backend/app/memories/source.py`
- Create: `backend/app/audit/persistence.py`
- Create: `backend/tests/persistence/test_memory_repository.py`
- Modify: `backend/app/memories/repository.py`
- Modify: `backend/app/memories/service.py`
- Modify: `backend/app/memories/deletion.py`
- Modify: `backend/app/audit/service.py`
- Modify: `backend/app/persistence/repositories.py`

**Interfaces:**
- Consumes: Task 7 Protocol 与 Task 6 SQL rows。
- Produces: `SqlMemoryUnitOfWork`、`SqlMemoryRepository`、`SqlAuditLog`、`SqlDiagnosticMemorySource`、统一幂等接口与 `MemoryPersistenceError`。

- [ ] **Step 1: 写跨实例重建与时区 RED 测试**

使用临时 SQL 数据库做快速 adapter 反馈：实例 A 写 proposal/memory/grant/deletion，实例 B 完整重建 dataclass；所有 datetime `utcoffset()` 非空。该测试不用于声明 PostgreSQL Gate 通过。

- [ ] **Step 2: 写原子审计失败 RED 测试**

注入 `SqlAuditLog.record` flush 失败，断言接受后 proposal 仍 pending、没有 memory；对 correction/grant/revoke/delete 重复相同断言。

- [ ] **Step 3: 写幂等冲突 RED 测试**

```python
def test_same_key_cannot_change_memory_correction_body(sql_fixture):
    first = service.correct_memory(owner, memory_id, "first", request_id="r1", idempotency_key="k1")
    with pytest.raises(IdempotencyConflict):
        service.correct_memory(owner, memory_id, "different", request_id="r2", idempotency_key="k1")
    assert repository.memory_successor(memory_id) == first
```

另测相同 key 换 proposal/memory/diagnosis 资源返回同一稳定冲突。

- [ ] **Step 4: 运行 RED**

Run: `python -m pytest tests/persistence/test_memory_repository.py tests/memories -q`

Expected: FAIL，因为 SQL adapter、共享事务与统一幂等尚不存在。

- [ ] **Step 5: 实现共享 Unit of Work**

`SqlMemoryUnitOfWork` 维护 ContextVar Session。最外层 `transaction()` 使用 `sessions.begin()`；claim context 在同一 session 执行 `FOR UPDATE`；`SqlAuditLog.transaction()` 在 active UoW 中只 join，不单独 commit。无 active UoW 的敏感读取审计独立开启短事务，失败后异常在 DTO 返回前抛出。

- [ ] **Step 6: 实现完整 SQL Repository 映射**

实现 Protocol 的每个方法和 dataclass 转换；捕获 `IntegrityError/SQLAlchemyError` 后统一抛 `MemoryPersistenceError("memory storage operation failed")`，不向上泄露 SQL。删除/纠正保存使用锁后当前 row，而不是调用前 stale dataclass。

- [ ] **Step 7: 实现 SQL Audit 与 SQL MemorySource**

审计只接收 `AuditEvent` 已允许字段。来源 adapter 使用 join 返回 `MemoryProposalSource` / `DiagnosisSummary`，不遍历全部 explanation checks，不接受客户端 owner/course/confidence/eligibility。

- [ ] **Step 8: 把服务状态转换接入统一幂等与锁顺序**

为 accept/reject/proposal correction/memory correction/grant create/revoke/delete/retry 增加 idempotency claim。调整 retry 为先解析 logical ID，再按 memory→deletion 加锁；所有 expiration helper 在锁内重新读取并禁止从 deletion 状态倒退。

- [ ] **Step 9: 运行 GREEN**

Run: `python -m pytest tests/persistence/test_memory_repository.py tests/memories -q`

Expected: PASS；现有领域测试保持通过，新测试证明跨实例重建、UTC、失败关闭和幂等冲突。

- [ ] **Step 10: Commit**

```powershell
git add backend/app/memories backend/app/audit backend/app/persistence/repositories.py backend/tests/persistence/test_memory_repository.py backend/tests/memories
git commit -m "feat: persist Task 7 memory transactions"
```

## Task 4: 正式装配 Router 与 explanation-check 提议桥接

**Files:**
- Create: `backend/tests/integration/test_task7_gate.py`
- Modify: `backend/app/api/diagnostics.py`
- Modify: `backend/app/api/memories.py`
- Modify: `backend/app/api/errors.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: Task 2 Authenticator/CourseService、Task 6 services、Task 7 SQL/内存 adapters。
- Produces: 正式 Task 7 routes、app state 依赖、eligible explanation 服务端提议 hook、统一错误映射。

- [ ] **Step 1: 写组合根 RED 测试**

```python
def test_composed_application_mounts_task7_and_uses_sql_when_configured(monkeypatch, database_url):
    monkeypatch.setenv("DATABASE_URL", database_url)
    app = create_app()
    assert TASK7_ROUTES <= runtime_operations(app)
    assert isinstance(app.state.memory_repository, SqlMemoryRepository)
    assert isinstance(app.state.memory_audit, SqlAuditLog)
```

另测无 DATABASE_URL 的 test/development 仍使用内存 adapters，production 无 DATABASE_URL 继续拒绝启动。

- [ ] **Step 2: 写 API RED 测试**

覆盖缺失/畸形 Bearer 401、未知与越权同形 404、非法状态 409、额外/伪造字段 422、SQL/audit 失败脱敏 503、所有响应保留 `X-Request-ID`，以及教师无法访问 `/me/memories`。

- [ ] **Step 3: 写 explanation-check 自动提议 RED 测试**

通过现有 Task 6 endpoint 创建 eligible check，然后 GET `/me/memory-proposals` 得到一个 pending proposal；同一 explanation request 重试仍只有一个。ineligible/needs-review/低置信度不产生 proposal。

- [ ] **Step 4: 运行 RED**

Run: `python -m pytest tests/integration/test_task7_gate.py tests/memories/test_api.py -q`

Expected: FAIL，Task 7 router 未挂载、SQL dependencies 未注册、diagnostics router 没有 hook。

- [ ] **Step 5: 扩展组合根但不改变既有依赖注入兼容性**

`create_app` 增加可选 memory repository/source/index/audit/service/deletion 参数；未提供时根据 DATABASE_URL 选择 SQL 或内存 adapter。将对象存入 `application.state`，然后挂载 `create_memories_router(...)`。

- [ ] **Step 6: 添加服务端 proposal hook**

`create_diagnostics_router` 新增可选 callable；handler 先持久化 ExplanationCheck，再对 eligible 结果调用 hook。hook 的 owner 来自认证 Actor，source facts 来自 SQL join。重复调用走 `explanation_check_id` 唯一约束并返回同一 proposal。

- [ ] **Step 7: 添加错误映射和安全 responses**

`MemoryPersistenceError`→503 `STORAGE_UNAVAILABLE`；`IdempotencyConflict`→409 `IDEMPOTENCY_KEY_REUSED`；domain conflict 保持 409；所有 handler 不序列化 exception、SQL、index ID 或 token。

- [ ] **Step 8: 运行 GREEN 与受影响权限回归**

Run: `python -m pytest tests/integration/test_task7_gate.py tests/memories tests/auth tests/courses tests/diagnostics tests/submissions -q`

Expected: PASS。

- [ ] **Step 9: Commit**

```powershell
git add backend/app/main.py backend/app/api backend/tests/integration/test_task7_gate.py backend/tests/memories
git commit -m "fix: compose Task 7 memory routes"
```

## Task 5: 真实 PostgreSQL 迁移、约束、并发与回滚 Gate

**Files:**
- Create: `backend/tests/integration/test_task7_postgres.py`
- Modify: `backend/tests/persistence/test_task7_migration_contract.py`
- Modify: `backend/app/memories/persistence.py`
- Modify: `backend/app/memories/service.py`
- Modify: `backend/app/memories/deletion.py`
- Modify: `backend/migrations/versions/0005_memories_audit.py`

**Interfaces:**
- Consumes: `TASK7_POSTGRES_URL` 指向专用真实 PostgreSQL。
- Produces: Gate 核心的约束、事务与跨 Repository 并发证据。

- [ ] **Step 1: 启动隔离 PostgreSQL**

主路径：

```powershell
docker compose -p knowbound-task7-gate -f infra/compose/docker-compose.yml up -d postgres
```

使用专用 project/network/volume；不执行 `down -v` 针对任何其他 project。若无宿主端口，测试命令进入该 project 的一次性 API 测试容器并使用 `postgres:5432`。

- [ ] **Step 2: 写迁移往返 RED 集成测试/脚本**

依次执行 `upgrade 0004_diagnostics_hints`、播种 Task 2/4/5/6 sentinel、`upgrade 0005_memories_audit`、`downgrade 0004_diagnostics_hints`、核对 sentinel、再次 upgrade、`current`、`check`。

- [ ] **Step 3: 写 PostgreSQL 约束 RED 测试**

直接尝试非法状态、跨 owner/course proposal-memory 链、跨课程诊断 grant、重复 explanation proposal、重复 source proposal memory、重复 logical version、第二 active 版本和第二 deletion；断言真实数据库拒绝且原事务无部分数据。

- [ ] **Step 4: 写并发 RED 测试**

用两个独立 `create_sql_repositories(url)` 实例和 Barrier 覆盖：并发接受只返回一个 memory；并发纠正只产生一个 active；删除与过期、索引发布、补偿重试竞态；状态不能从 deleted 倒退。

- [ ] **Step 5: 写审计失败与权限撤销 RED 测试**

数据库触发器或 monkeypatch 在 audit flush 抛错，断言权威写全部回滚。删除 enrollment 或 course authorized teacher 后，新 Repository 实例立即拒绝 owner/grantee 读取。

- [ ] **Step 6: 运行 RED 并记录具体失败**

Run: `python -m pytest tests/integration/test_task7_postgres.py -q`

Expected: 新测试至少在未补齐的约束、锁或异常映射处 FAIL；记录测试名与根因，不通过删断言获得 GREEN。

- [ ] **Step 7: 最小修复约束、锁与事务**

只修改 Task 7 SQL/migration/domain glue；若失败要求改变 ADR 权限或删除状态，停止并请求用户确认。

- [ ] **Step 8: 运行 GREEN 与完整 migration 命令**

```powershell
python -m alembic upgrade 0004_diagnostics_hints
python -m alembic upgrade 0005_memories_audit
python -m alembic downgrade 0004_diagnostics_hints
python -m alembic upgrade 0005_memories_audit
python -m alembic current
python -m alembic check
python -m pytest tests/integration/test_task7_postgres.py -q
```

Expected: 全部退出码 0；current 为 `0005_memories_audit (head)`；sentinel 数据仍在。

- [ ] **Step 9: Commit**

```powershell
git add backend/app/memories backend/migrations/versions/0005_memories_audit.py backend/tests/integration/test_task7_postgres.py backend/tests/persistence/test_task7_migration_contract.py
git commit -m "fix: enforce Task 7 PostgreSQL invariants"
```

## Task 6: 删除失败、重启恢复、反向验证与敏感数据检查

**Files:**
- Create: `backend/tests/integration/test_task7_deletion_recovery.py`
- Modify: `backend/app/memories/deletion.py`
- Modify: `backend/app/memories/persistence.py`
- Modify: `backend/tests/memories/test_deletion.py`

**Interfaces:**
- Consumes: 同一 PostgreSQL 数据库和可跨 app 实例保留的确定性 RetrievalIndex 测试替身。
- Produces: pending deletion 的重启恢复、逐步补偿和 deleted 单调性证据。

- [ ] **Step 1: 写 14 步恢复 RED 测试**

按用户定义顺序创建/接受、让 index 第一次删除失败、断言立即不可见与正文清空、销毁 app/service/repository、以同一 DB 与同一测试 index 新建 app、按 deletion ID retry、反查为空、再次重启并断言 deleted、重复 delete/retry 无副作用。

- [ ] **Step 2: 写迟到 upsert 与旧快照 RED 测试**

使用 Event 暂停索引 upsert，同时让另一连接删除；断言 lock 顺序最终删除文档。另用旧 active snapshot 调用 expire/save，断言条件更新影响 0 行且 tombstone/deleted 不变。

- [ ] **Step 3: 写敏感数据扫描 RED 测试**

对 deletion receipt、audit rows、idempotency public DTO、captured logs 与 409/503 bodies 搜索私人正文、学生代码、提示词、向量、正文哈希、index key、token、堆栈；全部不得出现。

- [ ] **Step 4: 运行 RED**

Run: `python -m pytest tests/integration/test_task7_deletion_recovery.py tests/memories/test_deletion.py -q`

- [ ] **Step 5: 实现可恢复补偿的最小修复**

Repository 提供 `pending_deletions()` 与完整 receipt 重建；retry 根据各布尔字段只执行未完成步骤；完成更新带 `WHERE status='deletion_pending'`；index 删除与 verify 的失败仅保存稳定错误码。

- [ ] **Step 6: 运行 GREEN**

Run: `python -m pytest tests/integration/test_task7_deletion_recovery.py tests/memories/test_deletion.py -q`

Expected: PASS；测试说明共享 index 只是模拟外部派生存储，不是生产向量数据库证据。

- [ ] **Step 7: Commit**

```powershell
git add backend/app/memories backend/tests/integration/test_task7_deletion_recovery.py backend/tests/memories/test_deletion.py
git commit -m "fix: recover Task 7 deletion compensation"
```

## Task 7: 真实 Runner + Mock Provider + PostgreSQL 学习闭环

**Files:**
- Create: `backend/tests/integration/test_task7_closed_loop.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/integration/test_task7_gate.py`

**Interfaces:**
- Consumes: `TASK7_POSTGRES_URL`、`TASK7_RUNNER_ENDPOINT`、真实 cjc Runner、`DeterministicMockProvider`。
- Produces: Task 6→proposal→accept→restart→isolation→grant→delete 的端到端证据。

- [ ] **Step 1: 写真实闭环 RED 测试**

测试创建《仓颉语言设计》课程、两个学生、第二课程和教师；真实 Runner 执行仓颉代码；Mock Provider 生成 Diagnosis/ExplanationCheck；HTTP GET 得到自动 proposal；本人接受并持久化；重建 app 后本人可读，另一学生/另一课程/教师均 404；明确 grant 只读指定 diagnosis summary；删除失败后立即不可检索，重试到 deleted。

- [ ] **Step 2: 运行 RED**

Run: `python -m pytest tests/integration/test_task7_closed_loop.py -q`

Expected: 若 Runner、数据库或组合根仍有断点，测试以对应失败暴露；环境缺失只能记为 skip/环境故障，不能记为通过。

- [ ] **Step 3: 修复闭环内最小接线缺口**

只允许修改 Task 7 composition/adapter；不改变 Task 6 诊断语义，不调用真实模型，不实现前端或教师分析。

- [ ] **Step 4: 运行 GREEN 并重跑 Task 6 闭环**

Run: `python -m pytest tests/integration/test_task7_closed_loop.py tests/integration/test_task6_closed_loop.py -q`

Expected: 两条闭环 PASS；输出明确模型为 deterministic mock，Runner 为仓颉 1.2.0 隔离服务。

- [ ] **Step 5: Gate 集成提交**

```powershell
git add backend/app/main.py backend/tests/integration/test_task7_closed_loop.py backend/tests/integration/test_task7_gate.py
git commit -m "fix: integrate Task 7 memory pipeline"
```

## Task 8: 全量回归、独立审查与最终 Gate 判定

**Files:**
- Modify only when a failing test or Critical/Important review finding has a Task 7 root cause.
- Record results in final handoff; do not create simulated result documents.

**Interfaces:**
- Consumes: 所有前述提交。
- Produces: 可审计验证矩阵、独立审查结论、干净未合并分支。

- [ ] **Step 1: 运行受影响回归**

```powershell
python -m pytest tests/memories -q
python -m pytest tests/auth tests/courses tests/diagnostics tests/submissions tests/persistence tests/contracts -q
python -m pytest tests/integration/test_task7_gate.py tests/integration/test_task7_postgres.py tests/integration/test_task7_deletion_recovery.py tests/integration/test_task7_closed_loop.py -q
python -m pytest -q
```

逐条记录 collected/passed/failed/skipped；skip 必须写缺少的具体变量或服务。

- [ ] **Step 2: 运行静态与配置验证**

```powershell
python -m compileall -q app
python -m pip check
git diff --check
docker compose -f infra/compose/docker-compose.yml config --quiet
```

- [ ] **Step 3: 在真实仓颉沙箱运行 Runner 测试**

Run: `python -m pytest ../runner/tests -q`，环境必须是包含真实 `cjc` 的 sandbox/controller 拓扑；Windows 宿主结果不能替代容器隔离结论。

- [ ] **Step 4: 进行只读独立代码审查**

审查范围严格限制为 ADR 0004、约束、原子性、锁顺序、幂等作用域、删除单调性、重启恢复、owner/course 隔离、教师权限、审计/日志脱敏、OpenAPI 漂移与 Wave 3 小样本隐私。审查者不得直接修改代码。

- [ ] **Step 5: 对 Critical/Important 发现执行 RED→GREEN**

每个发现先补失败测试，再最小修复并重跑其相关测试；最后重跑 Task 7 PostgreSQL、删除恢复、闭环和完整后端套件。Minor 只记录，不扩大到 Task 8/9/10。

- [ ] **Step 6: 清理本 Gate 资源并复核 Git 状态**

只停止/删除 `knowbound-task7-gate` project 创建的容器、网络与临时 volume；保留 Task 7/Gate worktree。运行：

```powershell
git merge-base --is-ancestor f4ad8d8 HEAD
git status --short --branch
git log --oneline --decorate 8aa21ab..HEAD
```

Expected: Task 7 原提交仍在历史，分支为 `codex/wave2-task7-gate`，工作树干净；没有 merge、rebase、push、PR 或 worktree 删除。

- [ ] **Step 7: 按证据给出 Gate 结论**

只有迁移往返、真实 PostgreSQL 约束/并发/事务、真实 Runner 闭环、重启删除恢复、权限隔离、runtime/shared OpenAPI、全量回归全部有真实通过证据时写“通过”。任一核心证据缺失时写“未通过”或“部分完成”，并把环境故障、skip 与业务失败分开列出。

---

## 2. PostgreSQL 与 Compose 验证方式

优先使用 project `knowbound-task7-gate` 启动现有 `postgres`、`runner-controller`、`runner-sandbox`，其网络与 volume 名均由 project 隔离。宿主可访问时为 Gate 数据库临时绑定 loopback 高位端口并设置 `TASK7_POSTGRES_URL`；宿主不可访问时，在同一 project network 的一次性 API 测试容器中设置：

```text
TASK7_POSTGRES_URL=postgresql+psycopg://knowbound:change-me@postgres:5432/knowbound
TASK7_RUNNER_ENDPOINT=http://runner-controller:8080
MODEL_PROVIDER=mock
```

测试容器必须从当前 Gate worktree 构建，安装项目已经声明的 `.[dev]`，不得向仓库增加依赖。真实 PostgreSQL 版本通过 `SELECT version()` 记录；Runner 版本从真实 `RunnerResult.toolchain.cjc/cjpm/backend` 记录。

## 3. RED/GREEN 证据记录规则

每个任务第一次 RED 保存命令、失败测试名和核心错误；GREEN 保存同一命令的 passed/failed/skipped 数量。因缺少环境变量的 pytest skip、Docker daemon 权限问题、Windows 虚拟环境损坏、Runner/cjpm 环境问题分别标为“跳过”或“环境故障”，不归入通过。修复不得删除断言、降低匿名阈值、放宽 owner/course/teacher 校验或把 PostgreSQL 测试切换到 SQLite。

## 4. 最终交接清单

最终交接按用户要求逐项报告：Gate 结论；完成/未完成；全部修改文件；每条命令与实际结果；主要 RED→GREEN；PostgreSQL 版本与连接方式；迁移 upgrade/downgrade/upgrade/current/check；真实 Runner/Mock 闭环；并发/事务/约束；删除失败/立即不可见/重启恢复/反查；API/OpenAPI 与 Wave 3 契约；数据库/Compose/env/config 变化；权限隐私日志审计；真实或付费模型调用为否；独立审查与修复；风险及 Task 8/9/10 依赖；分支、最终提交、工作树状态；明确 merge/rebase/push/PR/worktree 删除均未执行。
