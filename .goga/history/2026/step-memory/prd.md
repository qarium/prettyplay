# Named Memory and Template Inputs Between PrettyPlay Steps

## Problem

Engineers authoring PrettyPlay tests as natural-language steps cannot retain an item name read from one page and use that observation in a later step after navigation. Previous-step descriptions contain instructions rather than actual observed values. Transferring values through additional Python code does not satisfy the intended authoring workflow.

Authors need to name observations, reuse them in ordinary steps, and pass explicit call-local inputs without writing Python code to move captured values between steps.

## Users

The primary user is an engineer authoring and running PrettyPlay browser tests through natural-language steps. The engineer needs to read page text, act on the observation, and check a later page against it. Values must belong to the current test execution, and success and failure must use the existing step experience.

## Goals

Enable authors to capture named page text and use it in subsequent actions and assertions through ordinary `step` and `expect` calls. Preserve replay with current observations for the same operation, including strict replay when the necessary code is cached.

## User Experience

### Capture, Navigate, and Verify

The following example describes intended behavior after this change:

```python
from prettyplay import PrettyPlay

with PrettyPlay("item-name") as t:
    t.step("Open https://shop.example/products")
    t.step("Read the first item name into {% var name %}")
    t.step("Open the item named {{ name }}")
    t.expect("The page contains {{ name }}")
```

`{% var name %}` declares where the step must save text actually read from the page. It does not supply a value itself. Once the step succeeds, the observation is available as `name` in later templates. `{{ name }}` uses that observation, subject to ordinary Jinja local scope. Navigation does not discard memory.

The final check passes when the destination contains the earlier observation and fails through the existing expectation-failure experience when it does not. It must not pass by replacing the observation with text newly read from the destination.

### Several Results and Dependent Captures

One step can capture several independent text values:

```python
t.step(
    "Read the first item name into {% var first_name %} "
    "and the second item name into {% var second_name %}"
)
t.step("For the item named {{ first_name }}, read its tags into {% var tags %}")
t.expect("The page contains {{ tags }}")
```

The first step succeeds only when every declared result is valid. Its values become available together. Tags in this example are one observed text fragment, such as `"sale, summer"`; structured lists are not required.

Capture names are literal, case-sensitive identifiers compatible with Jinja variable names. `vars` is reserved for call inputs. Repeating a capture declaration for the same name within one render is an understandable authoring error before browser execution. Only declarations reached during rendering create expected results. If none are reached, the step has no memory writes. Capture declarations are invalid in `expect`.

### Separate Inputs for One Call

Authors can provide string inputs through `vars`:

```python
t.expect(
    "The page contains {{ name }} and {{ vars.expected }}",
    vars={"expected": "Details"},
)
```

Memory and call inputs occupy separate namespaces. If memory contains `name="Book"` and a call supplies `vars={"name": "Pen"}`, `{{ name }}` reads `"Book"` and `{{ vars.name }}` reads `"Pen"`. Call inputs do not establish or replace memory and last only for that call. Non-string inputs are outside this feature's input contract.

### Replacement and Visibility

A successful later capture under an existing name replaces its previous value. A failed replacement preserves the previous successful value; other names remain unchanged. Captured text is preserved without additional normalization. Empty or whitespace-only captured text is invalid.

A step renders against the memory and inputs present when it starts. Its new results become available to subsequent steps after full acceptance. A read and a capture of the same name in one template therefore read the previous value; if no previous value exists, ordinary interpolation fails. Authors use two steps when they need to capture a value and then use the new observation.

All captures from a failed or rejected step remain unpublished. This atomicity applies to memory; it does not undo browser actions already performed.

### Templates, Missing Values, and Authoring Errors

Templates use standard Jinja features, including explicit filters, conditions, and local assignments. `{% var name %}` adds capture declarations; ordinary Jinja `set` does not publish test memory. Rendering produces plain text without automatic HTML escaping. Substituted values are data and are not rendered again as templates.

Ordinary interpolation of an unavailable value fails with an understandable explanation identifying the name. Merely reading or mentioning a name does not create an observation. The product does not guess its value or reread the page as a silent replacement.

Authors may explicitly handle absence through standard Jinja constructs such as `default` or `is defined`. These are deliberate author choices; generation and healing must not add fallbacks to conceal an unavailable observation.

Use ordinary Python strings for templates. A global f-string ban is not introduced: Python evaluates strings before PrettyPlay receives them. Existing scenarios containing literal Jinja syntax need standard escaping, for example:

```python
t.expect("The page contains {% raw %}{{ name }}{% endraw %}")
```

Other existing sentences retain their authoring and cache behavior.

### Replay and Recovery

Every new test execution starts with empty memory. A cached capture reads the current page again; it does not recover a previous run's observation. Subsequent cached steps use current values. Changing an item name for the same operation does not require rewriting the scenario or regenerating otherwise valid cached code. Strict mode supports this workflow with available cached steps and does not generate or heal.

Returned capture results are checked deterministically against the declared names and allowed text values. Wrong result shape, missing or additional keys, non-string values, and blank captures fail the attempt. Result-contract violations lead to corrective generation where non-strict execution permits it, within existing budgets; strict execution reports the error without generation. A candidate cannot succeed by fabricating data to satisfy these checks.

Applicable recovery retains the existing step experience. Only results from the successful, fully accepted execution are published; retrieving them must not require executing that accepted step again. Ordinary retries retain the prepared instruction. When recovery invokes a step again, its instruction is prepared against the current context.

Group recovery continues to decide its own restart point. Values from accepted steps outside the repeated portion remain available. Each successfully repeated capture updates memory; a later group failure does not roll back those accepted values or clear the whole context.

The cache remains associated with the original template. If Jinja changes the operation itself, cached code may still complete the earlier operation successfully, and existing recovery may not detect the mismatch. Automatic correctness across such changes is not guaranteed by this feature. Actual errors retain ordinary healing behavior; strict reports failures. This limitation does not remove replay support for new data used by the same operation.

## Requirements

- Ordinary action steps must capture one or more observed text values under explicit `{% var name %}` declarations without additional author-written transfer code.
- Later actions and assertions must consume current-test observations through template variables, including across navigation. Call-local string inputs must be separately available through `vars`.
- Capture declarations must identify results exactly, preserve name case, reject duplicate declarations in one render, and exclude the reserved name `vars`. Assertions must not publish memory.
- Every declared result must be present and valid before the step can succeed. Returned results must undergo deterministic validation; invalid result structure or contents cannot be accepted solely on an LLM verdict.
- A successful step must publish all captured values together after required checks. A failed or rejected step must neither establish new values nor replace existing ones.
- Captures must represent actual page observations. Unavailable references must fail ordinary interpolation; only explicit author-written Jinja absence handling may supply an alternative or skip a reference.
- Captured strings must be preserved without memory-level normalization. Empty or whitespace-only captures are failures. Explicit template transformations must remain available without changing the stored observation.
- New captures must become visible after step acceptance. Current-step rendering uses the pre-step snapshot; standard template assignments remain local.
- Cached replay must perform new capture reads and use current inputs. A data change for the same operation must not require regenerating otherwise valid cached code. Strict must remain replay-only.
- Result delivery and acceptance must work consistently across generation, polling, cached execution, healing, group recovery, and steering, without an extra execution just to obtain results.
- Tests and executions must remain isolated, including concurrent tests. Group recovery must preserve its existing restart behavior and update memory per accepted repeated step.
- Existing progress and success/failure reporting must remain the author-facing experience. Existing scenarios retain behavior except where literal Jinja syntax now requires escaping.

## Constraints

- Authoring remains within ordinary `step` and `expect`; no separate capture step kind or memory-management interface is introduced.
- Standard Jinja features remain available without a custom restricted subset. Capture declarations are an explicit extension with the rules above.
- Test memory holds observed strings. Call inputs also contain strings; richer objects and structured captured data are outside scope.
- Strict mode introduces no generation, healing, or new LLM replay checks. Cache misses and execution failures retain their established strict-mode consequences.
- Assertions observe and verify the current page without navigation or other page changes.
- Replay guarantees cover current data for the same operation. Changing a template's operation through its dynamic logic does not gain an automatic semantic compatibility guarantee.

## Scope

### In Scope

- Jinja templates in ordinary steps, `{% var name %}` capture declarations, memory references, and separate call-local `vars` inputs.
- The read, remember, navigate, and verify scenario, multiple named captures, and dependent captures such as reading a known item's textual tags.
- Atomic replacement, deterministic result validation, understandable missing-value failures, and explicit author-controlled absence handling.
- Current-execution values across cache, strict replay, applicable recovery, and existing reporting, with the stated replay limitation.
- Updated authoring examples and documentation of literal-template escaping and Python string-formatting expectations.

### Out of Scope

- Inferring memory references from unnamed phrases such as “that item.”
- Sharing or restoring memory across test executions.
- General-purpose memory listing, deletion, import, or export APIs.
- Structured captured data, non-text objects, or a general facility for persisting arbitrary computed values. Standard template calculations remain available for preparing instructions.
- Translating raw Jinja control flow into generated Python, branch-specific cache variants, or a new semantic correctness check on every replay.
- Automatic guarantees that a changed operation inside an existing cached template will be detected when the old code still succeeds.
- Additional template-loading/customization infrastructure or redesign of unrelated cache, reporting, and recovery behavior.

## Success Criteria

- An author completes capture, navigation, and verification through ordinary steps and explicit template syntax without Python transfer code.
- The destination check passes only when its condition using the earlier observation holds; it fails when that condition does not hold.
- New observations for the same operation work on later cached and strict executions without regenerating otherwise valid steps.
- Multiple captures publish together, independent names remain independent, successful recaptures replace values, and failed captures preserve previous successful values.
- Invalid returned result shape, names, or values cause deterministic failure and applicable correction rather than fabricated success.
- Memory and `vars` remain distinct; missing ordinary references fail, and explicit Jinja absence handling behaves as authored.
- Recovery uses results from the accepted execution without executing it again merely to obtain them. Group restart selection remains unchanged and successful repeated captures update context.
- Separate tests remain independent. Existing non-template scenarios retain behavior, and template escaping and the changed-operation replay limitation are documented.
