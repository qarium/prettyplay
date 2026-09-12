"""Generation of working step code: LLM candidates executed against the live page under the settle window."""

import logging
from datetime import date

from ..cache import CachedStep, RunBudgets, StepCache, StepIdentity
from ..config import Config
from ..driver import PageFacade
from ..failures import FailureVerdict, IncurableStepError, LLMUnavailableError, ProductDefectError
from ..llm import FailureClassification, LLMProvider
from ..reporting import StepReporter
from .classification import classify_step_failure
from .execution import run_step_code
from .polling import SettleWindow, settle
from .text import format_step_error

logger = logging.getLogger("prettyplay")

#: System prompt of every generation and regeneration request; applied verbatim by the provider.
#: Frozen mirror of ``.goga/usages/prompts/generation.md`` (the section after the ``---``
#: separator) — the single source of the prompt; the constant changes only together with the file.
SYSTEM_PROMPT = """You generate executable Python code for one step of a web UI test.

Input you receive:
- STEP: the step sentence in a natural language
- PREVIOUS STEPS: the sentences of the previous steps of the test, in order
- PAGE SNAPSHOT: the accessibility snapshot of the current page
- SCREENSHOT: an image of the page, when attached
- PAGE API: the exact surface listing of the page facade — call nothing outside it
- USER INSTRUCTIONS: the project's code style guidance, when configured
- CODE: the existing step code that failed (regeneration requests only)
- ERROR: the failure description of the existing code (regeneration requests only)
- RECOMMENDATION: the diagnosis of the classification that preceded this regeneration, when present
- USER GUIDANCE: the engineer guidance message of the interactive steering, when present
- HISTORY: the accumulated steering turns, when present

Output exactly one Python code block with one function of the fixed form:

def step(page) -> None:
    ...

Rules:
- The function receives exactly one argument: the page facade — the Playwright-mirroring page API. Never import anything, never use other libraries
- Work only through the page API: the request carries the exact surface listing of the page facade — call nothing outside it
- For an assertion sentence end with an expectation call; for an action sentence perform the actions
- Locating by role and accessible name is preferred; by visible text next; by label or placeholder for form fields
- get_by_test_id and locator(selector) exist for elements without accessible names — the accessibility-first priority stands unless USER INSTRUCTIONS say otherwise
- Dialogs: when the step verifies or steers a dialog, capture it — with page.expect_dialog() as dialog: — perform the triggering action inside the block, read dialog.message and dialog.type, then dialog.accept() or dialog.dismiss()
- Popups and new tabs: capture the opened page — with page.expect_popup() as popup: — trigger the opening action inside the block, work through the popup facade; bring_to_front() raises a page above the others
- Content inside an iframe goes through page.frame_locator(selector) — locate elements within the returned frame
- Scroll abilities exist for scenario scrolling: bring an element into view, scroll by an amount, to the page end or start, inside a scrollable container
- No fixed delays, no sleeps, no explicit waits — the facade waits itself
- RECOMMENDATION and USER GUIDANCE carry the diagnosis and the engineer's intent — follow them when they conflict with your first instinct
- The step must complete exactly what STEP says — nothing more, nothing less
- Output only the code block, no explanations"""

#: Frozen surface listing of the driver facade — the only calls step code may make.
#: Mirrors ``prettyplay/driver/.usages/facade.md`` verbatim; the driver facade is a
#: parity contract of the Playwright sync API, so this constant changes only
#: together with it. ``page.close()`` stays out: it is a runtime method of
#: PrettyPlay, not of step code.
PAGE_API_SURFACE = """page.goto(url)                                — navigate and wait for the load state
page.go_back()                                — browser-history back
page.go_forward()                             — browser-history forward
page.reload()                                 — reload and wait for the load state
page.wait_for_url(url)                        — wait until the URL matches a glob pattern
page.wait_for_load_state(state)               — wait for load, domcontentloaded or networkidle
page.expect_url(url)                          — assert the URL matches a glob pattern
page.expect_title(title)                      — assert the title contains
page.get_by_role(role, name)                  — element by aria role and accessible name
page.get_by_label(label)                      — element by associated label
page.get_by_text(text)                        — element by visible text
page.get_by_placeholder(placeholder)          — input by placeholder text
page.get_by_alt_text(alt)                     — image by alt text
page.get_by_title(title)                      — element by title attribute
page.get_by_test_id(test_id)                  — element by data-testid
page.locator(selector)                        — element by any selector — CSS, XPath, attribute
page.expect_dialog()                          — context manager — the block performs the triggering action; yields the DialogFacade
page.expect_popup()                           — context manager — the block performs the opening action; yields the popup as a full PageFacade
page.bring_to_front()                         — raise this page above the others — the switching primitive
page.pages                                    — the open pages of the context, each a full PageFacade
page.frame_locator(selector)                  — the locating scope of one iframe — yields a FrameFacade
page.aria_snapshot()                          — accessibility-tree page state
page.screenshot()                             — full-page PNG bytes
page.url                                      — current URL
page.scroll_to_element(element)               — bring an element into the viewport (works inside scrollable ancestors)
page.scroll_down(pixels)                      — scroll the page down by an amount
page.scroll_up(pixels)                        — scroll the page up by an amount
page.scroll_to_bottom()                       — scroll to the end of the page
page.scroll_to_top()                          — scroll to the start of the page
page.scroll_into_view(element, container)     — bring an element into view inside a specific scrollable container
page.scroll_container_down(container, pixels) — scroll a scrollable container down by an amount
page.scroll_container_up(container, pixels)   — scroll a scrollable container up by an amount
dialog.accept(prompt_text) — accept; prompt_text answers a prompt dialog (empty — no answer)
dialog.dismiss()           — dismiss
dialog.type                — alert, confirm, prompt or beforeunload
dialog.message             — the dialog message
dialog.default_value       — the prompt prefill of a prompt dialog
frame.get_by_role(role, name) — and the whole get_by_* family — locate inside the iframe
frame.locator(selector)                                       — any selector inside the iframe
frame.frame_locator(selector)                                 — the scope of a nested iframe
element.click(button)                 — click; empty button = left, "right" = right button
element.dblclick()                    — double click
element.fill(value)                   — set input text
element.clear()                       — clear the input
element.press(key)                    — press a key or combination, e.g. "Enter", "Control+A"
element.check()                       — check a checkbox or radio
element.uncheck()                     — uncheck
element.hover()                       — hover
element.select_option(value)          — choose an option
element.drag_to(target)               — drag onto another element
element.set_input_files(path)         — upload one file by filesystem path
element.expect_visible()              — assert visible
element.expect_hidden()               — assert hidden
element.expect_text(text)             — assert text contains (substring, whitespace-normalized)
element.expect_enabled()              — assert enabled
element.expect_value(value)           — assert the input value
element.expect_checked()              — assert the checkbox/radio state
element.expect_count(count)           — assert the matched element count
element.expect_attribute(name, value) — assert the attribute value"""


class StepGenerator:
    """Generates working step code by executing LLM candidates against the live page.

    Each attempt is one provider request: the generator snapshots the page,
    asks for code of the fixed form, and immediately executes the candidate
    under the settle window of the current step execution — transient
    page-state failures re-execute inside the window before any costly move.
    A failed check no longer burns the whole budget: the classification
    decides, and a rot or fixable verdict grants exactly one healing-funded
    regeneration carrying the recommendation (also at budget exhaustion). Any
    other candidate failure is retried as a regeneration request carrying the
    code and its error, until one candidate works or the attempt budget of
    the step runs out. Only a proven candidate is cached — failures are never
    stored.

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

    def generate(
        self,
        identity: StepIdentity,
        step_text: str,
        previous_steps: list[str],
        page: PageFacade,
        window: SettleWindow,
    ) -> CachedStep:
        """Generate step code until a candidate works, then cache it.

        Args:
            identity: the address of the step.
            step_text: the sentence of the step.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade the candidates run against.
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
        """
        return self._generation_loop(identity, step_text, previous_steps, page, window)

    def regenerate(  # noqa: PLR0913, PLR0917 — the signature is fixed by the engine contract
        self,
        identity: StepIdentity,
        step_text: str,
        previous_steps: list[str],
        page: PageFacade,
        existing_code: str,
        error: str,
        recommendation: str,
        window: SettleWindow,
    ) -> CachedStep:
        """Regenerate step code starting from the failed code and its diagnosis.

        The loop is the generation loop with three differences: attempts draw
        from the healing budget pool, every request carries the failed code,
        its error and the classification recommendation, and every failed
        attempt — a failed check included — takes the retry branch: the entry
        classification already guards the anti-masking, so no per-attempt
        classification happens inside the loop.

        Args:
            identity: the address of the step.
            step_text: the sentence of the step.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade the candidates run against.
            existing_code: the cached step code that failed.
            error: the failure description of the existing code.
            recommendation: the diagnosis of the classification that launched
                the healing; rendered into every request.
            window: the settle window of the current step execution.

        Returns:
            The cached step holding the proven regenerated code.

        Raises:
            IncurableStepError: the healing attempt budget is exhausted; the
                verdict stays None — the calling healer attaches its entry
                verdict — and the code field carries the last candidate.
            LLMUnavailableError: the provider service failed; no retry.
        """
        return self._healing_loop(identity, step_text, previous_steps, page, existing_code, error, recommendation, window)

    def _generation_loop(
        self,
        identity: StepIdentity,
        step_text: str,
        previous_steps: list[str],
        page: PageFacade,
        window: SettleWindow,
    ) -> CachedStep:
        """Run the generation pool loop until a candidate works or the budget runs out.

        A failed check — a candidate ``AssertionError`` that survived the
        settle window — goes through the bounded-healing decision table: the
        classification decides between a terminal kind and exactly one
        healing-funded regeneration carrying the recommendation. Any other
        candidate failure is retried as a regeneration request carrying the
        code and its error. Budget exhaustion classifies the last candidate
        and follows the same table — the rot and fixable verdicts grant one
        extra funded regeneration there too.

        Args:
            identity: the address of the step.
            step_text: the sentence of the step.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade the candidates run against.
            window: the settle window of the current step execution.

        Returns:
            The cached step holding the proven code.

        Raises:
            ProductDefectError: a failed candidate check classified as a
                genuine product defect.
            IncurableStepError: the generation attempt budget is exhausted,
                or a failure classified incurable.
            LLMUnavailableError: the provider service failed; no retry.
        """
        attempt: list[int] = [0]  # every LLM request of this pool run — loop attempts and funded regenerations
        existing_code: str | None = None
        error: str | None = None
        code = ""

        while True:
            if not self._budgets.try_generation(identity):
                return self._exhaustion_outcome(identity, step_text, previous_steps, page, code, error, window, attempt)

            attempt[0] += 1
            self._emit_generation_started(step_text, attempt[0])

            code = self._request(step_text, previous_steps, page, existing_code, error, recommendation=None)

            try:
                settle(run_step_code, code, page, window)
            except AssertionError as check_failure:
                # failed check survived the window — the decision table, never blind retries
                error_field = str(check_failure)  # full text, no prefix — the type is the semantics
                return self._failed_check_outcome(
                    identity, step_text, previous_steps, page, code, error_field, window, attempt
                )
            except Exception as candidate_error:  # other candidate failures heal via retry
                existing_code = code
                error = format_step_error(candidate_error)
            else:
                return self._store(identity, code)

    def _healing_loop(  # noqa: PLR0913, PLR0917 — the shared attempt loop with its fixed inputs
        self,
        identity: StepIdentity,
        step_text: str,
        previous_steps: list[str],
        page: PageFacade,
        existing_code: str,
        error: str,
        recommendation: str,
        window: SettleWindow,
    ) -> CachedStep:
        """Run the healing pool loop until a candidate works or the budget runs out.

        Every failed attempt — a failed check included — takes the retry
        branch with the fresh failure description and snapshot while attempts
        remain: the entry classification already guards the anti-masking, so
        no per-attempt classification happens inside the loop. Exhaustion
        raises without a classification — the calling healer attaches the
        verdict it already holds.

        Args:
            identity: the address of the step.
            step_text: the sentence of the step.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade the candidates run against.
            existing_code: the cached step code that failed.
            error: the failure description of the existing code.
            recommendation: the diagnosis of the classification that launched
                the healing; rendered into every request.
            window: the settle window of the current step execution.

        Returns:
            The cached step holding the proven code.

        Raises:
            IncurableStepError: the healing attempt budget is exhausted.
            LLMUnavailableError: the provider service failed; no retry.
        """
        attempt = 0
        code = existing_code

        while True:
            if not self._budgets.try_healing(identity):
                # colon-free authored reason; the last candidate failure travels in the error field
                raise IncurableStepError(step_text, "healing attempt budget exhausted", error, code=code)

            attempt += 1
            self._emit_generation_started(step_text, attempt)

            code = self._request(step_text, previous_steps, page, existing_code, error, recommendation)

            try:
                settle(run_step_code, code, page, window)
            except Exception as candidate_error:  # failed checks included — the entry classification guards
                existing_code = code
                error = format_step_error(candidate_error)
            else:
                return self._store(identity, code)

    def _failed_check_outcome(  # noqa: PLR0913, PLR0917 — the decision table of one failed candidate check
        self,
        identity: StepIdentity,
        step_text: str,
        previous_steps: list[str],
        page: PageFacade,
        code: str,
        error_field: str,
        window: SettleWindow,
        attempt: list[int],
    ) -> CachedStep:
        """Decide the bounded-healing outcome of a failed candidate check.

        The uniform decision table: product_defect raises at once, incurable
        raises carrying the verdict, and rot or fixable grants exactly one
        healing-funded regeneration carrying the recommendation — a refused
        funding is terminal, and a repeat failure gets one final
        classification that decides only the terminal kind, never another
        regeneration.

        Args:
            identity: the address of the step — the healing funding key.
            step_text: the sentence of the failed step.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade of the test.
            code: the code of the failed candidate.
            error_field: the full failure text of the failed check.
            window: the settle window of the current step execution.
            attempt: the shared LLM attempt counter of the pool run.

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
            identity, step_text, previous_steps, page, code, error_field, verdict.recommendation, window, attempt
        )
        if healed is not None:
            return healed

        # repeat failure — one final classification deciding the terminal kind only
        final = self._classify(step_text, failed_code, failure_text, page)
        if final is not None and final.category == "product_defect":
            raise ProductDefectError(step_text, final.explanation, failure_text, final) from None
        if final is None or repeat_was_check:
            # quiet skip keeps the contract wording; an assertion repeat names the failed check
            repeat_reason = f"candidate check failed — {_first_line(failure_text)}"
        else:
            repeat_reason = f"candidate failed — {_first_line(failure_text)}"
        raise IncurableStepError(step_text, repeat_reason, failure_text, code=failed_code, verdict=final) from None

    def _exhaustion_outcome(  # noqa: PLR0913, PLR0917 — the decision table of the refused generation pool
        self,
        identity: StepIdentity,
        step_text: str,
        previous_steps: list[str],
        page: PageFacade,
        code: str,
        error: str | None,
        window: SettleWindow,
        attempt: list[int],
    ) -> CachedStep:
        """Decide the outcome of a refused generation attempt.

        No candidate ever existed — the plain budget failure with an empty
        error. Otherwise the last candidate is classified and follows the
        decision table: the rot and fixable verdicts grant one extra
        healing-funded regeneration carrying the recommendation; a repeat
        failure is terminal without reclassification, carrying the verdict of
        the entry classification.

        Args:
            identity: the address of the step — the healing funding key.
            step_text: the sentence of the failed step.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade of the test.
            code: the code of the last candidate.
            error: the failure description of the last candidate; None — no
                candidate ever existed.
            window: the settle window of the current step execution.
            attempt: the shared LLM attempt counter of the pool run.

        Returns:
            The healed step when the funded regeneration worked.

        Raises:
            ProductDefectError: the verdict says product defect.
            IncurableStepError: the generation attempt budget is exhausted,
                the verdict says incurable, or the healing funding is
                refused — the code field carries the failed step code.
        """
        reason = "generation attempt budget exhausted"
        if error is None:
            raise IncurableStepError(step_text, reason, "", code="") from None  # nothing to classify

        verdict = self._classify(step_text, code, error, page)
        if verdict is None:  # quiet skip — the budget failure is the primary signal
            raise IncurableStepError(step_text, reason, error, code=code) from None
        if verdict.category == "product_defect":
            raise ProductDefectError(step_text, verdict.explanation, error, verdict) from None
        if verdict.category == "incurable":
            raise IncurableStepError(step_text, reason, error, code=code, verdict=verdict) from None

        # rot | fixable — one extra healing-funded regeneration
        if not self._budgets.try_healing(identity):
            raise IncurableStepError(step_text, "healing attempt budget exhausted", error, code=code, verdict=verdict) from None

        healed, failed_code, failure_text, _repeat_was_check = self._funded_regeneration(
            identity, step_text, previous_steps, page, code, error, verdict.recommendation, window, attempt
        )
        if healed is not None:
            return healed

        # repeat failure — terminal, no reclassification; the verdict of the entry classification travels
        raise IncurableStepError(step_text, reason, failure_text, code=failed_code, verdict=verdict) from None

    def _funded_regeneration(  # noqa: PLR0913, PLR0917 — the single healing-funded request of the bounded healing
        self,
        identity: StepIdentity,
        step_text: str,
        previous_steps: list[str],
        page: PageFacade,
        existing_code: str,
        error: str,
        recommendation: str,
        window: SettleWindow,
        attempt: list[int],
    ) -> tuple[CachedStep | None, str, str, bool]:
        """Run the one healing-funded regeneration request of the bounded healing.

        A single inline request — never a call to the retrying regenerate
        loop. It is an LLM attempt: the shared counter increments and
        ``on_generation_started`` fires. A provider failure propagates
        immediately — no retry, no final classification; only the execution
        of the funded candidate can fail softly, yielding the failed code and
        its formatted error for the caller's terminal handling.

        Args:
            identity: the address of the step — the identity of the stored step.
            step_text: the sentence of the step.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade the candidate runs against.
            existing_code: the code of the failed candidate.
            error: the failure description of the failed candidate.
            recommendation: the classification diagnosis carried by the request.
            window: the settle window of the current step execution — shared
                with the loop, the same step execution.
            attempt: the shared LLM attempt counter of the pool run.

        Returns:
            The stored healed step with empty failure facts on success; None
            with the failed code, the formatted failure text and whether the
            failure was a failed check on a failed execution.

        Raises:
            LLMUnavailableError: the provider request failed; no retry, no
                final classification.
        """
        attempt[0] += 1
        self._emit_generation_started(step_text, attempt[0])

        code = self._request(step_text, previous_steps, page, existing_code, error, recommendation)
        try:
            settle(run_step_code, code, page, window)
        except AssertionError as check_failure:
            return None, code, str(check_failure), True
        except Exception as failure:
            return None, code, format_step_error(failure), False

        return self._store(identity, code), code, "", False

    def _request(  # noqa: PLR0913, PLR0917 — the fixed request inputs of the port signature
        self,
        step_text: str,
        previous_steps: list[str],
        page: PageFacade,
        existing_code: str | None,
        error: str | None,
        recommendation: str | None,
    ) -> str:
        """Collect the request inputs and ask the provider for one candidate.

        Args:
            step_text: the sentence of the step.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade of the test.
            existing_code: the failed code of the request, if any.
            error: the failure description of the request, if any.
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
            previous_steps=previous_steps,
            snapshot=snapshot,
            screenshot=screenshot,
            page_api=PAGE_API_SURFACE,
            existing_code=existing_code,
            error=error,
            recommendation=recommendation,
            guidance=None,  # steering-only input — the engine never carries guidance
            guidance_history=[],
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
