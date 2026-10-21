# ADR 0010: Configure the model provider from the web UI at runtime

Status: Accepted (confirmed 2026-10-21: teachers own the shared configuration, students may
store a personal override, production stays environment-only).

## Context

ADR 0009 wired real providers (DeepSeek, Qwen) through environment variables only. The
competition entry therefore requires an operator to edit `.delivery/live-model.env` in a
text editor and restart the stack before every model change. During review this is the
slowest and most error-prone step: the reviewer must find an ignored file, paste a key,
and restart containers; a typo surfaces as a failed diagnosis rather than a configuration
error.

The service already builds exactly one provider instance at startup and injects it into
`DiagnosisService` and `HintLadderService`, so a runtime change needs an indirection
object rather than a service rewrite.

Students need the same choice from their own side: the course ships one shared key, but a
student who has their own quota must be able to switch models without editing deployment
files, and that switch must not silently move every other student onto their key. One
process-wide provider cannot express both, so the seam has to resolve per request owner.

## Decision

1. Wrap the injected provider in `RuntimeModelProvider`, a thread-safe delegating
   `ModelProvider`. Services keep the same reference; a swap replaces the inner provider.
   Injected test providers stay valid because delegation is transparent.
2. Add teacher-only endpoints under `/teacher/model-settings`:
   - `GET` returns the effective settings: provider, model, base URL, source
     (`environment` / `web` / `default`), whether a key is configured, a four-character
     key hint, timeout, and whether the value is persisted.
   - `PUT` validates and applies a new configuration, then returns the same view.
   - `POST /probe` performs one minimal chat-completions call to verify credentials,
     model name and endpoint without persisting anything. Failures map to a closed set of
     categories (`invalid_credentials`, `model_or_endpoint_not_found`, `rate_limited`,
     `rejected_request`, `timeout`, `transport_error`, `http_error`) and never include
     upstream response bodies.
3. Configurable providers from the UI are `deepseek`, `qwen`, `openai_compatible`
   (arbitrary HTTPS base URL, which also covers OpenAI and future relays such as
   TeleAgent), plus `mock`, `disabled`, and `environment` (reload from env).
   `model` and `api_key` are mandatory for remote providers; `base_url` must be HTTPS
   (plain HTTP is accepted only for loopback hosts). Credentials are built and validated
   before the swap, so a rejected configuration never degrades a working provider.
4. Only the `teacher` role may call these endpoints. A student receives the same
   `404 RESOURCE_NOT_AVAILABLE` used for other teacher-only resources, so the endpoint
   does not leak its existence. This does not grant any access to student private memory
   or teacher-restricted data; it is a deployment-scoped setting, not course data.
5. In `APP_ENV=production` the web entry point is read-only: `PUT` and `/probe` return
   `409 MODEL_CONFIGURATION_MANAGED`. Production keeps ADR 0009's environment-only rule.
6. The API key is never returned, logged, placed in an error message, or written to the
   audit line. Only a four-character hint and a boolean are exposed. The key is stored in
   the API container's own configuration file (`MODEL_SETTINGS_PATH`, default
   `/var/lib/knowbound/model-settings.json`, mode `0600`, atomic replace). It survives
   `docker compose stop/start` but not container recreation, because no volume is added:
   a new Compose volume would enter the resource-ownership guards of the delivery, live
   model and test stacks. This is a plaintext at-rest store equivalent to the existing
   git-ignored `.delivery/live-model.env`; it is acceptable only for the
   development/demo posture and is why the production gate in item 5 exists.
   Encrypted-at-rest storage is deferred until a reviewable AEAD dependency is approved.
   When the submitted key is blank and the provider is unchanged, the stored key is
   reused, so changing only the model name does not require pasting the key again.
   A deterministic-Mock injection (the synthetic delivery demo) is never overridden by a
   stored real-model configuration.
7. Startup is tolerant: a stored configuration that fails validation is ignored with a
   warning and the environment configuration is used. A broken file never blocks boot.
8. Changing the model never changes diagnosis, hint or memory semantics. Prompts, DTOs
   and schema validation are untouched; a provider that violates the schema still surfaces
   as `ProviderFailure`, never as a silent fallback.
9. A student may keep using the shared configuration or save a personal override:
   - `GET /model-settings` returns the configuration that actually applies to the caller:
     `scope` (`shared` / `own`), the effective provider and model, whether a key exists, the
     key hint of the caller's own key only, and a summary of the shared configuration.
   - `PUT /model-settings` accepts `mode: "own" | "shared"`. `own` validates and stores a
     personal provider for the caller; `shared` deletes it and inherits again. A teacher
     writing here receives `422` and is pointed at `/teacher/model-settings`, so the shared
     configuration has exactly one write path.
   - `POST /model-settings/probe` tests the submitted personal configuration without
     persisting it, using the same closed status categories.
   - Resolution happens per request through `UserScopedModelProvider.for_user(user_id)`.
     `DiagnosisService` uses `submission.owner_user_id`; `HintLadderService` and the
     explanation check use `actor.user_id`. Requests without a personal entry keep the
     shared provider, so existing single-provider injection still works.
   - A blank personal key is only inherited from that same user's stored entry. It never
     borrows the shared credential: using the teacher's key is the explicit `mode:
     "shared"` path, not a same-provider side effect.
   - Storage is one file: `{"version": 2, "shared": ..., "users": {"<user_id>": {...}}}`,
     mode `0600`. A version-1 flat file is still read as the shared entry, so an existing
     demo volume keeps working. Per-user providers are cached in process; applying or
     clearing an override invalidates that user's entry.
   - The production gate in item 5 applies to the personal scope too: in `APP_ENV=production`
     `PUT` and `/probe` return `409`, and the student panel is read-only.
   - This does not widen any teaching-data permission. A student can only read and write
     their own model entry; other students' entries and the shared one stay invisible and
     immutable to them.

## Consequences

- Reviewers can paste a key and pick a model in the browser, with an explicit connectivity
  test, without editing files or rebuilding images.
- The first boot still needs one usable provider in `.delivery/live-model.env`, because the
  live launcher and `create_live_app` fail fast on a missing key or model (ADR 0009).
  Every later change happens in the UI and takes effect on the next request.
- Stopping and starting the stack keeps the web configuration; recreating containers or
  rebuilding images does not, because the file lives in the container layer. The UI states
  this.
- `backend/Dockerfile` now creates `/var/lib/knowbound` owned by the API user. It is a
  shared file, but the change is additive: no Compose file, port, volume or network is
  touched, so the delivery, live model, gate and test guards are unaffected.
- No database migration, no new dependency, no role change, no new teaching-data category.
- Three operations were added for the teacher panel (41 -> 44) and three more for the
  per-user scope (44 -> 47).
- The settings file now holds one entry per user who saved a key. It is still plaintext at
  rest with mode `0600`, which is acceptable only for the development/demo posture; the
  production gate keeps the environment-only rule. Personal entries are not covered by any
  backup or rotation procedure yet, so operators should clear them with `-FreshData`.
- A student who saves a personal key is billed by that provider directly, and the key is
  visible to whoever can read the API container's filesystem. The UI states that the key
  stays on the server and only affects that student's requests.

## Alternatives rejected

- Keeping file-only configuration: the pain this ADR exists to remove.
- Writing the key back into `.delivery/live-model.env`: the API container cannot write the
  host path, and the change would still need a restart.
- Hand-rolled encryption over `AUTH_TOKEN_SECRET`: unreviewable custom crypto in a project
  whose selling point is a careful security story.
- Database persistence: needs a migration plus the same at-rest secret question, for no
  additional benefit over a file in the API's own volume.

## Testing

Failing tests first: settings validation (missing key, missing model, non-HTTPS base URL),
provider construction for every provider name, swap visibility through the services,
failed build leaves the previous provider active, probe category mapping with a mock
transport, secret never appears in `snapshot()`, store round-trip and `0600` mode, corrupt
store falls back to the environment, production gate returns 409, student receives 404,
and the frozen OpenAPI operation set still matches the runtime document.

Per-user scope: one student's override leaves other students on the shared provider; a
user without an override falls back; clearing restores the fallback; a blank personal key
reuses only that user's own key and never the shared one; `environment` is rejected as a
personal provider; the production gate also blocks the personal scope; a version-1 file is
read as the shared entry; the HTTP surface is scoped per student and a teacher cannot write
the personal scope; the diagnosis path resolves the provider for `owner_user_id`.
