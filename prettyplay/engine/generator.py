"""Generation of working step code: LLM candidates executed against the live page under the settle window."""

import logging
from datetime import date

from ..cache import CachedStep, RunBudgets, StepCache, StepIdentity
from ..config import Config
from ..driver import PageFacade
from ..failures import FailureVerdict, IncurableStepError, LLMUnavailableError, ProductDefectError
from ..llm import ComplianceFinding, FailureClassification, LLMProvider, ScenarioStep
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
from .renderer import PreparedStep, StepMemory, validate_step_result
from .text import format_step_error

logger = logging.getLogger("prettyplay")

#: System prompt of every generation and regeneration request; applied verbatim by the provider.
#: Frozen mirror of ``.goga/usages/prompts/step_generation.md`` (the section after the ``---``
#: separator) — the single source of the prompt; the constant changes only together with the file.
SYSTEM_PROMPT = """You generate executable Python code for one step of a web UI test.

Input you receive:
- STEP TYPE: action or assertion — the kind of the step
- STEP: the prepared instruction of the step — the plain-text sentence with actual values embedded
- INPUTS: the call input bindings, one name = value line each — present when the step carries inputs
- RESULTS: the declared result names — present when the step declares captures; the code must return a dictionary of exactly these names to non-blank strings observed on the page
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

- without RESULTS: def step(page) -> None: ...
- with RESULTS: def step(page) -> dict[str, str] | None: ... — return the dictionary of exactly the declared names to values actually read from the current page

Rules:
- The function receives exactly one argument: the page — the genuine Playwright sync Page; the whole step runs inside the driver worker thread
- Import from playwright.sync_api and the Python standard library only — no third-party
  libraries; imports are global only: at the top level of the code block, before `def
  step`, never inside the function body
- Work through the standard Playwright sync API: locator factories, actions, waits, expect chains, plain asserts on immediate reads — everything standard is allowed; the CHEAT SHEET is guidance, never a boundary
- Assertions: for an assertion sentence end with a check — a waiting expect(...) chain for dynamic content, or an immediate read with a plain Python assert (assert locator.count() > 1)
- When the request carries a RESULTS block: read every declared value from the current page — never fabricate, never reuse values from HISTORY; return all declared names in one dictionary; every value is a non-blank string; a missing observation fails the step rather than fabricating a value
- No fixed delays, no sleeps, no wait_for_timeout — locators and expect chains auto-wait
- The runtime owns the page lifecycle: never call page.close() or context.close()
- No stateful actions that outlive the step on the page shared by the whole test: page.route, page.clock, add_init_script, tracing, HAR, CDP — excluded from generated code; a cached step would poison every later step far from the cause
- Dialogs: capture with the stock means — with page.expect_event("dialog") as info: — perform the triggering action inside the block, read info.value.type, info.value.message, info.value.default_value, then info.value.accept() or info.value.dismiss()
- Popups and new tabs: capture with with page.expect_popup() as popup_info: — trigger the opening action inside the block, work through popup_info.value; page.bring_to_front() raises a page above the others
- Content inside an iframe goes through page.frame_locator(selector) — locate elements within the returned scope; nested frames chain
- Scrolling: locator.scroll_into_view_if_needed() and page.mouse.wheel(dx, dy) are the standard means
- The page state may already include the effects of prior attempts or manual intervention — the HISTORY records and their URL before -> after lines show what already happened. Regeneration after failed attempts never rides the leftover state of those attempts: an action step repeats its action through the page even when the page looks done. A first attempt — no HISTORY — works on the page the previous steps produced: the PAGE URL line and the snapshot show where they landed
- An action step performs its action and ends there — no trailing check that confirms the action's own completion; the following steps of the test carry their own expectations
- An assertion step only observes the current page — never navigate, click, type or fill; passive observation such as scroll_into_view_if_needed() stays allowed
- RECOMMENDATION and USER GUIDANCE carry the diagnosis and the engineer's intent — follow them when they conflict with your first instinct
- USER INSTRUCTIONS are binding for everything below the safety core of these Rules: follow them when configured; silently ignoring an instruction is a violation
- The safety core of these Rules always outranks the instructions: the fixed function form, the import rule, the lifecycle rule, the stateful-action exclusions, no fixed delays. An instruction conflicting with a Rule or demanding a stateful action is unfollowable: never implement it silently — raise in the step code with the message "instruction conflicts with rule Y" naming the conflict, so the failure surfaces loudly
- Prefer-type instructions are conditional by their own wording: follow them when the page offers the option — best-effort with a graceful fallback is compliance
- The step must complete exactly what STEP says — nothing more, nothing less
- Output only the code block, no explanations"""

#: The compact standard Playwright sync API reference of every generation request;
#: guidance, not an allowlist — everything standard stays allowed.
#: Frozen mirror of ``.goga/usages/prompts/step_cheatsheet.md`` — the whole file, verbatim
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

    items = page.get_by_role("listitem")
    assert items.count() > 1

An exact count: `expect(items).to_have_count(3)`. One check per meaning — a visibility expect
plus a count assert on the same locator verifies one fact twice.

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
    """Generates working step code by executing LLM candidates against the live page; only proven candidates are cached.

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
        prepared: PreparedStep,
        step_type: str,
        previous_steps: list[ScenarioStep],
        group_prompt: str | None,
        page: PageFacade,
        attempt_history: list[StepAttempt],
        window: SettleWindow,
        memory: StepMemory,
    ) -> CachedStep:
        """Generate step code until a candidate works, then cache it.

        Args:
            identity: the address of the step.
            prepared: the render product of the step — instruction, input
                bindings, result declarations; every request renders the
                instruction with its INPUTS and RESULTS blocks; declarations
                present — the candidate code must return the result
                dictionary of exactly the declared names.
            step_type: action or assertion — carried into every request.
            previous_steps: the typed scenario records of the previous steps
                of the test, in execution order — each the prepared
                instruction plus its permanent group membership.
            group_prompt: the group prompt of the current step's group;
                None — an ordinary step: every path stays byte-identical to
                today, the same requests, the same classification points,
                the same bounded healing; non-empty — a group step: every
                request carries the group framing and the internal
                classification points are suppressed — the calling executor
                routes the unclassified failures to the group recovery.
            page: the live page facade the candidates run against.
            attempt_history: the per-step attempt history created by the
                executor — this loop appends a record after every attempt
                that does not produce a cached step.
            window: the settle window of the current step execution — every
                candidate execution absorbs transient failures inside it.
            memory: the test memory — the accepted candidate's validated
                captures publish here after validation and the gate; a
                failed or gate-blocked attempt publishes nothing.

        Returns:
            The cached step holding the proven code.

        Raises:
            ProductDefectError: a failed candidate check classified as a
                genuine product defect — by the entry or the final
                classification; never raised for a group step inside this
                loop.
            IncurableStepError: a check, result-contract violation or budget
                outcome classified incurable, or the healing funding
                refused; the code field carries the failed step code; a
                group step raises the unclassified variant at its failed
                check and its budget exhaustion — the group recovery
                decides.
            LLMUnavailableError: the provider service failed after the
                bounded transport retries; no engine retry.
            ComplianceVerdictError: the compliance verdict of a green
                candidate did not parse; nothing is cached.
        """
        return self._generation_loop(
            identity, prepared, step_type, previous_steps, group_prompt, page, attempt_history, window, memory
        )

    def regenerate(  # noqa: PLR0913, PLR0917 — the signature is fixed by the engine contract
        self,
        identity: StepIdentity,
        prepared: PreparedStep,
        step_type: str,
        previous_steps: list[ScenarioStep],
        group_prompt: str | None,
        page: PageFacade,
        attempt_history: list[StepAttempt],
        recommendation: str,
        window: SettleWindow,
        memory: StepMemory,
    ) -> CachedStep:
        """Regenerate step code starting from the anchored history and the diagnosis.

        Args:
            identity: the address of the step.
            prepared: the render product of the row or healed step — carried
                into every request with its INPUTS and RESULTS blocks;
                passed by the calling path: the healer threads the
                executor's product, the recovery re-renders the row step
                against the current context.
            step_type: action or assertion — carried into every request.
            previous_steps: the typed scenario records of the previous steps
                of the test, in execution order.
            group_prompt: the group prompt of the row step's group — the
                recovery row passes it; non-empty — the request carries the
                group framing; None — an ordinary regeneration.
            page: the live page facade the candidates run against.
            attempt_history: the anchored per-step attempt history — record 0
                carries the original cached code composed by the caller; this
                loop appends after every attempt that does not produce a
                cached step; the original is never lost to a re-binding.
            recommendation: the diagnosis of the classification that launched
                the healing; rendered into every request — the entry
                classification guards the anti-masking, no per-attempt
                classification happens inside the loop.
            window: the settle window of the current step execution.
            memory: the test memory — publication at the acceptance point,
                as in generate.

        Returns:
            The cached step holding the proven regenerated code.

        Raises:
            IncurableStepError: the healing attempt budget is exhausted; the
                verdict stays None — the calling healer attaches its entry
                verdict — and the code field carries the last record's code.
            LLMUnavailableError: the provider service failed after the
                bounded transport retries; no engine retry.
            ComplianceVerdictError: the compliance verdict of a green
                candidate did not parse; nothing is cached.
        """
        return self._healing_loop(
            identity,
            prepared,
            step_type,
            previous_steps,
            group_prompt,
            page,
            attempt_history,
            recommendation,
            window,
            memory,
        )

    def _generation_loop(  # noqa: PLR0913, PLR0917 — the shared attempt loop with its fixed inputs
        self,
        identity: StepIdentity,
        prepared: PreparedStep,
        step_type: str,
        previous_steps: list[ScenarioStep],
        group_prompt: str | None,
        page: PageFacade,
        history: list[StepAttempt],
        window: SettleWindow,
        memory: StepMemory,
    ) -> CachedStep:
        """Run the generation pool loop until a candidate works or the budget runs out.

        Args:
            identity: the address of the step.
            prepared: the render product of the step — instruction, input
                bindings, result declarations.
            step_type: action or assertion — carried into every request.
            previous_steps: the typed scenario records of the previous steps
                of the test, in execution order.
            group_prompt: the group prompt of the current step's group;
                None — an ordinary step, the ordinary paths byte-identical;
                non-empty — a group step, the classification points
                suppressed.
            page: the live page facade the candidates run against.
            history: the per-step attempt history this loop grows — every
                attempt that does not produce a cached step appends its
                record; the green attempt never records.
            window: the settle window of the current step execution.
            memory: the test memory — the accepted candidate's validated
                captures publish after validation and the gate.

        Returns:
            The cached step holding the proven code.

        Raises:
            ProductDefectError: a failed candidate check classified as a
                genuine product defect.
            IncurableStepError: the generation attempt budget is exhausted,
                or a failure classified incurable.
            LLMUnavailableError: the provider service failed after the
                bounded transport retries; no engine retry.
            ComplianceVerdictError: the compliance verdict of a green
                candidate did not parse; nothing is cached.
        """
        attempt = 0  # every LLM request of this pool run — loop attempts and funded regenerations
        standing: ComplianceFinding | None = None  # the high finding the retries still carry

        while True:
            if not self._budgets.try_generation(identity):
                return self._exhaustion_outcome(
                    identity,
                    prepared,
                    step_type,
                    previous_steps,
                    group_prompt,
                    page,
                    history,
                    window,
                    memory,
                    attempt,
                    standing,
                )

            attempt += 1
            self._emit_generation_started(prepared.instruction, attempt)

            code = self._request(prepared, step_type, previous_steps, group_prompt, page, history, recommendation=None)

            url_before = _read_url(page)
            try:
                result = settle(run_step_code, code, page, window)
            except AssertionError as check_failure:
                # failed check survived the window — the decision table, never blind retries
                url_after = _read_url(page)
                # full text, no prefix — the type is the semantics
                history.append(
                    _record(code, format_step_error(check_failure), OUTCOME_FAILED_CHECK, url_before, url_after)
                )
                return self._failed_check_outcome(
                    identity,
                    prepared,
                    step_type,
                    previous_steps,
                    group_prompt,
                    page,
                    history,
                    code,
                    format_step_error(check_failure),
                    window,
                    memory,
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
                captures, violation = _validated_captures(prepared, result)

                if violation is not None:  # the result contract failed — the identical failed-check channel
                    history.append(_record(code, violation, OUTCOME_FAILED_CHECK, url_before, url_after))
                    return self._failed_check_outcome(
                        identity,
                        prepared,
                        step_type,
                        previous_steps,
                        group_prompt,
                        page,
                        history,
                        code,
                        violation,
                        window,
                        memory,
                        attempt,
                    )

                # the gate sits outside every exception-swallowing try: its hard failures propagate
                findings = check_step_compliance(self._config, self._provider, prepared, step_type, code, history)
                high = _high_finding(findings)
                if high is not None:  # the attempt failed on the violation — retry targeted at it
                    history.append(
                        _record(code, _violation_text(high), OUTCOME_COMPLIANCE_BLOCKED, url_before, url_after)
                    )
                    standing = high
                    continue
                if findings:
                    _medium_warning(prepared.instruction, findings)

                memory.publish(captures)  # publication exactly once — after validation and the gate
                return self._store(identity, code)

    def _healing_loop(  # noqa: PLR0913, PLR0917 — the shared attempt loop with its fixed inputs
        self,
        identity: StepIdentity,
        prepared: PreparedStep,
        step_type: str,
        previous_steps: list[ScenarioStep],
        group_prompt: str | None,
        page: PageFacade,
        history: list[StepAttempt],
        recommendation: str,
        window: SettleWindow,
        memory: StepMemory,
    ) -> CachedStep:
        """Run the healing pool loop until a candidate works or the budget runs out.

        Args:
            identity: the address of the step.
            prepared: the render product of the row or healed step —
                instruction, input bindings, result declarations.
            step_type: action or assertion — carried into every request.
            previous_steps: the typed scenario records of the previous steps
                of the test, in execution order.
            group_prompt: the group prompt of the row step's group — the
                recovery row passes it; non-empty — the request carries the
                framing; None — an ordinary regeneration.
            page: the live page facade the candidates run against.
            history: the anchored per-step attempt history — record 0 stays
                untouched at index 0; every failed attempt, a failed check
                included, appends its record and retries.
            recommendation: the diagnosis of the classification that launched
                the healing; rendered into every request.
            window: the settle window of the current step execution.
            memory: the test memory — the accepted candidate's validated
                captures publish after validation and the gate.

        Returns:
            The cached step holding the proven code.

        Raises:
            IncurableStepError: the healing attempt budget is exhausted; no
                classification inside the loop — the calling healer attaches
                the verdict it already holds.
            LLMUnavailableError: the provider service failed after the
                bounded transport retries; no engine retry.
            ComplianceVerdictError: the compliance verdict of a green
                candidate did not parse; nothing is cached.
        """
        attempt = 0

        while True:
            if not self._budgets.try_healing(identity):
                # colon-free authored reason; the last record carries the terminal-failure facts
                code, error = _last_facts(history)
                raise IncurableStepError(prepared.instruction, "healing attempt budget exhausted", error, code=code)

            attempt += 1
            self._emit_generation_started(prepared.instruction, attempt)

            code = self._request(prepared, step_type, previous_steps, group_prompt, page, history, recommendation)

            url_before = _read_url(page)
            try:
                result = settle(run_step_code, code, page, window)
            except AssertionError as check_failure:  # failed checks included — the entry classification guards
                url_after = _read_url(page)
                history.append(
                    _record(code, format_step_error(check_failure), OUTCOME_FAILED_CHECK, url_before, url_after)
                )
                continue
            except Exception as candidate_error:
                url_after = _read_url(page)
                history.append(
                    _record(code, format_step_error(candidate_error), OUTCOME_EXECUTION_FAILED, url_before, url_after)
                )
                continue
            url_after = _read_url(page)

            captures, violation = _validated_captures(prepared, result)

            if violation is not None:  # a result-contract violation is a failed attempt like any other
                history.append(_record(code, violation, OUTCOME_FAILED_CHECK, url_before, url_after))
                continue

            # the gate sits outside every exception-swallowing try: its hard failures propagate
            findings = check_step_compliance(self._config, self._provider, prepared, step_type, code, history)
            high = _high_finding(findings)
            if high is not None:  # the attempt failed on the violation — retry targeted at it
                history.append(_record(code, _violation_text(high), OUTCOME_COMPLIANCE_BLOCKED, url_before, url_after))
                continue
            if findings:
                _medium_warning(prepared.instruction, findings)

            memory.publish(captures)  # publication exactly once — after validation and the gate
            return self._store(identity, code)

    def _failed_check_outcome(  # noqa: PLR0913, PLR0917 — the decision table of one failed candidate check
        self,
        identity: StepIdentity,
        prepared: PreparedStep,
        step_type: str,
        previous_steps: list[ScenarioStep],
        group_prompt: str | None,
        page: PageFacade,
        history: list[StepAttempt],
        code: str,
        error_field: str,
        window: SettleWindow,
        memory: StepMemory,
        attempt: int,
    ) -> CachedStep:
        """Decide the bounded-healing outcome of a failed candidate check.

        Args:
            identity: the address of the step — the healing funding key.
            prepared: the render product of the failed step.
            step_type: action or assertion — carried into the funded request.
            previous_steps: the typed scenario records of the previous steps
                of the test, in execution order.
            group_prompt: the group prompt of the current step's group;
                non-empty — the suppressed-classification group raise;
                None — the ordinary decision table.
            page: the live page facade of the test.
            history: the per-step attempt history — the failed check's
                record already appended; the funded request carries it grown.
            code: the code of the failed candidate.
            error_field: the full failure text of the failed check — a page
                assertion or the deterministic result-contract violation.
            window: the settle window of the current step execution.
            memory: the test memory — the funded regeneration publishes at
                its own acceptance point.
            attempt: the number of LLM requests the pool run made so far.

        Returns:
            The healed step when the funded regeneration worked.

        Raises:
            ProductDefectError: the entry or final verdict says product defect.
            IncurableStepError: the verdict says incurable, the healing
                funding is refused, or the repeat failure stays terminal —
                one final classification decides the terminal kind only; a
                group step raises the unclassified variant — the group
                recovery decides.
        """
        if group_prompt:
            # a group step suppresses the classification and the funded regeneration — the
            # group recovery decides; colon-free authored reason, no verdict attached
            raise IncurableStepError(
                prepared.instruction,
                "group step check failed — the group recovery decides",
                error_field,
                code=code,
            ) from None

        reason = f"candidate check failed — {_first_line(error_field)}"
        verdict = self._classify(prepared.instruction, code, error_field, page)
        if verdict is None:  # quiet skip — the failed check itself is the primary signal
            raise IncurableStepError(prepared.instruction, reason, error_field, code=code) from None
        if verdict.category == "product_defect":
            raise ProductDefectError(prepared.instruction, verdict.explanation, error_field, verdict) from None
        if verdict.category == "incurable":
            raise IncurableStepError(prepared.instruction, reason, error_field, code=code, verdict=verdict) from None

        # rot | fixable — exactly one healing-funded regeneration
        if not self._budgets.try_healing(identity):
            raise IncurableStepError(
                prepared.instruction, "healing attempt budget exhausted", error_field, code=code, verdict=verdict
            ) from None

        healed, failed_code, failure_text, repeat_was_check = self._funded_regeneration(
            identity,
            prepared,
            step_type,
            previous_steps,
            page,
            history,
            verdict.recommendation,
            window,
            memory,
            attempt,
        )
        if healed is not None:
            return healed

        # repeat failure — one final classification deciding the terminal kind only
        final = self._classify(prepared.instruction, failed_code, failure_text, page)
        if final is not None and final.category == "product_defect":
            raise ProductDefectError(prepared.instruction, final.explanation, failure_text, final) from None
        if repeat_was_check:
            # an assertion repeat names the failed check
            repeat_reason = f"candidate check failed — {_first_line(failure_text)}"
        else:
            # a compliance block or a failed execution is a candidate failure, quiet skip or
            # not — the violation text carries colons; the first-line contract forbids them
            repeat_reason = f"candidate failed — {_reason_safe(failure_text)}"
        raise IncurableStepError(
            prepared.instruction, repeat_reason, failure_text, code=failed_code, verdict=final
        ) from None

    def _exhaustion_outcome(  # noqa: PLR0913, PLR0917 — the decision table of the refused generation pool
        self,
        identity: StepIdentity,
        prepared: PreparedStep,
        step_type: str,
        previous_steps: list[ScenarioStep],
        group_prompt: str | None,
        page: PageFacade,
        history: list[StepAttempt],
        window: SettleWindow,
        memory: StepMemory,
        attempt: int,
        standing: ComplianceFinding | None,
    ) -> CachedStep:
        """Decide the outcome of a refused generation attempt.

        Args:
            identity: the address of the step — the healing funding key.
            prepared: the render product of the failed step.
            step_type: action or assertion — carried into the funded request.
            previous_steps: the typed scenario records of the previous steps
                of the test, in execution order.
            group_prompt: the group prompt of the current step's group;
                non-empty — the suppressed-classification group raise;
                None — the ordinary exhaustion table.
            page: the live page facade of the test.
            history: the per-step attempt history of the pool run — its last
                record carries the last candidate's facts; empty — no
                candidate ever existed.
            window: the settle window of the current step execution.
            memory: the test memory — the funded regeneration publishes at
                its own acceptance point.
            attempt: the number of LLM requests the pool run made so far.
            standing: the high compliance finding the last retries carried;
                None — the exhaustion is not a standing violation.

        Returns:
            The healed step when the funded regeneration worked.

        Raises:
            ProductDefectError: the verdict says product defect.
            IncurableStepError: the generation attempt budget is exhausted —
                the finding named when a high one stands, the verdict says
                incurable, or the healing funding is refused; a repeat
                failure is terminal without reclassification; a group step
                raises the unclassified variant — the group recovery decides.
        """
        if group_prompt:
            # a group step suppresses the exhaustion classification and the funded regeneration —
            # the group recovery decides; the last record carries the terminal-failure facts
            code, error = _last_facts(history)
            raise IncurableStepError(
                prepared.instruction,
                "group step generation budget exhausted — the group recovery decides",
                error,
                code=code,
            ) from None

        if standing is not None:
            # the verdict is built from the finding — no classification, no regrant of a funded attempt
            verdict = FailureVerdict(
                category="incurable",
                explanation=f"{standing.instruction} — {standing.explanation}",
                recommendation=f"satisfy the finding in the step code: {standing.instruction}",
            )
            raise IncurableStepError(
                prepared.instruction,
                f"generation attempt budget exhausted — {_reason_safe(standing.instruction)}",
                _violation_text(standing),
                code=_last_facts(history)[0],
                verdict=verdict,
            ) from None

        reason = "generation attempt budget exhausted"
        if not history:
            raise IncurableStepError(prepared.instruction, reason, "", code="") from None  # nothing to classify

        code, error = _last_facts(history)  # the last failed attempt's record carries the facts
        verdict = self._classify(prepared.instruction, code, error, page)
        if verdict is None:  # quiet skip — the budget failure is the primary signal
            raise IncurableStepError(prepared.instruction, reason, error, code=code) from None
        if verdict.category == "product_defect":
            raise ProductDefectError(prepared.instruction, verdict.explanation, error, verdict) from None
        if verdict.category == "incurable":
            raise IncurableStepError(prepared.instruction, reason, error, code=code, verdict=verdict) from None

        # rot | fixable — one extra healing-funded regeneration
        if not self._budgets.try_healing(identity):
            raise IncurableStepError(
                prepared.instruction, "healing attempt budget exhausted", error, code=code, verdict=verdict
            ) from None

        healed, failed_code, failure_text, _repeat_was_check = self._funded_regeneration(
            identity,
            prepared,
            step_type,
            previous_steps,
            page,
            history,
            verdict.recommendation,
            window,
            memory,
            attempt,
        )
        if healed is not None:
            return healed

        # repeat failure — terminal, no reclassification; the verdict of the entry classification travels
        raise IncurableStepError(
            prepared.instruction, reason, failure_text, code=failed_code, verdict=verdict
        ) from None

    def _funded_regeneration(  # noqa: PLR0913, PLR0917 — the single healing-funded request of the bounded healing
        self,
        identity: StepIdentity,
        prepared: PreparedStep,
        step_type: str,
        previous_steps: list[ScenarioStep],
        page: PageFacade,
        history: list[StepAttempt],
        recommendation: str,
        window: SettleWindow,
        memory: StepMemory,
        attempt: int,
    ) -> tuple[CachedStep | None, str, str, bool]:
        """Run the one healing-funded regeneration request of the bounded healing.

        Args:
            identity: the address of the step — the identity of the stored step.
            prepared: the render product of the failed step.
            step_type: action or assertion — carried into the request.
            previous_steps: the typed scenario records of the previous steps
                of the test, in execution order.
            page: the live page facade the candidate runs against.
            history: the per-step attempt history — the request carries it
                grown; the funded attempt's own failure appends its record.
            recommendation: the classification diagnosis carried by the request.
            window: the settle window of the current step execution — shared
                with the loop, the same step execution.
            memory: the test memory — the funded acceptance publishes its
                validated captures like any acceptance.
            attempt: the number of LLM requests the pool run made so far.

        Returns:
            The stored healed step with empty failure facts on success; None
            with the failed code, the formatted failure text and whether the
            failure was a failed check. A single inline request — never the
            retrying regenerate loop; a high compliance finding counts as a
            candidate failure, never a check; a result-contract violation is
            a check.

        Raises:
            LLMUnavailableError: the provider request failed after the
                bounded transport retries; no engine retry, no final
                classification.
            ComplianceVerdictError: the compliance verdict of a green funded
                candidate did not parse; nothing is cached.
        """
        attempt += 1
        self._emit_generation_started(prepared.instruction, attempt)

        # the funded path only runs for an ordinary step — the group branches raise before it
        code = self._request(prepared, step_type, previous_steps, None, page, history, recommendation)
        url_before = _read_url(page)
        try:
            result = settle(run_step_code, code, page, window)
        except AssertionError as check_failure:
            url_after = _read_url(page)
            history.append(_record(code, format_step_error(check_failure), OUTCOME_FAILED_CHECK, url_before, url_after))
            return None, code, format_step_error(check_failure), True
        except Exception as failure:
            url_after = _read_url(page)
            history.append(_record(code, format_step_error(failure), OUTCOME_EXECUTION_FAILED, url_before, url_after))
            return None, code, format_step_error(failure), False
        url_after = _read_url(page)

        captures, violation = _validated_captures(prepared, result)

        if violation is not None:  # the result contract failed — a failed check like a page assertion
            history.append(_record(code, violation, OUTCOME_FAILED_CHECK, url_before, url_after))
            return None, code, violation, True

        # the gate sits outside the settle try: its hard failures propagate
        findings = check_step_compliance(self._config, self._provider, prepared, step_type, code, history)
        high = _high_finding(findings)
        if high is not None:  # a compliance block is a candidate failure, not a check
            history.append(_record(code, _violation_text(high), OUTCOME_COMPLIANCE_BLOCKED, url_before, url_after))
            return None, code, _violation_text(high), False
        if findings:
            _medium_warning(prepared.instruction, findings)

        memory.publish(captures)  # publication exactly once — after validation and the gate
        return self._store(identity, code), code, "", False

    def _request(  # noqa: PLR0913, PLR0917 — the fixed request inputs of the port signature
        self,
        prepared: PreparedStep,
        step_type: str,
        previous_steps: list[ScenarioStep],
        group_prompt: str | None,
        page: PageFacade,
        history: list[StepAttempt],
        recommendation: str | None,
    ) -> str:
        """Collect the request inputs and ask the provider for one candidate.

        Args:
            prepared: the render product of the step — the instruction with
                its INPUTS and RESULTS blocks; the raw template sentence
                never reaches the request.
            step_type: action or assertion — carried into every request.
            previous_steps: the typed scenario records of the previous steps
                of the test, in execution order — the provider renders the
                PREVIOUS STEPS block from them, the group entries marked.
            group_prompt: the group prompt of the current step's group;
                non-empty — the provider renders the GROUP PROMPT block
                immediately before PREVIOUS STEPS; None — no block, the
                ordinary request byte-identical to today.
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
            instruction=prepared.instruction,
            step_type=step_type,
            previous_steps=previous_steps,
            group_prompt=group_prompt,
            inputs=prepared.inputs,
            declarations=prepared.declarations,
            snapshot=snapshot,
            page_url=_read_url(page),  # the guarded read — an empty string renders no PAGE URL line
            screenshot=screenshot,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[record.render() for record in history],
            recommendation=recommendation,
            guidance=None,  # steering-only input — the engine never carries guidance
        )

    def _emit_generation_started(self, step_text: str, attempt: int) -> None:
        """Report the start of one LLM attempt — once per provider request, never per settle re-execution.

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

        Args:
            step_text: the sentence of the failed step.
            code: the code of the last candidate.
            error: the failure description of the candidate.
            page: the live page facade of the test.

        Returns:
            The verdict of the classification, or ``None`` when the LLM was
            unavailable — the quiet skip logs a WARNING; an already-decided
            failure never waits for the LLM.
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


def _validated_captures(prepared: PreparedStep, result: object) -> tuple[dict[str, str], str | None]:
    """Validate the settled result of a green candidate against the render product.

    Args:
        prepared: the render product of the step — the declaration set the
            returned result must satisfy.
        result: the step function's return, passed through by the run
            primitive and the settle window.

    Returns:
        The validated captures with no violation; an empty captures with the
        formatted deterministic violation text when the result contract
        failed — the violation joins the failed-check channel of the loops.
    """
    try:
        return validate_step_result(prepared, result), None
    except AssertionError as violation:
        return {}, format_step_error(violation)


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
