"""Generation of working step code: LLM candidates executed against the live page under the settle window."""

import logging
from datetime import date

from ..cache import CachedStep, RunBudgets, StepCache, StepIdentity
from ..config import Config
from ..driver import PageFacade
from ..failures import FailureVerdict, IncurableStepError, LLMUnavailableError, ProductDefectError
from ..llm import ComplianceFinding, FailureClassification, LLMProvider
from ..reporting import StepReporter
from .attempts import (
    OUTCOME_COMPLIANCE_BLOCKED,
    OUTCOME_EXECUTION_FAILED,
    OUTCOME_FAILED_CHECK,
    StepAttempt,
    _read_url,
)
from .classification import classify_step_failure
from .compliance import check_step_compliance
from .execution import run_step_code
from .polling import SettleWindow, settle
from .text import format_step_error

logger = logging.getLogger("prettyplay")

#: System prompt of every generation and regeneration request; applied verbatim by the provider.
#: Frozen mirror of ``.goga/usages/prompts/generation.md`` (the section after the ``---``
#: separator) — the single source of the prompt; the constant changes only together with the file.
SYSTEM_PROMPT = """You generate executable Python code for one step of a web UI test.

Input you receive:
- STEP TYPE: action or assertion — the kind of the step
- STEP: the step sentence in a natural language
- PREVIOUS STEPS: the sentences of the previous steps of the test, in order
- PAGE SNAPSHOT: the accessibility snapshot of the current page
- PAGE URL: the current URL of the page, when present
- SCREENSHOT: an image of the page, when attached
- CHEAT SHEET: a compact reference of useful Playwright sync API idioms — guidance, not an allowlist; everything standard stays allowed
- USER INSTRUCTIONS: the project's binding code style guidance, when configured
- HISTORY: the verbatim record of every attempt of this step so far, when present — the original cached code first when it exists; each record carries the attempt outcome, the URL before -> after line, the complete candidate code and the complete error
- RECOMMENDATION: the diagnosis of the classification that preceded this regeneration, when present
- USER GUIDANCE: the engineer guidance message of the interactive steering, when present

Output exactly one Python code block with one function of the fixed form:

def step(page) -> None:
    ...

Rules:
- The function receives exactly one argument: the page — the genuine Playwright sync Page; the whole step runs inside the driver worker thread
- Import from playwright.sync_api and the Python standard library only — no third-party
  libraries; imports are global only: at the top level of the code block, before `def
  step`, never inside the function body
- Work through the standard Playwright sync API: locator factories, actions, waits, expect chains, plain asserts on immediate reads — everything standard is allowed; the CHEAT SHEET is guidance, never a boundary
- Assertions: for an assertion sentence end with a check — a waiting expect(...) chain for dynamic content, or an immediate read with a plain Python assert (assert locator.count() > 1)
- No fixed delays, no sleeps, no wait_for_timeout — locators and expect chains auto-wait
- The runtime owns the page lifecycle: never call page.close() or context.close()
- No stateful actions that outlive the step on the page shared by the whole test: page.route, page.clock, add_init_script, tracing, HAR, CDP — excluded from generated code; a cached step would poison every later step far from the cause
- Dialogs: capture with the stock means — with page.expect_event("dialog") as info: — perform the triggering action inside the block, read info.value.type, info.value.message, info.value.default_value, then info.value.accept() or info.value.dismiss()
- Popups and new tabs: capture with with page.expect_popup() as popup_info: — trigger the opening action inside the block, work through popup_info.value; page.bring_to_front() raises a page above the others
- Content inside an iframe goes through page.frame_locator(selector) — locate elements within the returned scope; nested frames chain
- Scrolling: locator.scroll_into_view_if_needed() and page.mouse.wheel(dx, dy) are the standard means
- The page state may already include the effects of prior attempts or manual intervention — the HISTORY records and their URL before -> after lines show what already happened. Your code must produce the step outcome itself: never rely on the current page state already satisfying the step; complete the action or the check even if the page looks done
- RECOMMENDATION and USER GUIDANCE carry the diagnosis and the engineer's intent — follow them when they conflict with your first instinct
- USER INSTRUCTIONS are binding for everything below the safety core of these Rules: follow them when configured; silently ignoring an instruction is a violation
- The safety core of these Rules always outranks the instructions: the fixed function form, the import rule, the lifecycle rule, the stateful-action exclusions, no fixed delays. An instruction conflicting with a Rule or demanding a stateful action is unfollowable: never implement it silently — raise in the step code with the message "instruction conflicts with rule Y" naming the conflict, so the failure surfaces loudly
- Prefer-type instructions are conditional by their own wording: follow them when the page offers the option — best-effort with a graceful fallback is compliance
- The step must complete exactly what STEP says — nothing more, nothing less
- Output only the code block, no explanations"""

#: The compact standard Playwright sync API reference of every generation request;
#: guidance, not an allowlist — everything standard stays allowed.
#: Frozen mirror of ``.goga/usages/prompts/cheatsheet.md`` — the whole file, verbatim
#: (the practice has no ``---`` separator, so the whole-file rule is the only mirror
#: rule with no extraction logic to drift); the constant changes only together with the file.
CHEAT_SHEET = """# Playwright cheat sheet

The compact standard Playwright sync API reference carried by every step-code generation and regeneration request
of prettyplay — referenced by the engine and steering cells as the `cheat_sheet` practice; rendered by the provider
implementations as the leading CHEAT SHEET block of the user content. Guidance, not an allowlist: everything
standard stays allowed — the error-driven regeneration loop is the second line of defense against hallucinated
calls. Target audience: the generation model — a model that knows Playwright weakly writes a correct step from
this reference alone.

## Locator factories

    page.get_by_role("button", name="Sign in")
    page.get_by_label("Username")
    page.get_by_text("Welcome back")
    page.get_by_placeholder("Search")
    page.get_by_alt_text("Logo")
    page.get_by_title("Close")
    page.get_by_test_id("submit")
    page.locator("css selector | //xpath | [data-qa=row]")

## Narrowing

    locator.first / locator.last / locator.nth(2)
    locator.filter(has_text="Product X")
    locator.and_(other) / locator.or_(other)

## Actions

    .click() / .dblclick() / .click(button="right")
    .fill("text") / .clear() / .press("Enter") / .press("Control+A")
    .check() / .uncheck() / .hover() / .select_option("v")
    .drag_to(target) / .set_input_files("path.png")

## Navigation and waits

    page.goto(url) / page.go_back() / page.go_forward() / page.reload()
    page.wait_for_url("**/dashboard") / page.wait_for_load_state("networkidle")
    page.url  # the current URL — an immediate read beside the waiting forms

## Waiting assertions — expect chains

    from playwright.sync_api import expect

    expect(locator).to_be_visible() / to_be_hidden()
    expect(locator).to_be_enabled() / to_be_checked()
    expect(locator).to_have_text("...") / to_contain_text("...")
    expect(locator).to_have_value("v") / to_have_attribute("href", "/docs")
    expect(page).to_have_url("**/dashboard") / to_have_title("Dashboard")

## Count forms — "the page shows a list of X"

    videos = page.get_by_role("listitem")
    expect(videos.first).to_be_visible()
    assert videos.count() > 1

An exact count is the rarer need: `expect(videos).to_have_count(3)`.

## Immediate reads with plain asserts

    assert locator.count() >= 1
    assert "Dashboard" in page.title()
    assert "/dashboard" in page.url

## Dialogs

    with page.expect_event("dialog") as info:
        page.get_by_role("button", name="Delete").click()
    dialog = info.value
    dialog.type / dialog.message / dialog.default_value
    dialog.accept() / dialog.dismiss() / dialog.accept("the answer")

## Popups and new tabs

    with page.expect_popup() as popup_info:
        page.get_by_role("link", name="Open docs").click()
    popup = popup_info.value
    popup.bring_to_front()

## Frames

    frame = page.frame_locator("#checkout")
    frame.get_by_role("button", name="Pay").click()

## Scrolling

    locator.scroll_into_view_if_needed()
    page.mouse.wheel(0, 600)
"""


class StepGenerator:
    """Generates working step code by executing LLM candidates against the live page.

    Each attempt is one provider request: the generator snapshots the page,
    asks for code of the fixed form — carrying the raw step sentence, the
    step type and the rendered per-step attempt history — and immediately
    executes the candidate under the settle window of the current step
    execution, the URL pair bracketing the whole attempt. Every attempt that
    does not produce a cached step appends one verbatim record into the
    shared history owned by the executor, and the retry request carries the
    grown history. A failed check no longer burns the whole budget: the
    classification decides, and a rot or fixable verdict grants exactly one
    healing-funded regeneration carrying the recommendation (also at budget
    exhaustion). A green candidate passes the two-dimension compliance gate
    before it is cached; a high finding of either dimension fails the
    attempt. Only a proven candidate is cached — failures are never stored.

    Attributes:
        _config: project settings; the screenshot flag feeds the requests.
        _provider: the LLM port implementation doing the requests.
        _cache: the store where working steps are saved.
        _budgets: the per-test attempt registry of the engine.
        _reporter: the visibility point for generation and cache events.
    """

    def __init__(
        self,
        config: Config,
        provider: LLMProvider,
        cache: StepCache,
        budgets: RunBudgets,
        reporter: StepReporter,
    ) -> None:
        """Keep the collaborators of the generation loop.

        Args:
            config: project settings; ``send_screenshots`` attaches page images.
            provider: the LLM port implementation.
            cache: the store of working steps.
            budgets: the per-test attempt registry.
            reporter: the visibility point for engine events.
        """
        self._config = config
        self._provider = provider
        self._cache = cache
        self._budgets = budgets
        self._reporter = reporter

    def generate(  # noqa: PLR0913, PLR0917 — the signature is fixed by the engine contract
        self,
        identity: StepIdentity,
        step_text: str,
        step_type: str,
        previous_steps: list[str],
        page: PageFacade,
        attempt_history: list[StepAttempt],
        window: SettleWindow,
    ) -> CachedStep:
        """Generate step code until a candidate works, then cache it.

        Args:
            identity: the address of the step.
            step_text: the raw sentence of the step — carried into every
                request verbatim.
            step_type: action or assertion — carried into every request.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade the candidates run against.
            attempt_history: the per-step attempt history created by the
                executor — this loop appends a record after every attempt
                that does not produce a cached step.
            window: the settle window of the current step execution — every
                candidate execution absorbs transient failures inside it.

        Returns:
            The cached step holding the proven code.

        Raises:
            ProductDefectError: a failed candidate check classified as a
                genuine product defect — by the entry or the final
                classification.
            IncurableStepError: a check or budget outcome classified
                incurable, or the healing funding refused; the code field
                carries the failed step code.
            LLMUnavailableError: the provider service failed; no retry.
            ComplianceVerdictError: the compliance verdict of a green
                candidate did not parse; nothing is cached.
        """
        return self._generation_loop(identity, step_text, step_type, previous_steps, page, attempt_history, window)

    def regenerate(  # noqa: PLR0913, PLR0917 — the signature is fixed by the engine contract
        self,
        identity: StepIdentity,
        step_text: str,
        step_type: str,
        previous_steps: list[str],
        page: PageFacade,
        attempt_history: list[StepAttempt],
        recommendation: str,
        window: SettleWindow,
    ) -> CachedStep:
        """Regenerate step code starting from the anchored history and the diagnosis.

        The loop is the generation loop with four differences: attempts draw
        from the healing budget pool, every request carries the raw sentence,
        the step type, the rendered anchored history and the classification
        recommendation, and every failed attempt — a failed check included —
        takes the retry branch with the grown history: the entry
        classification already guards the anti-masking, so no per-attempt
        classification happens inside the loop. Exhaustion derives the
        terminal-failure facts from the last record of the history.

        Args:
            identity: the address of the step.
            step_text: the raw sentence of the step — carried into every
                request verbatim, never the casefolded normalization.
            step_type: action or assertion — carried into every request.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade the candidates run against.
            attempt_history: the anchored per-step attempt history — record 0
                carries the original cached code composed by the caller; this
                loop appends after every attempt that does not produce a
                cached step; the original is never lost to a re-binding.
            recommendation: the diagnosis of the classification that launched
                the healing; rendered into every request.
            window: the settle window of the current step execution.

        Returns:
            The cached step holding the proven regenerated code.

        Raises:
            IncurableStepError: the healing attempt budget is exhausted; the
                verdict stays None — the calling healer attaches its entry
                verdict — and the code field carries the last record's code.
            LLMUnavailableError: the provider service failed; no retry.
            ComplianceVerdictError: the compliance verdict of a green
                candidate did not parse; nothing is cached.
        """
        return self._healing_loop(
            identity, step_text, step_type, previous_steps, page, attempt_history, recommendation, window
        )

    def _generation_loop(  # noqa: PLR0913, PLR0917 — the shared attempt loop with its fixed inputs
        self,
        identity: StepIdentity,
        step_text: str,
        step_type: str,
        previous_steps: list[str],
        page: PageFacade,
        history: list[StepAttempt],
        window: SettleWindow,
    ) -> CachedStep:
        """Run the generation pool loop until a candidate works or the budget runs out.

        A failed check — a candidate ``AssertionError`` that survived the
        settle window — goes through the bounded-healing decision table: the
        classification decides between a terminal kind and exactly one
        healing-funded regeneration carrying the recommendation and the grown
        history. Any other candidate failure appends its record and retries
        with the grown history. A green candidate is gated through
        ``check_step_compliance`` before it is cached: a high finding of
        either dimension fails the attempt and the retry carries the grown
        history, medium and low findings pass with a WARNING, the gate hard
        failures propagate. Budget exhaustion classifies the last candidate
        and follows the same table — the rot and fixable verdicts grant one
        extra funded regeneration there too; a standing high finding raises
        carrying the verdict built from the finding, with no classification.

        Args:
            identity: the address of the step.
            step_text: the raw sentence of the step.
            step_type: action or assertion — carried into every request.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade the candidates run against.
            history: the per-step attempt history this loop grows — every
                attempt that does not produce a cached step appends its
                record; the green attempt never records.
            window: the settle window of the current step execution.

        Returns:
            The cached step holding the proven code.

        Raises:
            ProductDefectError: a failed candidate check classified as a
                genuine product defect.
            IncurableStepError: the generation attempt budget is exhausted,
                or a failure classified incurable.
            LLMUnavailableError: the provider service failed; no retry.
            ComplianceVerdictError: the compliance verdict of a green
                candidate did not parse; nothing is cached.
        """
        attempt = 0  # every LLM request of this pool run — loop attempts and funded regenerations
        standing: ComplianceFinding | None = None  # the high finding the retries still carry

        while True:
            if not self._budgets.try_generation(identity):
                return self._exhaustion_outcome(
                    identity, step_text, step_type, previous_steps, page, history, window, attempt, standing
                )

            attempt += 1
            self._emit_generation_started(step_text, attempt)

            code = self._request(step_text, step_type, previous_steps, page, history, recommendation=None)

            url_before = _read_url(page)
            try:
                settle(run_step_code, code, page, window)
            except AssertionError as check_failure:
                # failed check survived the window — the decision table, never blind retries
                url_after = _read_url(page)
                # full text, no prefix — the type is the semantics
                history.append(_record(code, str(check_failure), OUTCOME_FAILED_CHECK, url_before, url_after))
                return self._failed_check_outcome(
                    identity,
                    step_text,
                    step_type,
                    previous_steps,
                    page,
                    history,
                    code,
                    str(check_failure),
                    window,
                    attempt,
                )
            except Exception as candidate_error:  # other candidate failures heal via retry
                url_after = _read_url(page)
                history.append(
                    _record(code, format_step_error(candidate_error), OUTCOME_EXECUTION_FAILED, url_before, url_after)
                )
                standing = None  # a real candidate failure replaces the standing violation
            else:
                url_after = _read_url(page)
                # the gate sits outside every exception-swallowing try: its hard failures propagate
                findings = check_step_compliance(self._config, self._provider, step_text, step_type, code, history)
                high = _high_finding(findings)
                if high is not None:  # the attempt failed on the violation — retry targeted at it
                    history.append(
                        _record(code, _violation_text(high), OUTCOME_COMPLIANCE_BLOCKED, url_before, url_after)
                    )
                    standing = high
                    continue
                if findings:
                    _medium_warning(step_text, findings)
                return self._store(identity, code)

    def _healing_loop(  # noqa: PLR0913, PLR0917 — the shared attempt loop with its fixed inputs
        self,
        identity: StepIdentity,
        step_text: str,
        step_type: str,
        previous_steps: list[str],
        page: PageFacade,
        history: list[StepAttempt],
        recommendation: str,
        window: SettleWindow,
    ) -> CachedStep:
        """Run the healing pool loop until a candidate works or the budget runs out.

        Every failed attempt — a failed check included — appends its record
        and retries with the fresh failure description, the fresh snapshot
        and the grown history while attempts remain: the entry classification
        already guards the anti-masking, so no per-attempt classification
        happens inside the loop. Every green candidate is gated through
        ``check_step_compliance`` before it is cached — the same semantics as
        the generation loop minus the standing state: a high finding of
        either dimension fails the attempt and the retry carries the grown
        history, the gate hard failures propagate. Exhaustion raises without
        a classification — the terminal-failure facts derive from the last
        record of the history and the calling healer attaches the verdict it
        already holds.

        Args:
            identity: the address of the step.
            step_text: the raw sentence of the step.
            step_type: action or assertion — carried into every request.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade the candidates run against.
            history: the anchored per-step attempt history — record 0 stays
                untouched at index 0 through every retry.
            recommendation: the diagnosis of the classification that launched
                the healing; rendered into every request.
            window: the settle window of the current step execution.

        Returns:
            The cached step holding the proven code.

        Raises:
            IncurableStepError: the healing attempt budget is exhausted.
            LLMUnavailableError: the provider service failed; no retry.
            ComplianceVerdictError: the compliance verdict of a green
                candidate did not parse; nothing is cached.
        """
        attempt = 0

        while True:
            if not self._budgets.try_healing(identity):
                # colon-free authored reason; the last record carries the terminal-failure facts
                code, error = _last_facts(history)
                raise IncurableStepError(step_text, "healing attempt budget exhausted", error, code=code)

            attempt += 1
            self._emit_generation_started(step_text, attempt)

            code = self._request(step_text, step_type, previous_steps, page, history, recommendation)

            url_before = _read_url(page)
            try:
                settle(run_step_code, code, page, window)
            except AssertionError as check_failure:  # failed checks included — the entry classification guards
                url_after = _read_url(page)
                history.append(_record(code, str(check_failure), OUTCOME_FAILED_CHECK, url_before, url_after))
                continue
            except Exception as candidate_error:
                url_after = _read_url(page)
                history.append(
                    _record(code, format_step_error(candidate_error), OUTCOME_EXECUTION_FAILED, url_before, url_after)
                )
                continue
            url_after = _read_url(page)

            # the gate sits outside every exception-swallowing try: its hard failures propagate
            findings = check_step_compliance(self._config, self._provider, step_text, step_type, code, history)
            high = _high_finding(findings)
            if high is not None:  # the attempt failed on the violation — retry targeted at it
                history.append(_record(code, _violation_text(high), OUTCOME_COMPLIANCE_BLOCKED, url_before, url_after))
                continue
            if findings:
                _medium_warning(step_text, findings)
            return self._store(identity, code)

    def _failed_check_outcome(  # noqa: PLR0913, PLR0917 — the decision table of one failed candidate check
        self,
        identity: StepIdentity,
        step_text: str,
        step_type: str,
        previous_steps: list[str],
        page: PageFacade,
        history: list[StepAttempt],
        code: str,
        error_field: str,
        window: SettleWindow,
        attempt: int,
    ) -> CachedStep:
        """Decide the bounded-healing outcome of a failed candidate check.

        The uniform decision table: product_defect raises at once, incurable
        raises carrying the verdict, and rot or fixable grants exactly one
        healing-funded regeneration carrying the recommendation and the grown
        history — a refused funding is terminal, and a repeat failure gets
        one final classification that decides only the terminal kind, never
        another regeneration. The loop already appended the failed check's
        record before this table runs.

        Args:
            identity: the address of the step — the healing funding key.
            step_text: the raw sentence of the failed step.
            step_type: action or assertion — carried into the funded request.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade of the test.
            history: the per-step attempt history — the failed check's
                record already appended; the funded request carries it grown.
            code: the code of the failed candidate.
            error_field: the full failure text of the failed check.
            window: the settle window of the current step execution.
            attempt: the number of LLM requests the pool run made so far.

        Returns:
            The healed step when the funded regeneration worked.

        Raises:
            ProductDefectError: the entry or final verdict says product defect.
            IncurableStepError: the verdict says incurable, the healing
                funding is refused, or the repeat failure stays terminal —
                the code field carries the failed step code.
        """
        reason = f"candidate check failed — {_first_line(error_field)}"
        verdict = self._classify(step_text, code, error_field, page)
        if verdict is None:  # quiet skip — the failed check itself is the primary signal
            raise IncurableStepError(step_text, reason, error_field, code=code) from None
        if verdict.category == "product_defect":
            raise ProductDefectError(step_text, verdict.explanation, error_field, verdict) from None
        if verdict.category == "incurable":
            raise IncurableStepError(step_text, reason, error_field, code=code, verdict=verdict) from None

        # rot | fixable — exactly one healing-funded regeneration
        if not self._budgets.try_healing(identity):
            raise IncurableStepError(
                step_text, "healing attempt budget exhausted", error_field, code=code, verdict=verdict
            ) from None

        healed, failed_code, failure_text, repeat_was_check = self._funded_regeneration(
            identity, step_text, step_type, previous_steps, page, history, verdict.recommendation, window, attempt
        )
        if healed is not None:
            return healed

        # repeat failure — one final classification deciding the terminal kind only
        final = self._classify(step_text, failed_code, failure_text, page)
        if final is not None and final.category == "product_defect":
            raise ProductDefectError(step_text, final.explanation, failure_text, final) from None
        if repeat_was_check:
            # an assertion repeat names the failed check
            repeat_reason = f"candidate check failed — {_first_line(failure_text)}"
        else:
            # a compliance block or a failed execution is a candidate failure, quiet skip or
            # not — the violation text carries colons; the first-line contract forbids them
            repeat_reason = f"candidate failed — {_reason_safe(failure_text)}"
        raise IncurableStepError(step_text, repeat_reason, failure_text, code=failed_code, verdict=final) from None

    def _exhaustion_outcome(  # noqa: PLR0913, PLR0917 — the decision table of the refused generation pool
        self,
        identity: StepIdentity,
        step_text: str,
        step_type: str,
        previous_steps: list[str],
        page: PageFacade,
        history: list[StepAttempt],
        window: SettleWindow,
        attempt: int,
        standing: ComplianceFinding | None,
    ) -> CachedStep:
        """Decide the outcome of a refused generation attempt.

        A standing high compliance finding raises first, carrying the verdict
        built from the finding itself — no LLM classification, no
        healing-funded regeneration: the standing violation already consumed
        the failed attempt and the pool is exhausted. Otherwise: no candidate
        ever existed — the plain budget failure with an empty error; else the
        last record of the history carries the last candidate's facts and is
        classified through the decision table: the rot and fixable verdicts
        grant one extra healing-funded regeneration carrying the
        recommendation and the grown history; a repeat failure is terminal
        without reclassification, carrying the verdict of the entry
        classification.

        Args:
            identity: the address of the step — the healing funding key.
            step_text: the raw sentence of the failed step.
            step_type: action or assertion — carried into the funded request.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade of the test.
            history: the per-step attempt history of the pool run — its last
                record carries the last candidate's facts; empty — no
                candidate ever existed.
            window: the settle window of the current step execution.
            attempt: the number of LLM requests the pool run made so far.
            standing: the high compliance finding the last retries carried;
                None — the exhaustion is not a standing violation.

        Returns:
            The healed step when the funded regeneration worked.

        Raises:
            ProductDefectError: the verdict says product defect.
            IncurableStepError: the generation attempt budget is exhausted —
                with the finding named when a high one stands, the verdict
                says incurable, or the healing funding is refused — the code
                field carries the failed step code.
        """
        if standing is not None:
            # the verdict is built from the finding — no classification, no regrant of a funded attempt
            verdict = FailureVerdict(
                category="incurable",
                explanation=f"{standing.instruction} — {standing.explanation}",
                recommendation=f"satisfy the finding in the step code: {standing.instruction}",
            )
            raise IncurableStepError(
                step_text,
                f"generation attempt budget exhausted — {_reason_safe(standing.instruction)}",
                _violation_text(standing),
                code=_last_facts(history)[0],
                verdict=verdict,
            ) from None

        reason = "generation attempt budget exhausted"
        if not history:
            raise IncurableStepError(step_text, reason, "", code="") from None  # nothing to classify

        code, error = _last_facts(history)  # the last failed attempt's record carries the facts
        verdict = self._classify(step_text, code, error, page)
        if verdict is None:  # quiet skip — the budget failure is the primary signal
            raise IncurableStepError(step_text, reason, error, code=code) from None
        if verdict.category == "product_defect":
            raise ProductDefectError(step_text, verdict.explanation, error, verdict) from None
        if verdict.category == "incurable":
            raise IncurableStepError(step_text, reason, error, code=code, verdict=verdict) from None

        # rot | fixable — one extra healing-funded regeneration
        if not self._budgets.try_healing(identity):
            raise IncurableStepError(
                step_text, "healing attempt budget exhausted", error, code=code, verdict=verdict
            ) from None

        healed, failed_code, failure_text, _repeat_was_check = self._funded_regeneration(
            identity, step_text, step_type, previous_steps, page, history, verdict.recommendation, window, attempt
        )
        if healed is not None:
            return healed

        # repeat failure — terminal, no reclassification; the verdict of the entry classification travels
        raise IncurableStepError(step_text, reason, failure_text, code=failed_code, verdict=verdict) from None

    def _funded_regeneration(  # noqa: PLR0913, PLR0917 — the single healing-funded request of the bounded healing
        self,
        identity: StepIdentity,
        step_text: str,
        step_type: str,
        previous_steps: list[str],
        page: PageFacade,
        history: list[StepAttempt],
        recommendation: str,
        window: SettleWindow,
        attempt: int,
    ) -> tuple[CachedStep | None, str, str, bool]:
        """Run the one healing-funded regeneration request of the bounded healing.

        A single inline request — never a call to the retrying regenerate
        loop. It is an LLM attempt: the ordinal continues the pool run's
        count and ``on_generation_started`` fires. The request carries the
        grown history — the failed attempt that funded it rides its record.
        A provider failure propagates immediately — no retry, no final
        classification; only the execution of the funded candidate can fail
        softly, appending its record into the history and yielding the failed
        code and its formatted error for the caller's terminal handling. A
        green candidate is gated through ``check_step_compliance`` before it
        is stored; a high finding is a repeat failure of the funded attempt —
        a candidate failure, never a check — so the caller runs its one final
        classification on the violation text.

        Args:
            identity: the address of the step — the identity of the stored step.
            step_text: the raw sentence of the step.
            step_type: action or assertion — carried into the request.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade the candidate runs against.
            history: the per-step attempt history — the request carries it
                grown; the funded attempt's own failure appends its record.
            recommendation: the classification diagnosis carried by the request.
            window: the settle window of the current step execution — shared
                with the loop, the same step execution.
            attempt: the number of LLM requests the pool run made so far.

        Returns:
            The stored healed step with empty failure facts on success; None
            with the failed code, the formatted failure text and whether the
            failure was a failed check on a failed execution.

        Raises:
            LLMUnavailableError: the provider request failed; no retry, no
                final classification.
            ComplianceVerdictError: the compliance verdict of a green funded
                candidate did not parse; nothing is cached.
        """
        attempt += 1
        self._emit_generation_started(step_text, attempt)

        code = self._request(step_text, step_type, previous_steps, page, history, recommendation)
        url_before = _read_url(page)
        try:
            settle(run_step_code, code, page, window)
        except AssertionError as check_failure:
            url_after = _read_url(page)
            history.append(_record(code, str(check_failure), OUTCOME_FAILED_CHECK, url_before, url_after))
            return None, code, str(check_failure), True
        except Exception as failure:
            url_after = _read_url(page)
            history.append(_record(code, format_step_error(failure), OUTCOME_EXECUTION_FAILED, url_before, url_after))
            return None, code, format_step_error(failure), False
        url_after = _read_url(page)

        # the gate sits outside the settle try: its hard failures propagate
        findings = check_step_compliance(self._config, self._provider, step_text, step_type, code, history)
        high = _high_finding(findings)
        if high is not None:  # a compliance block is a candidate failure, not a check
            history.append(_record(code, _violation_text(high), OUTCOME_COMPLIANCE_BLOCKED, url_before, url_after))
            return None, code, _violation_text(high), False
        if findings:
            _medium_warning(step_text, findings)

        return self._store(identity, code), code, "", False

    def _request(  # noqa: PLR0913, PLR0917 — the fixed request inputs of the port signature
        self,
        step_text: str,
        step_type: str,
        previous_steps: list[str],
        page: PageFacade,
        history: list[StepAttempt],
        recommendation: str | None,
    ) -> str:
        """Collect the request inputs and ask the provider for one candidate.

        Args:
            step_text: the raw sentence of the step — carried verbatim.
            step_type: action or assertion — carried into every request.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade of the test.
            history: the per-step attempt history — rendered record by
                record into the HISTORY block of the request.
            recommendation: the classification diagnosis of the request, if any.

        Returns:
            The generated step code of the fixed form.
        """
        snapshot = page.aria_snapshot()
        screenshot = page.screenshot() if self._config.send_screenshots else None

        return self._provider.generate_step_code(
            prompt=SYSTEM_PROMPT,
            user_instructions=self._config.generation_prompt,
            step_text=step_text,
            step_type=step_type,
            previous_steps=previous_steps,
            snapshot=snapshot,
            page_url=None,  # the URL input is steering-only — uniform with the guidance None below
            screenshot=screenshot,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[record.render() for record in history],
            recommendation=recommendation,
            guidance=None,  # steering-only input — the engine never carries guidance
        )

    def _emit_generation_started(self, step_text: str, attempt: int) -> None:
        """Report the start of one LLM attempt.

        Fires once per provider request, never per settle re-execution inside
        it.

        Args:
            step_text: the sentence of the step.
            attempt: the 1-based ordinal of the LLM request in the pool run.
        """
        self._reporter.emit("on_generation_started", {"step_text": step_text, "attempt": attempt})

    def _store(self, identity: StepIdentity, code: str) -> CachedStep:
        """Save the proven candidate as the cached step of the identity.

        Args:
            identity: the address of the step.
            code: the proven step code.

        Returns:
            The stored cached step.
        """
        step = CachedStep(
            identity=identity,
            code=code,
            created_at=date.today().isoformat(),  # noqa: DTZ011 — calendar date of step creation
        )
        self._cache.save(step)

        return step

    def _classify(self, step_text: str, code: str, error: str, page: PageFacade) -> FailureVerdict | None:
        """Classify a failure through the shared routine with the quiet skip.

        Every classification inside the loop enriches an already-decided
        failure, so an unavailable LLM yields no verdict — the failure never
        waits for it and never turns into an infrastructure error.

        Args:
            step_text: the sentence of the failed step.
            code: the code of the last candidate.
            error: the failure description of the candidate.
            page: the live page facade of the test.

        Returns:
            The verdict of the classification, or ``None`` when the LLM was
            unavailable — the quiet skip logs a WARNING.
        """
        try:
            classification = classify_step_failure(self._config, self._provider, step_text, code, error, page)
        except LLMUnavailableError:
            logger.warning("verdict skipped: llm unavailable")
            return None

        return _verdict(classification)


def _first_line(text: str) -> str:
    """Return the first line of a failure text — the authored-reason tail.

    Args:
        text: the full failure text.

    Returns:
        The text up to the first newline; the whole text when single-line.
    """
    return text.partition("\n")[0]


def _reason_safe(instruction: str) -> str:
    """Make an instruction quote safe for an authored reason — the first-line contract.

    Args:
        instruction: the violated instruction text, quoted from the project's
            user configuration; may contain colons and newlines.

    Returns:
        The first line of the instruction with every colon replaced by a
        space — the reason line stays colon-free.
    """
    return _first_line(instruction).replace(":", " ")


def _high_finding(findings: list[ComplianceFinding]) -> ComplianceFinding | None:
    """Return the first high finding of a compliance verdict — either dimension blocks.

    Args:
        findings: the findings of the verdict, in the verdict's own ordering.

    Returns:
        The first finding of priority high, or ``None`` when the verdict
        holds none — the gate re-runs on the next candidate and catches any
        remaining violation.
    """
    return next((finding for finding in findings if finding.priority == "high"), None)


def _violation_text(finding: ComplianceFinding) -> str:
    """Render the violation text of a high finding — the record's error field.

    Args:
        finding: the high finding of either dimension that blocked the candidate.

    Returns:
        The dimension, the named instruction or step fragment, and its
        explanation in the fixed violation wording.
    """
    return f"{finding.dimension} violation: {finding.instruction} — {finding.explanation}"


def _medium_warning(step_text: str, findings: list[ComplianceFinding]) -> None:
    """Log the medium and low findings a green candidate passed with.

    Args:
        step_text: the sentence of the gated step.
        findings: the non-blocking findings of both dimensions of the verdict.
    """
    logger.warning(
        "compliance findings passed",
        extra={
            "step_text": step_text,
            "findings": [
                f"{finding.priority} {finding.dimension}: {finding.instruction} — {finding.explanation}"
                for finding in findings
            ],
        },
    )


def _record(code: str, error: str, outcome: str, url_before: str, url_after: str) -> StepAttempt:
    """Compose one verbatim attempt record — the shape every append site of the loops shares.

    Args:
        code: the complete candidate code of the attempt.
        error: the complete failure text of the attempt; empty on no error.
        outcome: the outcome label constant of the attempt.
        url_before: the page URL read immediately before the attempt's execution.
        url_after: the page URL read immediately after the attempt's execution.

    Returns:
        The immutable record appended to the per-step attempt history.
    """
    return StepAttempt(code=code, error=error, outcome=outcome, url_before=url_before, url_after=url_after)


def _last_facts(history: list[StepAttempt]) -> tuple[str, str]:
    """Derive the terminal-failure facts from the last record of the history.

    Args:
        history: the per-step attempt history of the exhausted pool run.

    Returns:
        The code and the error of the last record; the empty pair when the
        history holds no record — no candidate ever existed.
    """
    if not history:
        return "", ""
    return history[-1].code, history[-1].error


def _verdict(classification: FailureClassification) -> FailureVerdict:
    """Build the verdict value object carried by the terminal errors.

    Args:
        classification: the classification verdict of the provider.

    Returns:
        The frozen verdict of the terminal failure.
    """
    return FailureVerdict(
        category=classification.category,
        explanation=classification.explanation,
        recommendation=classification.recommendation,
    )
