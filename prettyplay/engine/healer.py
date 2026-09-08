"""Healing of failed cached steps: classification verdict decides the branch."""

from ..cache import CachedStep, RunBudgets, StepCache
from ..config import Config
from ..driver import PageFacade
from ..failures import IncurableStepError, ProductDefectError
from ..llm import LlmProvider
from ..reporting import StepReporter
from .generator import CLASSIFICATION_PROMPT, StepGenerator


class StepHealer:
    """Heals a failed cached step according to the classification verdict.

    The healer never heals blindly. It first asks the provider to classify
    the failure of the cached code, then follows the verdict: a product
    defect propagates loudly as the signal the test suite exists for
    (the cache stays untouched — nothing to regenerate), an incurable step
    propagates with the verdict fields, and rot delegates to the generator,
    which regenerates the code and rewrites the cache only after the healed
    candidate has actually worked on the page.

    Attributes:
        _config: project settings; the screenshot flag feeds the requests.
        _provider: the LLM port implementation classifying the failure.
        _generator: the regeneration loop of the rot branch.
        _reporter: the visibility point for healing events.
    """

    def __init__(  # noqa: PLR0913, PLR0917 — the signature is fixed by the engine contract
        self,
        config: Config,
        provider: LlmProvider,
        generator: StepGenerator,
        cache: StepCache,  # noqa: ARG002 — written by the generator only; kept for contract symmetry
        budgets: RunBudgets,  # noqa: ARG002 — spent by the generator only; kept for contract symmetry
        reporter: StepReporter,
    ) -> None:
        """Keep the collaborators of the healing branch.

        Args:
            config: project settings; ``send_screenshots`` attaches page images.
            provider: the LLM port implementation classifying the failure.
            generator: the regeneration loop handling the rot verdict.
            cache: the store of the failed step; written by the generator
                only — accepted for contract symmetry, never read here.
            budgets: the per-run attempt registry; spent by the generator —
                accepted for contract symmetry, never read here.
            reporter: the visibility point for engine events.
        """
        self._config = config
        self._provider = provider
        self._generator = generator
        self._reporter = reporter

    def heal(
        self,
        step: CachedStep,
        error: str,
        previous_steps: list[str],
        page: PageFacade,
    ) -> CachedStep:
        """Heal a failed cached step according to the classification verdict.

        Args:
            step: the cached step whose code failed.
            error: the failure description of the cached code.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade the healed code runs against.

        Returns:
            The healed step with proven code, already cached by the generator.

        Raises:
            ProductDefectError: the expectation of the step is genuinely
                broken in the product; the cache stays untouched.
            IncurableStepError: the verdict says regeneration cannot help.
            LlmUnavailableError: the provider service failed; no retry.
        """
        step_text = step.identity.normalized_text
        snapshot = page.aria_snapshot()
        screenshot = page.screenshot() if self._config.send_screenshots else None
        verdict = self._provider.classify_failure(
            prompt=CLASSIFICATION_PROMPT,
            step_text=step_text,
            code=step.code,
            error=error,
            snapshot=snapshot,
            screenshot=screenshot,
        )
        self._reporter.emit("on_healing_started", {"step_text": step_text, "category": verdict.category})
        if verdict.category == "product_defect":
            raise ProductDefectError(step_text, verdict.explanation)  # кэш не тронут
        if verdict.category == "incurable":
            raise IncurableStepError(step_text, verdict.explanation, verdict.recommendation)

        healed = self._generator.regenerate(
            identity=step.identity,
            step_text=step_text,
            previous_steps=previous_steps,
            page=page,
            existing_code=step.code,
            error=error,
        )
        self._reporter.emit("on_healed", {"step_text": step_text, "explanation": verdict.explanation})
        return healed
