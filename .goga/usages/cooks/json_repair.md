# json_repair — Salvage of Malformed JSON From Model Answers

Practices for the `json-repair` library within prettyplay. Target audience: implementing agents parsing model answers as JSON — the compliance verdict parse of the `prettyplay/llm` cell.

`json-repair` repairs malformed JSON from LLMs: missing quotes, commas and brackets, single-quoted strings, markdown fences, stray prose, truncated values. Zero dependencies, pure Python, requires Python >= 3.10 (the project compatibility floor).

## Verdict-answer salvage — repair syntax, keep semantics strict

A JSON syntax failure is salvaged once; the repaired object passes the same strict semantic validation as a cleanly parsed one. Valid JSON never touches the salvage — `json.loads` runs first, so clean answers take the unchanged path:

```python
import json

from json_repair import loads as repair_loads

try:
    data = json.loads(text)
except ValueError:
    data = repair_loads(text)  # syntax salvage of a model glitch
```

Rules:

- The salvage repairs syntax only: field presence, string types and the closed priority/dimension label sets are validated identically after it
- An empty findings list passes only from an explicitly valid JSON `[]` answer — `json_repair.loads("[")` returns `[]`, so a repaired-to-empty answer is rejected as malformed: no unchecked candidate rides a synthesized empty verdict
- Prose answers repair to a non-list value (an empty string) — the shape check rejects them loudly
- A failure of the salvage library itself is a malformed verdict too: wrap the call so no third-party exception crosses the library boundary
- The salvage never repairs semantics: a finding without a dimension (the old answer shape) or with an unknown priority stays a hard failure

## Recognized glitch shapes

Salvageable — the verdict resolves to the required shape after the repair:

```python
# a dropped opening quote of a key
'[{"instruction": "Accept all the terms", priority": "medium", "explanation": "consent only", "dimension": "instruction"}]'

# single quotes and a trailing comma
"[{'instruction': 'Prefer id attributes', 'priority': 'high', 'explanation': 'locates by text', 'dimension': 'instruction'},]"

# a markdown-fenced findings list
'```json\n[{"instruction": "Prefer id attributes", "priority": "low", "explanation": "chatty", "dimension": "instruction"}]\n```'
```

Not salvageable — the loud failure stands:

```python
"["  # repairs to [] — an emptiness synthesized by the salvage, never a pass

"not json at all"  # prose — repairs to a non-list value
'[{"instruction": "Prefer id attributes", "priority": "high", "explanation": "locates by text"'  # truncated — no dimension survives
'[{"instruction": "i", "priority": "critical", "explanation": "e", "dimension": "instruction"}]'  # unknown priority — semantics stay strict
```
