"""The instruction compliance gate: verify a green candidate against the user instructions."""

from ..config import Config
from ..llm import ComplianceFinding, LLMProvider

#: System prompt of every compliance verdict request; used by the engine gate, applied verbatim.
#: Frozen mirror of the ``compliance_prompt`` practice of the engine CODEMANIFEST —
#: the single source of the prompt; the constant changes only together with the manifest.
COMPLIANCE_PROMPT = """You verify that generated step code follows the project's user instructions.

Input you receive:
- INSTRUCTIONS: the project's user instructions, verbatim
- STEP: the step sentence the code was generated for
- CODE: the successfully executed candidate code

Check the code against every instruction and answer with exactly one JSON list of
findings:
[{"instruction": "<the violated instruction quote>", "priority": "high|medium|low",
"explanation": "<one short sentence>"}]

Priority calibration:
- high — a confident, material violation evident from the code itself: the instruction
  was expressible through the page API the code already uses, and the code plainly
  skipped or contradicted it without any fallback attempt; only high blocks the
  candidate
- medium and low — minor observations, partial compliance or doubt: visible, never
  blocking; when in doubt, never high
- an empty list [] means the code complies

Rules:
- Conditional prefer-type instructions are checked conditionally: when the code shows
  a graceful fallback attempt, that is compliance; judge followability from the code
  and the step sentence alone — you see no page state, never speculate about it
- An instruction the code could not follow because the step sentence itself prevents
  it is not a violation; when the inputs leave the followability in doubt, the finding
  is never high
- Judge only what the code does against the instructions — not the step sentence,
  not the page state beyond the instructions
- Output only the JSON list, no other text"""


def check_step_compliance(
    config: Config,
    provider: LLMProvider,
    step_text: str,
    code: str,
) -> list[ComplianceFinding]:
    """Gate a successfully executed candidate against the project user instructions.

    The single compliance check of every caching path — generation, healing and
    steering alike call it before a green candidate is stored. The gate never
    runs on replayed cached code. An off switch or empty instructions restores
    the old behavior with zero provider calls; the hard failures of the verdict
    request propagate untouched — this routine never swallows, never logs,
    never caches, and consumes no attempt budget.

    Args:
        config: project settings — ``generation_approve`` is the gate switch
            and ``generation_prompt`` supplies the checked user instructions.
        provider: the LLM port implementation returning the verdict.
        step_text: the sentence of the generated step.
        code: the successfully executed candidate code.

    Returns:
        The verdict findings; an empty list — compliant or the gate is off.

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
        code=code,
    )
