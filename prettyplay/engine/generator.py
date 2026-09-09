"""Generation of working step code: LLM candidates executed against the live page in a loop."""

import logging
from datetime import date

from ..cache import CachedStep, RunBudgets, StepCache, StepIdentity
from ..config import Config
from ..driver import PageFacade
from ..failures import FailureVerdict, IncurableStepError, LlmUnavailableError, ProductDefectError
from ..llm import FailureClassification, LlmProvider
from ..reporting import StepReporter
from .classification import classify_step_failure
from .execution import run_step_code
from .text import first_line_short

logger = logging.getLogger("prettyplay")

#: System prompt of every generation request; applied verbatim by the provider.
GENERATION_PROMPT = """You generate executable Python code for one step of a web UI test.

Input you receive:
- STEP: the step sentence in a natural language
- PREVIOUS STEPS: the sentences of the previous steps of the test, in order
- PAGE SNAPSHOT: the accessibility snapshot of the current page
- SCREENSHOT: an image of the page, when attached
- PAGE API: the exact surface listing of the page facade — call nothing outside it
- CODE: the existing step code that failed (regeneration requests only)
- ERROR: the failure description of the existing code (regeneration requests only)

Output exactly one Python code block with one function of the fixed form:

def step(page) -> None:
    ...

Rules:
- The function receives exactly one argument: the page facade. Never import anything, never use other libraries
- Work only through the page API: the request carries the exact surface listing of the page facade — call nothing outside it
- For an assertion sentence end with an expectation call; for an action sentence perform the actions
- Locating by role and accessible name is preferred; by visible text next; by label for form fields
- Scroll abilities exist for scenario scrolling: bring an element into view, scroll by an amount, to the page end or start, inside a scrollable container
- No fixed delays, no sleeps, no explicit waits — the facade waits itself
- The step must complete exactly what STEP says — nothing more, nothing less
- Output only the code block, no explanations"""

#: Frozen surface listing of the driver facade — the only calls step code may make.
#: Mirrors ``prettyplay/driver/.usages/facade.md`` verbatim; the driver facade is a
#: backward-compatibility contract, so this constant changes only together with it.
#: ``close()`` stays out: it is a runtime method of PrettyTest, not of step code.
PAGE_API_SURFACE = """page.open(url)                    — navigate and wait for load
page.find_by_role(role, name)     — element by aria role and accessible name
page.find_by_label(label)         — element by associated label
page.find_by_text(text)           — element by visible text
page.aria_snapshot()              — accessibility-tree page state
page.screenshot()                 — full-page PNG bytes
page.url                          — current URL
page.scroll_to_element(element)            — bring an element into the viewport (works inside scrollable ancestors)
page.scroll_down(pixels)                   — scroll the page down by an amount
page.scroll_up(pixels)                     — scroll the page up by an amount
page.scroll_to_bottom()                    — scroll to the end of the page
page.scroll_to_top()                       — scroll to the start of the page
page.scroll_into_view(element, container)  — bring an element into view inside a specific scrollable container
page.scroll_container_down(container, pixels) — scroll a scrollable container down by an amount
page.scroll_container_up(container, pixels)   — scroll a scrollable container up by an amount
element.click()                   — click with auto-wait
element.fill(value)               — set input text
element.select_option(value)      — choose an option
element.expect_visible()          — assert visible
element.expect_text(text)         — assert text
element.expect_enabled()          — assert enabled"""


class StepGenerator:
    """Generates working step code by executing LLM candidates against the live page.

    Each attempt is one provider request: the generator snapshots the page,
    asks for code of the fixed form, and immediately executes the candidate.
    A failing candidate is retried as a regeneration request carrying the code
    and its error, until one candidate works or the attempt budget of the step
    runs out. Only a proven candidate is cached — failures are never stored.

    Attributes:
        _config: project settings; the screenshot flag feeds the requests.
        _provider: the LLM port implementation doing the requests.
        _cache: the store where working steps are saved.
        _budgets: the per-run attempt registry of the engine.
        _reporter: the visibility point for generation and cache events.
    """

    def __init__(
        self,
        config: Config,
        provider: LlmProvider,
        cache: StepCache,
        budgets: RunBudgets,
        reporter: StepReporter,
    ) -> None:
        """Keep the collaborators of the generation loop.

        Args:
            config: project settings; ``send_screenshots`` attaches page images.
            provider: the LLM port implementation.
            cache: the store of working steps.
            budgets: the per-run attempt registry.
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
    ) -> CachedStep:
        """Generate step code until a candidate works, then cache it.

        Args:
            identity: the address of the step.
            step_text: the sentence of the step.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade the candidates run against.

        Returns:
            The cached step holding the proven code.

        Raises:
            IncurableStepError: the generation attempt budget is exhausted.
            LlmUnavailableError: the provider service failed; no retry.
        """
        return self._loop(identity, step_text, previous_steps, page, "generation", None, None)

    def regenerate(  # noqa: PLR0913, PLR0917 — the signature is fixed by the engine contract
        self,
        identity: StepIdentity,
        step_text: str,
        previous_steps: list[str],
        page: PageFacade,
        existing_code: str,
        error: str,
    ) -> CachedStep:
        """Regenerate step code starting from the failed candidate.

        The loop is the generation loop; the differences are the healing budget
        pool and the failed code and error carried by the first request.

        Args:
            identity: the address of the step.
            step_text: the sentence of the step.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade the candidates run against.
            existing_code: the cached step code that failed.
            error: the failure description of the existing code.

        Returns:
            The cached step holding the proven regenerated code.

        Raises:
            IncurableStepError: the healing attempt budget is exhausted.
            LlmUnavailableError: the provider service failed; no retry.
        """
        return self._loop(identity, step_text, previous_steps, page, "healing", existing_code, error)

    def _loop(  # noqa: PLR0913, PLR0917 — the shared attempt loop with its fixed inputs
        self,
        identity: StepIdentity,
        step_text: str,
        previous_steps: list[str],
        page: PageFacade,
        pool: str,
        existing_code: str | None,
        error: str | None,
    ) -> CachedStep:
        """Run the shared attempt loop until a candidate works or the budget runs out.

        A failed check — a candidate ``AssertionError`` — stops the retries at
        once and is classified: the attempt budget is never spent on a
        legitimately failing assertion. Any other candidate failure is retried
        as a regeneration request carrying the code and its error. When the
        budget runs out, the generation pool classifies the last candidate;
        the healing pool raises without classification — the healer attaches
        the verdict it already holds, so no extra LLM request is made.

        Args:
            identity: the address of the step.
            step_text: the sentence of the step.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade the candidates run against.
            pool: the budget pool name — "generation" or "healing".
            existing_code: the failed code of the first request, if any.
            error: the failure description of the first request, if any.

        Returns:
            The cached step holding the proven code.

        Raises:
            ProductDefectError: a failed candidate check classified as a
                genuine product defect.
            IncurableStepError: the attempt budget of the step is exhausted,
                or a failure classified as incurable.
            LlmUnavailableError: the provider service failed; no retry.
        """
        attempt = 0
        code = None
        spend = self._budgets.try_generation if pool == "generation" else self._budgets.try_healing
        while True:
            if not spend(identity):
                # причина кандидата — часть контракта reason: «the specific incurability cause»
                reason = f"{pool} attempt budget exhausted"
                if error:
                    reason = f"{reason}; last failure: {error}"
                if pool == "healing":
                    raise IncurableStepError(
                        step_text,
                        reason,
                        None,  # вердикт присоединяет healer — без второго LLM-запроса
                    )
                if error is None:
                    raise IncurableStepError(
                        step_text,
                        reason,
                        None,  # классифицировать нечего: ни одного кандидата не было
                    )
                raise IncurableStepError(step_text, reason, self._classify(step_text, code, error, page))
            attempt += 1
            self._reporter.emit("on_generation_started", {"step_text": step_text, "attempt": attempt})

            snapshot = page.aria_snapshot()
            screenshot = page.screenshot() if self._config.send_screenshots else None
            code = self._provider.generate_step_code(
                prompt=GENERATION_PROMPT,
                step_text=step_text,
                previous_steps=previous_steps,
                snapshot=snapshot,
                screenshot=screenshot,
                page_api=PAGE_API_SURFACE,
                existing_code=existing_code,
                error=error,
            )
            try:
                run_step_code(code, page)
            except AssertionError as check_failure:
                # провалённая проверка: попытки не тратятся — классифицируем и останавливаемся
                reason = f"candidate check failed: {first_line_short(check_failure)}"
                verdict = self._classify_quietly(step_text, code, reason, page)
                if verdict is not None and verdict.category == "product_defect":
                    raise ProductDefectError(step_text, first_line_short(check_failure), verdict) from None
                raise IncurableStepError(step_text, reason, verdict) from None
            except Exception as candidate_error:  # прочий сбой кандидата лечится повтором
                existing_code = code
                error = first_line_short(candidate_error)
            else:
                break

        step = CachedStep(
            identity=identity,
            code=code,
            created_at=date.today().isoformat(),  # noqa: DTZ011 — календарная дата создания шага
        )
        self._cache.save(step)
        return step

    def _classify(self, step_text: str, code: str | None, error: str, page: PageFacade) -> FailureVerdict:
        """Classify a failure through the shared routine and build the verdict.

        Args:
            step_text: the sentence of the failed step.
            code: the code of the last candidate.
            error: the failure description of the candidate.
            page: the live page facade of the test.

        Returns:
            The verdict of the classification.

        Raises:
            LlmUnavailableError: the provider service failed during the
                classification request.
        """
        classification = classify_step_failure(self._config, self._provider, step_text, code, error, page)
        return _verdict(classification)

    def _classify_quietly(
        self,
        step_text: str,
        code: str | None,
        error: str,
        page: PageFacade,
    ) -> FailureVerdict | None:
        """Classify with the quiet skip: an unavailable LLM yields no verdict, not a failure.

        Args:
            step_text: the sentence of the failed step.
            code: the code of the failed candidate.
            error: the failure description of the candidate.
            page: the live page facade of the test.

        Returns:
            The verdict of the classification, or ``None`` when the LLM was
            unavailable — the failure never waits for the verdict.
        """
        try:
            return self._classify(step_text, code, error, page)
        except LlmUnavailableError:
            logger.warning("verdict skipped: llm unavailable")
            return None


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
