# Breaking Change Escalation Report

## Detected Break

The approved fix changes the semantics of the `PrettyPlay.__init__` keyword parameter `config`:

- **Before**: a passed `PrettyConfig` is a per-test overlay; unset/`None`/empty fields resolve from the pyproject+env file layer (`load_config(None, config)`).
- **After**: a passed `PrettyConfig` is the pre-assembled effective configuration taken verbatim (`adopt_config(config)`); the file layer loads only when `config is None`.

## Affected Guarantees

| Guarantee | Source | Change |
|---|---|---|
| "explicitly set values win, unset/empty fields resolve from pyproject+env" | root CODEMANIFEST `PrettyPlay.config`; `configuration.md`; `lifecycle.md` | Replaced by verbatim semantics; manifests and usages updated in the same change |
| `load_config` algorithm (file → env → overlay) | config CODEMANIFEST | Preserved verbatim — direct `load_config` consumers unaffected |
| Construction requires an upward pyproject.toml | implicit in `load_config` reach | Removed for the passed-config path — the reported defect |

## Consumer Impact

- Integrators passing partial configs and relying on pyproject/env back-fill must now pass complete configs (or keep `config=None` and use the file layer). Migration is a one-step: fill the missing fields in the passed `PrettyConfig`.
- Tests pinning the overlay behavior are rewritten in this change.

## Pipeline Decision

The pipeline STOP rule fired at Step 4 (Compatibility Guard). Per the Breaking Change Policy — "Only user can override a STOP" — the user was presented the break at the planning checkpoint and explicitly approved the breaking shape:

> Question q2 (2026-10-29, run Bugfix-20261029-124547-7996): "Утверждаю план с breaking-семантикой: config передан — берётся дословно (рекомендуется)"

Pipeline proceeds under this recorded override. No risk was dismissed silently; the non-breaking alternative (separate opt-in parameter) was offered and declined.
