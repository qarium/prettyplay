# Scope Resolution Report

## Task Summary

The user reports a defect in the `prettyplay` project: when an already-assembled `PrettyConfig` instance is passed in, prettyplay still loads the configuration (pyproject/env file layer) instead of taking the ready instance as-is. The fix must ensure a passed pre-built config is honored without re-loading the file layer.

## Candidate Cells

| Cell | Reason | Priority |
|---|---|---|
| `prettyplay/config` | Owns `load_config`, `PrettyConfig`, `BrowserConfig`, `ConfigurationError` — the loader semantics under defect | 1 (runtime participation) |
| `prettyplay` (root) | `prettyplay/scenario.py` calls `load_config(None, config)` in `Scenario.__init__` — the call site passing the pre-built config | 2 (runtime participation) |

## Included Dependencies

| Cell | Behavioral Relevance |
|---|---|
| `prettyplay/failures` | Provides `PrettyplayError`/`ConfigurationError` taxonomy used by the loader; error-path semantics may be touched by the fix |
| `prettyplay/reporting` | `StepReporter` is constructed right after config resolution in `Scenario.__init__`; adjacent construction context only |

## Excluded Dependencies

| Cell | Exclusion Reason |
|---|---|
| `prettyplay/driver` | Consumes the final `PrettyConfig` only; no participation in config resolution |
| `prettyplay/llm` | Receives `PrettyConfig` from runtime; infrastructure-only dependency for this task |
| `prettyplay/cache` | Receives `self._runtime.config` after resolution; no behavioral participation |
| `prettyplay/engine/*` | Downstream consumers of resolved config; speculative relevance only |
| `prettyplay/skills` | No data flow through config resolution |

## Usage Relationships

| Usage | Relevance |
|---|---|
| `prettyplay/config/.usages/configuration.md` | Documents how consumers pass config; must reflect the honored pre-built config behavior after the fix |
| `prettyplay/.usages/lifecycle.md`, `prettyplay/.usages/steps.md` | Root cell practices referencing `Scenario` construction with `config` — verify consistency |
| `.goga/usages/conventions.md` | Project-wide code and testing conventions (mandatory) |

## Semantic Participation Summary

- `prettyplay/config` — the defect lives in the resolution semantics of `load_config` when `overrides` carries a pre-built `PrettyConfig`.
- `prettyplay` (root) — `Scenario.__init__` is the entry point where an integrator passes the assembled config; it currently always routes through `load_config`.

## Final Investigation Scope

- `prettyplay/config` (`loader.py`, `models.py`, `.usages/configuration.md`)
- `prettyplay` root — `scenario.py` (`Scenario.__init__`), `runtime.py` (config consumption), `.usages/lifecycle.md`
- `tests/` mirror of the above

## Scope Risks

- **Under-scoping**: `PrettyplayRuntime` or `PrettyPlay` facade may also resolve config independently of `Scenario`; if missed, the defect would persist on other entry points.
- **Over-scoping**: touching consumers (driver/llm/cache/engine) would risk breaking the manifest boundary — excluded unless investigation proves participation.

## Notes

- `load_config` signature already declares `overrides: PrettyConfig | None` (loader.py:279) — investigation must decide whether the contract semantics, the loader behavior, or the call site is the root cause.
- History for this run is `.goga/history/2026/0-0-x/` (branch `0.0.x`).
