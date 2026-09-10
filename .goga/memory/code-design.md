# Project rules

## Ask-First Problem Acquisition

When no written problem statement exists anywhere in the repository, documentation, memory, or stage state, ask the user directly for the symptom, where it reproduces, and expected versus actual behavior, and wait for the answer before investigating the code or repairing the environment.

## Compatibility-Floor Verification

Treat the oldest interpreter version exercised by CI as the project's compatibility floor: reproduce the failure and verify every fix on a real interpreter at that floor, in addition to the local newer interpreter, before declaring the bug fixed.

## Specification Precedence

Prescribed specification manifests are the single source of truth for how the code must be written: keep implementation calls exactly as prescribed, resolve any drift by fixing the implementation side while leaving the specification and usage documents untouched, and when a lint rule demands a construct the specification forbids, suppress that rule narrowly with a justification comment rather than rewriting the code.

## Formatting Completion Gate

Before finishing any change, run the project's canonical formatter across source, tests, and code examples embedded in usage documentation, and confirm the formatting check that CI enforces passes over all of them.
