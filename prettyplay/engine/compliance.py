"""The two-dimension compliance gate: instruction compliance and step adequacy of a green candidate."""

from ..config import Config
from ..llm import ComplianceFinding, LLMProvider
from .attempts import StepAttempt
from .renderer import PreparedStep

#: System prompt of every compliance verdict request; used by the engine gate, applied verbatim.
#: Frozen mirror of the ``compliance_prompt`` practice of the engine CODEMANIFEST —
#: the single source of the prompt; the constant changes only together with the manifest.
COMPLIANCE_PROMPT = """You verify generated step code on two dimensions: the project's user instructions and what the step says.

Input you receive:
- INSTRUCTIONS: the project's user instructions, verbatim
- STEP TYPE: action or assertion
- STEP: the prepared instruction of the step — the plain-text sentence with actual values embedded
- INPUTS: the call input bindings, one name = value line each — present when the step carries inputs
- RESULTS: the declared result names — present when the step declares captures; the code must return a dictionary of exactly these names to non-blank strings observed on the page
- ATTEMPT HISTORY: the verbatim record of every attempt of this step so far, when present — the original cached code first when it exists; each record carries the attempt outcome, the URL before -> after line, the complete candidate code and the complete error
- CODE: the successfully executed candidate code

Check the code on both dimensions and answer with exactly one JSON list of
findings:
[{"instruction": "<quote>", "priority": "high|medium|low",
"explanation": "<one short sentence>", "dimension": "instruction|adequacy"}]

Dimension calibration:
- instruction — the code violates a project instruction: the quote is the
  violated instruction
- adequacy — the code does not match what the step says, given the step
  type and the attempt history: the quote is the fragment of the step
  sentence the code fails to accomplish, or — for behavior that exceeds
  the step — the code line performing it

Priority calibration:
- high — a confident, material finding evident from the code, the step type
  and the attempt history; for instruction: a material violation evident
  from the code itself — the instruction was expressible through the page
  API the code already uses, and the code plainly skipped or contradicted
  it without any fallback attempt; for adequacy: an action step whose code
  contains no action of the step — the page state the code relies on was
  produced by a prior attempt or manual intervention, not by the code
  itself, use the URL lines and the records of the history to see it — or
  material behavior the step never asked for: an assertion step that
  changes page state (a navigation, a click, a fill), a trailing check in
  an action step that only confirms the action's own completion, a check
  of a fact the step sentence never names; only high blocks the candidate
- medium and low — minor observations, partial compliance or doubt: visible,
  never blocking; when in doubt, never high
- an empty list [] means the code complies and accomplishes the step

Rules:
- The attempt history is your ground truth for what already happened on the
  page: the candidate ran on a page that may already contain effects of prior
  attempts or manual intervention — code that only checks an already-achieved
  state without producing it is an adequacy violation for an action step
- Adequacy covers both directions: falling short of the step and exceeding
  it — extra actions inside an assertion step, a trailing confirmation of
  the action's own completion, extra checks of facts the step sentence
  never names are adequacy findings too
- Conditional prefer-type instructions are checked conditionally: when the code shows
  a graceful fallback attempt, that is compliance; judge followability from the code
  and the step sentence alone — never speculate about page state beyond the attempt
  history and the inputs
- An instruction the code could not follow because the step sentence itself prevents
  it is not a violation; when the inputs leave the followability in doubt, the finding
  is never high
- Judge both dimensions: the code against the instructions, and the code against the
  step sentence with its type
- Treat RESULTS as the exact-key return contract: the code must return a dictionary of exactly
  the declared names to non-blank strings observed on the page — code that cannot produce it
  is an adequacy finding
- When INPUTS values influence the step, code that hardcodes their current values instead of
  reading step_inputs["vars"] cannot replay with new inputs; report a high adequacy finding
- Output only the JSON list, no other text"""


def check_step_compliance(  # noqa: PLR0913, PLR0917 — the parameter list is fixed by the engine contract
    config: Config,
    provider: LLMProvider,
    prepared: PreparedStep,
    step_type: str,
    code: str,
    attempt_history: list[StepAttempt],
) -> list[ComplianceFinding]:
    """Gate a successfully executed candidate on the two compliance dimensions.

    Args:
        config: project settings — ``generation_approve`` is the gate switch
            and ``generation_prompt`` supplies the checked user instructions.
        provider: the LLM port implementation returning the verdict.
        prepared: the render product of the generated step — instruction,
            input bindings and result declarations; the verdict request
            renders them as the STEP, INPUTS and RESULTS blocks.
        step_type: action or assertion — the adequacy dimension judges by it.
        code: the successfully executed candidate code.
        attempt_history: the step's attempt history — rendered through the
            record render and passed to the verdict request as the ATTEMPT
            HISTORY block.

    Returns:
        The verdict findings of both dimensions; an empty list — compliant
        and adequate, or the gate is off. The single check of every caching
        path — generation, healing and steering alike; never runs on
        replayed cached code.

    Raises:
        LLMUnavailableError: the provider service failed after the bounded
            transport retries; the calling path never caches the candidate.
        ComplianceVerdictError: the provider answer did not parse into
            findings; the calling path never caches the candidate.
    """
    if not config.generation_approve or not config.generation_prompt:
        return []  # the gate is off or nothing to check against — zero provider calls

    return provider.check_instruction_compliance(
        prompt=COMPLIANCE_PROMPT,
        user_instructions=config.generation_prompt,
        instruction=prepared.instruction,
        step_type=step_type,
        inputs=prepared.inputs,
        declarations=prepared.declarations,
        code=code,
        attempt_history=[record.render() for record in attempt_history],
    )
