# Specification Drift Analysis

## Manifest Drift

| Cell | Drift Description | Resolved? |
|---|---|---|
| `prettyplay/config` | New behavior (`adopt_config` verbatim adoption) initially absent from CODEMANIFEST | yes — Routine declared (signature, Algorithm, Requirements, Constraints), header directive and footer Description extended; `goga lint` 0 errors |
| `prettyplay` | `PrettyPlay` `config` annotation and Algorithm step 1 still described the overlay resolution | yes — rewritten to the verbatim branch; `adopt_config` added to `Imports` |

## Usage Drift

| Cell | Drift Description | Resolved? |
|---|---|---|
| `prettyplay/config` | `configuration.md` documented the layered per-test merge and overlay rules | yes — replaced by "The programmatic configuration"; `adopt_config` recipe added under "Loading"; wording unified |
| `prettyplay` | `lifecycle.md` composition paragraph and strict/interactive wording assumed the overlay | yes — verbatim semantics, `config=None` file path stated |
| project docs | `README.md`, `docs/configuration.md`, `docs/getting-started.md`, `docs/guides/browser-setup.md`, `docs/reference/interactive-steering.md` described the removed overlay | yes — all statements updated; migration note added for integrators relying on back-fill |

## Behavioral Drift

| Cell | Drift Description | Resolved? |
|---|---|---|
| `prettyplay` | Behavior change: a passed config no longer back-fills from pyproject+env; no `FileNotFoundError` without a pyproject; env vars cannot mutate a passed config | yes — intentional, user-approved breaking change (escalation override recorded); covered by new/updated tests (1524 passed) |

## Algorithmic Drift

| Cell | Drift Description | Resolved? |
|---|---|---|
| `prettyplay/config` | New algorithm (empty `cache_root` resolution → verbatim return) had no specification | yes — `adopt_config` Algorithm steps match `loader.py` line for line |
| `prettyplay` | `PrettyPlay` construction algorithm gained the resolution branch | yes — Algorithm step 1 mirrors `scenario.py:183`; steps 2–7 unchanged and verified |

## Resolution Status

**All drift resolved.** Verification: `goga lint` — 13 cells, 0 errors; facade import smoke check passes; `PrettyPlay` constructs with a passed config in a pyproject-free directory and returns the adopted values; full suite green. No unresolved manifest, usage, behavioral, or algorithmic drift remains.
