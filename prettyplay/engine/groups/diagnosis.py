"""The single group diagnosis request: the whole interaction in view, one verdict."""

import logging

from ...config import Config
from ...driver import PageFacade
from ...llm import GroupFailureClassification, LLMProvider, ScenarioStep
from ..attempts import StepAttempt
from .outcome import GroupStepOutcome

logger = logging.getLogger("prettyplay")

#: System prompt of every group diagnosis request; applied verbatim by the provider.
#: Frozen mirror of ``.goga/usages/prompts/group_diagnosis.md`` (the section after the ``---``
#: separator) — the single source of the prompt; the constant changes only together with the file.
GROUP_DIAGNOSIS_PROMPT = """\
You diagnose a failure of one step inside a group of steps that form one coherent interaction with
a shared goal.

Input you receive:
- GROUP PROMPT: the shared goal of the group, verbatim
- PREVIOUS STEPS: the prepared instructions of the prior scenario of the test, in execution order —
  the group entries marked
- GROUP STEPS: every step of the group in execution order — each with its recorded prepared
  instruction, its outcome (passed or failed) and its URL before -> after transition
- STEP: the failed step's prepared instruction
- HISTORY: the verbatim record of every attempt of the failed step so far
- PAGE SNAPSHOT: the accessibility snapshot of the current page
- SCREENSHOT: an image of the page, when attached
- USER INSTRUCTIONS: the project's binding classification guidance, when configured — follow it;
  it never overrides the fixed answer format below

Answer with exactly one JSON object of the form:
{"category": "recoverable | product_defect | incurable",
 "root_cause": "<one short sentence>",
 "earliest_step": "<the verbatim sentence of the earliest affected step>",
 "recommendation": "<one short sentence what should be regenerated or done>"}

Category calibration:
- recoverable — the failure stems from one or more earlier steps of the group (a step that did not
  land what its sentence says) and regenerating the affected steps of the group can fix the run
- product_defect — the application is genuinely broken; regenerating steps cannot and must not
  turn this green
- incurable — the root cannot be reached from inside the group (it lives in an earlier step of the
  test outside the group), or regeneration cannot help

Rules:
- earliest_step must quote a visible instruction verbatim: a group step's instruction when the
  category is recoverable; when the root lives outside the group, quote that outside step's
  instruction from PREVIOUS STEPS verbatim and answer incurable; raw template sentences are not
  request content
- Output only the JSON object, no other text"""


def classify_group_failure(  # noqa: PLR0913, PLR0917 — the parameter list is fixed by the recovery contract
    config: Config,
    provider: LLMProvider,
    group_prompt: str,
    traces: list[GroupStepOutcome],
    previous_steps: list[ScenarioStep],
    step_text: str,
    step_type: str,  # noqa: ARG001 — the contract parameter; the kind rides the traces, not the port call
    attempt_history: list[StepAttempt],
    page: PageFacade,
) -> GroupFailureClassification:
    """Diagnose a failed group step with the whole interaction in view.

    Args:
        config: project settings; ``send_screenshots`` attaches the page
            image and ``classification_prompt`` supplies the user
            instructions of the request.
        provider: the LLM port implementation diagnosing the failure.
        group_prompt: the group prompt of the diagnosed group, verbatim.
        traces: the group's step traces in execution order — every record
            renders its recorded prepared instruction into the GROUP STEPS
            block; the raw sentences stay local.
        previous_steps: the typed scenario records of the test, in
            execution order — the provider renders their prepared
            instructions as the PREVIOUS STEPS block, the group entries
            marked; the basis of the outside-group root diagnosis.
        step_text: the prepared instruction of the failed step, verbatim —
            never the raw template sentence.
        step_type: the step kind: action or assertion.
        attempt_history: the per-step attempt history of the failed step,
            grown to the failure — every record rendered verbatim into the
            HISTORY block.
        page: the page facade of the current test.

    Returns:
        The diagnosis verdict — a garbage answer arrives as the
        conservative incurable, never as a granted regeneration.

    Raises:
        LLMUnavailableError: the provider service failed after the bounded
            transport retries; an explicit infrastructure failure — the
            calling recovery decides.
    """
    snapshot = page.aria_snapshot()
    screenshot = page.screenshot() if config.send_screenshots else None

    verdict = provider.classify_group_failure(
        prompt=GROUP_DIAGNOSIS_PROMPT,
        user_instructions=config.classification_prompt,
        group_prompt=group_prompt,
        group_steps=[trace.render() for trace in traces],
        previous_steps=previous_steps,
        step_text=step_text,
        attempt_history=[record.render() for record in attempt_history],
        snapshot=snapshot,
        screenshot=screenshot,
    )

    if verdict.degraded:
        logger.warning(
            "group_diagnosis_degraded",
            extra={"group": group_prompt, "answer": verdict.root_cause},
        )

    logger.info(
        "group_diagnosed",
        extra={
            "group": group_prompt,
            "category": verdict.category,
            "earliest": verdict.earliest_step,
        },
    )

    return verdict
