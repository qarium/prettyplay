# Failure classification

Domain: classifying a failed cached step before healing. Audience: engineers reasoning about healing decisions.

## Categories

| Category | Meaning | Consequence |
|---|---|---|
| rot | the UI changed: selectors, texts, structure | the step is regenerated from the current page and retried |
| product_defect | the expectation legitimately failed | the test fails loudly — never healed green |
| incurable | regeneration cannot help: budget exhausted, text no longer matches reality, ambiguity | the incurable failure carries step, reason, recommendation |

## Call

```python
classification = provider.classify_failure(
    prompt=system_prompt,  # the system prompt text comes from the calling engine
    user_instructions="",  # the classification instructions from the classification_prompt setting; empty — no block
    step_text="click the «Sign in» button",
    code=step_code,
    error="element not found: button «Sign in»",
    snapshot=snapshot_text,
    screenshot=None,
)
print(classification.category, classification.explanation, classification.recommendation)
```

A non-empty `user_instructions` renders as a separate USER INSTRUCTIONS block in the request — the final block of the user content, after all classification inputs. It comes from the classification_prompt setting of the project; generation requests never see it, and classification requests never see the generation instructions.
