# Task 6 Integration Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reliably integrate the existing Task 6 evidence-bound diagnosis and hint ladder with Task 5, SQL persistence, the composed FastAPI application, the shared OpenAPI contract, and a configurable production model provider, then prove the complete Runner → deterministic Mock Model → PostgreSQL flow.

**Architecture:** Keep Task 6's provider-neutral domain services, replace their concrete in-memory dependency with a `DiagnosticRepository` protocol, and add a SQL adapter sharing the application's SQLAlchemy session factory. Durable orchestration claims and terminal writes use PostgreSQL transactions and row locks; provider calls happen outside database transactions, with resumable run records preventing a crash from permanently stranding a submission in `diagnosing`. Task 5 invokes an injected post-execution callback only after the real execution result and deterministic rule matches commit.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 17/pgvector image, httpx, pytest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-01-knowbound-cangjie-design.md` plus the user-supplied “Task 6 集成 Gate” brief dated 2026-10-03.

## Global Constraints

- Preserve commit `299d477ab753693f7d816a6fa0fa7b80eb879298` in branch history; do not merge, rebase, push, or create a PR.
- Keep only teacher and student roles; do not implement Task 7 memory, Task 8 review APIs, or Task 9 UI.
- Never fabricate execution evidence or let model output overwrite `CompilerDiagnostic` or `RuleMatch`.
- Do not expose private diagnoses to teachers, reference answers to public APIs, or secrets/private input to logs and client errors.
- Do not run a paid model request. All adapter tests use `httpx.MockTransport`.
- OpenAPI is the public contract; request DTOs forbid unknown fields and runtime status codes must match it.
- Add no new dependency unless the existing stack cannot satisfy the requirement; this plan uses existing `httpx` and SQLAlchemy.
- Use test-first RED → GREEN for every behavior change.

## Review Focus

- A crash after `executing → executed` but before diagnosis finalization must be recoverable and must not leave multiple final diagnoses.
- Two simultaneous hint requests must serialize on the diagnosis row and return distinct consecutive levels.
- Evidence foreign keys must reject cross-course concepts, cross-submission rule matches, and unapproved/cross-course knowledge.
- OpenAI-compatible error bodies, request IDs, and HTTP status variants must never leak the API key, source, explanation, or protected answer.
- SQLite unit coverage must not be reported as PostgreSQL or Runner validation; the Gate only passes after real Docker checks.

---

### Task 1: Strict evidence union and shared OpenAPI contract

**Files:**
- Modify: `backend/app/diagnostics/schema.py`
- Modify: `contracts/openapi.yaml`
- Modify: `contracts/fragments/task-6-diagnostics.yaml`
- Create: `backend/tests/contracts/test_task6_openapi.py`
- Modify: `backend/tests/diagnostics/test_schema.py`

**Interfaces:**
- Consumes: Task 5 `SubmissionId`, shared bearer auth, `ErrorResponse`, and Task 6 route DTOs.
- Produces: discriminated `EvidenceBinding` runtime type and matching `oneOf` OpenAPI schemas used by persistence and provider validation.

- [ ] **Step 1: Write strict-union and shared-contract tests**

Add table-driven tests that hand-build valid compiler, rule, and approved-knowledge evidence and reject every contradictory extra field. Assert the shared contract contains all three Task 6 routes, unique operation IDs, shared response refs, `additionalProperties: false`, and this shape:

```python
evidence = document["components"]["schemas"]["EvidenceBinding"]
assert evidence["discriminator"]["propertyName"] == "kind"
assert len(evidence["oneOf"]) == 3
for name in ("CompilerDiagnosticEvidence", "RuleMatchEvidence", "ApprovedKnowledgeEvidence"):
    assert document["components"]["schemas"][name]["additionalProperties"] is False
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `& '..\..\.venv\Scripts\python.exe' -m pytest backend\tests\diagnostics\test_schema.py backend\tests\contracts\test_task6_openapi.py -q`

Expected: FAIL because `EvidenceBinding` accepts irrelevant nullable fields and Task 6 paths are absent from `contracts/openapi.yaml`.

- [ ] **Step 3: Implement the discriminated models and merge the fragment**

Define three frozen Pydantic models with literal `kind` values and no irrelevant fields, then use:

```python
EvidenceBinding = Annotated[
    CompilerDiagnosticEvidence | RuleMatchEvidence | ApprovedKnowledgeEvidence,
    Field(discriminator="kind"),
]
```

Merge the three paths, parameters, request/response schemas, and strict evidence variants into the shared OpenAPI without duplicating common bearer/error/submission components. Keep fragment and runtime names aligned.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `& '..\..\.venv\Scripts\python.exe' -m pytest backend\tests\diagnostics\test_schema.py backend\tests\contracts -q`

Expected: PASS with all local `$ref` values resolved and every operation ID unique.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/diagnostics/schema.py backend/tests/diagnostics/test_schema.py backend/tests/contracts/test_task6_openapi.py contracts/openapi.yaml contracts/fragments/task-6-diagnostics.yaml
git commit -m "fix: tighten Task 6 diagnosis contract"
```

### Task 2: Course-scoped protected reference answers

**Files:**
- Modify: `backend/app/courses/models.py`
- Modify: `backend/app/persistence/models.py`
- Modify: `backend/app/persistence/repositories.py`
- Modify: `backend/app/diagnostics/hints.py`
- Modify: `backend/tests/diagnostics/test_hints.py`
- Modify: `backend/tests/courses/test_course_access.py`

**Interfaces:**
- Consumes: the diagnosis's submission → exercise → course relationship.
- Produces: `ProtectedAnswerLookup.for_exercise(course_id, exercise_id) -> str | None` for hint leakage checks; public `Exercise` responses remain answer-free.

- [ ] **Step 1: Write answer-isolation and leakage tests**

Test that the current exercise answer blocks a similar Level 1/2 hint, another exercise/course answer is never passed to leakage detection, no configured answer still triggers structural full-program detection, and serialized student exercise data has no protected-answer field.

- [ ] **Step 2: Run and verify RED**

Run: `& '..\..\.venv\Scripts\python.exe' -m pytest backend\tests\diagnostics\test_hints.py backend\tests\courses\test_course_access.py -q`

Expected: FAIL because `HintLadderService` currently receives one global `protected_answers` tuple.

- [ ] **Step 3: Add a private lookup without widening the public Exercise DTO**

Keep the public `Exercise` dataclass unchanged. Add repository-only methods:

```python
class ProtectedAnswerLookup(Protocol):
    def for_exercise(self, course_id: str, exercise_id: str) -> str | None: ...
```

Store the nullable value on `ExerciseRow`, let both in-memory and SQL course repositories manage it through private methods, and have `HintLadderService` resolve exactly the diagnosed submission's `(course_id, exercise_id)` before calling `contains_answer_leakage`.

- [ ] **Step 4: Run and verify GREEN**

Run: `& '..\..\.venv\Scripts\python.exe' -m pytest backend\tests\diagnostics\test_hints.py backend\tests\courses -q`

Expected: PASS; public API snapshots contain no reference answer.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/courses backend/app/persistence/models.py backend/app/persistence/repositories.py backend/app/diagnostics/hints.py backend/tests/diagnostics/test_hints.py backend/tests/courses
git commit -m "fix: scope protected answers to exercises"
```

### Task 3: Diagnostic SQL schema, migration, repository, and transactional invariants

**Files:**
- Create: `backend/migrations/versions/0004_diagnostics_hints.py`
- Modify: `backend/app/persistence/models.py`
- Modify: `backend/app/persistence/repositories.py`
- Modify: `backend/app/diagnostics/repository.py`
- Create: `backend/app/diagnostics/persistence.py`
- Create: `backend/tests/persistence/test_diagnostic_repository.py`
- Create: `backend/tests/integration/test_task6_postgres.py`
- Modify: `backend/tests/persistence/test_migration_contract.py`

**Interfaces:**
- Consumes: strict evidence variants, Task 5 submissions/execution/rule rows, course concepts and approved misconceptions.
- Produces: `DiagnosticRepository` protocol, `SqlDiagnosticRepository`, durable run/idempotency records, and persisted events consumed by Tasks 7/8/9.

- [ ] **Step 1: Write repository recreation, idempotency, constraint, rollback, UTC, and concurrency tests**

Cover all persisted aggregates across adapter recreation; duplicate `(diagnosis_id, request_id)` explanation/hint keys; duplicate review events; one diagnosis per submission; cross-course submission/concept/knowledge and cross-submission rule evidence; rollback after injected failure; and two threaded hint claims producing levels `[1, 2]`. PostgreSQL-only tests execute direct invalid inserts and assert `IntegrityError`.

- [ ] **Step 2: Run and verify RED**

Run: `& '..\..\.venv\Scripts\python.exe' -m pytest backend\tests\persistence\test_diagnostic_repository.py backend\tests\persistence\test_migration_contract.py -q`

Expected: FAIL because no diagnostic SQL tables, migration, protocol, or adapter exist.

- [ ] **Step 3: Define metadata and `0004` migration**

Create nullable `exercises.protected_answer` plus tables for diagnoses, diagnosis concepts, evidence bindings, review queue events, hint events, student attempts, explanation checks, and diagnosis run results. Add composite unique keys needed as FK targets and enforce:

```text
diagnoses.submission_id UNIQUE
hint_events(diagnosis_id, request_id) UNIQUE
hint_events(diagnosis_id, current_level) UNIQUE
explanation_checks(diagnosis_id, request_id) UNIQUE
review_queue_events(submission_id, request_id) UNIQUE
diagnosis_run_results(submission_id, request_id) UNIQUE
```

Use composite foreign keys carrying `course_id`, `owner_user_id`, `submission_id`, `concept_id`, and `misconception_id` where needed. Because review status is mutable rather than a key, the repository must also lock and verify that approved-knowledge evidence points to a same-course `misconception_patterns.review_status = 'approved'` row before inserting it. Set `down_revision = "0003_submissions_diagnostics"`; downgrade drops only `0004` objects and the protected-answer column.

- [ ] **Step 4: Implement the protocol and SQL adapter**

The protocol exposes the existing read/write methods plus transaction-sized operations for beginning/resuming a run and atomically finalizing `diagnosed` or `needs_review`. `SqlDiagnosticRepository` uses `SELECT ... FOR UPDATE` on the submission/diagnosis row for run and hint claims, translates all `SQLAlchemyError` values to `DiagnosticPersistenceError("diagnostic storage operation failed")`, and normalizes loaded datetimes to UTC.

- [ ] **Step 5: Run unit persistence tests and verify GREEN**

Run: `& '..\..\.venv\Scripts\python.exe' -m pytest backend\tests\persistence\test_diagnostic_repository.py backend\tests\persistence\test_migration_contract.py -q`

Expected: PASS on SQLite-compatible repository behavior; PostgreSQL-only tests remain explicitly selected for Task 7 and are not counted as real validation here.

- [ ] **Step 6: Commit**

```powershell
git add backend/migrations/versions/0004_diagnostics_hints.py backend/app/persistence backend/app/diagnostics/repository.py backend/app/diagnostics/persistence.py backend/tests/persistence backend/tests/integration/test_task6_postgres.py
git commit -m "feat: persist Task 6 diagnostic state"
```

### Task 4: Configurable Responses API provider with safe failure boundaries

**Files:**
- Create: `backend/app/model_gateway/openai_responses.py`
- Create: `backend/app/model_gateway/config.py`
- Modify: `backend/app/model_gateway/__init__.py`
- Create: `backend/tests/model_gateway/test_openai_responses.py`
- Modify: `.env.example`
- Modify: `infra/compose/docker-compose.yml`

**Interfaces:**
- Consumes: `ModelProvider`, existing Pydantic output models, server environment, and injected `httpx.Client`/transport.
- Produces: `model_provider_from_config(...) -> ModelProvider` with production fail-fast behavior and a disabled development provider.

- [ ] **Step 1: Write configuration, request-shape, response, and redaction tests**

Use `httpx.MockTransport` to assert POST to `/v1/responses` includes explicit `model`, `store: false`, and `text.format = {type: "json_schema", strict: true, ...}`. Cover diagnosis/hint/explanation parsing, timeout, 429, connection failure, malformed JSON, missing output text, local Pydantic rejection, and captured logs/errors containing none of a sentinel key/source/explanation/reference answer.

- [ ] **Step 2: Run and verify RED**

Run: `& '..\..\.venv\Scripts\python.exe' -m pytest backend\tests\model_gateway -q`

Expected: FAIL because the production adapter and configuration factory do not exist.

- [ ] **Step 3: Implement the adapter using existing httpx**

Send structured schemas generated from the existing Pydantic models, extract only output-text JSON, and revalidate locally. Map `httpx.TimeoutException` to `ProviderTimeout`; map transport errors, 429/5xx, non-JSON, refusal/incomplete output, and validation errors to `ProviderFailure`. Log only a redacted provider request ID, error category, and elapsed milliseconds.

Configuration behavior:

```text
MODEL_PROVIDER=openai + APP_ENV=production requires MODEL_NAME and OPENAI_API_KEY
MODEL_PROVIDER=mock is rejected by default in production
development/test without credentials yields DisabledModelProvider, never fake output
OPENAI_BASE_URL defaults to https://api.openai.com
MODEL_TIMEOUT_SECONDS is a positive float
```

- [ ] **Step 4: Update environment examples and Compose pass-through**

Replace legacy `MODEL_API_BASE`/`MODEL_API_KEY` examples with `OPENAI_BASE_URL`/`OPENAI_API_KEY`, add timeout, and pass model variables only to the trusted API service. Do not place a real key in any file.

- [ ] **Step 5: Run and verify GREEN**

Run: `& '..\..\.venv\Scripts\python.exe' -m pytest backend\tests\model_gateway -q`

Expected: PASS with MockTransport only and zero real network requests.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/model_gateway backend/tests/model_gateway .env.example infra/compose/docker-compose.yml
git commit -m "feat: add safe Responses API provider"
```

### Task 5: Durable diagnosis orchestration and Task 5 completion handoff

**Files:**
- Modify: `backend/app/diagnostics/service.py`
- Modify: `backend/app/diagnostics/hints.py`
- Modify: `backend/app/submissions/service.py`
- Modify: `backend/app/submissions/persistence.py`
- Modify: `backend/tests/diagnostics/test_service.py`
- Modify: `backend/tests/diagnostics/test_hints.py`
- Create: `backend/tests/integration/test_task6_orchestration.py`

**Interfaces:**
- Consumes: Task 5 atomic `complete_execution`, `DiagnosticRepository`, provider, approved course evidence, protected-answer lookup.
- Produces: exactly one recoverable final diagnosis/review outcome and persisted hint/explanation events.

- [ ] **Step 1: Write orchestration failure and restart tests**

Test callback ordering by making the callback read the already-committed execution row; high confidence → `diagnosed`; low confidence/no approved evidence/provider timeout → `needs_review`; unavailable execution never calls the provider; repeated callbacks/restarts return one final diagnosis; injected persistence failure is either rolled back to `executed` or leaves a resumable run that the next callback completes.

- [ ] **Step 2: Run and verify RED**

Run: `& '..\..\.venv\Scripts\python.exe' -m pytest backend\tests\integration\test_task6_orchestration.py backend\tests\diagnostics -q`

Expected: FAIL because Task 5 has no completion hook and services depend on the in-memory concrete repository.

- [ ] **Step 3: Generalize services and add post-commit orchestration**

Change annotations to `DiagnosticRepository`. Add an optional callable to `SubmissionService`:

```python
ExecutionCompleted = Callable[[str, str], None]
```

Invoke it only after `complete_execution(...)` returns. Diagnosis run start/resume and terminal persistence use repository transaction methods; provider calls remain outside open DB transactions. A duplicate or restarted callback first reads the durable run/final diagnosis. Provider failure produces a safe review event; persistence failure raises a stable domain error and never fabricates output.

- [ ] **Step 4: Make hint/explanation idempotency transactional**

Under `hint_claim`, reread persisted events, derive the next level, enforce Level 4 attempts, and insert using both request and level uniqueness. Explanation retries read by `(diagnosis_id, request_id)` before calling the provider and rely on the same unique key at commit.

- [ ] **Step 5: Run and verify GREEN**

Run: `& '..\..\.venv\Scripts\python.exe' -m pytest backend\tests\diagnostics backend\tests\integration\test_task6_orchestration.py backend\tests\submissions -q`

Expected: PASS while preserving Task 5 Runner and deterministic rule behavior.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/diagnostics backend/app/submissions backend/tests/diagnostics backend/tests/integration/test_task6_orchestration.py backend/tests/submissions
git commit -m "fix: connect execution to durable diagnosis"
```

### Task 6: Compose the application, routes, permissions, and stable errors

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/diagnostics.py`
- Modify: `backend/app/api/errors.py`
- Modify: `backend/app/persistence/repositories.py`
- Create: `backend/tests/integration/test_task6_app.py`
- Modify: `backend/tests/contracts/test_openapi_runtime.py`

**Interfaces:**
- Consumes: SQL/in-memory repositories, model provider factory, diagnosis/hint services, auth, course access.
- Produces: three mounted runtime routes and explicit `create_app()` injection points.

- [ ] **Step 1: Write application composition, privacy, body, and error tests**

Assert all three routes exist; `DATABASE_URL` wires `SqlDiagnosticRepository`; production never falls back to memory or mock; explicit injection works; owner succeeds while another student, teacher, cross-course actor, and unknown IDs receive byte-identical 404 bodies; GET never calls provider; request bodies reject `level`, `course_id`, `owner_user_id`, `threshold`, and review fields; persistence unavailability maps to sanitized 503 and missing execution to 409. Pin provider degradation semantics: diagnosis failure transitions to `needs_review`, hint failure returns a persisted safe fallback with `used_safe_fallback=true`, and explanation failure returns a persisted ineligible check; none returns the provider exception.

- [ ] **Step 2: Run and verify RED**

Run: `& '..\..\.venv\Scripts\python.exe' -m pytest backend\tests\integration\test_task6_app.py backend\tests\contracts\test_openapi_runtime.py -q`

Expected: FAIL because `create_app()` does not mount or inject Task 6 services.

- [ ] **Step 3: Wire dependencies and error handlers**

Extend `create_app()` with optional `diagnostic_repository`, `model_provider`, `diagnosis_service`, `hint_ladder_service`, `diagnosis_confidence_threshold`, and `protected_answer_lookup`. Store them on `application.state`, include `create_diagnostics_router`, and configure the Task 5 completion hook from the same objects. Add handlers for execution conflict, hint conflict, and diagnostic persistence unavailable without returning exception text; document the provider safe-degradation responses in OpenAPI while retaining 503 for requests that cannot safely complete.

- [ ] **Step 4: Run and verify GREEN**

Run: `& '..\..\.venv\Scripts\python.exe' -m pytest backend\tests\integration\test_task6_app.py backend\tests\contracts backend\tests\auth backend\tests\submissions -q`

Expected: PASS with runtime/OpenAPI version and status-code agreement.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/main.py backend/app/api backend/app/persistence/repositories.py backend/tests/integration/test_task6_app.py backend/tests/contracts
git commit -m "fix: compose Task 6 application routes"
```

### Task 7: Real PostgreSQL migration and Runner closed-loop verification

**Files:**
- Modify: `backend/tests/integration/test_task6_postgres.py`
- Create: `backend/tests/integration/test_task6_closed_loop.py`
- Modify: `infra/compose/docker-compose.yml` only if verification exposes a tested configuration defect.

**Interfaces:**
- Consumes: Docker PostgreSQL, real runner-controller/sandbox, deterministic `MockProvider`, composed API.
- Produces: evidence for migration round-trip, FK enforcement, restart persistence, concurrent hints, and end-to-end Gate status.

- [ ] **Step 1: Add opt-in real-service tests before changing production code**

Tests require explicit `TASK6_POSTGRES_URL` and `TASK6_RUNNER_ENDPOINT`, fail clearly if requested services are unavailable, and execute: real submission; real Runner result; deterministic mock diagnosis; persisted Level 1 hint; explanation check; application/repository recreation; reread diagnosis, hint, and explanation.

- [ ] **Step 2: Run Compose static validation**

Run: `docker compose -f infra\compose\docker-compose.yml config`

Expected: exit 0.

- [ ] **Step 3: Start isolated test services and wait with bounded health checks**

Use a unique Compose project name and disposable PostgreSQL volume. Build/start `postgres`, `runner-sandbox`, and `runner-controller`; poll health for at most 120 seconds. Do not reuse or delete unrelated containers/volumes.

- [ ] **Step 4: Run migration round-trip**

Against the disposable PostgreSQL URL run:

```powershell
alembic upgrade 0004
alembic downgrade 0003
alembic upgrade 0004
alembic current
alembic check
```

Expected: every command exits 0; current revision is `0004_diagnostics_hints` and check reports no new upgrade operations.

- [ ] **Step 5: Run PostgreSQL and closed-loop tests**

Run: `& '..\..\.venv\Scripts\python.exe' -m pytest backend\tests\integration\test_task6_postgres.py backend\tests\integration\test_task6_closed_loop.py -q`

Expected: PASS, including actual composite-FK rejection, adapter/application recreation, and concurrent hint levels. Report explicitly that Runner and PostgreSQL are real while the model is deterministic Mock.

- [ ] **Step 6: Stop only the isolated Compose project and commit tests/fixes**

```powershell
git add backend/tests/integration infra/compose/docker-compose.yml
git commit -m "test: verify Task 6 PostgreSQL closed loop"
```

### Task 8: Full regression, review, and Gate handoff

**Files:**
- Modify only files required by failures reproduced during this task, always with a failing test first.

**Interfaces:**
- Consumes: all Task 6 Gate changes.
- Produces: final verified branch and exact handoff evidence; no merge/push/PR.

- [ ] **Step 1: Run the required verification matrix**

Run each command separately and record its exact result:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest backend\tests\diagnostics -q
& '..\..\.venv\Scripts\python.exe' -m pytest backend\tests\contracts backend\tests\persistence backend\tests\integration -q
& '..\..\.venv\Scripts\python.exe' -m pytest backend\tests\submissions backend\tests\knowledge backend\tests\auth -q
& '..\..\.venv\Scripts\python.exe' -m pytest backend\tests runner\tests -q
& '..\..\.venv\Scripts\python.exe' -m compileall -q backend\app
& '..\..\.venv\Scripts\python.exe' -m pip check
git diff --check
docker compose -f infra\compose\docker-compose.yml config
```

Expected: all exit 0; any skip is named and assessed rather than hidden.

- [ ] **Step 2: Perform whole-branch review**

Generate the review package from base `299d477ab753693f7d816a6fa0fa7b80eb879298`, check every Gate requirement and Review Focus item, and fix Critical/Important findings in one RED → GREEN pass. Record deferred minors and rulings.

- [ ] **Step 3: Create the final integration commit if needed**

```powershell
git add -A
git commit -m "fix: integrate Task 6 diagnosis pipeline"
```

Do not create an empty commit if the preceding commits already contain all changes.

- [ ] **Step 4: Verify clean worktree and preserved history**

Run:

```powershell
git status --short
git log --oneline --decorate 54bb283e7b6377e38016cb5b796ebd8e74c497b5..HEAD
git merge-base --is-ancestor 299d477ab753693f7d816a6fa0fa7b80eb879298 HEAD
git rev-parse HEAD
```

Expected: empty status; ancestor check exits 0; report the complete final hash.

- [ ] **Step 5: Hand off without integration side effects**

Report completed/uncompleted work, every changed file, every command/result, PostgreSQL round-trip, real Runner → Mock Model → PostgreSQL result, SQL constraints/transactions, API/OpenAPI/config/provider boundaries, paid-call status, shared-file impact, risks and Task 7/8/9 dependencies, branch/hash/cleanliness, and explicit Gate pass/fail. Preserve the worktree and branch; do not merge, rebase, push, or create a PR.
