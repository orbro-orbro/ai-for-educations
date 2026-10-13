# Wave 4 / Task 11 Delivery Implementation Plan

> **For agentic workers:** use superpowers:executing-plans; the main Agent implements serially, followed by one fresh read-only review. User confirmed this plan on 2026-10-12. User subsequently delegated both pending decisions (「这些都是你来决定」): ADR 0007 and ADR 0008 are Accepted.

**Goal:** a reproducible local system, real competition rehearsal and accurately scoped evidence package for 《仓颉语言设计》.

**Architecture:** existing React → FastAPI → PostgreSQL authority and trusted controller → per-job isolated Cangjie sandbox. Mock replaces model responses only. Separate synthetic demo and regression Compose projects never reuse daily or Wave 3 databases.

**Tech Stack:** existing React/TypeScript/Vite/Playwright, Python/FastAPI/SQLAlchemy/Alembic/pytest, PostgreSQL17/pgvector, Docker, Cangjie1.2.0 STS cjnative. No new production dependencies or external services.

**Spec:** `docs/superpowers/specs/2026-10-01-knowbound-cangjie-design.md`; original Task11 and Coordinator Review Checklist; user's attached Task11 instructions and Phase A plan in this chat.

## Global Constraints

- Only students and teachers; course 《仓颉语言设计》; concept misconception diagnosis is the main flow.
- Teachers cannot read private memory/conversations; long-term memory requires its owner's acceptance and supports correction/rejection/deletion.
- Every anonymous filter/group requires at least five distinct students.
- Untrusted source executes only in hardened disposable containers, never on host/API/controller.
- No real student/teacher identities, paid models, new providers/infrastructure, experimental redefinition or dependency upgrades.
- No main edits, merges, rebases, pushes, PRs, worktree/branch deletion or changes to root user artifacts.
- Behavior changes require observed RED before minimal implementation; no skipped mandatory tests, weakened assertions or fake services replacing PG/Runner.
- Architecture/permissions/external adapter/frozen API decisions require ADR and explicit confirmation.
- Preserve historical failure evidence; software and synthetic tests are not teaching outcomes.

## Review Focus

1. Wrong target: initializers/tests must refuse daily resources and foreign databases before writing.
2. Clean start: no local venv/node_modules, old volumes or empty Mock queues may be prerequisites.
3. Privacy evidence: receipts and installed pgvector do not prove external physical erasure.
4. Rehearsal authenticity: no intercepted API responses, prefilled repair rows or screenshots substitute for actual execution.
5. Final evidence: bind command exits and reports to the actual final source commit; no inherited Wave3 green claims.

## Phase A facts

Local main, cached origin/main and live remote are 73bd2b4c6defdc139179c3b17c657773cfc2250a. Tracked tree clean; root artifacts and five report/speech files belong to user and are untouched. Runtime OpenAPI 40 operations/42 assertions passed in memory. Single migration head 0007_teacher_analytics_reviews. evaluate.py structure and historical mapper validation passed (163 automated_passed/1 not_executed); these are not Task11 full regression results. Docker Compose parses, but no cold start was performed in Phase A.

Observed gaps: API/Web healthchecks absent; README remains Wave1 and its Runner test command executes on host; API misses RUNNER_TIMEOUT_SECONDS forwarding; no root .env means disabled models; bootstrap lacks exercises/enrollments and approvals; configured Mock has empty queues; Python dependency ranges and some image tags are unlocked. Some Wave3 fixtures hardcode ports/DBs and truncate test tables. record_submission_attempt exists but has no official API/UI caller.

Actual PhaseA versions: Docker29.8.1/Compose5.5.1, host Python3.14.6/Node24.15.0/npm11.12.1/cjc1.2.0/cjpm1.2.0; existing synthetic PG17.11/vector0.8.7. Container versions must be measured again. SDK digest 082f87930e2752fddab9a5633ca232847ff164944cf96e0b7bbec8df45edbbee is historical local image identity, not a Task11 build result.

## Task 1: Workspace and execution ledger

Files: this plan, `docs/adr/0007-request-correlation-policy.md`, `docs/experiments/wave4-task11-handoff.md`; ignored `.superpowers/sdd/2026-10-12-wave4-task11-delivery/progress.md`.

- [x] Recheck live main and root status; fetch origin main; create branch codex/wave4-task11-delivery and worktree .worktrees/wave4-task11-delivery from origin/main.
- [x] Record approval boundary, actual commands and evidence storage; commit plan/ADR draft.
- [x] Baseline existing auth/contracts/submission tests without host worker execution. Full DB-dependent baseline follows isolated setup.

## Task 2: Isolated regression resources

Files: new `scripts/verify-delivery.ps1`, `backend/scripts/delivery_environment.py`, `infra/compose/docker-compose.wave4-test.yml`, `backend/tests/contracts/test_wave4_environment.py`; adjust `backend/tests/integration/wave3_support.py`, `wave3_environment.py`, `wave3_browser_fixture.py`, `wave3_browser_sql_probe.py`, `backend/tests/contracts/test_wave3_environment.py`, both frontend Playwright configs, `frontend/e2e/wave3-real.spec.ts`, `runner/tests/test_wave3_isolated_topology.py` only where required for target selection.

- [x] RED: refuse daily project/labels, non-whitelisted DB, wrong host/port and malformed names; demonstrate Wave4 configuration can select its own endpoint.
- [x] Minimal configuration, preserving Wave3 defaults and every security assertion; no test reduction.
- [x] GREEN before starting dedicated knowbound-wave4-test resources. Distinct task6/task7/task10/router/migration/browser databases; no DATABASE_URL override during pytest migration fixtures.
- [x] Reserve free loopback ports; separate regression API/UI from demo. Never stop/reuse Wave3/daily containers.
- [x] Commit `test: isolate Task 11 verification resources`.

## Task 3: Reproducible startup

Files: README.md, .env.example, infra/compose/docker-compose.yml, backend/Dockerfile, frontend/Dockerfile, runner/Dockerfile, runner/controller.Dockerfile; exact existing dependency lock files; scripts/start-delivery.ps1; minimal .gitignore additions for local credentials/evidence.

- [x] RED contracts for healthchecks, healthy dependencies, loopback publication, timeout forwarding, required configuration and immutable dependencies.
- [x] Lock existing dependency closure/build requirements and base images without upgrading or adding packages. Never download an unconstrained dependency.
- [x] Configure explicit synthetic demo secrets generated into an ignored local file; no real secrets in examples or command evidence. Reject incompatible existing configuration rather than overwrite it.
- [x] One launcher builds/starts a fresh knowbound-wave4-demo project and waits for all long-lived services healthy. Sandbox image helper exits successfully; per-job containers remain networkless.
- [x] Test empty-volume start and idempotent restart; record image identities and actual runtime versions.
- [x] Commit `build: make delivery startup reproducible`.

## Task 4: Authentic synthetic competition demo

Files: new backend/scripts/delivery_demo.py, data/demo inputs, backend/tests/integration/test_delivery_demo.py, frontend/e2e/delivery-real.spec.ts, frontend/playwright.delivery.config.ts, docs/demo-script.md; existing UI only if a confirmed minimal defect is reproduced.

- [x] RED for wrong DB/production refusal, repeatable seed preserving existing state, approved synthetic knowledge, enrolled actors/published exercise and repeatable Mock responses.
- [x] Assemble existing application with real SQL repositories/Runner and deterministic model responses. No test failure endpoints, no API interception, no automatic memory acceptance.
- [x] Rehearse all 15 requested steps with expected result/recovery/time and synthetic/Mock labels. Record compiler failure→success, hints, explanation, memory accept/correct/reject/delete, cross-user/teacher denial, five-person aggregate and logout replay.
- [x] Read-only DB probe after browser actions and identical-query reverse retrieval after deletion.
- [x] Resolved authorized blocker: ADR 0008 adds explicit retry association through the existing checked service, SQL state and frontend caller; real browser and read-only SQL proof passed. No repair rows were injected.
- [x] Commit `test: add repeatable synthetic competition demo` when its implemented scope passes; unresolved requirements remain blockers.

## Task 5: Approved request-ID policy

Files: ADR0007; backend/app/api/errors.py; focused HTTP tests and affected existing correlation assertions; data/evaluation mapping and Task11 command/evidence records. Frozen business DTOs/schema/permissions unchanged.

- [x] Obtain explicit policy confirmation; worktree approval alone is insufficient.
- [x] RED: secret-bearing inbound ID is reflected today; new tests demand server random32hex, current error/header/audit consistency, no inbound text and independent IDs across requests/users.
- [x] Minimal middleware change; resource DTO request_id remains creation provenance. Update old echo assertions to stronger approved-policy assertions without deleting coverage.
- [x] Execute sec-sensitive-logging-008's original operation, build Task11-specific manifest from actual per-node reports and preserve Wave3 evidence.
- [x] Commit `fix: enforce approved request correlation policy` only after approval/RED→GREEN.

## Task 6: Bounded real Runner stability

Files: new runner/tests/test_wave4_stability.py and trusted scripts/runner_stability.py; scoped actual evidence.

- [x] Query cangjie-coding for actual source/toolchain behavior; record container cjc/cjpm -v and real isolated compilation.
- [x] Five scenarios × three rounds × concurrency1/2 =45 tasks, fixed bounded deadlines; keep original2s regression unchanged.
- [x] Capture expected outcomes, latency distributions, raw synthetic diagnostics, events, inspect/resource data and before/after container IDs. Maximum two simultaneous512MiB/1CPU jobs; overall deadline.
- [x] Unexpected compile_failed: preserve evidence, diagnose before fixing; no unsupported claim about historic root cause.
- [x] Commit `test: record bounded isolated Runner stability evidence`.

## Task 7: Complete verification, reports and independent review

Files: README.md, docs/demo-script.md, docs/operations.md, docs/security-report.md, docs/evaluation-report.md, docs/experiments/wave4-task11-handoff.md, command ledger/report/hash indexes.

- [x] Candidate backend1033 passed with required PG/Runner env vars; original220 safety and54 real SQL vectors; migration empty upgrade/singlehead/base roundtrip/0006/0005 rollback safety. Final same-HEAD rerun remains below.
- [x] Candidate runtime OpenAPI43, components43, types/build, default16/Gate10, real15-step browser and read-only SQL checks passed. Rejection completes a memory decision without accepting it; RED→GREEN preserved.
- [x] Candidate hardened worker31/controller12/topology4 and45-job bounded stability passed; actual Compose config/build/up/health/cold start verified.
- [x] Candidate evaluation schema/raw+LF hashes/164-case manifest and git diff checks passed; final clean-HEAD checks are part of the mandatory rerun.
- [x] Documents separate software, synthetic, teacher gold, real model and pilot results. Last three remain 尚未执行. External copies not written/adapter not implemented ≠ physically erased.
- [ ] Candidate final commit, then whole matrix again at that exact HEAD. Store final rerun outside tracked worktree in authorized evidence directory. Any later change invalidates final claim and requires another rerun.
- [ ] Fresh read-only review against every design section; preserve findings. Critical/Important safety issue stops delivery pending user decision; authorized fixes require RED→GREEN/full regression and same-context follow-up review.
- [x] Prepare final local commit `docs: finalize verified demo and competition evidence baseline`; actual full hash/status and final rerun/review will be recorded externally to avoid changing the verified source. Never push/merge/PR/delete.

## Shared impacts and stop rules

Compose/.env/root ignore/build configuration are coordinated here. Default schema and frozen OpenAPI business semantics stay unchanged. Request correlation needs its own approval. New retry linkage API needs another ADR/approval; do not infer association from arbitrary later submissions. Root artifacts are never staged or overwritten. New Critical/Important safety issues, isolation failure, foreign-data targets, real identities/models, schema/architecture/permissions/infrastructure/experiment changes stop dependent work with preserved evidence. Missing environments are not_executed, never green skips.
