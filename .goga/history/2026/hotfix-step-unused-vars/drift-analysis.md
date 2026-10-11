# Specification Drift Analysis

## Manifest Drift

| Cell | Drift Description | Resolved? |
|---|---|---|
| prettyplay/engine | `compliance_prompt` practice and the fixed-form annotation gained the cleanliness dimension; the frozen constant and the practice are byte-equal (mirror test `test_compliance_prompt_mirror_matches_the_code_manifest_practice`); annotation matches what the prompt teaches and the gate enforces | YES — reconciled in the same change |
| prettyplay/engine/steering | The frozen SYSTEM_PROMPT mirror was edited identically to the practice and the engine constant — the manifest's mirror-discipline annotations hold without text change | YES — no drift introduced |

## Usage Drift

| Cell | Drift Description | Resolved? |
|---|---|---|
| prettyplay/engine | `.usages/generation.md` «The fixed form» section lacked the binding-economy clause the contract now carries — completed with the same wording as the manifest annotation and docs | YES — updated |
| project practices | `step_generation.md` economy rule extended; still byte-equal to both frozen constants (mirror tests pass); no other practice states the code contract | YES — consistent |
| user docs | `docs/reference/step-cache.md` self-contained contract sentence now states the clause and «no dead weight» | YES — updated |

## Behavioral Drift

| Cell | Drift Description | Resolved? |
|---|---|---|
| prettyplay/engine | The gate's verdict for dead-code candidates changes from pass+cache to high finding+block+retry — the planned, owner-approved repair (dialog q2, option A); delivered by the existing high-finding mechanism with no runtime code change; pinned by the new prompt tests and covered by the existing block-and-retry tests | YES — intended and approved |
| prettyplay/engine/steering | Guided write-back inherits the same gate semantics through the shared `check_step_compliance` — the manifest's write-back guarantee («a high finding of either dimension never reaches the cache») now covers dead weight | YES — consistent |

## Algorithmic Drift

| Cell | Drift Description | Resolved? |
|---|---|---|
| — | No algorithm step, ordering, branch or side-effect point changed in any cell; manifests' algorithm texts untouched and still matching the code | NO DRIFT |

## Resolution Status

All drift resolved. Final state verified: 1382 tests passed on Python 3.12.15 and 3.11.2; `ruff check` clean; `ruff format --check` — 122 files formatted; `goga lint` — 12 cells, 0 errors; all prompt mirrors byte-equal; the git diff carries exactly the planned nine files. Live-model adherence to the new prompt rule remains observational by project convention — the owner's next example run regenerates the purged entry as the live proof.
