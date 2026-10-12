# ADR 0007: Server-generated request correlation

- Status: Proposed — explicit approval pending; worktree approval does not change runtime policy.
- Date: 2026-10-12
- Scope: Task11 / WG-CORRELATION-POLICY; no role, schema or business DTO changes.

## Existing behavior and evidence

backend/app/api/errors.py accepts any nonempty inbound X-Request-ID and echoes it in response headers, error envelopes and downstream metadata. sec-sensitive-logging-008 currently observes that echo, and remains not_executed in the historical manifest because trust/admissibility rules were not defined. Existing SQL request_id fields are bounded to128 characters while the header has no application bound.

## Options

A (recommended): ignore all inbound IDs and generate uuid4().hex (32 lowercase ASCII hexadecimal characters) per application request. Only the server ID enters response/log/audit metadata. Callers use the response header to locate evidence. No attacker-controlled correlation text is retained.

B: accept strictly formatted UUIDv4, replace everything else. Preserves caller correlation but allows repeated IDs and attacker-selected cross-request associations.

C: validate caller UUID and reject invalid values with422. Adds rejection semantics and broader contract/client changes.

## Proposed decision A

Generate a new opaque random32hex ID for every request reaching the application. Do not normalize, echo, persist, log or hash the inbound value. Response X-Request-ID and current error-envelope request_id equal this server ID; metadata-only audit and application logs for the operation use the same ID. Existing resource DTO request_id is its original creation provenance and is not rewritten during reads. IDs never authorize actions or identify a learner. No inbound/client-ID field or new external tracing system is added.

HTTP parsing failures before the application are a separate transport boundary. Tests must distinguish transport rejection from actual application sanitization. Existing handled401/404/409/422/503 and normal responses are verified, including CORS header exposure.

## Acceptance

First preserve an observed RED for a secret-bearing inbound header. Then test missing/empty/valid/duplicate/oversized/secret/representable-control-character inputs, server format and per-request independence, no client marker in response/current audit/logs, and current header/error/audit consistency through real PostgreSQL. Preserve resource-provenance fields on later reads. Replace echo-specific assertions with these stronger approved-policy assertions; never delete safety coverage. Only actual new per-case evidence can close sec-sensitive-logging-008.

## Consequences

Callers cannot choose correlation IDs; they must read the server response. Existing authorization, statuses, persisted schema and business DTOs remain. No external erasure or historical Runner-stability claim follows from this decision. Runtime implementation awaits explicit approval of this draft.
