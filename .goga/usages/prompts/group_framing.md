# Group generation framing

The additive framing every generation and regeneration request of a group step carries —
referenced by the engine and engine/groups cells as the `group_framing` practice. It changes
nothing in the ordinary step requests: the framing rides on top of the full test scenario context,
nothing existing is removed.

---

Blocks a group step request renders additionally:

- GROUP PROMPT — the group's shared goal, verbatim, rendered as its own block immediately before
  the PREVIOUS STEPS block
- PREVIOUS STEPS marking — the entries belonging to the group render marked: the group prompt of
  the entry renders with the marked sentence, so the model sees which earlier steps belong to the
  same interaction

Semantics:

- The group prompt is framing on top of the scenario context — it never replaces the step
  sentence, the step type, the attempt history or any existing block
- The marking is permanent: a scenario-context entry keeps its group membership forever, so later
  ordinary steps and the group diagnosis see the group-marked steps in the full test context
- The model generates one step at a time exactly as for ordinary steps: the one-function-per-step
  form and per-step caching are unchanged — the group is never generated as one multi-step unit
