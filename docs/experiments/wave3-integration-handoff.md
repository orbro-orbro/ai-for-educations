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
`n## G3 reviews and minimal migration`n- Missing review_claim observed RED. Added teacher_diagnosis_reviews only, migration0007 after0006. Shared SqlMemoryUnitOfWork locks diagnosis FOR NO KEY UPDATE, revalidates current candidate/teacher permissions, then inserts review and metadata-only audit with one commit.`n- 89 projection/domain/review tests passed; additional single-commit/factory-UOW proof passed in the final 7-review-test run. Same/different simultaneous requests use independent SQL adapters and yield one review/one success audit. Flush failures roll back both; actual memory rows/version/status unchanged; post-wait permission revocation uniformly404.`n- Legacy PG first run: 23 passed/2 environment failures (Task6 empty DB has no migration fixture). Migrated only wave3_task6, then all25 passed/no skips. Single head 0007 verified. Full migration roundtrip remains G7.
