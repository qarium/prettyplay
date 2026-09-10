# Prettyplay MVP Technical Decisions (branch `master`)

> Recorded from the technical discovery interview of 26.08.2026. Status: **approved**.
> Based on the PRD `.goga/history/2026/the-first-version/prd.md`. Each entry records the fact of the decision and its "why".

## Terms

- **Cache step** — a generated executable step artifact stored in the repository and executed without the LLM.
- **`cache_key`** — the mandatory explicit context key set by the integrator on the main object; part of the cache step identity.
- **`cache_path`** — a subdirectory inside the cache directory, part of cache step addressing.
- **Main object** — the object the integrator creates per test; owns the browser context and the cache addressing (user's example: `PrettyTest('cache_key', cache_path=…)` — a form illustration, not a contract).
- **Rot / product defect / incurability** — the taxonomy from the PRD (R14, R18, R19).

---

## ADR-1. Browser driver — Playwright

The product is a wrapper over Playwright: its built-in auto-wait directly reduces the PRD's main pain (selector fragility → "rot"), the a11y snapshot provides cheap structured context for the LLM, and the sync and async APIs cover any runner.

**Alternatives considered:** Selenium — the industry standard, but without auto-wait (the generated code manages waits itself → more false rot) and without an a11y snapshot (the LLM would be fed raw HTML); an abstraction over several drivers — doubles the generation/healing surface in the MVP and makes every cache step driver-dependent. Both rejected for the MVP.

**Consequences:** the MVP browser matrix = {Chromium, Firefox, WebKit} (the PRD left it as an engineering decision); `playwright` is a hard dependency of the package.

## ADR-2. Execution — synchronous

The MVP executes only through the sync API: pytest/unittest tests are synchronous by default, R2 requires running by the standard runner command, the integrator does not drag in an event loop, cache code stays homogeneous.

**Unresolved (future):** async execution — an explicit extension, not in the MVP.

## ADR-3. Cache step = generated Python code

The cache stores generated Python code (a fixed-shape function working through the driver facade), not a declarative IR: steps like "ввести логин и пароль" and checks with waits require a full language, while an IR would turn into developing a second language with endless extension.

**Alternatives considered:** a declarative IR/JSON (safe and validatable, but an expressiveness ceiling); a hybrid with a strict validator over a Python subset.

**Consequences:** the trust boundary is the repository itself (running tests already executes arbitrary repo code, and the cache lives inside it); code is generated only through the narrow facade — this is a generation prompt rule, not a validator, in the MVP; git diffs give reviewability of healing for free ("full magic" does not suffer — the engineer does not read the code).

## ADR-4. Cache step identity

The unique step key = `cache_key` (the mandatory explicit parameter of the main object) + step type (action/assertion) + hash of the normalized step text. Normalization: Unicode NFC, trim, whitespace collapse, casefold ("Нажать Войти" = "нажать войти"); a translation (RU/EN) is a different step; there is no machine translation on the cache path.

**Rejected:** auto-inferring the "context" from the application origin and a default cache_key value — the integrator sets the context explicitly; "substantially different context" from R12 = a different `cache_key` → cache miss → regeneration (not an error). The same text as an action and as an assertion are different steps.

## ADR-5. Cache addressing and storage

One `.py` file per step with metadata (text, cache_key, date); the filename is a deterministic function of the key. `cache_path` is **part of the address**: steps live in the given subdirectory, reuse happens within one subdirectory; by default (no path given) — the shared root, so identical `cache_key`s are reused across tests (the first half of R12). The default cache root is `<repository root>/.prettyplay/cache/`, configurable (`cache_root`).

**Rejected:** treating `cache_path` as a purely organizational layout (the address only from cache_key+text) — creates storage ambiguity when identical steps live in different paths.

## ADR-6. LLM integration — the official OpenAI and Anthropic SDKs

Two providers are supported through the official `openai` and `anthropic` SDKs; all three dependencies (`playwright`, `openai`, `anthropic`) are hard, on the "install and it works" principle.

**Rejected:** LiteLLM (a heavy dependency and someone else's abstraction layer over a key function); the "own thin protocol/interface + extras" variant — rejected by the user in favor of hard dependencies on the official SDKs. No vendor lock-in: cache code does not depend on the provider, the LLM is needed only for generation and healing.

## ADR-7. LLM inputs during generation and healing

The model receives: an a11y snapshot of the current page (Playwright ariaSnapshot — cheap and stable, without HTML noise), the step text, the previous step texts of the test (scenario context raises the quality of composite steps), and for healing — the existing step code and the error. A screenshot is an optional additional input, enabled by a project flag (`send_screenshots`).

**Rejected for the MVP:** raw HTML as the primary input (noisy and expensive); screenshots as a mandatory input.

## ADR-8. Iterative generation and attempt budgets

Generation is a bounded loop: generate → execute → on error return the error and a fresh snapshot → regenerate, ≤ **3** attempts. Healing — ≤ **2** regeneration attempts. The budget is shared per step within a run (not reset between tests — excludes infinite loops on step reuse); configurable in the project config; exhaustion of any budget = an explicit "incurable" failure (R15, success criterion 5).

## ADR-9. The cache is not invalidated by library version

The library version does not participate in cache step validity (user's decision): cache files carry no format version, a step is not regenerated on a prettyplay upgrade.

**Consequence (limitation):** the driver facade the step code is generated against must stay backward compatible across library versions — otherwise the old cache breaks silently; breaking facade changes require a migration strategy.

## ADR-10. Parallel cache writes — atomic replacement without locks

Write to a temporary file with a unique name (pid+random) in the target subdirectory, then `os.replace()` over the target file: atomic on POSIX; on Windows, when the target is busy — a short retry, then skip that step's write with a loud message (the run does not fail). A race of two processes over one step — the last write wins (both code variants are semantically equivalent: one key = one step meaning).

**Rejected:** directory file locks — downtime, the risk of hung locks, new failures instead of eliminating old ones. Rationale regarding the remark about rename/move conflicts: the conflict is exhausted by the unique tmp name + retry; subdirectory isolation (ADR-5) further narrows collision points.

## ADR-11. Cache in read-only environments (CI) — best-effort

The cache is always read; the write happens only when the directory is writable. In a read-only environment generation/healing work "in memory", the run result is correct, but the unsaved new/healed step is loudly marked in the output ("not saved: read-only cache"). The team workflow: generate locally → commit the cache → CI executes fully from the cache without LLM keys (success criterion 2). No separate "CI mode" is introduced.

## ADR-12. Step and healing visibility — logging + hooks

Step texts (R7) and loud healing messages (R17) go through standard `logging` (logger `prettyplay`) — runners and CI capture logs themselves, reporting stays unchanged (R2). For integrators — a thin callback interface; no own event bus is introduced.

## ADR-13. Project configuration

The immutable part of the settings — the `[tool.prettyplay]` section in `pyproject.toml`: browser/driver, `model` (+ optional `generation_model` / `classification_model` overrides), `base_url`, `cache_root`, attempt budgets, `send_screenshots`. Secrets (LLM keys) — only from env variables, never in a repository file (the config may name the variable); env overrides of all settings — for CI.

## ADR-14. Secrets and test data in step text — unsupported in the MVP

Step text lands in the cache, reports and LLM requests, so secrets in steps are unsupported and this is recorded as a documented limitation (user's decision). Substituting env variables into step text was considered and rejected for the MVP.

---

## Open questions / outside the MVP

- **Async execution** — the only major extension of the execution model (ADR-2).
- **Abstraction over drivers** (e.g. Selenium) — do not pull it in until real demand appears.
- **Secrets/test data in steps** — an env-variable substitution scheme is needed if it surfaces in real usage (ADR-14).
- **Breaking changes of the generation facade** — a migration strategy for the existing cache (consequence of ADR-9).
