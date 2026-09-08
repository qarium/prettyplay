"""The step cycle: cache hit — execute; cache miss — generate; cached failure — heal."""

from .cache import RunBudgets, StepCache, StepIdentity, normalize_step_text
from .driver import PageFacade
from .engine import StepGenerator, StepHealer, run_step_code
from .engine.text import first_line_short
from .reporting import StepReporter


class StepExecutor:
    """The owner of the step cycle of one test.

    One step goes through the full cycle: a cache hit executes the cached
    code with no LLM involvement whatsoever; a miss delegates to the
    generator, which stores the step after the candidate has actually
    worked; a failed cached step delegates to the healer, whose verdict
    decides between a loud product defect, an incurable step, and rot
    regeneration. The scenario context — the sentences of the previous
    steps of this test — feeds every generation and healing request.

    Attributes:
        cache_key: the context key of the owning test object.
        _cache: the step cache of the test.
        _generator: the generation engine of the cycle.
        _healer: the healing engine of the cycle.
        _reporter: the visibility point of the test.
        _scenario: the sentences of the previous steps of this test.
    """

    def __init__(  # noqa: PLR0913, PLR0917 — the signature is fixed by the root cell contract
        self,
        cache_key: str,
        cache: StepCache,
        generator: StepGenerator,
        healer: StepHealer,
        budgets: RunBudgets,  # noqa: ARG002 — spent by the engine; kept for contract symmetry
        reporter: StepReporter,
    ) -> None:
        """Keep the collaborators of the step cycle and reset the scenario context.

        Args:
            cache_key: the context key of the owning test object.
            cache: the step cache of the test.
            generator: the generation engine of the cycle.
            healer: the healing engine of the cycle.
            budgets: the run-scoped attempt registry; attempts are spent
                by the engine, not by the executor.
            reporter: the visibility point of the test.
        """
        self.cache_key = cache_key
        self._cache = cache
        self._generator = generator
        self._healer = healer
        self._reporter = reporter
        self._scenario: list[str] = []  # сценерный контекст теста

    def execute(self, step_text: str, step_type: str, page: PageFacade) -> None:
        """Run one step through the full cycle.

        Args:
            step_text: the sentence of the step as written by the engineer.
            step_type: the kind of the step sentence ({action, assertion}).
            page: the live page facade of the current test.

        Raises:
            ProductDefectError: the healed step verdict says the expectation
                of the step is genuinely broken in the product.
            IncurableStepError: the step never generated successfully, or the
                verdict says regeneration cannot help.
            LlmUnavailableError: the provider service failed; no retry.
        """
        try:
            self._reporter.emit("on_step_started", {"step_text": step_text, "step_type": step_type})
            identity = StepIdentity(
                cache_key=self.cache_key,
                step_type=step_type,
                normalized_text=normalize_step_text(step_text),
            )
            cached = self._cache.load(identity)
            if cached is not None:
                try:
                    run_step_code(cached.code, page)
                except Exception as error:  # кэшированный код пал — контекст лечению
                    self._healer.heal(cached, first_line_short(error), self._scenario, page)  # вылечен = переисполнен
            else:
                self._generator.generate(identity, step_text, self._scenario, page)

            self._scenario.append(step_text)
            self._reporter.emit("on_step_passed", {"step_text": step_text, "step_type": step_type})
        except Exception as error:
            self._reporter.emit(
                "on_step_failed",
                {"step_text": step_text, "step_type": step_type, "error": first_line_short(error)},
            )
            raise
