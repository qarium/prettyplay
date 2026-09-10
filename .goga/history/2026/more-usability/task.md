# Prettyplay Usability: Clean Failure, LLM Verdicts, Screenshots, Headless and Channels, Scroll Actions

## Current State

The current state of the library (facts collected at technical discovery from the implementation code):

1. **Ugly failure.** `ProductDefectError` does not inherit `AssertionError` — unittest/pytest show a legitimately failed check as ERROR with a traceback through the library internals instead of FAILED with a short reason; the traceback does not collapse to the library boundary.
2. **LLM value is lost on failures.** The explanation and recommendation of the classification verdict reach neither the exception message, nor the hooks, nor the log: on the healing path `recommendation` is cut off at `ProductDefectError`; when healing is exhausted after rot the verdict is lost entirely; on the generation-failure path classification is not called at all.
3. **Defect masking.** The first run of a legitimately failing assertion step burns the generation budget (3 LLM requests by default) and fails as `IncurableStepError` — the real product defect is invisible.
4. **The test author has no screenshots.** `PrettyTest` cannot get or save a PNG for a report; the internal `PageFacade.screenshot()` exists only as an LLM input.
5. **Settings "simply do not work".** `headless` is not configurable at all (`launch()` is called without it), `browser = "chrome"` fails as an invalid value, the browser env variable is named `PRETTYPLAY_BROWSER`, invalid configuration yields a raw `pydantic.ValidationError` instead of the actionable error the documentation promises.
6. **No scroll actions.** The page facade has no scrolling at all; Playwright auto-scroll fires only as part of actions.

## Description

Implement the seven approved ADR decisions of the `more-usability` topic
(`.goga/history/2026/more-usability/adr.md`) in the existing prettyplay cells — a single usability release:

- **ADR-1.** `ProductDefectError` inherits both `PrettyplayError` and `AssertionError` (multiple inheritance); the message starts with the reason; the traceback collapses to the library boundary. Runners show a failed check as a failure, the facade stays framework-agnostic.
- **ADR-2.** A single verdict "category (where applicable) + explanation + recommendation" on every terminal step failure (`ProductDefectError`, `IncurableStepError`): entirely into the exception message, into a new hooks event (for integrator reports) and into the log. The explanation is built from the fresh page state; when the LLM is unavailable — a silent skip with a WARNING, the primary failure is not distorted and not delayed. On paths with existing classification the verdict is reused, on paths without it — requested. Fixes the loss of `recommendation` at `ProductDefectError` and the loss of the verdict when healing is exhausted after rot.
- **ADR-3.** A failed candidate check during generation (Playwright `expect_*` raises `AssertionError`, typically distinguishable from "element not found") stops the retries and moves the step to LLM classification: a `product_defect` verdict raises `ProductDefectError` with an explanation, other verdicts — `IncurableStepError` with an explanation and recommendation. Non-`AssertionError` candidate errors are retried as today.
- **ADR-4.** The main object gains two abilities: `get_screenshot` — full-page PNG bytes of the current state — and `save_screenshot(filepath)` — writing a PNG to an explicitly user-specified path, with no directory binding. No auto-screenshots on terminal step failure.
- **ADR-5.** The `headless` setting (TOML key `[tool.prettyplay]`, default `true`, env `PRETTYPLAY_BROWSER_HEADLESS`); the allowed `browser` values expand to `{chromium, firefox, webkit, chrome, msedge}` — the last two launch the installed browser through the Playwright channel mechanism. The browser env variable is renamed cleanly: `PRETTYPLAY_BROWSER` → `PRETTYPLAY_BROWSER_NAME`, the old name stops working, on encounter — a hint of the new one.
- **ADR-6.** Settings validation errors are wrapped in a loud actionable library error: setting name, received value, list of allowed values; the original `ValidationError` stays chained.
- **ADR-7.** The page facade is extended with scrolls: page-level — scroll to an element, by an amount down/up, to the end/start of the page; container-level (carousels) — bring an element into view inside a scrollable container and scroll the container by an amount. The page API listing string hardcoded in the engine (the mirror of `.usages/facade.md`) is updated synchronously — otherwise the model will not see the new abilities.

## Scope

**In scope:**

- `ProductDefectError` — multiple inheritance with `AssertionError`; clean failure surface (ADR-1)
- A verdict on every terminal failure: exception message + a new `StepHooks` event + log; silent skip on LLM unavailability (ADR-2)
- Stopping generation retries on a candidate `AssertionError` with classification (ADR-3)
- Updating the classification prompt text in `engine` (`classification_prompt`): from "cached step failure" to "step failure" — for classification calls from the generation path (ADR-3); the `llm` cell contract is untouched
- `PrettyTest.get_screenshot()` and `PrettyTest.save_screenshot(filepath)` (ADR-4)
- The `headless` setting; `chrome`/`msedge` channels; the `PRETTYPLAY_BROWSER_NAME` env rename with a hint (ADR-5)
- An actionable configuration error instead of a raw `pydantic.ValidationError` (ADR-6)
- Page facade scrolls (page-level and container-level) + synchronous update of the page API listing string in the engine (ADR-7)
- Updating the cell-level usage `driver/.usages/facade.md` for the new surface
- Tests per the project conventions (`pytest`, `ruff`)

**Out of scope:**

- "Scroll until it appears" (infinite feeds) — deferred outside the topic
- Auto-screenshots on terminal step failure — explicitly rejected
- A scroll API at the main object level (`PrettyTest`) — does not appear; scrolling is a surface of generated step code
- A verdict for `LlmUnavailableError` — an infrastructure failure, not given an explanation
- Renaming the `browser` TOML key — only the env variable is renamed
- Runner plugins and integrations — architecturally excluded
- Changes to the `llm` contract — the `FailureClassification` verdict is reused as is

## Acceptance Criteria

- `isinstance` check: `ProductDefectError` is simultaneously `PrettyplayError` and `AssertionError`; unittest and pytest show a failed check as a failure (not an error); the traceback collapses to the library boundary
- Every terminal failure `ProductDefectError`/`IncurableStepError` carries a verdict (category where applicable, explanation, recommendation) in the exception message, in the hooks event and in the log; when the LLM is unavailable the primary failure is not distorted and not delayed, with a WARNING in the log
- On the healing path `recommendation` reaches `ProductDefectError`; when healing is exhausted after rot the verdict is not lost
- A legitimately failing assertion step on first generation: exactly one failed check stops the retries (does not burn the budget of 3 attempts), classification is called, `product_defect` → `ProductDefectError` with an explanation; non-`AssertionError` candidate errors are retried as before
- `get_screenshot()` returns full-page PNG bytes; `save_screenshot(filepath)` creates a file at the given path; there are no auto-screenshots on failure
- `[tool.prettyplay] headless = false` launches the browser with a head (env `PRETTYPLAY_BROWSER_HEADLESS`); `browser = "chrome"`/`"msedge"` launches the installed browser through the channel; `PRETTYPLAY_BROWSER_NAME` works, `PRETTYPLAY_BROWSER` does not and yields a hint; an invalid setting value — an actionable error with the setting name, the value and the list of allowed ones
- Generated step code can scroll: to an element, by an amount down/up, to the end/start of the page, inside a container (bring an element into view and scroll by an amount); the page API listing string in the engine mirrors the updated `facade.md`
- Facade backward compatibility: extension only, no renames or removals; cached steps keep working
- `ruff check` and `pytest tests/ -x` green; Python 3.10+

## Stack

- **Frameworks:** — (a pure Python library, does not touch runners)
- **Libraries:** pydantic v2 (config schema and validation wrapping), Playwright sync API 1.62 (headless, channel, scroll primitives `scroll_into_view_if_needed` / `mouse.wheel` / `evaluate`+`window.scrollTo`), openai SDK and anthropic SDK — unchanged
- **Infrastructure:** none; no new external dependencies

## External Dependencies

| Component | Usage file | Status |
|-----------|------------|--------|
| playwright | `.goga/usages/cooks/playwright.md` | updated (chrome/msedge channels, headless, scroll primitives) |
| pydantic | `.goga/usages/cooks/pydantic.md` | updated (browser+headless in the schema, actionable error, env rename) |
| openai | `.goga/usages/cooks/openai.md` | existing |
| anthropic | `.goga/usages/cooks/anthropic.md` | existing |

## Risks and Constraints

- **Facade backward compatibility** — a hard contract: `PageFacade`/`LocatorFacade` extension only; cached step code works across releases
- **Synchrony of the two surface copies**: the page API listing string is hardcoded in the engine and mirrors `driver/.usages/facade.md` — they are edited only together
- **Multiple inheritance** of `ProductDefectError`: pytest and unittest render exceptions differently — verify behavior on both runners
- **The typical distinction** of a check's `AssertionError` from "element not found" in ADR-3 relies on the real Playwright error hierarchy (`expect_*` vs locator timeouts) — cover with tests against the real types; the boundary is fragile
- **The chrome/msedge channels** require a locally installed browser — channel tests via `pytest.mark.skipif` when the browser is absent; when missing — an actionable message
- **The env rename** is safe: there are no external consumers (a discovery fact); a hint on encountering the old name
- Python 3.10+; project conventions (`conventions`) are mandatory

## Scope Estimate

One task (user's decision). Scale: 7 ADRs, 6 cells, ~10 types — mostly point extensions. Splitting rejected: the change clusters (failures+verdicts; settings+browser+scrolls; screenshots) intersect across the `engine` and `driver` cells and carry no standalone value — the whole release ships together on the `more-usability` branch. The next stage (brainstorm) will distribute the contract edits across cells.

## Existing Architecture

The affected cells and the nature of changes:

- `prettyplay/failures` — `ProductDefectError`: multiple inheritance with `AssertionError`, message rendering with the verdict (ADR-1, ADR-2)
- `prettyplay/llm` — the contract does not change: `FailureClassification` is reused; classification starts being called from the generation path too (ADR-3)
- `prettyplay/engine` — `StepGenerator`: interception of the candidate `AssertionError`, retry stop, classification (ADR-3); the verdict on terminal failures (ADR-2); the page API listing string (ADR-7)
- `prettyplay/reporting` — `StepHooks`/`StepReporter`: a new event with the verdict for integrator reports (ADR-2)
- `prettyplay/driver` — `DriverSession`: `launch(headless=..., channel=...)` (ADR-5); `PageFacade`: scrolls (ADR-7); `PageFacade.screenshot()` as the basis of author screenshots (ADR-4); updating `.usages/facade.md`
- `prettyplay/config` — `Config`: the `headless` field, the expanded `browser`; `load_config`: env `PRETTYPLAY_BROWSER_NAME`, ValidationError wrapping (ADR-5, ADR-6)
- `prettyplay` (root facade) — `PrettyTest`: `get_screenshot`/`save_screenshot` (ADR-4)
- `prettyplay/cache` — untouched

## Notes

- User's decisions at formulation: target API code examples are not included in the task (q1-B); one task without decomposition (q3-A); the usage files `playwright.md` and `pydantic.md` were updated at this stage (q2-A)
- Open details for the next stage (brainstorm), not fixed in the ADRs: the name of the new hooks event with the verdict; the signatures of the facade scroll methods; the behavior of `get_screenshot`/`save_screenshot` before the test's page is opened (the page opens lazily on the first step); the verdict render format in the exception message; the traceback collapsing mechanics
- Task input: ADR `.goga/history/2026/more-usability/adr.md` (approved 08.09.2026, seven decisions + terms)
