"""The diagnosis-driven recovery engine of step groups: bounded cycles over a group-scoped row."""

import logging
import time

from ...cache import CachedStep, RunBudgets, StepCache, StepIdentity
from ...config import Config
from ...driver import PageFacade
from ...failures import FailureVerdict, IncurableStepError, ProductDefectError
from ...llm import GroupFailureClassification, LLMProvider, ScenarioStep
from ...reporting import StepReporter
from ..attempts import OUTCOME_ORIGINAL, StepAttempt
from ..generator import StepGenerator
from ..polling import SettleWindow
from ..renderer import PreparedStep, StepMemory, render_step
from .diagnosis import classify_group_failure
from .outcome import GroupStepOutcome

logger = logging.getLogger("prettyplay")

#: The authored reason of a refused recovery cycle — colon-free; the verdict explanation is the same text.
_CYCLE_CAP = "the per-group recovery cycle cap is exhausted"

#: The authored recommendation of the refused-cycle verdict.
_CYCLE_CAP_RECOMMENDATION = "raise healing_attempts or rework the group"

#: The authored explanation head of an out-of-mandate root — the verbatim step sentence follows the dash.
_OUTSIDE_ROOT = "the root lives outside the group"


class _ActiveFailure:
    """The failure facts the next diagnosis describes — the failed step on entry, fresh per row failure.

    Attributes:
        prepared: the render product of the failing step — the executor's
            product on entry, the failing row occurrence's fresh render
            after a row failure.
        step_type: the step kind of the failing step.
        identity: the address of the failing step.
        history: the per-step attempt history grown to the failure.
        occurrence: the group-order index of the failing step's trace in
            the recovery-local view.
    """

    def __init__(
        self,
        prepared: PreparedStep,
        step_type: str,
        identity: StepIdentity,
        history: list[StepAttempt],
        occurrence: int,
    ) -> None:
        """Keep the active failure facts of the next diagnosis.

        Args:
            prepared: the render product of the failing step.
            step_type: the step kind of the failing step.
            identity: the address of the failing step.
            history: the per-step attempt history grown to the failure.
            occurrence: the group-order index of the failing step's trace.
        """
        self.prepared = prepared
        self.step_type = step_type
        self.identity = identity
        self.history = history
        self.occurrence = occurrence


class GroupRecovery:
    """The diagnosis-driven recovery engine of step groups.

    Attributes:
        _config: project settings; the polling settings build every row
            step's window.
        _provider: the LLM port implementation of the diagnosis request.
        _generator: the regeneration engine — every row step regenerates as
            its own per-step unit.
        _cache: the step cache of the test — record 0 of an earlier row step
            anchors its cached code, the write-back happens per step.
        _budgets: the per-test attempt registry — the cycle cap and the
            per-cycle refresh.
        _reporter: the visibility point for the healing events of the row.
    """

    def __init__(  # noqa: PLR0913, PLR0917 — the signature is fixed by the groups cell contract
        self,
        config: Config,
        provider: LLMProvider,
        generator: StepGenerator,
        cache: StepCache,
        budgets: RunBudgets,
        reporter: StepReporter,
    ) -> None:
        """Keep the collaborators of the recovery cycles.

        Args:
            config: project settings; the polling settings build every row
                step's settle window.
            provider: the LLM port implementation diagnosing the failure.
            generator: the regeneration engine of the row steps.
            cache: the step cache of the test — record 0 anchors and the
                per-step write-backs.
            budgets: the per-test attempt registry — the cycle cap and the
                per-cycle healing refresh.
            reporter: the visibility point for the healing events of the row.
        """
        self._config = config
        self._provider = provider
        self._generator = generator
        self._cache = cache
        self._budgets = budgets
        self._reporter = reporter

    def recover(  # noqa: PLR0913, PLR0917 — the signature is fixed by the groups cell contract
        self,
        group_prompt: str,
        traces: list[GroupStepOutcome],
        prepared: PreparedStep,
        step_type: str,
        previous_steps: list[ScenarioStep],
        identity: StepIdentity,
        attempt_history: list[StepAttempt],
        page: PageFacade,
        window: SettleWindow,  # noqa: ARG002 — the contract parameter; every row step builds its own window from its trace
        memory: StepMemory,
    ) -> CachedStep:
        """Diagnose a failed group step and recover the affected row of the group.

        Args:
            group_prompt: the group prompt of the failed step's group,
                verbatim — reaches the diagnosis and every row request.
            traces: the group's step traces in execution order — the failed
                step's record is the last one; copied into the recovery-local
                view on entry, the caller's list is never mutated.
            prepared: the render product of the failed step, threaded from
                the executor — the active failure's instruction rides the
                diagnosis as STEP; its INPUTS and RESULTS blocks reach the
                requests of the failed step's own row entry through the
                fresh re-render of its trace.
            step_type: action or assertion — the failed step's kind, carried
                into the diagnosis.
            previous_steps: the typed scenario records of the test, in
                execution order — copied into the recovery-local view, every
                row regeneration request carries the view, and the
                outside-group resolution matches the quote against its
                instructions.
            identity: the address of the failed step — the active failure's
                identity on entry; the row resolves every regeneration
                identity, the failed step's included, from the trace records.
            attempt_history: the per-step attempt history of the failed
                step, grown to the failure — the active failure's history;
                the failed step's row entry reuses it, the terminal-failure
                facts derive from its last record.
            page: the live page facade of the test — the row re-executes
                forward on the current page.
            window: the settle window of the failed step's execution — the
                contract parameter; every row step builds its own window
                from its trace.
            memory: the test memory — the render source of every row
                re-render and the publication point of every accepted row
                step's captures.

        Returns:
            The healed cached step of the failed step — written back to the
            cache by the regeneration of its row entry; the row replays the
            group's own steps from the earliest affected one, each
            re-rendered against the current memory and regenerating under a
            fresh full healing counter; a repeat failure re-enters the
            cap-checked cycle with the failing row step as the active
            failure.

        Raises:
            ProductDefectError: the diagnosis says the application is
                genuinely broken — the loud test failure, no cycle is spent
                on it.
            IncurableStepError: the per-group cycle cap is exhausted, the
                diagnosis is incurable, or the quoted root lives outside the
                group — every form carries its verdict.
            PrettyplayError: a row step's re-render hit an authoring error —
                that step's failure, loud, never silently skipped.
            LLMUnavailableError: the provider service failed after the
                bounded transport retries; no engine retry, the steering
                dialog never intercepts it.
        """
        local_scenario = [record.model_copy() for record in previous_steps]
        local_traces = [trace.model_copy() for trace in traces]
        scenario_occurrences = [
            index for index, record in enumerate(local_scenario) if record.group_prompt == group_prompt
        ]
        active = _ActiveFailure(prepared, step_type, identity, attempt_history, len(local_traces) - 1)

        while True:
            if not self._budgets.open_group_cycle(group_prompt):
                # colon-free authored reason; the verdict authors the same explanation
                raise IncurableStepError(
                    active.prepared.instruction,
                    _CYCLE_CAP,
                    "",
                    verdict=FailureVerdict("incurable", _CYCLE_CAP, _CYCLE_CAP_RECOMMENDATION),
                )

            code, error = _last_facts(active.history)  # the active failure's terminal-failure facts
            verdict = classify_group_failure(
                self._config,
                self._provider,
                group_prompt,
                local_traces,
                local_scenario,
                active.prepared.instruction,
                active.step_type,
                active.history,
                page,
            )

            quoted_index = _quoted_group_index(verdict, local_traces)
            outside = _outside_root(verdict, local_scenario, group_prompt)

            if verdict.category == "product_defect":
                # anti-masking — the loud test failure, even when the quote points anywhere
                explanation = _mapped_explanation(verdict, quoted_index is not None)
                raise ProductDefectError(
                    active.prepared.instruction,
                    explanation,
                    error,
                    FailureVerdict(verdict.category, explanation, verdict.recommendation),
                )

            if outside is not None and quoted_index is None:
                # the quoted root lives outside the group — recovery is out of mandate; a quote
                # that matched a group step names the row start first, never the outside raise
                explanation = f"{_OUTSIDE_ROOT} — {outside}"
                raise IncurableStepError(
                    active.prepared.instruction,
                    explanation,
                    error,
                    code=code,
                    verdict=FailureVerdict("incurable", explanation, verdict.recommendation),
                )

            if verdict.category == "incurable":
                explanation = _mapped_explanation(verdict, quoted_index is not None)
                raise IncurableStepError(
                    active.prepared.instruction,
                    explanation,
                    error,
                    code=code,
                    verdict=FailureVerdict(verdict.category, explanation, verdict.recommendation),
                )

            # recoverable — the row runs from the quoted group step, else from the active failure's occurrence
            row_start = quoted_index if quoted_index is not None else active.occurrence
            row = list(enumerate(local_traces))[row_start:]

            for _occurrence, trace in row:  # a fresh full healing counter per row step, every cycle
                self._budgets.refresh_healing(trace.identity)

            try:
                return self._run_row(
                    row, group_prompt, local_scenario, local_traces, scenario_occurrences, active, verdict, memory, page
                )
            except IncurableStepError:
                # the failure state is fresh — the failing row step became the active failure; a
                # new cycle is cap-checked and re-diagnosed with the updated local views
                continue

    def _run_row(  # noqa: PLR0913, PLR0917 — the row threading is fixed by the recovery contract
        self,
        row: list[tuple[int, GroupStepOutcome]],
        group_prompt: str,
        local_scenario: list[ScenarioStep],
        local_traces: list[GroupStepOutcome],
        scenario_occurrences: list[int],
        active: _ActiveFailure,
        verdict: GroupFailureClassification,
        memory: StepMemory,
        page: PageFacade,
    ) -> CachedStep:
        """Regenerate the row sequentially and return the failed step's healed step.

        Args:
            row: the row's occurrence-index and trace-record pairs, the
                failed step's last.
            group_prompt: the group prompt of the recovered group, verbatim
                — the framing of every row request.
            local_scenario: the recovery-local scenario view — carried into
                every row request, its occurrence instructions updated per
                acceptance.
            local_traces: the recovery-local trace view — the occurrence
                records updated per acceptance, marked failed per row
                failure.
            scenario_occurrences: the local_scenario indices of the group's
                own records, in group order.
            active: the active failure — its occurrence's entry reuses its
                grown history; a failing row step replaces its facts before
                the re-raise.
            verdict: the recoverable diagnosis verdict of the cycle — its
                recommendation rides every row request.
            memory: the test memory — the render source of every row
                re-render and the publication point of every acceptance.
            page: the live page facade — the row re-executes forward on the
                current page.

        Returns:
            The healed cached step of the failed step — every row step
            regenerates as its own per-step unit; the active failure's entry
            reuses its grown history, an earlier one anchors a fresh list by
            record 0.

        Raises:
            IncurableStepError: a row step's regeneration exhausted its
                fresh healing pool — the active failure already updated to
                that occurrence; caught by the caller for the cycle
                re-entry.
            PrettyplayError: a row step's re-render hit an authoring error —
                that step's failure, loud, never silently skipped.
            LLMUnavailableError: the provider service failed after the
                bounded transport retries; no engine retry.
            ComplianceVerdictError: the compliance verdict of a green row
                candidate did not parse; nothing is cached.
        """
        healed: CachedStep | None = None

        for occurrence, trace in row:
            if trace.delay is not None:
                time.sleep(trace.delay)  # the quiet library-level pause — never slow_mo

            # the fresh render against the current context: sentence + recorded vars + the current memory
            fresh = render_step(trace.sentence, trace.step_type, memory, trace.vars)

            # the active failure's own entry reuses its grown history; an earlier step anchors a fresh one
            row_history = active.history if occurrence == active.occurrence else self._anchored_history(trace)
            row_window = SettleWindow(self._config.polling_timeout, self._config.polling_delay, trace.tries)

            self._reporter.emit("on_healing_started", {"step_text": fresh.instruction, "category": "recoverable"})
            try:
                healed = self._generator.regenerate(
                    identity=trace.identity,
                    prepared=fresh,
                    step_type=trace.step_type,
                    previous_steps=local_scenario,
                    group_prompt=group_prompt,
                    page=page,
                    attempt_history=row_history,
                    recommendation=verdict.recommendation,
                    window=row_window,
                    memory=memory,
                )
            except IncurableStepError:
                # the failing occurrence becomes the active failure of the next diagnosis — its
                # fresh prepared step, identity, kind and grown history; the local trace view
                # marks the occurrence failed, preserving the freshly prepared instruction
                active.prepared = fresh
                active.step_type = trace.step_type
                active.identity = trace.identity
                active.history = row_history
                active.occurrence = occurrence
                local_traces[occurrence] = trace.model_copy(
                    update={"instruction": fresh.instruction, "outcome": "failed"}
                )
                raise

            # accepted: the fresh instruction replaces the occurrence in both local views, by index —
            # the failed step's own record was never appended to the scenario, its occurrence finds none
            local_traces[occurrence] = trace.model_copy(update={"instruction": fresh.instruction})
            if occurrence < len(scenario_occurrences):
                scenario_index = scenario_occurrences[occurrence]
                local_scenario[scenario_index] = local_scenario[scenario_index].model_copy(
                    update={"instruction": fresh.instruction}
                )

            self._reporter.emit("on_healed", {"step_text": fresh.instruction, "explanation": verdict.root_cause})
            logger.info(
                "group_row_recovered",
                extra={"group": group_prompt, "step": fresh.instruction, "earliest": verdict.earliest_step},
            )

        return healed  # type: ignore[return-value] — the row always ends with the active failure's entry

    def _anchored_history(self, trace: GroupStepOutcome) -> list[StepAttempt]:
        """Compose the fresh per-step history of an earlier row step, anchored by record 0.

        Args:
            trace: the trace record of the earlier row step.

        Returns:
            The one-record history list the regeneration appends into —
            record 0 carries the cached code of the trace identity, empty
            when none is cached.
        """
        cached = self._cache.load(trace.identity)

        return [
            StepAttempt(
                code=cached.code if cached is not None else "",
                error="",
                outcome=OUTCOME_ORIGINAL,
                url_before=trace.url_before,
                url_after=trace.url_after,
            )
        ]


def _quoted_group_index(verdict: GroupFailureClassification, traces: list[GroupStepOutcome]) -> int | None:
    """Resolve the earliest-step quote against the group's own recorded instructions.

    Args:
        verdict: the diagnosis verdict of the cycle.
        traces: the recovery-local trace view of the group's steps, in
            execution order.

    Returns:
        The index of the trace whose instruction equals the quote verbatim,
        or ``None`` when the quote names no group step.
    """
    return next((index for index, trace in enumerate(traces) if trace.instruction == verdict.earliest_step), None)


def _outside_root(
    verdict: GroupFailureClassification,
    previous_steps: list[ScenarioStep],
    group_prompt: str,
) -> str | None:
    """Resolve the earliest-step quote against the instructions of the steps outside the group.

    Args:
        verdict: the diagnosis verdict of the cycle.
        previous_steps: the recovery-local scenario view of the test, in
            execution order.
        group_prompt: the group prompt of the recovered group.

    Returns:
        The verbatim instruction of the outside step the quote names, or
        ``None`` when the quote names none.
    """
    return next(
        (
            record.instruction
            for record in previous_steps
            if record.instruction == verdict.earliest_step and record.group_prompt != group_prompt
        ),
        None,
    )


def _mapped_explanation(verdict: GroupFailureClassification, quoted_in_group: bool) -> str:
    """Map the diagnosis explanation onto the failure taxonomy.

    Args:
        verdict: the diagnosis verdict of the cycle.
        quoted_in_group: whether the quote matched a group step sentence.

    Returns:
        The mapped explanation of the terminal failure — the root cause
        plus the earliest-step quote in parentheses when it named a group
        step.
    """
    if quoted_in_group:
        return f"{verdict.root_cause} (earliest affected step: {verdict.earliest_step})"

    return verdict.root_cause


def _last_facts(history: list[StepAttempt]) -> tuple[str, str]:
    """Derive the terminal-failure facts from the last record of the failed step's history.

    Args:
        history: the per-step attempt history of the failed step.

    Returns:
        The code and the error of the last record; the empty pair when the
        history is empty.
    """
    if not history:
        return "", ""

    return history[-1].code, history[-1].error
