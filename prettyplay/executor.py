"""The step cycle: cache hit — settle; miss — generate or the strict stop; failure — heal, recover, steer."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, NoReturn

from .cache import CachedStep, RunBudgets, StepCache, StepIdentity, normalize_step_text
from .config import PrettyConfig
from .driver import PageFacade
from .engine import StepGenerator, StepHealer, classify_step_failure, format_step_error, run_step_code
from .engine.attempts import OUTCOME_ORIGINAL, StepAttempt
from .engine.groups import GroupRecovery, GroupStepOutcome
from .engine.polling import SettleWindow, settle
from .engine.renderer import PreparedStep, StepMemory  # interim until the executor task threads the render product
from .engine.steering import StepSteering
from .failures import FailureVerdict, IncurableStepError, LLMUnavailableError, ProductDefectError
from .llm import LLMProvider, ScenarioStep
from .reporting import StepReporter

if TYPE_CHECKING:
    from .groups import StepGroup

logger = logging.getLogger("prettyplay")

#: Strict-mode cache miss — generation is forbidden, so the miss is incurable.
_STRICT_MISS_REASON = "strict mode forbids generation — the step is missing from the cache"

#: Strict-mode terminal failure produced by the quiet verdict skip.
_STRICT_NO_VERDICT_REASON = "the step failed in strict mode without an llm verdict"


def _read_url(page: PageFacade) -> str:
    """Read the page URL for the replay bracket; never kills the step.

    Args:
        page: the page facade handle of the current test.

    Returns:
        The current URL of the page, or the empty string when the read
        fails — the step itself proceeds normally.
    """
    try:
        return page.url
    except Exception:
        return ""


class StepExecutor:
    """The owner of the step cycle of one test.

    Attributes:
        cache_key: the context key of the owning test object.
        _cache: the step cache of the test.
        _generator: the generation engine of the cycle.
        _healer: the healing engine of the cycle — ordinary steps only.
        _steering: the interactive steering of terminally stuck steps.
        _recovery: the group recovery engine of failed group steps.
        _reporter: the visibility point of the test.
        _config: project settings; the strict switch picks the replay-only
            path, the interactive switch the steering gate.
        _provider: the LLM port implementation of the strict classification.
        _scenario: the typed records of the previous steps of this test.
    """

    def __init__(  # noqa: PLR0913, PLR0917 — the signature is fixed by the root cell contract
        self,
        cache_key: str,
        cache: StepCache,
        generator: StepGenerator,
        healer: StepHealer,
        steering: StepSteering,
        recovery: GroupRecovery,
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
            healer: the healing engine of the cycle — invoked only for
                ordinary steps of a non-strict run.
            steering: the interactive steering of terminally stuck steps —
                invoked only on a non-strict interactive run.
            recovery: the group recovery engine of failed group steps —
                invoked only on a non-strict run for a step executed inside
                a group.
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
        self._recovery = recovery
        self._reporter = reporter
        self._config = config
        self._provider = provider
        self._scenario: list[ScenarioStep] = []  # test scenario context

    def execute(  # noqa: PLR0913, PLR0917 — the signature is fixed by the root cell contract
        self,
        step_text: str,
        step_type: str,
        page: PageFacade,
        group: StepGroup | None = None,
        tries: int | None = None,
        delay: float | None = None,
    ) -> None:
        """Run one step through the full cycle.

        Args:
            step_text: the sentence of the step as written by the engineer.
            step_type: the kind of the step sentence ({action, assertion}).
            page: the live page facade of the current test.
            group: the authoring group the step executes inside; ``None`` —
                an ordinary step. A group step carries the group framing and
                its failures route to the group recovery; strict mode keeps
                the classification-only path for every step alike.
            tries: the declared retry count of this execution; ``None`` —
                the time-bounded settle mode; a declared count switches the
                settle window to the count-bounded mode.
            delay: the declared quiet start pause in seconds; ``None`` — no
                pause; passes quietly right after the started event.

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
            ComplianceVerdictError: the compliance gate could not obtain a
                usable verdict — the provider answer did not parse into
                findings; the executed candidate is never cached.
        """
        outcome = "failed"
        traced = False  # this step's group trace record — appended exactly once, failed or passed
        try:
            self._reporter.emit("on_step_started", {"step_text": step_text, "step_type": step_type})
            if delay is not None:
                time.sleep(delay)  # the quiet pre-step pause — no event, no log record

            identity = StepIdentity(
                cache_key=self.cache_key,
                step_type=step_type,
                normalized_text=normalize_step_text(step_text),
            )
            window = SettleWindow(self._config.polling_timeout, self._config.polling_delay, tries)
            attempt_history: list[StepAttempt] = []  # the per-step history — created here, dies with the step
            group_url_before = _read_url(page) if group is not None else ""  # the group bracket opens
            cached = self._cache.load(identity)

            if cached is not None:
                url_before = group_url_before if group is not None else _read_url(page)
                try:
                    settle(run_step_code, cached.code, page, window)
                except Exception as error:  # cached code failed — the mode picks the reaction
                    traced = self._replay_failure(
                        cached,
                        format_step_error(error),
                        url_before,
                        _read_url(page),  # the bracket closes on the failure record 0 anchors
                        step_text,
                        step_type,
                        group,
                        tries,
                        delay,
                        identity,
                        attempt_history,
                        page,
                        window,
                    )
            elif self._config.strict:
                raise IncurableStepError(step_text, _STRICT_MISS_REASON, "", code="")
            else:
                traced = self._generate_step(
                    step_text, step_type, group, tries, delay, identity, group_url_before, attempt_history, page, window
                )

            self._scenario.append(
                ScenarioStep(
                    sentence=step_text,
                    instruction=step_text,  # the pre-render interim — rendering lands with the executor task
                    group_prompt=group.prompt if group is not None else "",
                )
            )
            if group is not None and not traced:
                # the green step's own record — the bracket closes after the execution
                self._append_group_trace(
                    group, step_text, step_type, tries, delay, identity, group_url_before, _read_url(page), "passed"
                )
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

    def _append_group_trace(  # noqa: PLR0913, PLR0917 — the record fields are fixed by the groups cell contract
        self,
        group: StepGroup,
        step_text: str,
        step_type: str,
        tries: int | None,
        delay: float | None,
        identity: StepIdentity,
        url_before: str,
        url_after: str,
        outcome_label: str,
    ) -> None:
        """Append this step's verbatim trace record to the traces of its group.

        Args:
            group: the authoring group the step executes inside.
            step_text: the raw sentence of the step, verbatim.
            step_type: action or assertion.
            tries: the declared retry count of this execution; ``None`` —
                the global polling settings governed the step.
            delay: the declared start pause of this execution; ``None`` —
                no pause.
            identity: the cache address of the step.
            url_before: the page URL read before the execution.
            url_after: the page URL read after the execution — on the
                failure or the green completion.
            outcome_label: passed or failed — exactly one immutable record
                per executed group step.
        """
        group.traces.append(
            GroupStepOutcome(
                sentence=step_text,
                step_type=step_type,
                tries=tries,
                delay=delay,
                outcome=outcome_label,
                url_before=url_before,
                url_after=url_after,
                identity=identity,
            )
        )

    def _replay_failure(  # noqa: PLR0913, PLR0917 — the threading is fixed by the root cell contract
        self,
        step: CachedStep,
        error_text: str,
        url_before: str,
        url_after: str,
        step_text: str,
        step_type: str,
        group: StepGroup | None,
        tries: int | None,
        delay: float | None,
        identity: StepIdentity,
        attempt_history: list[StepAttempt],
        page: PageFacade,
        window: SettleWindow,
    ) -> bool:
        """React to a failed cached execution by mode: strict classifies, a group recovers, ordinary heals.

        Args:
            step: the cached step whose code failed.
            error_text: the full formatted error text of the failure.
            url_before: the page URL read before the cached execution.
            url_after: the page URL read on the failure — the bracket of
                record 0 and the failed trace record.
            step_text: the raw sentence of the step, verbatim.
            step_type: action or assertion.
            group: the authoring group the step executes inside;
                ``None`` — an ordinary step.
            tries: the declared retry count of this execution.
            delay: the declared start pause of this execution.
            identity: the cache address of the step.
            attempt_history: the per-step attempt history record 0 anchors.
            page: the live page facade of the test.
            window: the settle window of this step's execution.

        Returns:
            Whether this step's group trace record was appended; the strict
            path never returns, it raises.

        Raises:
            ProductDefectError: the strict classification or the healed
                verdict says the expectation is genuinely broken.
            IncurableStepError: the strict classification, the unrecoverable
                group verdict or the unrecoverable heal — the steering
                decline propagates the original failure object.
            LLMUnavailableError: the provider service failed; no retry.
        """
        if self._config.strict:
            self._strict_failure(step_text, step_type, step, error_text, page)  # always raises

        if group is not None:
            # the failed group step is traced once, then the group recovery decides
            self._append_group_trace(
                group, step_text, step_type, tries, delay, identity, url_before, url_after, "failed"
            )
            # record 0 — the anchor of the recovery: the original cached code with its
            # replay error and the replay URL pair, composed before the recovery delegation
            attempt_history.append(
                StepAttempt(
                    code=step.code,
                    error=error_text,
                    outcome=OUTCOME_ORIGINAL,
                    url_before=url_before,
                    url_after=url_after,
                )
            )
            self._recover_or_steer(group, step_text, step_type, identity, attempt_history, page, window)

            return True

        # record 0 — the anchor of the healing: the original cached code with its
        # replay error and the replay URL pair, composed before the heal delegation
        attempt_history.append(
            StepAttempt(
                code=step.code,
                error=error_text,
                outcome=OUTCOME_ORIGINAL,
                url_before=url_before,
                url_after=url_after,
            )
        )
        try:
            # healed = re-executed
            self._healer.heal(
                step,
                error_text,
                PreparedStep(instruction=step_text),  # interim until the executor task threads the render product
                step_type,
                self._scenario,
                page,
                attempt_history,
                window,
                StepMemory(),  # interim — the executor task threads the per-test memory
            )
        except IncurableStepError as failure:  # the only kind the steering intercept serves
            self._steer_or_raise(failure, identity, step_text, step_type, self._scenario, None, page, attempt_history)

        return False

    def _generate_step(  # noqa: PLR0913, PLR0917 — the threading is fixed by the root cell contract
        self,
        step_text: str,
        step_type: str,
        group: StepGroup | None,
        tries: int | None,
        delay: float | None,
        identity: StepIdentity,
        url_before: str,
        attempt_history: list[StepAttempt],
        page: PageFacade,
        window: SettleWindow,
    ) -> bool:
        """Generate a missing step; a group step's terminal failure routes to the recovery.

        Args:
            step_text: the raw sentence of the step, verbatim.
            step_type: action or assertion.
            group: the authoring group the step executes inside;
                ``None`` — an ordinary step.
            tries: the declared retry count of this execution.
            delay: the declared start pause of this execution.
            identity: the cache address of the step.
            url_before: the page URL read before the cycle — the opening
                side of the group bracket.
            attempt_history: the per-step attempt history the generation
                loop grows on its failures.
            page: the live page facade of the test.
            window: the settle window of this step's execution.

        Returns:
            Whether this step's group trace record was appended. A group
            step's generation failures arrive unclassified — the recovery
            decides; an ordinary step's terminal failure goes to the
            steering gate.

        Raises:
            ProductDefectError: a generation failure classified as a
                genuine product defect.
            IncurableStepError: the generation never succeeded — the
                steering decline propagates the original failure object.
            LLMUnavailableError: the provider service failed; no retry.
        """
        try:
            self._generator.generate(
                identity,
                PreparedStep(instruction=step_text),  # interim until the executor task threads the render product
                step_type,
                self._scenario,
                group.prompt if group is not None else None,
                page,
                attempt_history,
                window,
                StepMemory(),  # interim — the executor task threads the per-test memory
            )

            return False
        except IncurableStepError as failure:  # the only kind the steering intercept serves
            if group is None:
                self._steer_or_raise(
                    failure, identity, step_text, step_type, self._scenario, None, page, attempt_history
                )

                return False

            # the unclassified generation failure of a group step — the recovery decides
            self._append_group_trace(
                group, step_text, step_type, tries, delay, identity, url_before, _read_url(page), "failed"
            )
            self._recover_or_steer(group, step_text, step_type, identity, attempt_history, page, window)

            return True

    def _recover_or_steer(  # noqa: PLR0913, PLR0917 — the threading is fixed by the root cell contract
        self,
        group: StepGroup,
        step_text: str,
        step_type: str,
        identity: StepIdentity,
        attempt_history: list[StepAttempt],
        page: PageFacade,
        window: SettleWindow,
    ) -> None:
        """Delegate a failed group step to the recovery; a healed return continues the step as a success.

        Args:
            group: the authoring group of the failed step.
            step_text: the raw sentence of the failed step, verbatim.
            step_type: action or assertion.
            identity: the address of the failed step.
            attempt_history: the per-step attempt history anchored by
                record 0 on the cached-replay path, grown by the generation
                loop on the miss path.
            page: the live page facade of the test.
            window: the settle window of this step's execution.
        """
        try:
            self._recovery.recover(
                group.prompt,
                group.traces,
                step_text,
                step_type,
                self._scenario,
                identity,
                attempt_history,
                page,
                window,
            )
        except IncurableStepError as failure:  # the only kind the steering intercept serves
            self._steer_or_raise(
                failure, identity, step_text, step_type, self._scenario, group.prompt, page, attempt_history
            )

    def _steer_or_raise(  # noqa: PLR0913, PLR0917 — the threading is fixed by the root cell contract
        self,
        failure: IncurableStepError,
        identity: StepIdentity,
        step_text: str,
        step_type: str,
        previous_steps: list[ScenarioStep],
        group_prompt: str | None,
        page: PageFacade,
        attempt_history: list[StepAttempt],
    ) -> CachedStep:
        """Offer a terminal step failure to the steering dialog before it propagates.

        Args:
            failure: the terminal failure about to propagate.
            identity: the address of the stuck step — the healed step is
                written back under it.
            step_text: the raw sentence of the stuck step — carried into
                every guided regeneration request verbatim.
            step_type: action or assertion — carried into every guided
                regeneration request.
            previous_steps: the typed scenario records of the previous steps
                of the test, in execution order.
            group_prompt: the group prompt of the stuck step's group;
                ``None`` — an ordinary step.
            page: the live page facade of the test.
            attempt_history: the per-step attempt history already grown by
                the engine loop — the dialog joins it and appends the
                records of its own turns.

        Returns:
            The healed cached step — the step continues as a success.

        Raises:
            IncurableStepError: the dialog was declined or never opened —
                the original failure object, unchanged. Only a non-strict
                interactive run opens the dialog; the intercept wraps
                exactly ``IncurableStepError``.
        """
        if not (self._config.interactive and not self._config.strict):
            raise failure

        healed = self._steering.steer(
            failure, identity, step_text, step_type, previous_steps, group_prompt, page, attempt_history
        )
        if healed is None:  # quit, EOF, SIGINT, an unreadable stdin or a dead provider
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

        Args:
            step_text: the sentence of the failed step.
            step_type: the kind of the step sentence ({action, assertion}).
            step: the cached step whose code failed.
            error_text: the full formatted error text of the failure.
            page: the live page facade of the current test.

        Raises:
            Always: ProductDefectError or IncurableStepError — the strict
                terminal verdict. Strict mode never regenerates and never
                heals: the classification is the only LLM call; an
                unavailable LLM is skipped quietly and the step type alone
                picks the kind.
        """
        try:
            classification = classify_step_failure(self._config, self._provider, step_text, step.code, error_text, page)
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
        raise IncurableStepError(step_text, classification.explanation, error_text, code=step.code, verdict=verdict)
