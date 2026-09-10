"""The shared classification call: collect the page state and ask the provider."""

from ..config import Config
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
- USER INSTRUCTIONS: the project's classification guidance, when configured

Answer with exactly one line of the form:
category | explanation | recommendation

where category is one of:
- rot — the UI changed (selectors, texts, structure) and the step can be regenerated for the same intent
- product_defect — the step works as written but the expected behavior of the application is genuinely broken
- incurable — the step sentence no longer matches reality, the intent is ambiguous, or regeneration cannot help

explanation: one short sentence why. recommendation: one short sentence what the engineer should do.
Output only that single line — no code, no extra text."""


def classify_step_failure(  # noqa: PLR0913, PLR0917 — the parameter list is fixed by the engine contract
    config: Config,
    provider: LLMProvider,
    step_text: str,
    code: str,
    error: str,
    page: PageFacade,
) -> FailureClassification:
    """Classify a step failure: collect the page state and ask the provider.

    The single classification call for both engines — the generator failed-check
    stop and exhaustion, the healer verdict. Provider unavailability propagates
    to the caller: this routine never swallows it — the calling path decides
    whether it is a terminal infrastructure failure or a quiet verdict skip.

    Args:
        config: project settings; ``send_screenshots`` attaches page images
            and ``classification_prompt`` supplies the user instructions.
        provider: the LLM port implementation classifying the failure.
        step_text: the sentence of the failed step.
        code: the step code that failed.
        error: the human-readable failure description.
        page: the page facade of the current test.

    Returns:
        The classification verdict.

    Raises:
        LLMUnavailableError: the provider service failed; the calling path
            decides the handling.
    """
    snapshot = page.aria_snapshot()
    screenshot = page.screenshot() if config.send_screenshots else None

    return provider.classify_failure(
        prompt=CLASSIFICATION_PROMPT,
        user_instructions=config.classification_prompt,
        step_text=step_text,
        code=code,
        error=error,
        snapshot=snapshot,
        screenshot=screenshot,
    )
