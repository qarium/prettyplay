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
from .renderer import PreparedStep, StepMemory


class StepHealer:
    """Heals a failed cached step according to the classification verdict.

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
        prepared: PreparedStep,
        step_type: str,
        previous_steps: list[ScenarioStep],
        page: PageFacade,
        attempt_history: list[StepAttempt],
        window: SettleWindow,
        memory: StepMemory,
    ) -> CachedStep:
        """Heal a failed cached step according to the classification verdict.

        Args:
            step: the cached step whose code failed.
            error: the failure description of the cached code.
            prepared: the render product of the failed step — the
                classification and every regeneration request carry the
                prepared instruction with its INPUTS and RESULTS blocks; the
                raw template sentence never reaches a request.
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
            memory: the test memory of the executor — the accepted
                regeneration's captures publish inside the regeneration loop
                at the acceptance point, after validation and the gate.

        Returns:
            The healed step with proven code, already cached by the
            generator — the healer serves ordinary steps only: a group step
            never reaches it, the regeneration request always carries
            ``group_prompt=None``.

        Raises:
            ProductDefectError: the expectation of the step is genuinely
                broken in the product; the cache stays untouched.
            IncurableStepError: the verdict says regeneration cannot help,
                or the regeneration attempt budget is exhausted — the
                exhaustion reuses the verdict of this classification, no
                second LLM request is made; the code field carries the
                cached step code.
            LLMUnavailableError: the provider service failed after the
                bounded transport retries; no engine retry.
        """
        classification = classify_step_failure(
            self._config, self._provider, prepared.instruction, step.code, error, page
        )

        verdict = FailureVerdict(
            category=classification.category,
            explanation=classification.explanation,
            recommendation=classification.recommendation,
        )

        self._reporter.emit(
            "on_healing_started", {"step_text": prepared.instruction, "category": classification.category}
        )

        if classification.category == "product_defect":
            raise ProductDefectError(prepared.instruction, classification.explanation, error, verdict)
        if classification.category == "incurable":
            raise IncurableStepError(
                prepared.instruction, classification.explanation, error, code=step.code, verdict=verdict
            )

        # rot | fixable — regeneration carrying the recommendation, the render product and the memory
        try:
            healed = self._generator.regenerate(
                identity=step.identity,
                prepared=prepared,
                step_type=step_type,
                previous_steps=previous_steps,
                group_prompt=None,  # a group step never reaches the healer — no framing on this path
                page=page,
                attempt_history=attempt_history,
                recommendation=classification.recommendation,
                window=window,
                memory=memory,
            )
        except IncurableStepError as inner:  # regeneration exhausted — the verdict stays None inside
            # the entry verdict of this classification, never a second LLM request; raise … from inner
            raise IncurableStepError(
                prepared.instruction, inner.reason, inner.error, code=step.code, verdict=verdict
            ) from inner

        self._reporter.emit("on_healed", {"step_text": prepared.instruction, "explanation": classification.explanation})
        return healed
