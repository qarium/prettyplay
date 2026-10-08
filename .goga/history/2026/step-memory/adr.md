# Runtime step memory with Jinja result declarations

PrettyPlay needs to carry observed page text between natural-language steps while reusing cached code with current-run values. Keep ordinary `step` and `expect`, use standard Jinja for templates, and add `{% var name %}` through its [extension mechanism](https://jinja.palletsprojects.com/en/stable/extensions/#writing-extensions) to declare capture results. A generated Python step with captures returns a dictionary of declared names to observed strings; the agent cycle validates and accepts it before publishing test memory.

```python
t.step("Read the first item name into {% var name %}")
t.step("For the item named {{ name }}, read its tags into {% var tags %}")
t.step("Open the item named {{ name }}")
t.expect("The page contains {{ name }}")
t.expect("The page contains {{ vars.expected }}", vars={"expected": "Details"})
```

Memory names are template variables; call-local string inputs occupy the separate `vars` namespace. Neither overwrites the other. Standard Jinja scope applies, and ordinary `set` assignments remain local to the template. Captures contain nonblank strings preserved without memory-level normalization; textual tags are one string, not a structured collection. Memory belongs to one test execution and survives navigation, not test boundaries.

## Execution and acceptance

Rendering starts from a snapshot of memory and call inputs and produces a plain-text instruction, current input bindings, and declarations for result tags actually executed. Substituted data is not rendered again; automatic HTML escaping is disabled. New captures become visible after step acceptance, so a same-step read observes the previous value or fails if unavailable. Ordinary retries retain the prepared instruction; recovery that invokes a step again prepares it against the current context.

Capture names are case-sensitive Jinja-compatible identifiers; `vars` is reserved. Repeated declaration of a name within one render is an authoring error. An inactive branch declares nothing; with no declarations, the step has no memory writes. Capture tags are invalid in `expect`. Ordinary missing-value interpolation fails with the unavailable name; explicit author-written `default` and `is defined` retain standard behavior. Generation and healing must not invent a fallback or substitute a new observation for an unavailable earlier one.

Validate returned results deterministically: the dictionary must have the exact declared keys and valid text values. Wrong shape, missing or additional keys, non-string values, and blank captures fail the attempt. Result-contract violations require corrective generation on permitted non-strict paths within existing budgets; strict fails without generation. Values must actually be read from the page, not fabricated to satisfy validation. Steps without capture declarations retain their existing success-without-result behavior.

All results publish together after step acceptance, including any required candidate-compliance check. Failed or rejected attempts publish nothing. Carry the successful execution's results through polling, generation, healing, group recovery, and steering; never execute an accepted step again merely to recover its return value. Group recovery retains its existing restart-point selection: accepted repeated steps update memory, steps left behind retain their last accepted values, and a later failure does not roll back the whole group. Browser effects are not rolled back.

## Cache and deliberate scope boundary

Keep one cache identity per original step template, retaining scenario and step-kind distinctions and preserving the meaning and case of names and expressions. Runtime values do not enter the identity. Cached code consumes current input bindings and performs capture reads again; earlier observations are not restored as memory. A different item name for the same operation therefore works through cached and strict replay without regenerating otherwise valid code.

Jinja prepares the instruction. The LLM receives that instruction and the input/result binding information needed for execution; it is not tasked with translating raw Jinja control flow into Python. Do not add branch-specific cache identities or a new semantic check on every replay. If a template changes the operation itself, old code may succeed at the previous operation without triggering healing. This limitation is explicitly accepted: automatic correctness across such behavioral changes is outside this task. Actual failures follow existing recovery; strict remains replay-only.

## Consequences

The [driver contract](../../../../prettyplay/driver/CODEMANIFEST) already permits plain-data results, but the documented [execution cycle](../../../../prettyplay/engine/CODEMANIFEST), [polling](../../../../prettyplay/engine/polling/CODEMANIFEST), and [generation instructions](../../../usages/prompts/step_generation.md) do not provide the required result flow. Coordinated input-context and execution-result support is required throughout the agent cycle, not merely a return statement.

Use ordinary Python strings for templates; no global f-string ban or source-form detection is introduced. Existing literal Jinja syntax requires standard `raw` escaping. Other existing sentences and their cache behavior remain compatible. Standard Jinja features remain available without a custom restricted subset; additional template-loading or customization infrastructure is outside this decision.

Function signatures, context transport, binding/cache serialization, and contract layout remain for architectural design. This ADR records behavior and constraints; it does not implement the feature.
