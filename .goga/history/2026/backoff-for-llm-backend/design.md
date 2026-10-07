# Design Document: `backoff-for-llm-backend`

Complete architectural specification for the bounded transport backoff of LLM backend requests,
derived from the CODEMANIFEST changes applied by the `apply-architecture` stage (diff of
`backoff-for-llm-backend` vs `0.0.x`). This document specifies **what** to implement and **how**;
the implementation order and task split belong to the planning stage.

Scope: five cells touched — `prettyplay/failures`, `prettyplay/config`, `prettyplay/llm` (the
core), `prettyplay/engine`, `prettyplay/engine/groups`. Downstream facades (`prettyplay` root,
`prettyplay/engine/steering`) import only unchanged signatures and need no code changes.

---

## Contract Changes

### Changed CODEMANIFEST Files

- `prettyplay/failures/CODEMANIFEST`: `PrettyplayError::LLMUnavailableError` annotation widened —
  raised after bounded transport retries are exhausted, skipped on a permanent provider rejection
  or cut short by an over-cap Retry-After; covers all four LLM operations (generation, healing
  classification, group diagnosis, compliance verdict); the original transport cause stays
  chained (`raise … from`). No signature, property or method change.
- `prettyplay/config/CODEMANIFEST`: `Config` signature gains `llm_request_attempts: int` between
  `healing_attempts` and `send_screenshots`; parameter annotation, positive-integer requirement,
  property `llm_request_attempts -> int`, and the `load_config` step-6 env enumeration
  (`PRETTYPLAY_LLM_REQUEST_ATTEMPTS`, decimal integer) added.
- `prettyplay/llm/CODEMANIFEST`: five new types at `_request.py`
  (`TransportFailureClassification`, `classify_openai_failure`, `classify_anthropic_failure`,
  `compute_transport_pause`, `send_with_retries`); document annotations rewritten around the
  logical-attempt rule; both provider mutations gain the `max_retries=0` construction bullet,
  the `send_with_retries`-wrapped send step and the classifier mapping; all four `LLMProvider`
  operation requirements reworded to the retry semantics; footer description extended.
- `prettyplay/engine/CODEMANIFEST`: one requirement of the generate cycle reworded — provider
  unavailability surfaces after the bounded transport retries; the engine adds none above them.
- `prettyplay/engine/groups/CODEMANIFEST`: one constraint of the group diagnosis reworded
  identically.

### New Entities

- `TransportFailureClassification` — the verdict of one transport failure classification: a
  closed nine-label category plus the parsed Retry-After seconds; property `retryable` decides
  the retry-or-raise branch. Location `_request.py`.
- `classify_openai_failure` — pure classifier of one openai SDK exception into the verdict.
  Location `_request.py`.
- `classify_anthropic_failure` — pure classifier of one anthropic SDK exception into the verdict;
  rule-by-rule parity with the openai classifier. Location `_request.py`.
- `compute_transport_pause` — the fixed delay policy: exponential base, jitter, cap, Retry-After
  lift. Location `_request.py`.
- `send_with_retries` — the shared bounded retry loop wrapping every SDK call of all four
  operations of both providers. Location `_request.py`.

### Changed Entities

- `Config` — new field `llm_request_attempts` (default 3, positive integer, layered merge, env
  `PRETTYPLAY_LLM_REQUEST_ATTEMPTS`).
- `LLMProvider` (all four method requirements), `LLMProvider::OpenAIProvider`,
  `LLMProvider::AnthropicProvider` — construction with `max_retries=0`; the single SDK call of
  every operation wrapped in `send_with_retries`; error mapping through the provider classifier.
- `PrettyplayError::LLMUnavailableError` — annotation semantics only (see above).

### Deleted Entities

- None.

### Usages and Annotations Changes

- `prettyplay/llm` document annotations: the three deleted one-request-per-attempt rules are
  replaced by the unified logical-attempt rule; a new paragraph fixes the shared transport retry
  mechanism (retryable/permanent families, delay policy, Retry-After cap, logging); a new
  paragraph supersedes the old setting names (`transport_attempts` → `llm_request_attempts`).
- `prettyplay/llm/.usages/providers.md`: parity sentence replaced; new "Transport retries"
  section; group diagnosis statements reworded to logical requests.
- `prettyplay/config/.usages/configuration.md`: TOML example line, env-table row and the
  "Request retries of the LLM port" section added.
- `prettyplay/failures/.usages/taxonomy.md`: the `LLMUnavailableError` row updated to the four
  operations and the retry semantics.

---

## Applied Fixes

### Fixed CODEMANIFEST Defects

- None. `goga lint` reports 11 cells, 0 errors before and after this design; the four
  consistency dimensions (interface↔type, type↔mutation, interface↔interface,
  annotations↔entity) pass on the changed manifests; `goga schema` confirms the dependency map
  is unchanged (`prettyplay/llm` → `prettyplay/config` + `prettyplay/failures`; consumers of
  `prettyplay/llm` import unchanged signatures only).

### Fixed Usages Practices (user-approved during this design, decision 1A)

- `.goga/usages/cooks/openai.md` and `.goga/usages/cooks/anthropic.md`: the policy bullet named
  the superseded setting `transport_attempts` / `PRETTYPLAY_TRANSPORT_ATTEMPTS`; both files now
  name `llm_request_attempts` / `PRETTYPLAY_LLM_REQUEST_ATTEMPTS`. No tracked sync source exists
  for the cooks in this repository, so the files were corrected in place. The supersession
  annotation of `prettyplay/llm/CODEMANIFEST` stays verbatim — the resync prerequisite it names
  is now satisfied. Verification: `grep -r transport_attempts` over `.goga/usages/` and
  `prettyplay/` matches only the supersession annotation itself.

---

## Entity Interaction and Data Flow

### Interaction Diagram

```
                       engine attempt (generation / healing / diagnosis / verdict)
                                     │ one logical LLM attempt
                                     ▼
        OpenAIProvider / AnthropicProvider  (prettyplay/llm)
        │ construction: SDK client with max_retries=0
        │ 1. build request fields (existing _request.py builders, unchanged)
        │ 2. send_with_retries(provider, operation,
        │        attempts=config.llm_request_attempts,
        │        classify=classify_openai_failure | classify_anthropic_failure,
        │        send=<one SDK call closure>)
        ▼
   ┌───────────────────── send_with_retries (_request.py) ─────────────────────┐
   │  send() ─ ok ───────────────────────────────────────────────► response    │
   │  send() ─ Exception ─► classify(error) ─► TransportFailureClassification  │
   │     ├─ permanent category ─────────────► LLMUnavailableError (chained)    │
   │     ├─ retry_after > 10 s ─────────────► LLMUnavailableError (actionable) │
   │     ├─ attempt == attempts ────────────► LLMUnavailableError (chained)    │
   │     └─ else: compute_transport_pause(attempt, retry_after)               │
   │              WARNING → logger "prettyplay"; time.sleep(pause); next send  │
   └───────────────────────────────────────────────────────────────────────────┘
        │ success                                  │ LLMUnavailableError
        ▼                                          ▼
  parse/validate answer                      engine propagation (unchanged):
  (extract_code_block, parse_*                generate/heal/diagnose → terminal;
  — outside the retry loop)                  classification → quiet WARNING skip
```

### Data Flows

- **Attempt budget flow**: `pyproject [tool.prettyplay].llm_request_attempts` →
  `load_config` (file layer) ← `PRETTYPLAY_LLM_REQUEST_ATTEMPTS` (env layer) ← programmatic
  `PrettyConfig(llm_request_attempts=…)` (override layer) → validated `Config` → provider reads
  `config.llm_request_attempts` once per request → `send_with_retries(attempts=…)`. Engine
  budgets (`generation_attempts`, `healing_attempts`, group budgets) never interact with it.
- **Failure flow**: SDK exception → `classify_*_failure` → `TransportFailureClassification`
  → (permanent | over-cap | exhausted → `LLMUnavailableError` chained) or (retryable →
  `compute_transport_pause` → WARNING + sleep → identical resend).
- **Success flow**: SDK response object passes through `send_with_retries` untouched → the
  operation extracts and validates the text answer exactly as today (`require_completion_text`,
  `extract_code_block`, `parse_*`) — response-content recovery never enters the retry loop.

### Entity Dependencies

- `send_with_retries` depends on `TransportFailureClassification` (via the `classify` callable's
  return contract), `compute_transport_pause`, `LLMUnavailableError` (imported from
  `prettyplay/failures`) and the stdlib `logging`/`time`/`random` modules.
- `classify_openai_failure` / `classify_anthropic_failure` depend on `TransportFailureClassification`
  and their SDK exception modules (`openai._exceptions`, `anthropic._exceptions` — imported from
  the public `openai` / `anthropic` packages).
- `compute_transport_pause` is stdlib-only (`random`).
- Providers depend on all four new routines; `Config` carries only the new scalar.
- Initialization order for implementation: `TransportFailureClassification` + label constants →
  `classify_*_failure` → `compute_transport_pause` → `send_with_retries` → provider rewiring →
  `Config` field + loader entries (any order between config and llm; both precede engine
  docstring alignment).

---

## Code Stack Trace

Verified against the actual sources: `openai` 3.14.1 and `anthropic` 1.6.0 (site-packages of the
project venv), `prettyplay` sources at the current working tree, practices `openai`,
`anthropic`, `conventions`.

### Trace: `Config` construction with `llm_request_attempts`

#### Chain
1. **Input**: TOML `[tool.prettyplay]` section, environment, programmatic
   `PrettyConfig(...)` — current code at `prettyplay/config/models.py:157`,
   `prettyplay/config/loader.py:273`.
2. Field declaration `llm_request_attempts: PositiveInt = 3` placed between `healing_attempts`
   and `send_screenshots` → checkpoint: matches the CODEMANIFEST signature order exactly —
   passed. `PositiveInt` is already imported (`models.py:8`); the `generation_attempts` /
   `healing_attempts` precedent uses the same type.
3. `loader.py` `_ENV_NAMES` gains `"llm_request_attempts"` → env name computed
   `PRETTYPLAY_LLM_REQUEST_ATTEMPTS` → checkpoint: the generic derivation
   (`setting.upper().replace('.', '_')`, `loader.py:23`) produces exactly the manifest-mandated
   name — passed.
4. `"llm_request_attempts"` joins `_INT_ENV_SETTINGS` (`loader.py:63`) → `_parse_env_scalar`
   parses `int(raw)`; unparseable raises `ConfigurationError` naming setting, received value and
   "a decimal integer" → checkpoint: manifest step-6 wording ("a decimal integer; an unparseable
   value raises the loud actionable ConfigurationError naming the setting, the received value and
   the accepted form") — passed.
5. `_ALLOWED_TEXT["llm_request_attempts"] = "a positive integer"` → `_render_validation`
   renders `llm_request_attempts: received 0 — allowed: a positive integer` on a
   `Config(llm_request_attempts=0)` failure → checkpoint: "fails loudly with the received value
   named" — passed.
6. Layered merge: scalar settings merge generically (`merged = {**section, **env}` at
   `loader.py:310`; `_apply_overrides` at `loader.py:233` treats an int override as
   participating when passed at construction) → checkpoint: no merge code change needed; the
   programmatic layer validates at its own construction because pydantic validates before
   `model_copy` — passed.
7. **Output**: validated `Config` with `llm_request_attempts: int` ≥ 1, default 3.

#### Checkpoint Summary
- Signature order and default: passed.
- Env name derivation and int parsing: passed.
- Loud validation with named value: passed.
- Existing tests `test_all_nineteen_properties_accessible` and
  `test_signature_declares_seventeen_fields_in_contract_order` (tests/config/test_models.py:29,
  :55) enumerate fields and must be extended (see Additional Instructions).

### Trace: `TransportFailureClassification`

#### Chain
1. **Input**: `category: str`, `retry_after: float | None` — constructed only by the two
   classifiers.
2. Pydantic v2 `BaseModel`, `model_config = ConfigDict(kw_only=True)`; `category: str = ""`,
   `retry_after: float | None = None` → checkpoint: mirrors the `FailureClassification` /
   `ComplianceFinding` precedent in `prettyplay/llm/models.py` and the `conventions` rule
   (kw_only, empty defaults; None only for explicit absence) — passed.
3. `retryable` is a plain `@property` returning `self.category in RETRYABLE_TRANSPORT_CATEGORIES`
   — a computed flag, not a constructor field → checkpoint: the CODEMANIFEST lists it under
   `properties`, not in the signature; pydantic v2 exposes a native `@property` normally —
   passed.
4. **Output**: immutable verdict consumed by `send_with_retries`.

#### Checkpoint Summary
- Model shape and property placement: passed.
- The closed nine-label set is enforced by the classifiers (the only constructors), never by
  pydantic validation — matches the annotation "an unrecognized failure classifies permanent
  before reaching this type".

### Trace: `classify_openai_failure` (verified against `openai` 3.14.1 `_exceptions.py` / `_client.py`)

#### Chain
1. **Input**: one exception raised by an openai SDK call (`OpenAIError` subtree in practice).
2. Permanent evidence first — `isinstance(error, APIStatusError)` plus body evidence:
   - quota: `getattr(error, "code", None) == "insufficient_quota"` or
     `getattr(error, "type", None) == "insufficient_quota"` → `quota_exhausted`. `APIError`
     parses `code`/`type` from the body's `error` object (`_exceptions.py:46-80`,
     `_client.py:851`), and OpenAI signals an exhausted quota as 429 with
     `code`/`type` `insufficient_quota` → checkpoint: "an explicitly exhausted quota — even
     when the status looks retryable, e.g. 429" — passed.
   - `AuthenticationError` → `authentication`; `PermissionDeniedError` → `permission_denied`;
     `BadRequestError` → `invalid_request`; `NotFoundError` → `not_found` → checkpoint: the
     SDK maps 400/401/403/404 to exactly these classes (`_client.py:852-862`) — passed.
3. Retryable evidence:
   - `APITimeoutError` → `timeout` (checked before `APIConnectionError`, of which it is a
     subclass, `_exceptions.py:111`).
   - `APIConnectionError` → `connection`.
   - `RateLimitError` → `rate_limit` (429, `_client.py:870`).
   - `isinstance(error, APIStatusError) and error.status_code == 408` → `timeout` →
     checkpoint: **the openai SDK has no 408 subclass** — a 408 arrives as generic
     `APIStatusError` (`_client.py:875` falls through), so the status must be matched on the
     class attribute — passed, recorded as design decision D5.
   - `isinstance(error, APIStatusError) and 500 <= error.status_code <= 599` → `server_error`
     (SDK maps ≥500 to `InternalServerError`, `_client.py:873`).
4. Retry-After extraction (category-independent): `response = getattr(error, "response", None)`;
   `raw = response.headers.get("retry-after")` when both present; parse `float(raw)`; a missing
   header, a non-numeric value (HTTP-date included — D4) or a non-finite result yields `None`
   → checkpoint: both SDKs carry `response: httpx.Response` on `APIStatusError`
     (`openai _exceptions.py:93`, `anthropic _exceptions.py:78`) — passed.
5. Any other exception (unnamed 4xx such as `ConflictError` 409 / `UnprocessableEntityError`
   422, `APIResponseValidationError`, a non-SDK exception) → `invalid_request` (user-approved
   decision 2A) → checkpoint: "never raise", "a never-recognized failure is never blindly
   retried" — passed.
6. **Output**: `TransportFailureClassification(category=…, retry_after=…)`.

#### Checkpoint Summary
- SDK exception mapping: passed (verified against installed sources).
- Quota precedence over retryable status: passed.
- `RetryLimitError`-style traps: none — the openai SDK 3.x has no `InsufficientQuotaError`
  class; the body-evidence rule covers it.

### Trace: `classify_anthropic_failure` (verified against `anthropic` 1.6.0 `_exceptions.py` / `_client.py`)

#### Chain
1. **Input**: one exception raised by an anthropic SDK call (`AnthropicError` subtree).
2. Permanent evidence first:
   - quota: `getattr(error, "type", None) == "billing_error"` → `quota_exhausted`.
     `anthropic.types.shared.error_type.ErrorType` includes the literal `"billing_error"` and
     `APIStatusError.__init__` copies `body.error.type` into `self.type`
     (`_exceptions.py:71-93`) → checkpoint: the anthropic analogue of the explicit
     exhausted-quota signal, same precedence rule — passed (D6).
   - `AuthenticationError` → `authentication`; `PermissionDeniedError` → `permission_denied`;
     `BadRequestError` → `invalid_request`; `NotFoundError` → `not_found` (`_client.py:548-558`).
3. Retryable evidence: `APITimeoutError` → `timeout`; `APIConnectionError` → `connection`;
   `RateLimitError` → `rate_limit`; `APIStatusError` with status 408 → `timeout` (the anthropic
   SDK also leaves 408 unmapped — generic `APIStatusError`); `APIStatusError` with status
   500–599 → `server_error`, which covers `InternalServerError` (500+), `ServiceUnavailableError`
   (503), `OverloadedError` (529) and `DeadlineExceededError` (504) uniformly → checkpoint: 529
   sits inside the contract's "any status 500 through 599" — passed (D7).
4. Retry-After extraction: identical shape to the openai classifier — `error.response.headers`
   `.get("retry-after")`, `float(...)` or `None`. The anthropic SDK's non-standard
   `retry-after-ms` header stays unread (D4).
5. Any other exception → `invalid_request` (2A).
6. **Output**: `TransportFailureClassification(category=…, retry_after=…)`.

#### Checkpoint Summary
- Rule-by-rule parity with the openai classifier: passed — same nine labels, same
  permanent-precedence order, same Retry-After handling; only the evidence classes differ.
- `RetryableError` (an `AnthropicError` subclass not tied to a response) falls to step 5 →
  permanent — conservative, consistent with the closed retryable set.

### Trace: `compute_transport_pause`

#### Chain
1. **Input**: `failed_attempt: int` (1-based number of the attempt that just failed),
   `retry_after: float | None`.
2. `base = min(2 ** (failed_attempt - 1), 10.0)` → the sequence 1, 2, 4, 8, 10, 10… →
   checkpoint: matches "one second doubled per prior failure, capped at ten" — passed.
3. `pause = base + random.uniform(0.0, base * 0.25)` → 0–25 % jitter of the base → checkpoint:
   "add a random jitter of 0–25 percent of the base" — passed; with the default budget the two
   pauses are 1–1.25 s and 2–2.5 s (ADR arithmetic confirmed).
4. `pause = min(pause, 10.0)` → checkpoint: the 10 s cap — passed.
5. `if retry_after is not None and 0 < retry_after <= 10.0: pause = max(pause, retry_after)` →
   checkpoint: "a valid retry_after — positive and at most 10 — raises the pause to the
   indicated wait when it exceeds the computed delay"; a non-positive parsed value is treated as
   invalid and ignored — passed.
6. **Output**: `float` pause in `(0, 10]`.

#### Checkpoint Summary
- Formula checkpoints: passed. No I/O, no sleeps — pure aside from `random.uniform` (the only
  random source; tests monkeypatch `random.uniform`).

### Trace: `send_with_retries`

#### Chain
1. **Input**: `provider: str` ("openai" | "anthropic"), `operation: str` ("generation" |
   "classification" | "group diagnosis" | "compliance verdict"), `attempts: int` (≥ 1 from
   validated `Config`), `classify: Callable[[Exception], TransportFailureClassification]`,
   `send: Callable[[], T]`.
2. Loop `for attempt in range(1, attempts + 1)`: run `send()`; a success returns its response
   as is — no log, no pause → checkpoint: "a success returns its response as is" — passed.
3. `except Exception as error:` (never `BaseException` — `KeyboardInterrupt` during the SDK call
   propagates untouched) → `failure = classify(error)` → checkpoint: the classifier contract
   (never raises) holds — passed.
4. `if not failure.retryable:` → `raise LLMUnavailableError(f"llm unavailable: {provider}
   request failed permanently: {failure.category}") from error` → checkpoint: immediate, no
   retry, original cause chained — passed.
5. `elif failure.retry_after is not None and failure.retry_after > 10.0:` → `raise
   LLMUnavailableError(f"llm unavailable: {provider} asked to wait {failure.retry_after:g}
   seconds — above the 10 second retry cap, not retrying") from error` → checkpoint: raised
   **before** any pause is computed, and ahead of the exhaustion branch (an over-cap
   Retry-After on the final attempt reports the over-cap cause) — passed.
6. `elif attempt == attempts:` → `raise LLMUnavailableError(f"llm unavailable: {provider}
   request failed after {attempts} attempts") from error` → checkpoint: exhaustion, cause
   chained — passed.
7. Else: `pause = compute_transport_pause(attempt, failure.retry_after)`; emit exactly one
   WARNING to `logging.getLogger("prettyplay")` — message `"llm request retry"`, `extra={`
   `"provider": provider, "operation": operation, "attempt": attempt, "category":
   failure.category, "delay": pause}` — then `time.sleep(pause)` and the next iteration sends
   the identical request (the same `send` closure is re-invoked) → checkpoint: one record per
   retry, five metadata fields, no secrets/payloads (the fields are labels and numbers only);
   structured `extra` matches the `conventions` logging rules — passed.
8. `KeyboardInterrupt` inside `time.sleep` propagates — nothing catches it, no further `send`
   call happens → checkpoint: "interrupts it without another retry" — passed.
9. **Output**: the successful response of `send()`, or `LLMUnavailableError` on the three
   terminal branches. Total sends ≤ `attempts`.

#### Checkpoint Summary
- All six algorithm steps of the contract trace to concrete branches in order 3→4→5→6 — passed.
- `attempts == 1`: the loop body runs once; any retryable failure hits branch 6 immediately —
  fully the single-send behavior — passed.
- Generic typing: module-level `T = TypeVar("T")`; annotations
  `Callable[[Exception], TransportFailureClassification]` and `Callable[[], T]` (Python 3.10+
  compatible, `typing`/`collections.abc` imports — D9).

### Trace: `OpenAIProvider` / `AnthropicProvider` operations (generation shown; the other three differ only in builder and parser)

#### Chain
1. **Input**: the operation arguments; `self._config`.
2. Build the request exactly as today (`build_fields_text` / `build_classification_fields` /
   `build_group_diagnosis_fields` / `build_compliance_fields`; the anthropic side appends its
   fixed `max_tokens=4096`) → checkpoint: unchanged code path — passed.
3. `client = self._get_client()` — resolved **before** entering the retry loop (D3). The
   missing-key check raises `LLMUnavailableError("llm unavailable: openai: OPENAI_API_KEY is
   not set")` outside the loop, so a library error never enters the SDK classifier →
   checkpoint: today's error surface for the missing key is preserved byte-for-byte — passed.
   `_get_client` constructs `OpenAI(api_key=…, base_url=… or None, max_retries=0)` /
   `Anthropic(api_key=…, base_url=… or None, max_retries=0)` → checkpoint: "the SDK never
   resends on its own" — both SDKs expose the `max_retries` constructor parameter (verified in
   their client signatures) — passed.
4. `response = send_with_retries("openai" | "anthropic", <operation label>,
   self._config.llm_request_attempts, classify_openai_failure | classify_anthropic_failure,
   lambda: client.chat.completions.create(...) | lambda: client.messages.create(...))` →
   checkpoint: "the single SDK call wrapped in `send_with_retries`" — exactly one SDK call
   inside the closure; the request kwargs are built once and reused verbatim on every resend —
   passed.
5. On success the answer flows through `require_completion_text` → `extract_code_block` /
   `parse_classification_line` / `parse_group_failure_classification` /
   `parse_compliance_verdict` — all unchanged, all **outside** the retry loop → checkpoint: "the
   invalid content of a successful response never enters this loop" — an empty completion
   raises `LLMUnavailableError` inside the operation without a resend, exactly as today —
   passed.
6. **Output**: parsed operation result, or `LLMUnavailableError` from the loop.

#### Checkpoint Summary
- All four operations of both providers: passed (the classification, diagnosis and compliance
  paths trace identically — same builders, same wrap, same parsers).
- The old `try/except OpenAIError → LLMUnavailableError` blocks are deleted — the loop owns
  the mapping now.

### Trace: engine propagation points (no engine code change)

#### Chain
1. `engine/generator.py` generate path (`generator.py:733`, `:860`), `engine/healer.py:98`,
   `engine/groups/diagnosis.py:83`, `engine/groups/recovery.py:128`, `:228`,
   `engine/compliance.py:98`: every site catches or propagates `LLMUnavailableError` by type →
   checkpoint: the exception type and propagation topology are unchanged; the retries happen
   inside the provider before the error ever surfaces, so "the engine itself adds no retries
   above them" holds with zero engine edits — passed.
2. `engine/classification.py` / `generator.py:860` quiet skip: `except LLMUnavailableError:
   logger.warning("verdict skipped: llm unavailable")` → checkpoint: unchanged; the skip now
   fires only after the bounded retries are exhausted — passed.
3. Docstrings at `generator.py:251/301/346/453/733`, `healer.py:98`,
   `groups/recovery.py:128/228`, `groups/diagnosis.py:83`, `compliance.py:98` still say
   "no retry" → implementation-stage docstring alignment only (see Additional Instructions);
   no behavioral change.

#### Checkpoint Summary
- Engine/groups contract rewording requires no code change: passed.

---

## Algorithm Design

### `TransportFailureClassification`

**Responsibility**: the immutable verdict of one transport failure classification — the label
and the provider-asked wait.

**Algorithm** (construction is trivial; the logic lives in `retryable`):
```
retryable:
  RETURN category ∈ {connection, timeout, rate_limit, server_error}
```

**Module constants** (`_request.py`):
```
TRANSPORT_CONNECTION = "connection"; TRANSPORT_TIMEOUT = "timeout"
TRANSPORT_RATE_LIMIT = "rate_limit"; TRANSPORT_SERVER_ERROR = "server_error"
TRANSPORT_AUTHENTICATION = "authentication"; TRANSPORT_PERMISSION_DENIED = "permission_denied"
TRANSPORT_INVALID_REQUEST = "invalid_request"; TRANSPORT_NOT_FOUND = "not_found"
TRANSPORT_QUOTA_EXHAUSTED = "quota_exhausted"
RETRYABLE_TRANSPORT_CATEGORIES = frozenset({connection, timeout, rate_limit, server_error})
PERMANENT_TRANSPORT_CATEGORIES = frozenset({authentication, permission_denied,
                                            invalid_request, not_found, quota_exhausted})
```
House style follows the existing `CATEGORY_*` / `CATEGORIES` constants in `_request.py`.

**Errors**: none — a plain model.

**Edge cases**:
- `retry_after == 0.0` → carried verbatim; treated as invalid by the pause rule (ignored).
- `category` outside the nine labels → impossible by construction (the classifiers are the only
  producers); `retryable` would answer `False` — fail-safe permanent.

### `classify_openai_failure` / `classify_anthropic_failure`

**Responsibility**: the single classification point of one provider — SDK exception → verdict;
pure, total (never raises), no I/O.

**Algorithm** (shared shape; evidence classes per SDK):
```
GIVEN error
1. permanent evidence (first match wins):
   a. openai:  APIStatusError with code|type == "insufficient_quota"      → quota_exhausted
      anthropic: APIStatusError with type == "billing_error"             → quota_exhausted
   b. AuthenticationError   → authentication
   c. PermissionDeniedError → permission_denied
   d. BadRequestError       → invalid_request
   e. NotFoundError         → not_found
2. retryable evidence:
   a. APITimeoutError                                  → timeout
   b. APIConnectionError                               → connection
   c. RateLimitError                                   → rate_limit
   d. APIStatusError with status_code == 408           → timeout
   e. APIStatusError with 500 ≤ status_code ≤ 599      → server_error
3. retry_after := float(response.headers["retry-after"]) when parseable and finite, else None
   (extraction is category-independent; HTTP-dates and the anthropic retry-after-ms
    are not parsed — D4)
4. no rule matched → invalid_request                    (D2/2A — permanent fallback)
RETURN TransportFailureClassification(category, retry_after)
```

**Errors**: never raises — any attribute access goes through `getattr(..., None)` guards so
even a non-SDK exception classifies.

**Edge cases**:
- 429 carrying `insufficient_quota` → `quota_exhausted` (permanent), never `rate_limit` — step 1
  precedes step 2.
- 409 / 422 / 413 (unnamed 4xx) → `invalid_request` — the closed retryable set excludes them.
- `APIResponseValidationError` (a successful response that failed SDK-side validation) →
  `invalid_request`, permanent — a retry of the identical request is not contractually
  warranted.

### `compute_transport_pause`

**Responsibility**: the fixed delay policy of the port.

**Algorithm**:
```
GIVEN failed_attempt (≥ 1), retry_after
1. base := min(2 ** (failed_attempt - 1), 10.0)
2. pause := base + random.uniform(0.0, base * 0.25)
3. pause := min(pause, 10.0)
4. IF retry_after is not None AND 0 < retry_after ≤ 10.0:
     pause := max(pause, retry_after)
RETURN pause
```

**Errors**: none.

**Edge cases**:
- `failed_attempt = 1` → base 1.0, pause ∈ [1.0, 1.25] (plus any lift).
- `failed_attempt ≥ 5` → pause is exactly 10.0 (cap dominates; a lift cannot exceed it).
- `retry_after > 10` → never an input as a wait: the loop terminates before calling this
  routine (contract constraint; the function itself would still be safe — the lift guard
  excludes it).
- `retry_after` = 0 / negative / None → ignored.

### `send_with_retries`

**Responsibility**: the only retry authority of the port — bounded resends of the identical
SDK request, terminal mapping to `LLMUnavailableError`, one WARNING per retry.

**Algorithm**:
```
GIVEN provider, operation, attempts (≥ 1), classify, send
logger := logging.getLogger("prettyplay")
FOR attempt IN 1..attempts:
  TRY RETURN send()
  EXCEPT Exception AS error:
    failure := classify(error)
    IF NOT failure.retryable:
      RAISE LLMUnavailableError(
          f"llm unavailable: {provider} request failed permanently: {failure.category}") FROM error
    IF failure.retry_after IS NOT None AND failure.retry_after > 10.0:
      RAISE LLMUnavailableError(
          f"llm unavailable: {provider} asked to wait {failure.retry_after:g} seconds"
          " — above the 10 second retry cap, not retrying") FROM error
    IF attempt == attempts:
      RAISE LLMUnavailableError(
          f"llm unavailable: {provider} request failed after {attempts} attempts") FROM error
    pause := compute_transport_pause(attempt, failure.retry_after)
    logger.warning("llm request retry", extra={"provider": provider, "operation": operation,
                  "attempt": attempt, "category": failure.category, "delay": pause})
    time.sleep(pause)          # KeyboardInterrupt propagates — no further send
```

**Errors**: `LLMUnavailableError` on the three terminal branches, each with the original SDK
cause chained; nothing else escapes except what `send` raises that is not an `Exception`.

**Edge cases**:
- `attempts == 1` → exactly one send; a retryable failure exhausts immediately.
- Over-cap Retry-After on the last attempt → the over-cap message wins (checked before
  exhaustion).
- A retryable failure whose `retry_after` ≤ 10 → the pause is lifted to the asked wait; the
  resend still happens (only waits above the cap terminate).
- Success on a later attempt → no additional log record beyond the earlier retries' WARNINGs.

### `Config` (changed)

**Responsibility**: unchanged — the validated settings source.

**Algorithm** (delta only): field `llm_request_attempts: PositiveInt = 3` between
`healing_attempts` and `send_screenshots`; loader registries extended
(`_ENV_NAMES`, `_INT_ENV_SETTINGS`, `_ALLOWED_TEXT`); docstring attribute line added mirroring
the CODEMANIFEST parameter text.

**Errors**: `ValidationError` (rendered by `_render_validation` with "a positive integer");
`ConfigurationError` for an unparseable env value.

**Edge cases**: env value `"0"` parses to 0 and fails model validation loudly (naming the
setting and value); env value `"abc"` fails at the env parse with the accepted form named.

### `OpenAIProvider` / `AnthropicProvider` (changed)

**Responsibility**: unchanged operations; the send step and the error mapping move into the
shared loop.

**Algorithm** (delta per operation):
```
1. build request (existing builders; anthropic adds max_tokens=4096)   — unchanged
2. client := self._get_client()          # max_retries=0 inside; key check outside the loop (D3)
3. response := send_with_retries(provider label, operation label,
                                 config.llm_request_attempts,
                                 classify_openai_failure | classify_anthropic_failure,
                                 <one SDK call closure>)
4. parse/validate the answer (existing require_completion_text + parse path) — unchanged
```

**Errors**: `LLMUnavailableError` (loop-terminal or missing-key), `ComplianceVerdictError`
(compliance parse, unchanged). The per-operation `except OpenAIError`/`except AnthropicError`
blocks are removed.

**Edge cases**: the compliance operation and the diagnosis operation wrap exactly like
generation and classification — the manifest heading "Algorithm (all four operations)" is
literal; the operation labels passed to `send_with_retries` are `"generation"`,
`"classification"`, `"group diagnosis"`, `"compliance verdict"`.

---

## Cross-cutting Concerns

- **Error handling**: one terminal kind — `LLMUnavailableError` — with the original SDK cause
  chained on every branch (`raise … from`); message always names the provider. Response-content
  recovery (empty completion, malformed verdicts) stays in the operations and is never retried;
  `ComplianceVerdictError` semantics untouched. Engine handling topology unchanged.
- **Logging**: exactly one WARNING record per retry on the logger `prettyplay` (module-level
  `logger = logging.getLogger("prettyplay")`, matching `engine/generator.py:25` and
  `engine/groups/diagnosis.py:11`); message `"llm request retry"`; `extra` carries
  `provider`, `operation`, `attempt`, `category`, `delay`; lowercase stable event name per
  `conventions`; no secrets, no request/response payloads — the fields are labels and numbers.
  No records on success; no records on terminal failures beyond the exceptions themselves.
- **Validation**: `llm_request_attempts` validates as a positive integer at every layer (file,
  env, programmatic); env parsing is a decimal integer; failures are loud and actionable,
  naming the setting and the received value.
- **Caching**: none — the retry loop is stateless per request; no new cache interaction.
- **Concurrency**: no shared mutable state; `send_with_retries` runs on the calling thread
  (the engine/driver threads as today). `time.sleep` is the only blocking wait; it honors
  `KeyboardInterrupt`. No thread-safety requirements beyond the existing port contract.

---

## Usages Analysis

### `conventions`
- **What it provides**: mandatory Python rules — relative imports, pydantic v2 kw_only models
  with empty defaults, `logging` with structured `extra`, Google-style docstrings, test
  structure and mocking boundaries, 3.10+ compatibility.
- **Where used**: all five new entities (`TransportFailureClassification` cites it); the whole
  implementation and test suite.
- **Why chosen**: the project-wide code standard referenced by every manifest.
- **How exactly**: relative imports inside `prettyplay.llm`; `ConfigDict(kw_only=True)` +
  empty defaults for the new model; `logging.getLogger("prettyplay")` + `extra` metadata;
  Google docstrings on every new public symbol; tests mirrored under `tests/llm/`,
  `tests/config/`; mocks only at the SDK/sleep/random boundaries.

### `openai` (corrected in this design)
- **What it provides**: the openai SDK call patterns, client initialization with
  `max_retries=0`, the exception mapping table, the bounded-backoff policy bullet.
- **Where used**: `OpenAIProvider`, `classify_openai_failure`.
- **Why chosen**: the per-SDK practice of the port; the CODEMANIFEST routes every SDK concern
  through it.
- **How exactly**: `OpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=0)` (+
  `base_url` override when set); exception evidence per the table above; the policy names
  `llm_request_attempts` / `PRETTYPLAY_LLM_REQUEST_ATTEMPTS` (supersession applied, 1A).

### `anthropic` (corrected in this design)
- **What it provides**: the anthropic SDK mirror of the above — init with `max_retries=0`, the
  exception hierarchy, `max_tokens=4096`, the same bounded-backoff policy bullet.
- **Where used**: `AnthropicProvider`, `classify_anthropic_failure`.
- **Why chosen**: provider parity — the port's absolute rule.
- **How exactly**: `Anthropic(api_key=…, max_retries=0)`; `billing_error` as the explicit
  quota signal; 529/503/504 inside the 5xx retryable family; identical policy bullet with the
  corrected setting names (1A).

### `json_repair`
- **What it provides**: syntax salvage of malformed JSON verdict answers.
- **Where used**: `parse_compliance_verdict`, `parse_group_failure_classification` — untouched
  by this change.
- **Why chosen / how**: unchanged; listed for completeness — it participates in response
  parsing, which the retry loop deliberately never touches.

### Imported Usages
- None — `prettyplay/llm` imports types only (`Config` from `prettyplay/config`;
  `LLMUnavailableError`, `ComplianceVerdictError` from `prettyplay/failures`); no
  `Imports.Usages` groups exist in the changed cells.

---

## `.usages/` Update

### Cell: `prettyplay/config`
- **`configuration.md`** → `prettyplay/config/.usages/configuration.md`
  - Status: current (updated by the apply stage: TOML line `llm_request_attempts = 3`, env-table
    row, "Request retries of the LLM port" section with the `PrettyConfig(llm_request_attempts=5)`
    example).
  - Additions/Updates needed: none — verified against this design.

### Cell: `prettyplay/llm`
- **`providers.md`** → `prettyplay/llm/.usages/providers.md`
  - Status: current (parity sentence, "Transport retries" section, group diagnosis wording).
  - Additions/Updates needed: none — the seven bullets match the contract and this design
    (budget `llm_request_attempts`, delays, Retry-After rule, WARNING fields, budget
    neutrality).
- **`classification.md`** → `prettyplay/llm/.usages/classification.md`
  - Status: current — no transport-retry statements; no changes required.
- New files: none — the retry mechanism belongs to the existing providers domain, not a new
  consumer-facing domain.

### Cell: `prettyplay/failures`
- **`taxonomy.md`** → `prettyplay/failures/.usages/taxonomy.md`
  - Status: current (the `LLMUnavailableError` row names the four operations and the retry
    semantics).
  - Additions/Updates needed: none.

### Cells: `prettyplay/engine`, `prettyplay/engine/groups`
- No `.usages/` directories exist in these cells — skipped per the decision rules.

---

## Test Stack Trace

### General Setup

- Unit tests mirror the sources: the retry machinery lands in `tests/llm/test_request.py`
  (new test classes appended to the existing module for `_request.py`); provider wiring tests
  extend `tests/llm/test_openai_provider.py` / `tests/llm/test_anthropic_provider.py`; config
  tests extend `tests/config/test_models.py` / `tests/config/test_loader.py`.
- Existing fake-client helpers are reused (`make_client_create`,
  `completion_answer`, `mock.patch.object(provider, "_get_client", …)`).
- No real waits: `time.sleep` and `random.uniform` are monkeypatched at the external boundary
  (per `conventions` mock rules and the arch checklist).
- `caplog` captures the `prettyplay` logger for the log-field tests
  (`caplog.set_level(logging.WARNING, logger="prettyplay")`).
- SDK exception construction: status errors need a response object — a helper builds
  `SimpleNamespace(status_code=…, headers={…})` and the exception via
  `APIStatusError.__init__`-compatible fakes where constructing real ones is impractical;
  prefer the real SDK classes with a faked `response=` kwarg (they accept
  `response: httpx.Response` — a `SimpleNamespace` with `headers`/`status_code`/`request`
  attributes suffices because the classifiers only read attributes).

### Source File Registry

- `prettyplay/llm/_request.py` — new: constants, `TransportFailureClassification`,
  `classify_openai_failure`, `classify_anthropic_failure`, `compute_transport_pause`,
  `send_with_retries`.
- `prettyplay/llm/openai_provider.py`, `prettyplay/llm/anthropic_provider.py` — rewired send
  step, `max_retries=0`, deleted per-operation except blocks.
- `prettyplay/llm/__init__.py` — facade export of the five new names.
- `prettyplay/config/models.py`, `prettyplay/config/loader.py` — the new setting.
- Tests: `tests/llm/test_request.py`, `tests/llm/test_openai_provider.py`,
  `tests/llm/test_anthropic_provider.py`, `tests/config/test_models.py`,
  `tests/config/test_loader.py`.

---

### Positive Tests

#### `test_classify_openai_failure_maps_the_retryable_family`

**Setup**: import `openai` exceptions; helper `status_error(cls_or_status, headers=None)`
building an `APIStatusError` (or subclass) with a faked `httpx`-like response
(`SimpleNamespace(status_code=…, headers=headers or {}, request=SimpleNamespace())`) and
`body=None`.

**Input**: parametrized —
`APIConnectionError(request=…)`, `APITimeoutError(request=…)` (both take only `request`),
`RateLimitError(..., response=…429…)`, `APIStatusError(..., 408 ...)`,
`InternalServerError(..., 500 ...)`, `APIStatusError(..., 599 ...)`.

**Trace**:
```
classify_openai_failure(<exception>)
  → isinstance ladder: permanent set — no match
  → APITimeoutError before APIConnectionError; RateLimitError → rate_limit;
    status 408 → timeout; 500–599 → server_error
  → retry_after extraction: headers without "retry-after" → None
  → TransportFailureClassification(category=<expected>, retry_after=None)
```

**Assertions**:
```
failure.category == param.expected   # connection | timeout | rate_limit | server_error
failure.retryable is True
failure.retry_after is None
```

**Sufficiency**: pins the retryable evidence table — prevents a regressions that would
blindly retry permanent failures or drop a retryable family member (the core of the backoff).

---

#### `test_classify_openai_failure_quota_beats_retryable_status`

**Setup**: a `RateLimitError` (429) whose `code` attribute is set to `"insufficient_quota"`
(real class, response faked with status 429; set `error.code` after construction or pass a
`body` dict `{"error": {"code": "insufficient_quota", "type": "insufficient_quota"}}`).

**Input**: the quota 429.

**Trace**:
```
classify_openai_failure(error)
  → step 1a: code|type == "insufficient_quota" → quota_exhausted   (before the 429 rule)
  → TransportFailureClassification(quota_exhausted, None)
```

**Assertions**:
```
failure.category == "quota_exhausted"
failure.retryable is False
```

**Sufficiency**: guards the permanent-precedence rule — an exhausted quota on a 429 must never
be retried; the most consequential precedence bug this feature could carry.

---

#### `test_classify_anthropic_failure_billing_error_is_permanent_quota`

**Setup**: an `anthropic` `APIStatusError`-shaped error with `type = "billing_error"`
(set the attribute; the classifier reads `getattr(error, "type", None)`).

**Input**: the billing-error exception with status 429.

**Trace**:
```
classify_anthropic_failure(error)
  → step 1a: type == "billing_error" → quota_exhausted
  → TransportFailureClassification(quota_exhausted, <retry_after>)
```

**Assertions**:
```
failure.category == "quota_exhausted"
failure.retryable is False
```

**Sufficiency**: the anthropic quota signal — without it a billing-stopped account would be
retried to exhaustion on every request.

---

#### `test_classify_failures_parse_retry_after_seconds`

**Setup**: parametrized over both classifiers; a `RateLimitError` with
`headers={"retry-after": "7"}`; variants `"2.5"`, `"0"`, `"-3"`, `"Tue, 07 Oct 2026…"`,
missing header.

**Input**: each exception.

**Trace**:
```
classify_<sdk>_failure(error)
  → rate_limit branch
  → float("7") → 7.0 | float("2.5") → 2.5 | "-3" → -3.0 (carried; invalid for the lift)
  → HTTP-date / missing → None
```

**Assertions**:
```
failure.retry_after == 7.0 | 2.5 | -3.0 | None | None   # per the parametrized case
failure.category == "rate_limit"
```

**Sufficiency**: pins the Retry-After parsing rule (numeric seconds only, D4) — the value that
drives both the over-cap termination and the pause lift.

---

#### `test_classify_failures_unrecognized_exception_is_permanent_invalid_request`

**Setup**: `ValueError("boom")` and an openai `ConflictError`-shaped status error (409).

**Input**: both, through both classifiers (parametrized 2×2).

**Trace**:
```
classify_<sdk>_failure(error)
  → no permanent named class matches (ValueError matches nothing; 409 matches no rule)
  → no retryable rule matches
  → fallback → invalid_request
```

**Assertions**:
```
failure.category == "invalid_request"
failure.retryable is False
```

**Sufficiency**: the never-raise/never-blindly-retry contract plus the user-approved fallback
label (2A); protects against an unrecognized exception crashing the loop or being retried.

---

#### `test_compute_transport_pause_base_sequence_jitter_and_cap`

**Setup**: `monkeypatch.setattr("random.uniform", lambda a, b: 0.0)` (jitter off) for the
deterministic cases.

**Input**: `compute_transport_pause(n, None)` for `n` in 1..7.

**Trace**:
```
compute_transport_pause(n, None)
  → base = min(2**(n-1), 10) → 1, 2, 4, 8, 10, 10, 10
  → jitter 0 → pause = base; cap 10 no-op
```

**Assertions**:
```
[compute_transport_pause(n, None) for n in range(1, 8)] == [1.0, 2.0, 4.0, 8.0, 10.0, 10.0, 10.0]
```

**Sufficiency**: the fixed delay policy is contractual (ADR) — an off-by-one in the exponent
or cap would silently change the wait pattern.

---

#### `test_compute_transport_pause_jitter_bounds_and_final_cap`

**Setup**: `monkeypatch.setattr("random.uniform", lambda a, b: b)` (max jitter).

**Input**: `compute_transport_pause(1, None)` and `compute_transport_pause(5, None)`.

**Trace**:
```
attempt 1: base 1, jitter upper bound 0.25 → pause 1.25
attempt 5: base 10, jitter 2.5 → 12.5 → capped to 10.0
```

**Assertions**:
```
compute_transport_pause(1, None) == 1.25
compute_transport_pause(5, None) == 10.0
```

**Sufficiency**: the 0–25 % jitter window and the 10 s cap — the ADR's exact arithmetic
(1–1.25 s and 2–2.5 s under the default budget).

---

#### `test_compute_transport_pause_retry_after_lifts_within_cap`

**Setup**: jitter off (`random.uniform → 0`).

**Input**: `compute_transport_pause(1, 5.0)`, `compute_transport_pause(3, 2.0)`,
`compute_transport_pause(1, 0.0)`, `compute_transport_pause(1, None)`.

**Trace**:
```
(1, 5.0): base 1 → pause 1 → lift max(1, 5) → 5.0
(3, 2.0): base 4 → pause 4 → max(4, 2) → 4.0   (asked wait smaller — no effect)
(1, 0.0): 0 is not positive → ignored → 1.0
(1, None): ignored → 1.0
```

**Assertions**:
```
results == [5.0, 4.0, 1.0, 1.0]
```

**Sufficiency**: the "greater of the indicated wait and the computed delay" rule and the
validity guard (positive and ≤ 10) — the exact Retry-After honoring semantics.

---

#### `test_send_with_retries_success_returns_response_without_side_effects`

**Setup**: `sent = []; send = lambda: sent.append(1) or "ok"`; classifier =
`lambda e: pytest.fail("must not classify")`; `monkeypatch` on `time.sleep` to record calls.

**Input**: `send_with_retries("openai", "generation", 3, classifier, send)`.

**Trace**:
```
loop attempt 1 → send() → "ok" returned
  → no classify, no WARNING, no sleep
```

**Assertions**:
```
result == "ok"
sent == [1]                       # exactly one send
sleep_calls == []                 # no wait
caplog.records == []              # no log records
```

**Sufficiency**: the happy path stays byte-identical to a plain send — no hidden latency or
log noise on success.

---

#### `test_send_with_retries_retries_then_succeeds_with_two_warnings`

**Setup**: `attempts = [anthropic.APIConnectionError(request=…),
anthropic.APIConnectionError(request=…), "ok"]`; classifier =
`classify_anthropic_failure`; `monkeypatch.setattr(time, "sleep", record)`; `caplog` on the
`prettyplay` logger; `random.uniform → 0`.

**Input**: `send_with_retries("anthropic", "group diagnosis", 3, classify, send)` where `send`
raises an Anthropic connection failure twice, then returns a response object.

**Trace**:
```
attempt 1 → Anthropic connection error → Anthropic classifier → connection (retryable) → not last
  → pause = compute_transport_pause(1, None) = 1.0
  → WARNING(provider=anthropic, operation=group diagnosis, attempt=1, category=connection, delay=1.0)
  → sleep(1.0)
attempt 2 → raise → classify → pause 2.0 → WARNING(attempt=2, delay=2.0) → sleep(2.0)
attempt 3 → response returned
```

**Assertions**:
```
result is response
send_call_count == 3
[sleep args] == [1.0, 2.0]
len(caplog.records) == 2
records[0].levelname == "WARNING"; records[0].name == "prettyplay"
records[0].provider == "anthropic"; records[0].operation == "group diagnosis"
records[0].attempt == 1; records[0].category == "connection"; records[0].delay == 1.0
```

**Sufficiency**: the canonical retry cycle — attempt accounting, pause sequence, exactly one
WARNING per retry with the five contractual fields, and the identical request re-sent
(the same closure) up to the budget.

---

#### `test_providers_construct_clients_with_max_retries_zero`

**Setup**: `monkeypatch.setenv("OPENAI_API_KEY", "test")` and
`monkeypatch.setenv("ANTHROPIC_API_KEY", "test")`; separately patch
`prettyplay.llm.openai_provider.OpenAI` to return a fake client whose
`chat.completions.create` yields a completion, and
`prettyplay.llm.anthropic_provider.Anthropic` to return one whose `messages.create`
yields a message. Retain each patched constructor to inspect its call.

**Input**: `OpenAIProvider(Config(model="gpt-5"))` → `generate_step_code(...)` (minimal args);
`AnthropicProvider(Config(provider="anthropic", model="claude…"))` → `generate_step_code(...)`.

**Trace**:
```
OpenAI operation → _get_client() sees OPENAI_API_KEY → OpenAI(api_key=..., base_url=None,
  max_retries=0) → fake chat.completions.create returns a completion
Anthropic operation → _get_client() sees ANTHROPIC_API_KEY → Anthropic(api_key=...,
  base_url=None, max_retries=0) → fake messages.create returns a message
```

**Assertions**:
```
openai_ctor.call_args.kwargs["max_retries"] == 0
anthropic_ctor.call_args.kwargs["max_retries"] == 0
```

**Sufficiency**: "SDK built-in retries are disabled" — without it the configured budget would
not be the real send limit (SDK defaults to 2 retries).

---

#### `test_provider_transient_failure_recovers_inside_one_logical_attempt`

**Setup**: fake client whose `create` raises a connection-shaped `APIConnectionError` on the
first call and answers on the second; `Config(model="gpt-5", llm_request_attempts=2)`;
`mock.patch.object(provider, "_get_client", return_value=client)`; sleep monkeypatched.

**Input**: `provider.generate_step_code(prompt="p", …)` (full minimal arg set as in the
existing tests).

**Trace**:
```
generate_step_code → build_fields_text → send_with_retries(attempts=2)
  → send #1 raises → classify → connection → pause → WARNING → sleep
  → send #2 returns completion("```python\ndef step(page)…```")
→ require_completion_text → extract_code_block
```

**Assertions**:
```
result == "def step(page)…\n"
client.create.call_count == 2
```

**Sufficiency**: end-to-end proof that a transient outage no longer kills a logical attempt —
the headline behavior of the feature, through the real provider path.

---

#### `test_config_llm_request_attempts_field_defaults_and_order`

**Setup**: none (pure model check).

**Input**: `Config()`; `Config.model_fields`.

**Trace**:
```
Config() → defaults
model_fields keys → the contract order: generation_attempts at index 13,
healing_attempts at 14, llm_request_attempts at 15
```

**Assertions**:
```
Config().llm_request_attempts == 3
list(Config.model_fields)[13:16] == ["generation_attempts", "healing_attempts", "llm_request_attempts"]
```

**Sufficiency**: the default and the signature position fixed by the CODEMANIFEST.

---

#### `test_loader_env_override_parses_decimal_integer`

**Setup**: `tmp_path` pyproject.toml with `[tool.prettyplay] model = "m"` and
`llm_request_attempts = 2`; `monkeypatch.setenv("PRETTYPLAY_LLM_REQUEST_ATTEMPTS", "5")`;
`PRETTYPLAY_*` browser/legacy env cleaned.

**Input**: `load_config(str(tmp_path / "pyproject.toml"))`.

**Trace**:
```
file layer {llm_request_attempts: 2} ← env layer 5 (int parse) → Config validates 5
```

**Assertions**:
```
config.llm_request_attempts == 5
```

**Sufficiency**: the env precedence of the new setting — the `generation_attempts` pattern
extended.

---

#### `test_facade_exports_the_transport_machinery`

**Setup**: none.

**Input**: `import prettyplay.llm as llm`.

**Trace**:
```
facade __init__ re-exports the five names from ._request
```

**Assertions**:
```
all(name in llm.__all__ and getattr(llm, name) is not None for name in
    ["TransportFailureClassification", "classify_openai_failure",
     "classify_anthropic_failure", "compute_transport_pause", "send_with_retries"])
```

**Sufficiency**: the arch-plan checklist — the cell facade exposes the retry machinery; the
root facade stays unchanged (negative assertion: the names are absent from
`prettyplay.__all__`).

---

### Negative Tests

#### `test_send_with_retries_permanent_failure_terminates_immediately`

**Setup**: `send` raises an `AuthenticationError`-shaped exception every call; classifier =
`classify_openai_failure`; sleep recorder; `caplog`.

**Input**: `send_with_retries("openai", "generation", 3, classify, send)`.

**Trace**:
```
attempt 1 → raise → classify → authentication (not retryable)
  → raise LLMUnavailableError("llm unavailable: openai request failed permanently: authentication")
     from error
```

**Assertions**:
```
pytest.raises(LLMUnavailableError) — "openai" in str(excinfo.value); "authentication" in str(...)
excinfo.value.__cause__ is the SDK error
send_call_count == 1; sleep_calls == []; caplog.records == []
```

**Sufficiency**: "never retry a permanent category" — the fail-fast half of the mechanism and
the chained-cause requirement.

---

#### `test_send_with_retries_over_cap_retry_after_terminates_before_any_pause`

**Setup**: `send` raises a `RateLimitError`-shaped error with
`headers={"retry-after": "30"}`; classifier = `classify_openai_failure`; sleep recorder;
`caplog`.

**Input**: `send_with_retries("openai", "classification", 3, classify, send)`.

**Trace**:
```
attempt 1 → raise → classify → rate_limit, retry_after=30.0
  → 30 > 10 → raise LLMUnavailableError("…asked to wait 30 seconds — above the 10 second
    retry cap, not retrying") from error      (branch order: before exhaustion and pause)
```

**Assertions**:
```
pytest.raises(LLMUnavailableError) — "10 second retry cap" in str(excinfo.value)
excinfo.value.__cause__ is the SDK error
send_call_count == 1; sleep_calls == []; caplog.records == []
```

**Sufficiency**: the over-cap Retry-After rule — never an early resend, never a cap-breaking
wait, and the precedence over the exhaustion branch.

---

#### `test_send_with_retries_exhaustion_raises_with_cause_and_attempt_count`

**Setup**: `send` always raises a connection-shaped failure; classifier =
`classify_anthropic_failure`; sleep recorder; `random.uniform → 0`.

**Input**: `send_with_retries("anthropic", "compliance verdict", 3, classify, send)`.

**Trace**:
```
attempts 1, 2 → retry (pauses 1.0, 2.0; two WARNINGs)
attempt 3 → retryable but last → raise LLMUnavailableError(
    "llm unavailable: anthropic request failed after 3 attempts") from error
```

**Assertions**:
```
pytest.raises(LLMUnavailableError) — "after 3 attempts" in str(excinfo.value)
excinfo.value.__cause__ is the last SDK error
send_call_count == 3
[sleep args] == [1.0, 2.0]
len(caplog.records) == 2          # the terminal attempt logs nothing
```

**Sufficiency**: the bounded budget is a hard send limit and the exhaustion error is
actionable (provider + count + chained cause) — the guarantee that "attempts" means sends.

---

#### `test_send_with_retries_single_attempt_disables_retries`

**Setup**: `send` raises a connection-shaped failure; sleep recorder; `caplog`.

**Input**: `send_with_retries("openai", "generation", 1, classify, send)`.

**Trace**:
```
attempt 1 → retryable but attempt == attempts → immediate LLMUnavailableError
```

**Assertions**:
```
pytest.raises(LLMUnavailableError)
send_call_count == 1; sleep_calls == []; caplog.records == []
```

**Sufficiency**: `llm_request_attempts = 1` is the contractual single-send escape hatch.

---

#### `test_send_with_retries_keyboard_interrupt_during_wait_propagates`

**Setup**: `send` raises a connection-shaped failure; sleep raises `KeyboardInterrupt`;
classifier = `classify_openai_failure`.

**Input**: `send_with_retries("openai", "generation", 3, classify, send)`.

**Trace**:
```
attempt 1 → retryable → WARNING → sleep raises KeyboardInterrupt → propagates
  (loop catches only Exception; no second send)
```

**Assertions**:
```
pytest.raises(KeyboardInterrupt)
send_call_count == 1
```

**Sufficiency**: the cancellation contract — an interrupted wait must never trigger another
send.

---

#### `test_config_rejects_llm_request_attempts_below_one`

**Setup**: none (pytest.raises on model construction).

**Input**: `Config(llm_request_attempts=0)`; `-1`; `pytest.param` for both.

**Trace**:
```
PositiveInt validation fails → ValidationError; render names the field and the value
```

**Assertions**:
```
with pytest.raises(ValidationError): Config(llm_request_attempts=value)
rendered text contains "llm_request_attempts" and the received value
```

**Sufficiency**: "a value below 1 fails loudly with the received value named — never a silent
ignore" (mirrors the existing `test_zero_generation_attempts_fails_with_field_name`).

---

#### `test_loader_unparseable_env_llm_request_attempts_fails_loudly`

**Setup**: `tmp_path` pyproject with `[tool.prettyplay]`;
`monkeypatch.setenv("PRETTYPLAY_LLM_REQUEST_ATTEMPTS", "three")`.

**Input**: `load_config(str(tmp_path / "pyproject.toml"))`.

**Trace**:
```
_collect_env_overrides → _parse_env_scalar("llm_request_attempts", "three")
  → int("three") fails → ConfigurationError("llm_request_attempts: received 'three' —
    allowed: a decimal integer")
```

**Assertions**:
```
pytest.raises(ConfigurationError) — message names the setting, the value and the form
```

**Sufficiency**: the env parse error contract of step 6.

---

#### `test_provider_permanent_failure_maps_to_llm_unavailable_immediately`

**Setup**: fake client whose `create` raises an `AuthenticationError`-shaped error;
`Config(model="gpt-5")`; `mock.patch.object(provider, "_get_client", …)`; sleep recorder.

**Input**: `provider.classify_step_failure(...)` (minimal args).

**Trace**:
```
classify_step_failure → send_with_retries → permanent → LLMUnavailableError("…openai…")
```

**Assertions**:
```
pytest.raises(LLMUnavailableError) — "openai" in str(excinfo.value)
client.create.call_count == 1
```

**Sufficiency**: updates the existing single-send mapping test to the permanent branch of the
new mechanism — a bad key fails on the first send, not after the budget.

---

#### `test_missing_api_key_still_surfaces_before_the_retry_loop`

**Setup**: `monkeypatch.delenv("OPENAI_API_KEY", raising=False)`; `provider =
OpenAIProvider(Config())`; `caplog`; sleep recorder (must stay empty).

**Input**: `provider.classify_step_failure(...)`.

**Trace**:
```
operation → _get_client() raises LLMUnavailableError("…OPENAI_API_KEY is not set")
  → outside send_with_retries → propagates untouched (D3)
```

**Assertions**:
```
pytest.raises(LLMUnavailableError) — "OPENAI_API_KEY" in str(excinfo.value)
sleep_calls == []; caplog.records == []
```

**Sufficiency**: the client resolution ordering (D3) — the library's own actionable error is
never re-classified into the generic permanent message.

---

### Edge Case Tests

#### `test_transport_failure_classification_model_shape_and_retryable_truth_table`

**Setup**: none.

**Input**: `TransportFailureClassification(category=X)` for the nine labels; positional
construction attempt.

**Trace**:
```
kw_only model; retryable = category in the retryable family;
BaseModel.__init__ rejects a positional argument with TypeError before field validation
```

**Assertions**:
```
TransportFailureClassification(category="connection").retryable is True        # + timeout, rate_limit, server_error
TransportFailureClassification(category="authentication").retryable is False  # + permission_denied, invalid_request, not_found, quota_exhausted
TransportFailureClassification().retryable is False        # empty default category
pytest.raises(TypeError): TransportFailureClassification("connection")  # positional argument
```

**Sufficiency**: the model contract (pydantic v2, kw_only, empty defaults) and the
retry-or-raise decision table.

---

#### `test_send_with_retries_never_sends_more_than_the_budget`

**Setup**: `send` always fails retryably; attempts = 5; sleep recorder; `random.uniform → 0`.

**Input**: `send_with_retries("openai", "generation", 5, classify, send)` expecting the raise.

**Trace**:
```
sends at attempts 1..5; pauses 1,2,4,8 after the first four failures;
4 WARNINGs; the 5th failure → exhaustion raise without a pause
```

**Assertions**:
```
send_call_count == 5
[sleep args] == [1.0, 2.0, 4.0, 8.0]
len(caplog.records) == 4
```

**Sufficiency**: the budget boundary and the absence of a pause after the terminal fifth
failure; the 10 s cap is covered by `test_compute_transport_pause_base_sequence_jitter_and_cap`.

---

#### `test_send_with_retries_over_cap_retry_after_wins_over_exhaustion`

**Setup**: `send` raises a rate-limit-shaped error with `retry-after: 15`; attempts = 1.

**Input**: `send_with_retries("openai", "classification", 1, classify, send)`.

**Trace**:
```
attempt 1 → retryable, retry_after 15 > 10 → over-cap branch fires before the
exhaustion branch
```

**Assertions**:
```
pytest.raises(LLMUnavailableError) — "retry cap" in str(excinfo.value)
                            (not "after 1 attempts")
```

**Sufficiency**: pins the branch order 4-before-5 — the error message must name the
actionable cause (the asked wait), not the misleading "exhausted".

---

#### `test_send_with_retries_zero_retry_after_is_ignored_not_fatal`

**Setup**: rate-limit-shaped error with `headers={"retry-after": "0"}`; attempts = 2;
`random.uniform → 0`.

**Input**: `send_with_retries("openai", "generation", 2, classify, send)` with the second
send succeeding.

**Trace**:
```
attempt 1 → rate_limit, retry_after 0.0 → not > 10 → not last → pause = max-min rule
  with invalid (non-positive) lift → 1.0 → WARNING → sleep → attempt 2 succeeds
```

**Assertions**:
```
result is the response
sleep args == [1.0]
```

**Sufficiency**: a `Retry-After: 0` header is neither a termination nor a lift — the validity
guard of the pause rule exercised through the loop.

---

#### `test_logging_carries_no_request_payloads`

**Setup**: retry-then-succeed scenario (as above) with `caplog`; the send closure captured a
payload containing `"secret-token"` in its kwargs.

**Input**: run the retry; then scan the formatted records.

**Trace**:
```
WARNING records formatted → only the five metadata fields appear
```

**Assertions**:
```
all("secret-token" not in rec.getMessage() for rec in caplog.records)
all(set(("provider","operation","attempt","category","delay")) <= set(rec.__dict__) for rec in caplog.records)
```

**Sufficiency**: the never-secrets logging constraint, checked mechanically.

---

#### `test_engine_budgets_untouched_by_transport_retries` (integration)

**Setup**: real `OpenAIProvider` with `_get_client()` patched to return a fake SDK client:
its `chat.completions.create` raises `openai.APIConnectionError` on the first call and returns
a completion containing valid `def step(page) -> None:` code on the second. Use
`Config(model="gpt-5", llm_request_attempts=2, generation_attempts=1)` and monkeypatch
sleep. Pass that provider to a real `StepGenerator` with page, cache, reporter and settle
window fixtures that allow the generated code to execute and be cached; pass one known
`StepIdentity` and `RunBudgets(generation_limit=1, healing_limit=2)` to the same generator.

**Input**: `StepGenerator.generate(identity, step_text, step_type, previous_steps,
group_prompt, page, attempt_history, window)` for one generation cycle.

**Trace**:
```
engine `try_generation(identity)` grants attempt 1 (of generation_attempts=1)
→ real OpenAIProvider enters `send_with_retries(attempts=2)`
  → SDK send 1 fails retryably → WARNING → sleep → SDK send 2 returns a completion
→ provider extracts code → engine executes and caches it → `CachedStep` returned;
no second engine attempt occurs; `_generation_used[identity.filename] == 1`
```

**Assertions**:
```
cached_step.code == expected generated code; sdk_client.chat.completions.create.call_count == 2
budgets._generation_used[identity.filename] == 1  # transport retries consumed nothing
budgets.try_generation(identity) is False         # the single logical slot is exhausted
```

**Sufficiency**: the budget-neutrality guarantee end to end — the central invariant that
transport retries live inside one logical attempt.

---

## Additional Instructions for the Implementation Agent

- **Prerequisite satisfied**: the cooks practices were corrected in this design stage
  (`llm_request_attempts` / `PRETTYPLAY_LLM_REQUEST_ATTEMPTS` in both
  `.goga/usages/cooks/*.md`); nothing blocks implementation. Do not edit the supersession
  annotation of `prettyplay/llm/CODEMANIFEST` — it stays verbatim.
- **Design decisions to honor** (summarized):
  - D2 (user-approved): the permanent fallback label for unrecognized exceptions is
    `invalid_request` — both classifiers, last branch, never raises.
  - D3: providers resolve `self._get_client()` **before** entering `send_with_retries`; the
    send closure contains exactly one SDK call. The missing-key `LLMUnavailableError` never
    enters classification.
  - D4: Retry-After parsing is decimal seconds only (`float(...)`); HTTP-dates and the
    anthropic `retry-after-ms` header are treated as malformed (None). Extraction is
    category-independent; validity for the pause lift is `0 < retry_after ≤ 10`.
  - D5: HTTP 408 has no SDK subclass in either SDK — match `APIStatusError.status_code == 408`
    and label it `timeout`.
  - D6: quota evidence — openai: `code` or `type` == `"insufficient_quota"`; anthropic:
    `type` == `"billing_error"` (SDK `ErrorType` literal, verified in anthropic 1.6.0).
  - D7: anthropic 529/503/504 fall under the 500–599 `server_error` rule.
  - D9: `T = TypeVar("T")`; `Callable` from `typing`/`collections.abc` — Python 3.10+.
  - D16: terminal branch order inside the loop: permanent → over-cap Retry-After →
    exhaustion → pause/log/wait.
  - D17: export the five new names from `prettyplay/llm/__init__.py` (`__all__` updated);
    the root facade `prettyplay/__init__.py` stays unchanged.
- **Config loader**: three registry additions only — `_ENV_NAMES`, `_INT_ENV_SETTINGS`,
  `_ALLOWED_TEXT["llm_request_attempts"] = "a positive integer"`; the merge code is generic
  and needs no change.
- **Existing tests to update** (field enumerations, not behavior):
  `tests/config/test_models.py::test_all_nineteen_properties_accessible` → twenty entries
  (insert `llm_request_attempts` after `healing_attempts`); rename/extend
  `test_signature_declares_seventeen_fields_in_contract_order` → eighteen fields with
  `llm_request_attempts` between `healing_attempts` and `send_screenshots`.
- **Docstring alignment** (wording only, no behavior): replace the "no retry" phrasing on the
  provider-unavailability paths of `prettyplay/engine/generator.py` (≈ lines 251, 301, 346,
  453, 733), `engine/healer.py` (≈ 98), `engine/groups/recovery.py` (≈ 128, 228),
  `engine/groups/diagnosis.py` (≈ 83), `engine/compliance.py` (≈ 98) with the
  after-the-bounded-transport-retries wording; align the `LLMUnavailableError` class docstring
  in `prettyplay/failures/errors.py` with the widened CODEMANIFEST annotation.
- **Deleted code**: the per-operation `except OpenAIError` / `except AnthropicError` →
  `LLMUnavailableError` blocks in both providers are removed — `send_with_retries` owns the
  mapping. Keep `require_completion_text` exactly as is (empty completion stays outside the
  retry loop, per the contract constraint).
- **Message shapes** (keep stable, tests assert substrings): permanent —
  `llm unavailable: {provider} request failed permanently: {category}`; over-cap —
  `llm unavailable: {provider} asked to wait {n} seconds — above the 10 second retry cap,
  not retrying`; exhaustion — `llm unavailable: {provider} request failed after {attempts}
  attempts`. Always `raise … from` the original SDK error.
- **Verification** (from the arch plan checklist): `pytest tests/ -x`; `ruff check
  prettyplay/`; `goga lint`; `goga schema` shows the five new types at `_request.py`;
  `goga contract` once the implementation exists.
