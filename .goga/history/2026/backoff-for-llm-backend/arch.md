# Architecture Plan — Bounded transport backoff for LLM backend requests

## Topic

- Short name: **Bounded transport backoff for LLM backend requests**
- Plan path: `.goga/history/2026/backoff-for-llm-backend/arch.md`
- Behavioral authority: `.goga/history/2026/backoff-for-llm-backend/adr.md` (decision of 2026-10-07); task file `.goga/history/2026/backoff-for-llm-backend/task.md`
- Naming decision of this prototype session (overrides the task-file name): the setting is **`llm_request_attempts`** / **`PRETTYPLAY_LLM_REQUEST_ATTEMPTS`** (the task file's `transport_attempts` was rejected as unclear; semantics unchanged)
- The synced `openai` and `anthropic` practices still name the old setting. Their source must be corrected and the practices resynced before implementation; this plan does not edit those generated files. Until then, the new names in this contract take precedence over the stale practice lines.

All cells are **modifications** of existing cells; no new cells or Imports. The five new `prettyplay/llm` contract types must be exported from that cell's `__init__.py` and listed in its `__all__`, as required by the Python cell rules. The top-level `prettyplay` facade does not change.

## Implementation Order

1. **`prettyplay/failures`** — leaf (no Imports). Widens the `LLMUnavailableError` annotation consumed by every upstream cell; must land first so upstream wording references the final scope.
2. **`prettyplay/config`** — depends on `prettyplay/failures` (existing `PrettyplayError`, `taxonomy`). Adds `llm_request_attempts` read by the llm cell; must exist before the llm contract references it.
3. **`prettyplay/llm`** — depends on `prettyplay/config` (`Config`) and `prettyplay/failures` (`LLMUnavailableError`, `ComplianceVerdictError`), both existing. The core: five new contract types in `_request.py` plus provider/operation annotation reconciliation.
4. **`prettyplay/engine`** — depends on `prettyplay/llm` (existing). Annotation reconciliation of the generate Requirements.
5. **`prettyplay/engine/groups`** — depends on `prettyplay/engine` and `prettyplay/llm` (existing). Annotation reconciliation of the diagnosis Constraints.

## Artifacts

### Cell: `prettyplay/failures` — MODIFY

#### CODEMANIFEST diff

**CHANGE** the type annotation of `PrettyplayError::LLMUnavailableError(message: str)` (location `errors.py`).

Old annotation:

```yaml
    LLM infrastructure failure: the provider service is unreachable, times out, rate-limits or rejects authentication. Blocks only code generation and healing; cached steps keep running.

    `message`: the failure description naming the provider.

    Requirements:
    - Raised only on generation or healing paths; never on a cached step execution path
```

New annotation:

```yaml
    LLM infrastructure failure: the provider service is unreachable, times out, rate-limits or
    rejects authentication — raised when the bounded transport retries of one logical LLM attempt
    are exhausted, skipped by a permanent provider rejection or cut short by an over-cap
    Retry-After. Blocks every LLM operation — code generation, step failure classification, group
    diagnosis and the compliance verdict; cached steps keep running.

    `message`: the failure description naming the provider.

    Requirements:
    - Raised only on the LLM operation paths — generation, healing classification, group diagnosis
      and the compliance verdict, after the transport retries of the logical attempt; never on a
      cached step execution path
    - The original transport cause stays chained by the raiser (raise ... from)
```

Everything else in the CODEMANIFEST (header, other types, footer) stays unchanged.

#### `.usages/` files

**File:** `prettyplay/failures/.usages/taxonomy.md` — MODIFY (one table row; the rest verbatim).

Old row:

```md
| LLMUnavailableError | LLM infrastructure down | generation or healing ran while the provider was unavailable | restore provider access or keys; cached steps are unaffected |
```

New row:

```md
| LLMUnavailableError | LLM infrastructure down | an LLM operation (generation, failure classification, group diagnosis, compliance verdict) exhausted its bounded transport retries or met a permanent provider rejection | restore provider access or keys; cached steps are unaffected |
```

### Cell: `prettyplay/config` — MODIFY

#### CODEMANIFEST diff

**CHANGE** the `Config` signature — append `llm_request_attempts: int` after `healing_attempts: int`:

```yaml
"Config(provider: str, browser: BrowserConfig, model: str, generation_model: str, classification_model: str, base_url: str, cache_root: str, generation_prompt: str, classification_prompt: str, strict: bool, polling_timeout: float | None, polling_delay: float, interactive: bool, generation_attempts: int, healing_attempts: int, llm_request_attempts: int, send_screenshots: bool, generation_approve: bool)":
```

**ADD** the parameter description to the `Config` type annotation (after the `healing_attempts` line):

```
    `llm_request_attempts`: the total attempt budget of one LLM request — the maximum number of physical request sends of one logical LLM attempt of the port (generation, failure classification, group diagnosis, compliance verdict alike), the initial request included; default 3; 1 — request retries disabled, fully the single-send behavior; the retry delays themselves are fixed policy, never configurable; participates in the layered merge like every other scalar setting.
```

**ADD** a requirement to the `Config` Requirements list:

```
    - llm_request_attempts is a positive integer — a value below 1 fails loudly with the received value named
```

**ADD** a property to `Config` (after `"healing_attempts -> int"`):

```yaml
    "llm_request_attempts -> int": |
      The total attempt budget of one LLM request; 1 disables request retries.
```

**ADD** to `load_config` algorithm step 6 (into the env-override enumeration):

```
llm_request_attempts reads PRETTYPLAY_LLM_REQUEST_ATTEMPTS (a decimal integer; an unparseable value raises the loud actionable ConfigurationError naming the setting, the received value and the accepted form)
```

The existing generic requirements ("An env override exists for every setting of `Config`", scalar integer parsing, layered merge) already cover the new setting — no further edits.

#### `.usages/` files

**File:** `prettyplay/config/.usages/configuration.md` — MODIFY (three edits; the rest verbatim).

1. TOML example, add after `healing_attempts = 2`:

```toml
llm_request_attempts = 3  # total sends per LLM request; 1 disables request retries
```

2. Environment overrides table, add after the `healing_attempts` row:

```md
| llm_request_attempts | PRETTYPLAY_LLM_REQUEST_ATTEMPTS |
```

3. New section between "## Settle polling" and "## Pace":

```md
## Request retries of the LLM port

`llm_request_attempts` (default 3, env PRETTYPLAY_LLM_REQUEST_ATTEMPTS, per-test override) caps
the physical sends of one LLM request — generation, failure classification, group diagnosis and
the compliance verdict alike: the initial request included, retries of transient provider
failures (connection, timeout, 408/429, 5xx) happen inside the request with fixed delays and
never consume generation or healing budgets.

```python
from prettyplay import PrettyConfig, PrettyPlay

test = PrettyPlay(
    cache_key="flaky-ci",
    config=PrettyConfig(llm_request_attempts=5),  # tolerate a longer provider outage
)
```

- `1` disables request retries — fully the old single-send behavior
- a value below `1` fails loudly at configuration load — never a silent ignore
- the retry delays are fixed policy (1–10 s with jitter and the Retry-After rule) — not
  configurable; only the attempt count is
```

### Cell: `prettyplay/llm` — MODIFY

#### CODEMANIFEST diff

**Header** — Imports and Usages stay unchanged (keys: `conventions`, `openai`, `anthropic`, `json_repair`).

**Document annotations:**

**DELETE** these three rules:

```
  One completion request per attempt: attempt budgets are owned by the calling engine, never by a provider.
```

```
  The one-request-per-attempt rule covers the diagnosis request too.
```

```
  The one-request-per-attempt rule covers the verdict request too: attempt budgets are owned by the calling engine, never by a provider.
```

**ADD** (in place of the first deleted rule) one unified rule:

```
  One logical LLM attempt per engine attempt: inside it the shared transport retry mechanism of this cell may resend the identical request up to the configured request-attempt budget (llm_request_attempts of `Config`, default 3, initial send included); attempt budgets are owned by the calling engine, never by a provider — transport retries consume none of them.
```

**CHANGE** the remaining document-level operation descriptions so their request counts refer to logical operations, not physical sends: in the group-diagnosis paragraph replace "one request per diagnosis" with "one logical request per diagnosis, with bounded resends of the identical SDK request inside it"; in the compliance paragraph replace "one verdict request per successfully executed candidate" with "one logical verdict request per successfully executed candidate, with bounded resends of the identical SDK request inside it". Keep the existing input and answer-shape rules.

**ADD** a new document annotation paragraph (after the group-diagnosis parity paragraph):

```
  The shared transport retry mechanism lives in _request.py: every SDK call of all four operations of both provider implementations passes through `send_with_retries`. Retryable transport failures — connection failures, timeouts, HTTP 408/429 and any status 500 through 599 — resend the identical request; permanent failures — authentication, authorization, invalid requests, an explicitly exhausted quota — fail immediately, an explicit permanent cause taking precedence over a retryable status (see `openai` and `anthropic` for the per-SDK exception rules). SDK built-in retries are disabled: both clients are constructed with max_retries=0, so the configured budget is also the maximum number of request sends. Delays are fixed policy: base 1, 2, 4, 8, 10, 10… seconds plus a 0–25 percent jitter of the base, capped at 10 seconds; a valid Retry-After of at most 10 seconds raises the pause to the indicated wait, above 10 seconds the request terminates with an actionable `LLMUnavailableError` instead of retrying, malformed values are ignored. KeyboardInterrupt during a wait interrupts it without another retry. Exhaustion and permanent rejections raise `LLMUnavailableError` with the original cause chained. Every retry emits one WARNING record to the logger prettyplay — provider, operation, attempt number, error category, delay; never secrets, never request or response contents.
```

**ADD** a document annotation immediately after that paragraph:

```
  The request-attempt setting is `llm_request_attempts` / PRETTYPLAY_LLM_REQUEST_ATTEMPTS. These names supersede any older `transport_attempts` / PRETTYPLAY_TRANSPORT_ATTEMPTS wording in the imported `openai` and `anthropic` practices; do not implement the old names. The practices must be resynced from their corrected source before implementation.
```

**`LLMProvider` methods — CHANGE** the requirement line of each of the four operations.

Old (generate_step_code):

```
      - A provider service failure (connectivity, timeout, rate limit, authentication) raises `LLMUnavailableError` naming the provider
```

Old (classify_step_failure, classify_group_failure, check_instruction_compliance):

```
      - A provider service failure raises `LLMUnavailableError` naming the provider
```

New (all four operations):

```
      - A provider transport failure is retried inside this operation up to the configured request-attempt budget; exhaustion, a permanent rejection or an over-cap Retry-After raises `LLMUnavailableError` naming the provider with the original cause chained
```

**`classify_group_failure` — CHANGE** one more requirement:

Old:

```
      - One request per diagnosis — attempt budgets belong to the calling engine
```

New:

```
      - One logical diagnosis attempt with bounded transport retries inside it — attempt budgets belong to the calling engine
```

**`LLMProvider::OpenAIProvider(config: Config)` — CHANGE** the algorithm annotation: keep step 1 and step 3 as is; replace steps 2 and 4 and add a construction bullet:

Also change the algorithm heading from "all three operations" to "all four operations".

```
    Algorithm changes:
    - The SDK client is constructed with max_retries=0 — the SDK never resends on its own (see `openai`)
    - Step 2 of every operation: send the single SDK call wrapped in `send_with_retries` with the provider label openai, the operation label, attempts taken from config llm_request_attempts and `classify_openai_failure` as the classifier
    - Step 4: an SDK error classifies through `classify_openai_failure`; permanent categories and exhaustion map to `LLMUnavailableError` through the retry mechanism (see `openai`)
```

The compliance-operation paragraph of the same annotation gets the same mapping wording ("an SDK error classifies through `classify_openai_failure`; … maps through the shared transport retry mechanism").

**`LLMProvider::AnthropicProvider(config: Config)` — CHANGE** mirror-identically: provider label anthropic, `classify_anthropic_failure`, `anthropic` practice; the SDK-forced max_tokens cap asymmetry stays untouched.

Change this provider's algorithm heading from "all three operations" to "all four operations" too.

**ADD** five new types to the body, placed after `create_provider` (before `FailureClassification`):

The implementation must also expose all five through the `prettyplay/llm` package facade (`__init__.py`, `__all__`) so that the CODEMANIFEST declarations and the Python cell API agree. This is an additive cell-facade change; no top-level `prettyplay` re-export is added.

```yaml
"TransportFailureClassification(category: str, retry_after: float | None)":
  location: _request.py
  annotations: |
    The verdict of one transport failure classification: what kind of transport failure it is and
    the retry wait the provider asked for.

    `category`: one of the closed nine-label set — retryable family: connection, timeout,
    rate_limit, server_error; permanent family: authentication, permission_denied,
    invalid_request, not_found, quota_exhausted.
    `retry_after`: the parsed Retry-After seconds carried by the failure; None — the explicit
    absence (no header or a malformed value).

    Requirements:
    - pydantic v2, kw_only, empty defaults (see `conventions`)
    - `category` is always one of the nine labels — an unrecognized failure classifies permanent
      before reaching this type
  properties:
    "category -> str": |
      The transport failure label of the closed nine-label set.
    "retry_after -> float | None": |
      The parsed Retry-After seconds; None — absent or malformed.
    "retryable -> bool": |
      Whether the category belongs to the retryable family — the retry-or-raise decision of the
      retry loop.

"classify_openai_failure(error: Exception) -> failure: TransportFailureClassification":
  location: _request.py
  annotations: |
    Classify one openai SDK exception into the transport verdict — the single classification
    point of the openai implementation (see `openai`).

    `error`: the exception raised by the openai SDK call.
    `failure`: the transport verdict.

    Algorithm:
    1. Match the permanent signals first: an explicitly exhausted quota — even when the status
       looks retryable, e.g. 429 — authentication failure, permission denial, invalid request,
       not found; an explicit permanent cause always wins over a retryable status
    2. Otherwise match the retryable signals: connection failure, timeout, HTTP 408 and 429, any
       HTTP status 500 through 599
    3. Extract Retry-After from the failure response when present and parse it to seconds; a
       missing or malformed value yields None
    4. An exception matching no known signal classifies permanent — a never-recognized failure
       is never blindly retried

    Requirements:
    - Pure classification: no I/O, no logging, no state
    - The label set and the permanent-precedence rule mirror `classify_anthropic_failure`
      exactly — provider parity

    Constraints:
    - Never raise: every input classifies to a verdict

"classify_anthropic_failure(error: Exception) -> failure: TransportFailureClassification":
  location: _request.py
  annotations: |
    Classify one anthropic SDK exception into the transport verdict — the single classification
    point of the anthropic implementation (see `anthropic`); full parity with the openai
    classification: the same nine-label set, the same permanent-precedence rule, the same
    Retry-After handling mirrored onto the anthropic exception hierarchy.

    `error`: the exception raised by the anthropic SDK call.
    `failure`: the transport verdict.

    Algorithm:
    1. Match the permanent signals first: an explicitly exhausted quota — even when the status
       looks retryable — authentication failure, permission denial, invalid request, not found;
       an explicit permanent cause always wins over a retryable status
    2. Otherwise match the retryable signals: connection failure, timeout, HTTP 408 and 429, any
       HTTP status 500 through 599
    3. Extract Retry-After from the failure response when present and parse it to seconds; a
       missing or malformed value yields None
    4. An exception matching no known signal classifies permanent — a never-recognized failure
       is never blindly retried

    Requirements:
    - Pure classification: no I/O, no logging, no state
    - The label set and the permanent-precedence rule mirror `classify_openai_failure` exactly
      — provider parity

    Constraints:
    - Never raise: every input classifies to a verdict

"compute_transport_pause(failed_attempt: int, retry_after: float | None) -> pause: float":
  location: _request.py
  annotations: |
    Compute the backoff pause after one failed transport attempt — the fixed delay policy of
    the port.

    `failed_attempt`: the 1-based number of the attempt that just failed.
    `retry_after`: the parsed Retry-After seconds of the failure; None — absent or malformed.
    `pause`: the pause in seconds before the next send.

    Algorithm:
    1. Base: one second doubled per prior failure, capped at ten — the sequence 1, 2, 4, 8, 10,
       10… seconds
    2. Add a random jitter of 0–25 percent of the base
    3. Cap the result at 10 seconds
    4. A valid retry_after — positive and at most 10 — raises the pause to the indicated wait
       when it exceeds the computed delay

    Requirements:
    - Pure function: no I/O, no sleeps; deterministic on the inputs aside from the random jitter

    Constraints:
    - A retry_after above 10 seconds never reaches this routine as a wait: the retry loop
      terminates before computing a pause

"send_with_retries(provider: str, operation: str, attempts: int, classify: Callable[[Exception], TransportFailureClassification], send: Callable[[], T]) -> response: T":
  location: _request.py
  annotations: |
    Send one LLM request with the bounded transport retry loop — the shared retry mechanism of
    the port wrapping every SDK call of all four operations of both provider implementations.

    `provider`: the provider label for logs and errors — openai, anthropic.
    `operation`: the operation label for logs — generation, classification, group diagnosis,
    compliance verdict.
    `attempts`: the total send budget, initial send included — llm_request_attempts of `Config`;
    1 disables retries.
    `classify`: the provider-specific classifier of the caught exception.
    `send`: the closure performing exactly one SDK request.
    `response`: the successful response of `send`.

    Algorithm:
    1. Run send; a success returns its response as is
    2. On an exception: classify through `classify` into a `TransportFailureClassification`
    3. A permanent category raises `LLMUnavailableError` naming `provider` with the original
       cause chained — immediately, no retry
    4. A retry_after above 10 seconds raises `LLMUnavailableError` with an actionable message
       naming the provider and the indicated wait — before any pause is computed
    5. The attempt was the last of `attempts`: raise `LLMUnavailableError` naming `provider`
       with the original cause chained
    6. Otherwise compute the pause through `compute_transport_pause`, emit one WARNING record to
       the logger prettyplay — provider, operation, attempt number, error category, delay; never
       secrets, never request or response contents — then wait the pause and run the next attempt

    Requirements:
    - At most `attempts` sends of the identical request — the loop is the only retry authority
      of the port
    - KeyboardInterrupt during a wait propagates without another retry
    - One WARNING record per retry — no other log records, no hook events

    Constraints:
    - Never retry a permanent category; never consult engine attempt budgets — those belong to
      the calling engine
    - The invalid content of a successful response never enters this loop: response validation
      and recovery stay with the operations
```

**Footer** — unchanged (Author: Goga; the manifest description may optionally append "and the shared bounded transport retry mechanism" — non-normative).

#### `.usages/` files

**File:** `prettyplay/llm/.usages/providers.md` — MODIFY (three edits; the rest verbatim).

1. "## Parity" section, replace the sentence:

Old:

```md
… with identical inputs, identical output shapes and the identical failure taxonomy: a provider service failure raises LLMUnavailableError; cached step code never depends on the provider. One request per attempt; attempt budgets belong to the calling engine.
```

New:

```md
… with identical inputs, identical output shapes and the identical failure taxonomy: a provider transport failure resends the identical request inside one logical attempt (bounded transport retries) and raises LLMUnavailableError only on exhaustion, a permanent rejection or an over-cap Retry-After; cached step code never depends on the provider. One logical attempt per engine attempt; attempt budgets belong to the calling engine and are never consumed by transport retries.
```

2. New section after "## Parity", before "## The compliance operation":

```md
## Transport retries

Transient provider outages no longer kill a logical attempt: every SDK call of all four
operations passes through the shared bounded retry mechanism inside the port.

- Retryable: connection failures, timeouts, HTTP 408/429 and any 5xx — the identical request is
  resent after a computed pause (base 1, 2, 4, 8, 10, 10… s + 0–25% jitter, cap 10 s; a valid
  Retry-After ≤ 10 s lifts the pause to the asked wait)
- Permanent — authentication, authorization, invalid request, an explicitly exhausted quota —
  fails immediately; an explicit permanent cause wins over a retryable status
- Retry-After above 10 s terminates with an actionable LLMUnavailableError — never an early
  resend, never a cap-breaking wait
- The send budget per logical attempt: llm_request_attempts (default 3, initial send included,
  1 disables retries); SDK built-in retries are off (max_retries=0) — the budget is also the
  maximum number of physical sends
- Each retry logs one WARNING (provider, operation, attempt, category, delay) to the logger
  prettyplay — no secrets, no payloads; KeyboardInterrupt during a wait stops the retrying
- Generation, healing and group budgets are untouched: one logical LLM attempt per budget
  attempt, with or without transport retries
```

3. In "## The group diagnosis operation", change both "one request per diagnosis" statements to "one logical request per diagnosis, with bounded resends of the identical SDK request inside it"; preserve the existing model, parsing and budget guidance.

**File:** `prettyplay/llm/.usages/classification.md` — no changes.

### Cell: `prettyplay/engine` — MODIFY

#### CODEMANIFEST diff

**CHANGE** one requirement of `StepGenerator.generate`.

Old:

```
      - Provider unavailability of a generation request surfaces as `LLMUnavailableError` immediately — no retry on it
```

New:

```
      - Provider unavailability of a generation request surfaces as `LLMUnavailableError` after the
        bounded transport retries inside the logical LLM attempt; the engine itself adds no retries
        above them
```

Everything else (header, other types, `StepHealer`, `classify_step_failure`, `check_step_compliance`, footer) stays unchanged — their provider-unavailability statements remain accurate.

#### `.usages/` files

No changes (`generation.md`, `healing.md` statements remain accurate; transport-retry documentation lives in the llm and config cells).

### Cell: `prettyplay/engine/groups` — MODIFY

#### CODEMANIFEST diff

**CHANGE** one constraint of `classify_group_failure`.

Old:

```
    - Provider unavailability propagates as `LLMUnavailableError` — an explicit infrastructure failure; no retry
```

New:

```
    - Provider unavailability propagates as `LLMUnavailableError` — an explicit infrastructure
      failure raised after the bounded transport retries inside the logical diagnosis attempt; the
      caller adds no retries above them
```

#### `.usages/` files

No changes (`recovery.md` carries no retry statements).

## Dependency Map

```
prettyplay/failures ──(PrettyplayError + taxonomy)──────────────> prettyplay/config
prettyplay/config ──(Config: now carries llm_request_attempts)──> prettyplay/llm
prettyplay/failures ──(LLMUnavailableError, ComplianceVerdictError)──> prettyplay/llm
prettyplay/llm ──(LLMProvider, ScenarioStep, FailureClassification, ComplianceFinding + classification usage)──> prettyplay/engine
prettyplay/llm ──(LLMProvider, ScenarioStep, GroupFailureClassification)──> prettyplay/engine/groups
prettyplay/engine ──(StepGenerator, StepAttempt)────────────────> prettyplay/engine/groups
```

No new Imports; no cycles (dependency order: failures → config → llm → engine → groups).

## Verification Checklist

After implementing each artifact, verify:

**prettyplay/failures**
- `goga lint` passes on the cell; the annotation names all four operations and the chained-cause requirement
- Downstream handling unchanged: no new failure kinds, catchable with the single library except clause

**prettyplay/config**
- `Config(llm_request_attempts=0)` (and any value below 1) raises the loud actionable `ConfigurationError` naming the setting and the received value; file and programmatic values validate identically
- `PRETTYPLAY_LLM_REQUEST_ATTEMPTS` env: decimal integer parses; unparseable value fails loudly; explicit per-test value overrides file+env (the `generation_attempts` pattern)
- `configuration.md` renders the new setting in the TOML example, the env table and the new section

**prettyplay/llm**
- All five new types exist at `_request.py` with the declared signatures; `goga lint` and `goga contract` pass
- All five new types are importable from `prettyplay.llm` and listed in that cell's `__all__`; the top-level facade is unchanged
- Classification: per SDK exception type — retryable {connection, timeout, 408/429, 500–599}, permanent {authentication, permission, invalid request, not found, explicit quota}, permanent precedence over retryable status, malformed `Retry-After` → None, unrecognized exception → permanent; openai/anthropic parity rule-by-rule
- `compute_transport_pause`: base sequence 1, 2, 4, 8, 10, 10…; jitter within 0–25% of base; cap 10 s; `Retry-After` ≤ 10 lifts to max; `Retry-After` > 10 never reaches the function as a wait
- `send_with_retries`: attempt boundaries (1 attempt — single send, no pause, no log; attempts = max sends), permanent and over-cap `Retry-After` terminate immediately, exhaustion raises `LLMUnavailableError` with the original cause chained (`raise … from`) naming the provider, one WARNING per retry with provider/operation/attempt/category/delay and no payload content, `KeyboardInterrupt` during the wait propagates without another retry; waits are injectable-sleep testable (mock at the external boundary; no real seconds in tests)
- Both provider clients constructed with `max_retries=0`; each of the four operations of both providers wraps its single SDK call through `send_with_retries`
- `providers.md` carries the corrected parity sentence and the "Transport retries" section
- No `prettyplay/llm` contract or provider usage describes one physical SDK send per logical operation; both provider algorithm headings name all four operations

**prettyplay/engine / prettyplay/engine/groups**
- No remaining "no retry" statement about provider unavailability anywhere in the two CODEMANIFESTs (grep: "no retry")
- No signature, Import or behavioral changes beyond the two annotation lines

**Whole project**
- Before implementation, correct the synced source for `openai` and `anthropic` practices and resync both files; verify neither still names `transport_attempts` or `PRETTYPLAY_TRANSPORT_ATTEMPTS`. This is a prerequisite outside the CODEMANIFEST and cell-usage artifacts of this plan
- `goga lint` passes; `goga schema` shows `prettyplay/llm` with the five new types at `_request.py`
- `pytest tests/ -x` passes (including the new unit tests for classification, pause, boundaries, exhaustion, cancellation, construction, log fields, budget neutrality) and `ruff check prettyplay/` passes
- Acceptance criteria 1–11 of the task file verified (criterion 11 = the two commands above)
