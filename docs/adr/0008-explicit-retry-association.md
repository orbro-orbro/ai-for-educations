# ADR 0008: Explicit retry association for the real delivery flow

Status: Accepted — user delegated both pending decisions on 2026-10-12 (「这些都是你来决定」); main Agent selects the explicit API addition below.

## Evidence

`HintLadderService.record_submission_attempt` checks student ownership, enrollment/access, matching course/exercise, a different original submission and an existing execution result. SQL already stores a unique `(diagnosis_id, attempt_key)` and submission reference. No API or frontend caller exists. Analytics requires this explicit association plus successful execution, understanding evidence and no level-four hint to count autonomous repair. Arbitrary later same-exercise submissions must not be inferred as retries.

## Decision

Add authenticated `POST /diagnoses/{diagnosis_id}/attempts`, request `{ "submission_id": "…" }`, success 204. Route calls the existing checked service; missing/foreign/teacher/cross-course/cross-exercise/original/unexecuted submissions remain unavailable (404), invalid input 422, storage failure 503. Repetition of the same pair is idempotent. No new table, role, permission or experiment criterion.

The learning page retains its original diagnosis when submitting a correction. After obtaining the new real execution result, it explicitly records that retry against the retained diagnosis. Failed linking is visible and retryable; the UI must not declare autonomous repair based solely on compilation. Understanding checks remain attached to the original diagnosis. Existing analytics remains authoritative.

Update frozen OpenAPI deliberately with this one operation and its request schema, the typed client and runtime contract tests. Add failing API authorization/idempotency and real SQL/browser flow tests before implementation. No manually injected repair facts can substitute for the real demo.

## Alternative

Preserve the frozen contract. Demonstrate compilation success only and report step 7 as incomplete; no claim of a complete 15-step rehearsal or autonomous-repair validation.

## Approval

The separate user delegation authorizes this narrowly defined API addition. No schema, role or metric changes are included. RED→GREEN and full regression remain required.
