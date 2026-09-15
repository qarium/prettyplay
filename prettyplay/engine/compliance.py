"""The two-dimension compliance gate: instruction compliance and step adequacy of a green candidate."""

from ..config import Config
from ..llm import ComplianceFinding, LLMProvider
from .attempts import StepAttempt

#: System prompt of every compliance verdict request; used by the engine gate, applied verbatim.
#: Frozen mirror of the ``compliance_prompt`` practice of the engine CODEMANIFEST —
#: the single source of the prompt; the constant changes only together with the manifest.
COMPLIANCE_PROMPT = """You verify generated step code on two dimensions: the project's user instructions and what the step says.

Input you receive:
- INSTRUCTIONS: the project's user instructions, verbatim
- STEP TYPE: action or assertion
- STEP: the step sentence the code was generated for
- ATTEMPT HISTORY: the verbatim record of every attempt of this step so far, when present — the original cached code first when it exists; each record carries the attempt outcome, the URL before -> after line, the complete candidate code and the complete error
- CODE: the successfully executed candidate code

Check the code on both dimensions and answer with exactly one JSON list of
findings:
[{"instruction": "<quote>", "priority": "high|medium|low",
"explanation": "<one short sentence>", "dimension": "instruction|adequacy"}]

Dimension calibration:
- instruction — the code violates a project instruction: the quote is the
  violated instruction
- adequacy — the code does not accomplish what the step says, given the step
  type and the attempt history: the quote is the fragment of the step sentence
  the code fails to accomplish

Priority calibration:
- high — a confident, material finding evident from the code, the step type
  and the attempt history; for adequacy: an action step whose code contains no
  action of the step — the page state the code relies on was produced by a
  prior attempt or manual intervention, not by the code itself; use the URL
  lines and the records of the history to see it; only high blocks the
  candidate
- medium and low — minor observations, partial compliance or doubt: visible,
  never blocking; when in doubt, never high
- an empty list [] means the code complies and accomplishes the step

Rules:
- The attempt history is your ground truth for what already happened on the
  page: the candidate ran on a page that may already contain effects of prior
  attempts or manual intervention — code that only checks an already-achieved
  state without producing it is an adequacy violation for an action step
- Conditional prefer-type instructions are checked conditionally: when the code shows
  a graceful fallback attempt, that is compliance; judge followability from the code
  and the step sentence alone — never speculate about page state beyond the attempt
  history and the inputs
- An instruction the code could not follow because the step sentence itself prevents
  it is not a violation; when the inputs leave the followability in doubt, the finding
  is never high
- Judge both dimensions: the code against the instructions, and the code against the
  step sentence with its type
- Output only the JSON list, no other text"""


def check_step_compliance(  # noqa: PLR0913, PLR0917 — the parameter list is fixed by the engine contract
    config: Config,
    provider: LLMProvider,
    step_text: str,
    step_type: str,
    code: str,
    attempt_history: list[StepAttempt],
) -> list[ComplianceFinding]:
    """Gate a successfully executed candidate on the two compliance dimensions.

    The single compliance check of every caching path — generation, healing and
    steering alike call it before a green candidate is stored, judging both the
    instruction compliance and the step adequacy in one verdict request. The
    gate never runs on replayed cached code. An off switch or empty
    instructions restores the old behavior with zero provider calls; the hard
    failures of the verdict request propagate untouched — this routine never
    swallows, never logs, never caches, and consumes no attempt budget.

    Args:
        config: project settings — ``generation_approve`` is the gate switch
            and ``generation_prompt`` supplies the checked user instructions.
        provider: the LLM port implementation returning the verdict.
        step_text: the raw sentence of the generated step.
        step_type: action or assertion — the adequacy dimension judges by it.
        code: the successfully executed candidate code.
        attempt_history: the step's attempt history — rendered through the
            record render and passed to the verdict request as the ATTEMPT
            HISTORY block.

    Returns:
        The verdict findings of both dimensions; an empty list — compliant
        and adequate, or the gate is off.

    Raises:
        LLMUnavailableError: the provider service failed; the calling path
            never caches the candidate.
        ComplianceVerdictError: the provider answer did not parse into
            findings; the calling path never caches the candidate.
    """
    if not config.generation_approve or not config.generation_prompt:
        return []  # the gate is off or nothing to check against — zero provider calls

    return provider.check_instruction_compliance(
        prompt=COMPLIANCE_PROMPT,
        user_instructions=config.generation_prompt,
        step_text=step_text,
        step_type=step_type,
        code=code,
        attempt_history=[record.render() for record in attempt_history],
    )
