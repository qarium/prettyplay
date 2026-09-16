"""Healing of failed cached steps: classification verdict decides the branch."""

from ..cache import CachedStep, RunBudgets, StepCache
from ..config import Config
from ..driver import PageFacade
from ..failures import FailureVerdict, IncurableStepError, ProductDefectError
from ..llm import LLMProvider, ScenarioStep
from ..reporting import StepReporter
from .attempts import StepAttempt
from .classification import classify_step_failure
from .generator import StepGenerator
from .polling import SettleWindow


class StepHealer:
    """Heals a failed cached step according to the classification verdict.

    The healer never heals blindly. It first asks the provider to classify
    the failure of the cached code, then follows the verdict: a product
    defect propagates loudly as the signal the test suite exists for
    (the cache stays untouched — nothing to regenerate), an incurable step
    propagates with the verdict fields, and rot or fixable delegates to the
    generator, which regenerates the code and rewrites the cache only after
    the healed candidate has actually worked on the page.

    Attributes:
        _config: project settings; the screenshot flag feeds the requests.
        _provider: the LLM port implementation classifying the failure.
        _generator: the regeneration loop of the rot branch.
        _reporter: the visibility point for healing events.
    """

    def __init__(  # noqa: PLR0913, PLR0917 — the signature is fixed by the engine contract
        self,
        config: Config,
        provider: LLMProvider,
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
            budgets: the per-test attempt registry; spent by the generator —
                accepted for contract symmetry, never read here.
            reporter: the visibility point for engine events.
        """
        self._config = config
        self._provider = provider
        self._generator = generator
        self._reporter = reporter

    def heal(  # noqa: PLR0913, PLR0917 — the signature is fixed by the engine contract
        self,
        step: CachedStep,
        error: str,
        step_text: str,
        step_type: str,
        previous_steps: list[ScenarioStep],
        page: PageFacade,
        attempt_history: list[StepAttempt],
        window: SettleWindow,
    ) -> CachedStep:
        """Heal a failed cached step according to the classification verdict.

        The healer serves ordinary steps only — a group step never reaches
        it (the executor routes group failures to the group recovery), so
        the regeneration request always carries ``group_prompt=None``.

        Args:
            step: the cached step whose code failed.
            error: the failure description of the cached code.
            step_text: the raw sentence of the step as passed by the executor —
                forwarded into the classification and every regeneration
                request verbatim, never the casefolded normalization.
            step_type: action or assertion — forwarded into every regeneration
                request.
            previous_steps: the typed scenario records of the previous steps
                of the test, in execution order — each the raw sentence plus
                its permanent group membership; scenario context for
                regeneration, never the normalized addressing forms.
            page: the live page facade the healed code runs against.
            attempt_history: the anchored per-step attempt history — record 0
                carries the original cached code seeded by the executor;
                threaded by reference into the regeneration loop, which
                appends every further attempt of the healing.
            window: the settle window of the current step execution — the
                regenerated candidates absorb transient failures inside it.

        Returns:
            The healed step with proven code, already cached by the generator.

        Raises:
            ProductDefectError: the expectation of the step is genuinely
                broken in the product; the cache stays untouched.
            IncurableStepError: the verdict says regeneration cannot help,
                or the regeneration attempt budget is exhausted — the
                exhaustion reuses the verdict of this classification, no
                second LLM request is made; the code field carries the
                cached step code.
            LLMUnavailableError: the provider service failed; no retry.
        """
        classification = classify_step_failure(self._config, self._provider, step_text, step.code, error, page)

        verdict = FailureVerdict(
            category=classification.category,
            explanation=classification.explanation,
            recommendation=classification.recommendation,
        )

        self._reporter.emit("on_healing_started", {"step_text": step_text, "category": classification.category})

        if classification.category == "product_defect":
            raise ProductDefectError(step_text, classification.explanation, error, verdict)
        if classification.category == "incurable":
            raise IncurableStepError(step_text, classification.explanation, error, code=step.code, verdict=verdict)

        # rot | fixable — regeneration carrying the recommendation and the anchored history
        try:
            healed = self._generator.regenerate(
                identity=step.identity,
                step_text=step_text,
                step_type=step_type,
                previous_steps=previous_steps,
                group_prompt=None,  # a group step never reaches the healer — no framing on this path
                page=page,
                attempt_history=attempt_history,
                recommendation=classification.recommendation,
                window=window,
            )
        except IncurableStepError as inner:  # regeneration exhausted — the verdict stays None inside
            # the entry verdict of this classification, never a second LLM request; raise … from inner
            raise IncurableStepError(step_text, inner.reason, inner.error, code=step.code, verdict=verdict) from inner

        self._reporter.emit("on_healed", {"step_text": step_text, "explanation": classification.explanation})
        return healed
