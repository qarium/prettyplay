# Browser screen modes, strict replay, structured failure messages, classification instructions

Source: ADR `.goga/history/2026/strict-and-fullscreen-mode/adr.md` (discovery interview, 2026-09-10).

## Current State

- Browser size is not controllable: `[tool.prettyplay]` carries flat keys `browser` (engine), `headless`, `browser_endpoint`; `DriverSession.open_context` creates `browser.new_context()` with Playwright defaults — no viewport pinning, no fullscreen, no mobile emulation.
- No strict replay mode exists: the step cycle (`StepExecutor.execute`) is cache hit → execute; cached-step failure → `StepHealer.heal` (classification → rot: regeneration); cache miss → `StepGenerator.generate`. The LLM is always consulted — there is no honest replay-only mode for CI.
- Terminal failure messages render as primary reason + verdict tail with `category:`/`explanation:`/`recommendation:` labels; the full underlying error from the generated step code does not reach the exception; the primary signal, the step and the verdict blend into a wall of label soup.
- Only `generation_prompt` exists; classification requests carry no user instructions — the language of verdict explanations cannot be steered.

## Description

Implement the four capabilities of prettyplay per the ADR — browser screen modes (items 1–2), strict replay (3), the structured failure message (4), classification instructions (5):

1. **Nested browser group.** `[tool.prettyplay.browser]` holds `name` (formerly `browser`), `screen`, `headless`, `endpoint` (formerly `browser_endpoint`). Programmatic override is a `BrowserConfig` model inside `PrettyConfig`; fields inside the group carry no `browser_` prefix — the group name already scopes them. Env overrides stay flat: `PRETTYPLAY_BROWSER_{NAME|SCREEN|HEADLESS|ENDPOINT}`. Old flat keys are a hard pre-1.0 break: a loud `ConfigurationError` pointing at the new location.
2. **`screen` — the single size setting.** Values: empty (Playwright default), `WxH` (fixed viewport), `fullscreen`, or a Playwright device name — mobile emulation via the full device descriptor (viewport, user agent, touch, `is_mobile`, device scale factor). An unknown device name is a loud error suggesting close names. `fullscreen` means a maximized window with the viewport following the window on a local headed launch; headless and remote connects fall back to a fixed 1920×1080 viewport, since no window exists there. `WxH` and device descriptors apply in every launch mode.
3. **Strict mode is replay-only.** `strict = false` by default, env `PRETTYPLAY_STRICT`, per-test override via `PrettyConfig`. In strict mode cached code executes honestly and nothing is ever (re)generated: a cache miss raises `IncurableStepError` stating that strict forbids generation; a failed cached step is classified only when LLM access is configured — `product_defect` → `ProductDefectError`, `rot`/`incurable` → `IncurableStepError` — with no regeneration in any case; without an LLM the failure raises immediately without a verdict, by step type — an assertion step raises `ProductDefectError`, an action step raises `IncurableStepError`, each carrying the full underlying error in the `error:` block and logging a WARNING (the existing quiet-skip pattern). Generation and healing budgets are never consumed; the only LLM calls are classifications.
4. **Structured terminal failure message.** The message starts with the primary reason — the exception type prefix supplied by Python renders the `kind:` part, so the message itself contains no kind label and no internal colons in the first line. Then a `---`-separated block with `step:` (the step sentence) and `error:` (the full underlying error from the failed step code, including locator details). For failed checks the `error:` text carries no `AssertionError` prefix — the exception type already carries the assertion semantics; for action steps the underlying error type remains part of the full error text. Then a verdict block with `explanation:` and `recommendation:`, values column-aligned, multi-line continuations indented to the same column. The category line is dropped. Empty blocks are omitted entirely (no verdict → no verdict block; no underlying code error → no `error:` line). The failed step's code is never included — it lives in the cache and the log. One render feeds the exception message, the log record and the hook payload — the `error` field of the `on_step_failed` event and its log record carry the full render instead of the short first line, while `on_step_verdict` keeps its structured fields built from the verdict object, never from the render; traceback folding stays as is.
5. **`classification_prompt` mirrors `generation_prompt`.** A non-empty value renders as a USER INSTRUCTIONS block in classification requests only — generation requests never see it, and classification never sees `generation_prompt`. Env override `PRETTYPLAY_CLASSIFICATION_PROMPT`; step addressing is unaffected.

## Scope

**In scope:**

- Nested `[tool.prettyplay.browser]` group (`name`, `screen`, `headless`, `endpoint`) with the `BrowserConfig` model inside `PrettyConfig`; env overrides `PRETTYPLAY_BROWSER_{NAME|SCREEN|HEADLESS|ENDPOINT}`; loud actionable `ConfigurationError` on the old flat keys (`browser`, `headless`, `browser_endpoint` at the `[tool.prettyplay]` level)
- `screen` semantics in the driver: empty default; `WxH` fixed viewport; `fullscreen` = maximized window + viewport following the window on local headed launches, fixed 1920×1080 fallback for headless and remote connects; Playwright device-name emulation with the full descriptor; loud error with close-name suggestions on an unknown device; `WxH` and device descriptors in every launch mode
- Strict mode: `strict` setting (`false` default, env `PRETTYPLAY_STRICT`, per-test override); replay-only execution — cache miss → `IncurableStepError`; failed cached step classified only when the LLM is available (`product_defect` → `ProductDefectError`, `rot`/`incurable` → `IncurableStepError`), never regenerated; without LLM access the failure raises immediately without a verdict, by step type (`ProductDefectError` for assertion, `IncurableStepError` for action; WARNING); generation/healing budgets never consumed; classifications are the only LLM calls
- One structured message template for terminal failures: reason-only first line (kind comes from the exception type prefix), `---`-separated `step:`/`error:` block (no `AssertionError` prefix for failed checks; full underlying error text including locator details), `---`-separated verdict block with column-aligned `explanation:`/`recommendation:`; category line dropped; empty blocks omitted; step code never included; a single render feeding the exception message, the log record and the `error` field of the `on_step_failed` hook payload; traceback folding unchanged
- `classification_prompt` setting: USER INSTRUCTIONS block in classification requests only (both providers, full parity); env `PRETTYPLAY_CLASSIFICATION_PROMPT`; no effect on step addressing
- `BrowserConfig` re-exported on the package's main facade — `from prettyplay import BrowserConfig` — uniform with `PrettyConfig`
- Tests per `.goga/usages/conventions.md` (unit + edge cases per affected cell)

**Out of scope:**

- CODEMANIFEST contract design for the new settings and behavior — downstream stages (brainstorm/design)
- Migration or backward compatibility for the old flat config keys — hard break by ADR
- README and mkdocs documentation updates
- Playwright async API
- CI infrastructure changes

## Acceptance Criteria

- `[tool.prettyplay.browser]` validates as the nested group; each of the old flat keys produces a loud actionable `ConfigurationError` naming the new location
- `screen="1280x720"` pins the context viewport to 1280×720 in every launch mode; a valid device name applies the full descriptor; an unknown device name fails loudly with close-name suggestions; `screen="fullscreen"` on a local headed launch starts a maximized window with the viewport following it; `fullscreen` under headless or a remote connect pins the viewport to 1920×1080
- A strict run with a cache miss raises `IncurableStepError` stating that strict forbids generation — no generation request, no budget consumption; a failed cached step with LLM access raises by classification (`product_defect` → `ProductDefectError`, `rot`/`incurable` → `IncurableStepError`) with no regeneration attempt; without LLM access the failure raises immediately without a verdict, by step type — `ProductDefectError` for an assertion step, `IncurableStepError` for an action step, each carrying the full underlying error in the `error:` block — and logs a WARNING; no generation or healing LLM requests happen in strict mode
- Terminal failure messages match the approved template: reason-only first line with no internal colons, `---`-separated `step:`/`error:` block (failed checks carry no `AssertionError` prefix in `error:`), `---`-separated column-aligned verdict block; empty blocks omitted entirely; the exception message, the log record and the `on_step_failed` hook payload (`error` field) come from one render, `on_step_verdict` keeps structured fields
- A non-empty `classification_prompt` renders as a USER INSTRUCTIONS block in classification requests of both providers and never in generation requests; `generation_prompt` behavior is unchanged; cached steps never regenerate because instructions changed
- `from prettyplay import BrowserConfig, PrettyConfig, PrettyTest` works
- `pytest tests/ -x` passes; `ruff check prettyplay/` is clean

## Stack

- **Frameworks:** pytest (tests), ruff (lint)
- **Libraries:** pydantic v2 (`BrowserConfig`, nested config group), Playwright sync API (viewport, device descriptors, fullscreen), openai SDK + anthropic SDK (classification user-instructions parity)
- **Infrastructure:** none new — browser binaries via `playwright install` on user infrastructure

## External Dependencies

| Component | Usage file | Status |
|-----------|--------------------------------|---------|
| playwright | `.goga/usages/cooks/playwright.md` | updated (screen modes section) |
| pydantic | `.goga/usages/cooks/pydantic.md` | updated (nested browser group schema) |
| openai | `.goga/usages/cooks/openai.md` | existing |
| anthropic | `.goga/usages/cooks/anthropic.md` | existing |

## Risks and Constraints

- The `[tool.prettyplay]` schema change is breaking (pre-1.0 hard break): projects must migrate `browser`, `headless`, `browser_endpoint` to the `browser` group before upgrading
- The structured message template changes the rendered text of terminal failures — the dropped `category:` line and the new layout are a parsing break for integrators who parsed the old verdict labels (pre-1.0 break, uniform with the config schema change)
- `fullscreen` cannot be pixel-identical across environments — headed local runs follow the actual screen; headless and remote runs are pinned to 1920×1080
- Strict mode makes cache-miss failures an expected CI signal: generating a step is a deliberate non-strict act
- Python 3.10 compatibility (tomli fallback, `kw_only` syntax, no 3.11+ only constructs)
- The `PageFacade`/`LocatorFacade` surface is a backward-compatibility contract — the screen changes touch context creation, never the facade methods
- Device names resolve against the `devices` registry of the running Playwright — the package never hard-codes a device list

## Scope Estimate

Single task (approved during formulation). Scale: 4 capabilities, 7 affected cells, ~10 contract types. Contract-level decomposition per cell happens in the downstream brainstorm/design stages.

## Existing Architecture

Affected cells and integration points:

- `prettyplay/config` — new `BrowserConfig` type; `Config` gains the nested `browser` group, `strict`, `classification_prompt`; `load_config` gains the nested env overrides and the old-flat-key rejection
- `prettyplay/driver` — `DriverSession` context creation applies `screen`: viewport dict, device descriptor, or fullscreen handling per launch mode
- `prettyplay/engine` — the step cycle gains the strict branch (no generation, classification-only failure handling, budgets untouched); the classification call passes the classification user instructions
- `prettyplay/failures` — the terminal failure render moves to the structured template; one render feeds exception, log and hook payload
- `prettyplay/llm` — `classify_failure` accepts the classification user instructions; both provider implementations render the USER INSTRUCTIONS block with identical semantics
- `prettyplay` (root facade) — re-exports `BrowserConfig` alongside `PrettyConfig`; `StepExecutor` carries the strict execution path
- `prettyplay/reporting` — touched only through the single render feeding the `error` field of the `on_step_failed` hook payload and its log record; `on_step_verdict` stays structured

## Notes

- All decisions originate from the discovery interview recorded in the ADR (2026-09-10); nothing in this task contradicts the ADR.
- Target API examples approved during task formulation:

```toml
# pyproject.toml
[tool.prettyplay]
strict = false              # replay-only mode; env PRETTYPLAY_STRICT
classification_prompt = ""  # USER INSTRUCTIONS for classification; env PRETTYPLAY_CLASSIFICATION_PROMPT

[tool.prettyplay.browser]
name = "chromium"           # formerly browser; env PRETTYPLAY_BROWSER_NAME
screen = "1280x720"         # "" | WxH | fullscreen | Playwright device name; env PRETTYPLAY_BROWSER_SCREEN
headless = true             # env PRETTYPLAY_BROWSER_HEADLESS
endpoint = ""               # formerly browser_endpoint; env PRETTYPLAY_BROWSER_ENDPOINT
```

```python
from prettyplay import BrowserConfig, PrettyConfig, PrettyTest

# programmatic override: a strict run with a fullscreen browser
test = PrettyTest(
    cache_key="login",
    config=PrettyConfig(
        strict=True,
        browser=BrowserConfig(screen="fullscreen", headless=False),
    ),
)
```

```text
# assertion step (failed check): the error block carries no AssertionError prefix
ProductDefectError: кнопка «Войти» осталась невидимой после отправки формы
---
step: Проверить появление кнопки «Войти»
error: Locator expected to be visible
---
explanation:    на странице нет элемента с ролью button и именем «Войти»
recommendation: проверить селектор или текст кнопки в приложении

# action step: the full underlying error text, its type included, is acceptable
IncurableStepError: не удалось выполнить шаг в строгом режиме
---
step: Нажать «Войти»
error: TimeoutError: locator.click: Timeout 30000ms exceeded
---
explanation:    ...
recommendation: ...
```

- Message template clarifications confirmed during formulation: the `kind:` of the first line is supplied by the exception type prefix rendered by the runner — the message itself starts with the primary reason and contains no colons of its own in the first line; for failed checks `AssertionError` is never written into the `error:` text (the exception type already carries the assertion semantics), while for action steps the underlying error type stays part of the full error text.
- Explicit requirement from the product owner: `BrowserConfig` must land on the main package facade (re-exported by the root cell, uniform with `PrettyConfig`).
