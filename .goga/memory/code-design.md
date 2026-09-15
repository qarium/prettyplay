# Project rules

## Owner-Confirmed Repair Target

When a maintenance request arrives without a written problem statement and every detectable check is green, present
candidate findings to the user and request the actual symptom before acting. A failure surfaced by automated checks is
only a candidate symptom: the defect reported by the owner is the authoritative target, so scope and root-cause
analysis are rebuilt around the reported evidence before repairing, while self-discovered issues are kept as secondary
hygiene inside the same change.

## Library-First Recovery

Before hand-writing custom recovery logic for malformed model output, search for and evaluate a maintained,
purpose-built library (license, dependency footprint, runtime requirements), verify it against a real incident input,
and adopt it instead of bespoke code.

## Atomic Dependency Onboarding

Adopting a third-party dependency is complete only when it lands in the same change as its usage recipe and its wiring
into the consuming component's manifest; adding the package declaration alone is an incomplete adoption.

## Tolerant Syntax, Strict Semantics

Parsing unreliable model output allows exactly one repair attempt at the syntax level, followed by unchanged strict
semantic validation; anything unrepairable or semantically invalid still fails loudly, and well-formed input never
enters the repair path. An empty result is accepted as a pass only when it was explicitly present in valid raw input;
any emptiness produced or completed by a repair is treated as malformed and fails loudly, so a repair can never
manufacture approval.

## Breaking-Change Authorization Gate

A change classified as breaking halts the pipeline at the compatibility guard; the stop is lifted only by explicit user
approval of a presented change plan and escalation report, and the approval is recorded in the compatibility report.

## Specification Precedence

Prescribed specification manifests are the single source of truth for how the code must be written: keep implementation
calls exactly as prescribed, resolve any drift by fixing the implementation side while leaving the specification and
usage documents untouched, and when a lint rule demands a construct the specification forbids, suppress that rule
narrowly with a justification comment rather than rewriting the code.

## Compatibility-Floor Verification

Treat the oldest interpreter version exercised by CI as the project's compatibility floor: reproduce the failure and
verify every fix on a real interpreter at that floor, in addition to the local newer interpreter, before declaring the
bug fixed.

## Formatting Completion Gate

Before finishing any change, run the project's canonical formatter across source, tests, and code examples embedded in
usage documentation, and confirm the formatting check that CI enforces passes over all of them.

## Working-Directory-Anchored Defaults

Location defaults for run state resolve against the working directory the process was launched from; upward discovery
of the project configuration file serves only settings loading, and any explicitly configured override always takes
precedence over the default.
