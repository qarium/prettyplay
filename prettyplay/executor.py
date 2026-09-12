"""The step cycle: cache hit — execute under settle; miss — generate or stop in strict mode; failure — heal or steer."""

import logging
from typing import NoReturn

from .cache import CachedStep, RunBudgets, StepCache, StepIdentity, normalize_step_text
from .config import PrettyConfig
from .driver import PageFacade
from .engine import StepGenerator, StepHealer, classify_step_failure, format_step_error, run_step_code
from .engine.polling import SettleWindow, settle
from .engine.steering import StepSteering
from .failures import FailureVerdict, IncurableStepError, LLMUnavailableError, ProductDefectError
from .llm import LLMProvider
from .reporting import StepReporter

logger = logging.getLogger("prettyplay")

#: Strict-mode cache miss — generation is forbidden, so the miss is incurable.
_STRICT_MISS_REASON = "strict mode forbids generation — the step is missing from the cache"

#: Strict-mode terminal failure produced by the quiet verdict skip.
_STRICT_NO_VERDICT_REASON = "the step failed in strict mode without an llm verdict"


class StepExecutor:
    """The owner of the step cycle of one test.

    One step goes through the full cycle: a cache hit executes the cached
    code under the settle window with no LLM involvement whatsoever; a miss
    delegates to the generator, which stores the step after the candidate
    has actually worked; a failed cached step delegates to the healer, whose
    verdict decides between a loud product defect, an incurable step, and
    rot regeneration. In strict replay-only mode nothing is ever
    (re)generated: a cache miss is incurable outright, and a failed cached
    step is at most classified — the only LLM call — then raised by its
    category; the settle window still applies to the cached code. A terminal
    IncurableStepError of a non-strict interactive run makes one detour
    through the steering dialog — a healed return continues the step as a
    success. The scenario context — the sentences of the previous steps of
    this test — feeds every generation and healing request.

    Attributes:
        cache_key: the context key of the owning test object.
        _cache: the step cache of the test.
        _generator: the generation engine of the cycle.
        _healer: the healing engine of the cycle.
        _steering: the interactive steering of terminally stuck steps.
        _reporter: the visibility point of the test.
        _config: project settings; the strict switch picks the replay-only
            path, the interactive switch the steering gate.
        _provider: the LLM port implementation of the strict classification.
        _scenario: the sentences of the previous steps of this test.
    """

    def __init__(  # noqa: PLR0913, PLR0917 — the signature is fixed by the root cell contract
        self,
        cache_key: str,
        cache: StepCache,
        generator: StepGenerator,
        healer: StepHealer,
        steering: StepSteering,
        budgets: RunBudgets,  # noqa: ARG002 — spent by the engine; kept for contract symmetry
        reporter: StepReporter,
        config: PrettyConfig,
        provider: LLMProvider,
    ) -> None:
        """Keep the collaborators of the step cycle and reset the scenario context.

        Args:
            cache_key: the context key of the owning test object.
            cache: the step cache of the test.
            generator: the generation engine of the cycle.
            healer: the healing engine of the cycle.
            steering: the interactive steering of terminally stuck steps —
                invoked only on a non-strict interactive run.
            budgets: the per-test attempt registry; attempts are spent
                by the engine, not by the executor.
            reporter: the visibility point of the test.
            config: project settings; the strict switch picks the
                replay-only path, the interactive switch the steering gate,
                and the classification prompt feeds the strict path.
            provider: the LLM port implementation of the strict classification;
                a lightweight object — no SDK client, no credentials.
        """
        self.cache_key = cache_key
        self._cache = cache
        self._generator = generator
        self._healer = healer
        self._steering = steering
        self._reporter = reporter
        self._config = config
        self._provider = provider
        self._scenario: list[str] = []  # test scenario context

    def execute(self, step_text: str, step_type: str, page: PageFacade) -> None:
        """Run one step through the full cycle.

        Args:
            step_text: the sentence of the step as written by the engineer.
            step_type: the kind of the step sentence ({action, assertion}).
            page: the live page facade of the current test.

        Raises:
            ProductDefectError: the healed step verdict says the expectation
                of the step is genuinely broken in the product; in strict
                mode, a product_defect classification of a failed cached
                step — or an assertion step failing without a verdict.
            IncurableStepError: the step never generated successfully, or the
                verdict says regeneration cannot help; in strict mode, any
                cache miss or non-product-defect classification. Never raised
                by an interactive non-strict step the steering dialog healed.
            LLMUnavailableError: the provider service failed; no retry.
        """
        outcome = "failed"
        try:
            self._reporter.emit("on_step_started", {"step_text": step_text, "step_type": step_type})

            identity = StepIdentity(
                cache_key=self.cache_key,
                step_type=step_type,
                normalized_text=normalize_step_text(step_text),
            )
            window = SettleWindow(self._config.polling_timeout, self._config.polling_delay)
            cached = self._cache.load(identity)

            if cached is not None:
                try:
                    settle(run_step_code, cached.code, page, window)
                except Exception as error:  # cached code failed — the mode picks the reaction
                    error_text = format_step_error(error)

                    if self._config.strict:
                        self._strict_failure(step_text, step_type, cached, error_text, page)  # always raises
                    else:
                        try:
                            # healed = re-executed
                            self._healer.heal(cached, error_text, self._scenario, page, window)
                        except IncurableStepError as failure:  # the only kind the steering intercept serves
                            self._steer_or_raise(failure, identity, page)
            elif self._config.strict:
                raise IncurableStepError(step_text, _STRICT_MISS_REASON, "", code="")
            else:
                try:
                    self._generator.generate(identity, step_text, self._scenario, page, window)
                except IncurableStepError as failure:  # the only kind the steering intercept serves
                    self._steer_or_raise(failure, identity, page)

            self._scenario.append(step_text)
            self._reporter.emit("on_step_passed", {"step_text": step_text, "step_type": step_type})
            outcome = "passed"
        except Exception as error:
            self._reporter.emit(
                "on_step_failed",
                {"step_text": step_text, "step_type": step_type, "error": str(error)},  # the render, verbatim
            )

            if isinstance(error, (ProductDefectError, IncurableStepError)) and error.verdict is not None:
                self._reporter.emit(
                    "on_step_verdict",
                    {
                        "step_text": step_text,
                        "category": error.verdict.category,
                        "explanation": error.verdict.explanation,
                        "recommendation": error.verdict.recommendation,
                    },
                )
            raise
        finally:
            # the closing event of every step — exactly once, after every other
            # event, on pass, on failure and on the strict miss alike
            self._reporter.emit(
                "on_step_finished",
                {"step_text": step_text, "step_type": step_type, "outcome": outcome},
            )

    def _steer_or_raise(
        self,
        failure: IncurableStepError,
        identity: StepIdentity,
        page: PageFacade,
    ) -> CachedStep:
        """Offer a terminal step failure to the steering dialog before it propagates.

        The interactive gate first: only a non-strict interactive run opens
        the dialog — replay-strict and interactive-off propagate the failure
        unchanged, as do the other kinds structurally (the intercept wraps
        exactly ``IncurableStepError``; ``ProductDefectError`` and
        ``LLMUnavailableError`` are not ``IncurableStepError``). A healed
        return continues the step as a success — the cache write-back and the
        ``on_healed`` event already happened inside the dialog; a declined
        dialog propagates the original failure object unchanged.

        Args:
            failure: the terminal failure about to propagate.
            identity: the address of the stuck step — the healed step is
                written back under it.
            page: the live page facade of the test.

        Returns:
            The healed cached step — the step continues as a success.

        Raises:
            IncurableStepError: the dialog was declined or never opened —
                the original failure object, unchanged.
        """
        if not (self._config.interactive and not self._config.strict):
            raise failure

        healed = self._steering.steer(failure, identity, self._scenario, page)
        if healed is None:  # quit, EOF, SIGINT at the prompt or a dead provider
            raise failure

        return healed

    def _strict_failure(
        self,
        step_text: str,
        step_type: str,
        step: CachedStep,
        error_text: str,
        page: PageFacade,
    ) -> NoReturn:
        """Turn the failure of a cached step into a terminal error by classification only.

        Strict mode never regenerates and never heals: the classification is
        the only LLM call, and its category picks the error kind — a product
        defect fails loudly, everything else is incurable (rot included: the
        healer never runs). When the LLM is unavailable the verdict is
        skipped quietly and the step type alone picks the kind: a failed
        assertion is the signal the suite exists for, a failed action merely
        did not run.

        Args:
            step_text: the sentence of the failed step.
            step_type: the kind of the step sentence ({action, assertion}).
            step: the cached step whose code failed.
            error_text: the full formatted error text of the failure.
            page: the live page facade of the current test.

        Raises:
            Always: ProductDefectError or IncurableStepError — the strict
                terminal verdict of the failed cached step.
        """
        try:
            classification = classify_step_failure(
                self._config, self._provider, step_text, step.code, error_text, page
            )
        except LLMUnavailableError:
            logger.warning("verdict skipped: llm unavailable")

            # from None: the skip is logged; the step failure itself travels in the error field
            if step_type == "assertion":
                raise ProductDefectError(step_text, _STRICT_NO_VERDICT_REASON, error_text, None) from None
            raise IncurableStepError(step_text, _STRICT_NO_VERDICT_REASON, error_text, code=step.code) from None

        verdict = FailureVerdict(
            category=classification.category,
            explanation=classification.explanation,
            recommendation=classification.recommendation,
        )

        if classification.category == "product_defect":
            raise ProductDefectError(step_text, classification.explanation, error_text, verdict)
        raise IncurableStepError(
            step_text, classification.explanation, error_text, code=step.code, verdict=verdict
        )
