# Project rules

## Verbatim Configuration Adoption

An explicitly assembled configuration object is adopted verbatim as the complete and sole source of effective settings: no layered overlay or back-filling of unset, empty, or default-valued fields from any other source, and fields the caller leaves unset keep their declared model defaults. Any explicitly configured override always takes precedence, and location defaults for run state that remain unsupplied resolve against the working directory the process was launched from; upward discovery of the project configuration file serves only settings loading.

## Breaking-Change Authorization Gate

A change that makes identical call arguments yield different effective behavior is classified as breaking and halts the pipeline at the compatibility guard; the stop is lifted only by explicit user approval of a presented change plan and escalation report, and the approval is recorded in the compatibility report. Behavior outside the change's scope stays unchanged, and public interfaces not required by the change remain untouched. Removing a forbidden capability is such a breaking change and must be carried through every layer that grants, teaches, or enforces it — runtime binding sites, prompt copies, the compliance gate, the manifest guarantee, and the docs — because prompt-only or gate-only fixes leave the channel reachable and the contract unenforced.

## Self-Contained Step Code

Generated and cached step code may consume only its declared arguments, bound to the literal values rendered into the step's instruction sentence; it must never read execution-context channels or runtime globals, so a cached step remains valid wherever its sentence addresses it. Every name the code binds, the code uses: unused bindings are dead weight, a defect of the generation system, and a candidate that binds a name without using it is a blocking adequacy violation in the compliance gate — the attempt is refused and retried with the violation text kept in the history, repeated failures escalate to a loud unrecoverable error, and dirty candidates are never admitted to the cache. The generation prompt teaches this binding-economy rule and the gate enforces it, and the two are always edited in lockstep across every frozen mirror (the generation prompt in three copies, the gate prompt in two).

## Specification Precedence

Prescribed specification manifests are the single source of truth for how the code must be written: keep implementation calls exactly as prescribed, resolve any drift by fixing the implementation side while leaving the specification and usage documents untouched, and when a lint rule demands a construct the specification forbids, suppress that rule narrowly with a justification comment rather than rewriting the code.

## Tolerant Syntax, Strict Semantics

Parsing unreliable model output allows exactly one repair attempt at the syntax level, followed by unchanged strict semantic validation; anything unrepairable or semantically invalid still fails loudly, and well-formed input never enters the repair path. An empty result is accepted as a pass only when it was explicitly present in valid raw input; any emptiness produced or completed by a repair is treated as malformed and fails loudly, so a repair can never manufacture approval.

## Owner-Confirmed Repair Target

When no task or defect description exists anywhere in the run, first exhaustively re-verify that absence across every artifact, then stop and ask the owner to state the task in concrete terms — symptom, module or file, expected versus actual behavior — before doing any work, presenting any observed candidate symptoms as informed options; never select a self-invented interpretation of the work and start executing it. When every detectable check is green, present candidate findings to the user and request the actual symptom before acting: a failure surfaced by automated checks is only a candidate symptom, and the owner's own formulation is the authoritative target — adopted even when it is broader than the option offered — so scope and root-cause analysis are rebuilt around the reported evidence before repairing, while self-discovered issues are kept as secondary hygiene inside the same change.

## Positive-Only Prompt Rules

Generation prompts must state rules purely positively and stay unaware that a forbidden channel exists at all; even a negative clause naming the channel teaches the model that the channel exists, so every context-related clause, positive or negative, is stripped from the prompt.

## Regenerate Caches, Never Hand-Edit

Cached step files are local, gitignored outputs of the generation system rather than tracked source; the fix target is always the generation system end to end, and defective cache entries are purged so they regenerate from the corrected prompt rather than being hand-patched or committed.

## Compatibility-Floor Verification

Treat the oldest interpreter version exercised by CI as the project's compatibility floor: reproduce the failure and verify every fix on a real interpreter at that floor, in addition to the local newer interpreter, before declaring the bug fixed.

## Library-First Recovery

Before hand-writing custom recovery logic for malformed model output, search for and evaluate a maintained, purpose-built library (license, dependency footprint, runtime requirements), verify it against a real incident input, and adopt it instead of bespoke code.

## Foreign Environment Immutability

Treat tooling artifacts in the workspace that belong to another host or owner — such as an interpreter environment whose internals point into a foreign system — as untouchable: never delete, recreate, or repair them on your own initiative; run checks with an interpreter that already carries the project dependencies instead.

## Error-Output Hygiene

Keep failure texts, attempt records, and downstream log or model consumers readable: bulky machine-generated page-state blocks (such as accessibility snapshots) embedded in assertion messages must be stripped at the error-text formatting boundary, the same policy applies to generated assertion failure texts, and genuinely diagnostic sections are preserved verbatim.

## Atomic Dependency Onboarding

Adopting a third-party dependency is complete only when it lands in the same change as its usage recipe and its wiring into the consuming component's manifest; adding the package declaration alone is an incomplete adoption.

## Formatting Completion Gate

Before finishing any change, run the project's canonical formatter across source, tests, and code examples embedded in usage documentation, and confirm the formatting check that CI enforces passes over all of them.
