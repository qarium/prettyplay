# Project rules

## Working-Directory-Anchored Defaults

Location defaults for run state resolve against the working directory the process was launched from; upward discovery
of the project configuration file serves only settings loading, and any explicitly configured override always takes
precedence over the default.

## Breaking-Change Authorization Gate

A change classified as breaking halts the pipeline at the compatibility guard; the stop is lifted only by explicit user
approval of a presented change plan and escalation report, and the approval is recorded in the compatibility report.

## Symptom Elicitation Before Repair

When a maintenance request arrives without a written problem statement and every detectable check is green, candidate
findings are presented to the user and the actual symptom is requested before acting, rather than assuming the most
detectable defect is the intended target.

## Compatibility-Floor Verification

Treat the oldest interpreter version exercised by CI as the project's compatibility floor: reproduce the failure and
verify every fix on a real interpreter at that floor, in addition to the local newer interpreter, before declaring the
bug fixed.

## Specification Precedence

Prescribed specification manifests are the single source of truth for how the code must be written: keep implementation
calls exactly as prescribed, resolve any drift by fixing the implementation side while leaving the specification and
usage documents untouched, and when a lint rule demands a construct the specification forbids, suppress that rule
narrowly with a justification comment rather than rewriting the code.

## Formatting Completion Gate

Before finishing any change, run the project's canonical formatter across source, tests, and code examples embedded in
usage documentation, and confirm the formatting check that CI enforces passes over all of them.
