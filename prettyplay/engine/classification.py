"""The shared classification call: collect the page state and ask the provider."""

from ..config import PrettyConfig
from ..driver import PageFacade
from ..llm import FailureClassification, LLMProvider

#: System prompt of every classification request; used by both engines, applied verbatim.
CLASSIFICATION_PROMPT = """You classify a failure of a web UI test step.

Input you receive:
- STEP: the step sentence
- CODE: the step code that failed
- ERROR: the failure description
- PAGE SNAPSHOT: the accessibility snapshot of the current page
- SCREENSHOT: an image of the page, when attached
- USER INSTRUCTIONS: the project's binding classification guidance, when configured — follow it; it never overrides the fixed answer format above

Answer with exactly one line of the form:
category | explanation | recommendation

where category is one of:
- rot — the UI changed (selectors, texts, structure) and the step can be regenerated for the same intent
- product_defect — the step works as written but the expected behavior of the application is genuinely broken
- fixable — the step code is at fault (an ambiguous or wrong locator or strategy) while the intent stays satisfiable; regeneration for the same intent can help
- incurable — the step sentence no longer matches reality, the intent is ambiguous, or regeneration cannot help

explanation: one short sentence why. recommendation: one short sentence what the engineer should do.
Output only that single line — no code, no extra text."""

#: Formatted-error prefixes of deterministic code defects — a failure the step code itself
#: caused, never the product's behavior; ``format_step_error`` supplies the type-name prefix.
_CODE_DEFECT_PREFIXES = ("SyntaxError: ", "NameError: ", "ImportError: ", "ModuleNotFoundError: ")


def _code_defect_classification(error: str) -> FailureClassification | None:
    """Synthesize the verdict of a deterministic code defect — no page read, no provider request.

    Args:
        error: the formatted failure description — the type-name prefix decides.

    Returns:
        The fixable verdict naming the defect; ``None`` — the failure is not
        deterministic, the provider decides.
    """
    for prefix in _CODE_DEFECT_PREFIXES:
        if error.startswith(prefix):
            return FailureClassification(
                category="fixable",
                explanation=f"the step code has a deterministic defect — {error.splitlines()[0]}",
                recommendation="regenerate the step code removing the named defect",
            )

    return None


def classify_step_failure(  # noqa: PLR0913, PLR0917 — the parameter list is fixed by the engine contract
    config: PrettyConfig,
    provider: LLMProvider,
    step_text: str,
    code: str,
    error: str,
    page: PageFacade,
) -> FailureClassification:
    """Classify a step failure: collect the page state and ask the provider; a deterministic code defect returns a synthesized fixable verdict with neither.

    Args:
        config: project settings; ``send_screenshots`` attaches page images
            and ``classification_prompt`` supplies the user instructions.
        provider: the LLM port implementation classifying the failure.
        step_text: the prepared instruction of the failed step as passed by
            the calling engine — the code was generated for it; never the
            raw template sentence, never the casefolded normalization.
        code: the step code that failed.
        error: the human-readable failure description.
        page: the page facade of the current test.

    Returns:
        The classification verdict.

    Raises:
        LLMUnavailableError: the provider service failed — propagates
            untouched, the calling path decides the handling.
    """
    code_defect = _code_defect_classification(error)

    if code_defect is not None:  # a deterministic code defect — no page read, no provider request
        return code_defect

    snapshot = page.aria_snapshot()
    screenshot = page.screenshot() if config.send_screenshots else None

    return provider.classify_step_failure(
        prompt=CLASSIFICATION_PROMPT,
        user_instructions=config.classification_prompt,
        step_text=step_text,
        code=code,
        error=error,
        snapshot=snapshot,
        screenshot=screenshot,
    )
