# ADR 0009: Live model providers for a separate demonstration stack

Status: Accepted for DeepSeek/Qwen (user confirmed 2026-10-19). TeleAgent remains pending protocol capture.

## Context

`model_provider_from_config` supports only `disabled`, `mock` and `openai` (Responses API). The Wave 4 delivery demo forces `MODEL_PROVIDER=disabled` and injects `DeliveryMockProvider`; its evidence and ports (5209/8208) must remain valid. The competition entry needs a demo using real models: TeleAgent (交晓智), DeepSeek and Qwen (千问).

Protocol evidence:
- DeepSeek: `POST https://api.deepseek.com/chat/completions`, Bearer auth, `response_format={"type":"json_object"}` (valid JSON only; prompt must mention "json"; no strict schema).
- Qwen (Bailian): `POST https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`, OpenAI-compatible, Bearer auth, `json_object` supported.
- TeleAgent: public documents show only that an APPID and API key exist; **no endpoint or schema is public**. Details will come from the user's logged-in console. This ADR does not guess them; the TeleAgent section is completed once captured.

## Decision

1. Add `OpenAIChatCompletionsProvider` (httpx, no vendor SDK) configured by `base_url`, `model`, `api_key`, `timeout`. DeepSeek and Qwen are the same class with different configuration. Existing `OpenAIResponsesProvider` is untouched.
2. Add `TeleAgentProvider` only after the protocol is confirmed from the console; until then `MODEL_PROVIDER=teleagent` is rejected as unsupported.
3. `MODEL_PROVIDER` gains `deepseek`, `qwen` (and later `teleagent`). Model names and base URLs have no code defaults except the documented official base URLs; the model name is mandatory. Missing key/model fails fast at startup. No silent fallback to Mock.
4. Outputs are validated by the existing strict Pydantic models (`DiagnosisModelOutput`, `HintModelOutput`, `ExplanationModelOutput`). Because JSON mode is not schema-enforced, the schema is placed in the prompt and invalid output is a `ProviderFailure`. Timeouts raise `ProviderTimeout`.
5. Secrets are read only from env; never logged, returned, put in errors or sent to the frontend. Logs keep only category, safe request id and elapsed time, as today.
6. A separate stack: `scripts/start-live-demo.ps1`, `infra/compose/docker-compose.live-model.yml`, git-ignored `.delivery/live-model.env` (template without keys), distinct Compose project, ports and volumes. `start-delivery.ps1`, `DeliveryMockProvider` and 5209/8208 are not modified.
7. The UI separates data nature (synthetic actors/exercises) from model nature (real provider and model name vs deterministic Mock). Live mode must never claim real pilot results or teacher gold data.
8. Prompts sent to external providers contain only the existing request DTOs (code excerpts, compiler diagnostics, approved knowledge). No student private memory or teacher-restricted data is added, so role-isolated memory is not changed.

## Risks

- Student code and diagnostics leave the machine for third-party APIs; the demo uses synthetic actors only.
- JSON-mode models may violate the schema; this surfaces as visible errors, not fallbacks.
- Rate limits/quota (401/429/5xx) map to `ProviderFailure`.

## Testing

Failing tests first: transport (200/401/429/500/timeout/non-JSON/schema mismatch/missing content/log redaction), config validation, live launcher contract tests (key missing fails, separate project/ports, Mock launcher unchanged), then full regression.

## Approval

User confirmed on 2026-10-19 (「可以」). No dependency, schema, role or permission change.
