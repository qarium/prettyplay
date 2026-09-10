# Prettyplay Usability Decisions (branch `more-usability`)

> Recorded from the technical discovery interview of 08.09.2026. Status: **approved**.
> The topic was initiated by five usability problems formulated by the user (no PRD/TODO was created for the topic). Facts about current behavior were collected from the implementation code by subagents. Each entry records the fact of the decision and its "why".

## Terms

- **"Clean failure"** — the runner shows a failed check as FAILED with a short human-readable reason (the step; expectation vs observation), not as ERROR with a traceback through the library internals.
- **"Failure explanation"** — an LLM verdict: what happened on the page at the moment the step failed and what the engineer should do. It answers the question "is it clear to a human"; the healing classification (rot / product_defect / incurable) answers the question "should it be healed". Different questions, one vocabulary (ADR-2).
- **Terminal step failure** — `ProductDefectError` or `IncurableStepError` reaching the test. `LlmUnavailableError` is infrastructure and is not given an explanation.
- **"Scroll action"** — programmatic scrolling as part of the scenario (to an element, by an amount, to the end of the page, inside a container); not to be confused with Playwright's auto-scrolling when performing actions.
- **Browser channel** — a `chrome`/`msedge` value of the browser setting: launching the actually installed browser through the Playwright channel mechanism (the engine stays chromium).

---

## ADR-1. ProductDefectError is an assertion; clean failure surface

`ProductDefectError` additionally inherits `AssertionError` (multiple inheritance with the `PrettyplayError` base), the message starts with the reason, the traceback collapses to the library boundary. Runners and integrations expect `AssertionError` from checks (unittest distinguishes failure/error; pytest renders a foreign exception differently), while the library facade is framework-agnostic — a plugin for a specific runner is impossible, so the alignment is done by type, not by integration.

**Alternatives considered:** all three errors inherit `AssertionError` — rejected: an incurable step and LLM unavailability are execution errors, not check failures; a runner plugin — rejected: violates the architectural decision "no plugins or integrations"; keep the types as is — rejected: the "ugly" part of the user's problem remains.

**Consequences:** the three-kind taxonomy is preserved; `except AssertionError` and `except PrettyplayError` work simultaneously for integrators.

## ADR-2. A single verdict on every terminal failure

Every terminal step failure (`ProductDefectError`, `IncurableStepError`) ends with a verdict "category (where applicable) + explanation + recommendation" that lands entirely in the exception message, in a new hooks event (for integrator reports) and in the log. The explanation is built from the fresh page state (snapshot; screenshot — when `send_screenshots` is on); when the LLM is unavailable the explanation is silently skipped with a log warning — the primary failure is not distorted and not delayed. One mechanism instead of two: on paths where classification already exists (healing), the verdict is reused; on paths without it — requested.

**Alternatives considered:** a separate "explanatory" request in parallel with classification — rejected: two vocabularies and extra calls; the explanation only in log/hooks without the exception — rejected: the explanation is needed at the point of failure the engineer sees.

**Consequences:** two losses of the current implementation are fixed — `recommendation` does not reach `ProductDefectError` on the healing path; the classification verdict is lost entirely when healing is exhausted after rot.

## ADR-3. A failed check in new generation — stop retries and classify

When candidate code is executed during generation but the check does not converge (Playwright `expect_*` raises `AssertionError` — typically distinguishable from "element not found"), retries stop and the step goes to LLM classification: a `product_defect` verdict raises `ProductDefectError` with an explanation. Today the first run of a legitimately failing check burns the generation budget (3 attempts by default, each an LLM request) and fails as `IncurableStepError` — the "run value" (a real defect) is masked as an incurable step, and classification on this path is not called at all.

**Alternatives considered:** raise `ProductDefectError` immediately without the LLM — rejected: the explanation is lost, diverges from ADR-2; keep the retry status quo — rejected: defect masking.

**Consequences:** non-`AssertionError` candidate errors are retried as today; the extra LLM request arises only when the check actually failed.

## ADR-4. Screenshots in the hands of the test author — get and save

The main object gains two abilities: get PNG bytes of the current state and save a PNG file to an explicitly user-specified path (`filepath/filename.png`); there is no binding to a specific directory — the user chooses the path. The capture is of the whole page (full-page, uniform with the facade). There are no auto-screenshots on terminal step failure — the decision to capture stays with the user (explicitly rejected at the interview).

**Alternatives considered:** one method with optional saving — rejected by the user in favor of two simple ones; auto-saving on failure to a default directory — rejected: the user's decision.

**Consequences:** for the first time the library writes an artifact to an arbitrary user path; the cache directory remains the only own trace on disk.

## ADR-5. Headless setting and chrome/msedge channels; env rename

A `headless` setting appears (in `[tool.prettyplay]`, default `true` — current behavior; env `PRETTYPLAY_BROWSER_HEADLESS`), and the allowed `browser` values expand to `{chromium, firefox, webkit, chrome, msedge}`: the last two are the Playwright channel launching the installed browser, i.e. a user's existing `browser = "chrome"` starts working. The browser env variable is renamed cleanly: `PRETTYPLAY_BROWSER` → `PRETTYPLAY_BROWSER_NAME`, the old name stops working (there are no external consumers; on encountering the old name — a hint of the new one). Today headless is not passed to `launch()` at all (headless is the Playwright default), and `browser = "chrome"` fails as an invalid value.

**Consequences:** the TOML key stays `browser` — only the env variable is renamed; `chrome`/`msedge` require a locally installed browser, and when it is missing — an actionable message (see ADR-6).

## ADR-6. Actionable configuration errors

Settings validation errors are wrapped in a loud actionable library error: the setting name, the received value, the list of allowed values. The configuration documentation already promises this ("an invalid value — a loud actionable error naming the setting"), while the implementation yields a raw `pydantic.ValidationError`; this is the same "the setting simply does not work" surface from the user's problem about the browser.

## ADR-7. Scroll actions — in the page facade

The page facade is extended with scrolling abilities: page-level — scroll to an element, scroll by an amount down/up, scroll to the end/start of the page; container-level (carousels) — bring an element into view inside a scrollable container and scroll the container by an amount. It covers user scenarios that are currently inexpressible: the facade surface has no scrolling at all, and Playwright's auto-scroll fires only on actions. The primitives of the installed Playwright 1.62 suffice: `scroll_into_view_if_needed`, `mouse.wheel`, `evaluate`/`window.scrollTo`.

**Limitations:** the facade is a backward-compatibility contract: extension only, no renames or removals; the page API listing for the LLM is a string hardcoded in the engine mirroring `.usages/facade.md` — it changes only together with it (otherwise the model will not see the new abilities); scrolling is a surface of generated step code (sentences like "scroll down"), no separate scroll API at the main object level appears.

**Unresolved (future):** "scroll until it appears" (infinite feed: scroll until an element appears) — deferred outside the topic; partially assembled by repeating "to the end" + waiting for the element.

---

## Interview summary

Five user problems → solutions: "ugly" failure → ADR-1 + ADR-3; the unused LLM advantage → ADR-2; screenshots for reports → ADR-4; the browser "with a head" and `browser = chrome` → ADR-5 + ADR-6; scroll actions → ADR-7. All decisions were approved by the user in three rounds of the file-based dialog (files `autonomous_execution.q1–q4` in the pipeline stage directory).
