# Wave 3 Integration Gate — execution record

User approved the implementation plan on 2026-10-08. Work is confined to `codex/wave3-integration-gate` and its dedicated worktree.

Base: `0598a2ea1d2a5016b94cd6f35a5a0e678b76ee07` (local main, cached origin/main, and live remote agree).

Source order: `988cc2c`, `ce9fe254`, `b53b4b4`, `783bd84`, `e39f0df`.

Status: in progress. No Gate success is claimed. Daily services and source worktrees remain separate.

## G0 evidence

- Gate initializer RED: missing `tests.integration.wave3_environment`, pytest exit 1; observed before implementation.
- Main plan was copied with SHA-256 equality and its untracked original removed; no main product edit.
- Backend baseline: 79 passed. Earlier invocation had 66 passed / 13 setup errors due to inaccessible system pytest temp directory; fresh Gate basetemp resolves all 13.
- Frontend baseline: 1 passed; lockfile npm ci completed without dependency changes.
- Six synthetic databases initialized; PostgreSQL 17.11 and vector 0.8.7 verified.
- Resolved Compose isolation check passed. Actual loopback reachability initially failed (10 passed, 1 failed); Docker internal network had requested bindings but no effective host mappings.
- Ruling: attach trusted Gate PostgreSQL/controller to the already-declared public network as well as internal, with loopback-only bindings. This only changes the local test override; sandbox remains networkless and has no socket/source mount. Cost if wrong: host test resources could be unreachable; no product topology change.

## Decisions

- Ruling: execute the skill's task bookkeeping natively in PowerShell/Python rather than Bash helpers. The approved plan uses G0–G10 headings, whereas the helpers parse numbered `Task` headings. Preserve the same ledger, briefs, commit ranges and observed verification evidence. Cost if wrong: bookkeeping interoperability only.
- Ruling: preserve execution evidence in tracked handoff files rather than deleting it at completion. The user expressly requires reviewable evidence. Temporary scratch may be cleaned without deleting any worktree.

## G1 integration

- Task 8 source integrated with `-x`: analytics and frozen contract 73 passed (68 analytics + 5 contract).
- Task 9 UI source integrated with `-x`: 30 components passed, production build passed, original 2 browser projection scenarios passed.
- Task 9 CORS fix integrated with `-x`: 9 CORS/config tests passed.
- Task 10 framework: add/add conflict in `frontend/playwright.config.ts`. Semantic merge retains learning UI project/Edge/Vite service and security HTTP request project/Python fixture. Each has independent testMatch/baseURL; both services reject reuse.
- Automatic merge introduced duplicate `include` in `frontend/vite.config.ts`; retained Task 9 single aggregation entry, which excludes Playwright while preserving all 30 tests. `package.json` and lock preserve both test:e2e and unchanged Playwright/Node types versions.

- Framework security: exactly 196 passed / 9 historical failures / 0 skipped; all nine match the source handoff. Applied authorized repair source with -x; no main.py conflict. CORS middleware, SQL token revocations and deletion source_context all remain.
- ADR numbering: CORS retains 0005; accepted Task 10 security decision renamed 0006 and all deliverable safety references updated. Original case/vector data unchanged.
- G1 final source safety regression: 220 passed, 0 failed, 0 skipped; actual sandbox checks included. Shared authentication/CORS/config regression: 28 passed. Components: 30 passed; build passed. Initial TS2688 installation lag resolved by lockfile npm ci; configuration typecheck then passed.

## G2 SQL data source

- First actual PG test reached existing `SqlCourseRepository.add` ordering defect: authorized-teacher insert before course caused FK violation. Dedicated reproduction observed RED before fix.
- Ruling: flush the course parent within the existing transaction before inserting authorized teachers. No permissions/schema/API change; necessary to seed and persist valid course relationships. Cost if wrong: extra database round trip, transaction still atomic.
- G2 final: 83 passed (13 actual PostgreSQL projection tests + original 68 analytics + 2 development projection tests), no skips. Covered multiple concepts/checks, duplicate students, actual private memory sentinel, mismatched/null queue relations, half-open dates, cross-course HMAC keys and explicit successful retry evidence. Review SQL persistence remains G3; application mounting remains G4.

## G3 reviews and minimal migration
- Missing review_claim observed RED. Added teacher_diagnosis_reviews only, migration0007 after0006. Shared SqlMemoryUnitOfWork locks diagnosis FOR NO KEY UPDATE, revalidates current candidate/teacher permissions, then inserts review and metadata-only audit with one commit.
- 89 projection/domain/review tests passed; additional single-commit/factory-UOW proof passed in the final 7-review-test run. Same/different simultaneous requests use independent SQL adapters and yield one review/one success audit. Flush failures roll back both; actual memory rows/version/status unchanged; post-wait permission revocation uniformly404.
- Legacy PG first run: 23 passed/2 environment failures (Task6 empty DB has no migration fixture). Migrated only wave3_task6, then all25 passed/no skips. Single head 0007 verified. Full migration roundtrip remains G7.

### G4 — 正式应用及全部运行时契约
正式 create_app 挂载三个教师 Router。DATABASE_URL 装配 SqlTeacherAnalyticsRepository 与原 memory audit 同一 UOW；开发模式投影现有动态仓库。Task 7 来源清理、Task 10 SQL 撤销和 Task 9 CORS 保留。
全部 40 operations 精确比较 paths/methods/operationId/parameters/body/status/security/response；240 项相关回归执行通过，0 skip。比较器保留名为 title/description 的业务字段，仅忽略 schema 注释；nullable enum 合并 null 是表达等价转换，未放宽 enum。
新增 api/contract.py 只从实际 routes/models 生成 OpenAPI，移除无法失败的无请求体/无约束 string 路径自动 422；不读取共享 YAML。知识接口用实际有效 Annotated + SkipValidation 保留原业务校验和错误码，随后各 handler 仍调用严格模型；SourceMetadata 未提供 note 时省略，显式 null 拒绝。公开 DTO 独立于内部 Runner DTO，保留公开字段约束。
HTTP 探针确认删除墓碑仍返回既有已脱敏诊断，满足非空公开约束且无原文；初始新增测试要求 404 属于错误假设，已撤回该额外权限行为。两组重置 wave3_router 的测试误并发引发测试数据 FK/唯一冲突，已改串行，全部重跑通过。共享 OpenAPI 本身未修改。

### G5 — 原始匿名向量真实执行
原 54 组向量通过正式 create_app / SQL / PostgreSQL，附加 8 组逐个移除过滤条件的反例检查，共 62 passed / 0 failed / 0 skipped。JUnit 含唯一 vector node、真实请求 URL、响应、总入库事实数及 excluded_by 反例数；原 YAML 与哈希未变。
测试映射说明：源向量用课程内 exercise-a 名称，数据库已存在全局 Exercise PK + course 复合 FK。course-a 保留公开 ID；其他课程的练习使用 course_id--exercise_id，保持全部 diagnosis/owner/course/concept/time/repair 事实与反例入库，不绕过或降低 SQL 约束。跨课程排除另由 G2 真实 SQL 课程隔离测试佐证。多概念逐一构造独立已审核证据后一起装载；不依据 excluded_by 预过滤。
