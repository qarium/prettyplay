"""The failure taxonomy of prettyplay: three distinct kinds, one library base.

Every failure the library raises derives from :class:`PrettyplayError`, so a
test suite catches any prettyplay failure with a single ``except`` clause at
its boundary. Each kind carries actionable fields instead of an opaque string.
The rendered message of a terminal failure starts with its primary reason;
the verdict render is appended, never interleaved.
"""

from dataclasses import dataclass


class PrettyplayError(Exception):
    """The common base of every library failure.

    Args:
        message: the failure description.
    """

    def __init__(self, message: str) -> None:
        self.message = message

        super().__init__(message)


@dataclass(frozen=True)
class FailureVerdict:
    """The verdict of a terminal step failure, carried by the errors that stop the run.

    Built by the engines from a :class:`~prettyplay.llm.FailureClassification`;
    the failure types never request it themselves. A plain frozen value object,
    not a pydantic model — the source classification already validated the data,
    and failure paths stay cheap.

    Args:
        category: the classification label: rot, product_defect or incurable.
        explanation: what happened on the page — one short sentence.
        recommendation: the recommended engineer action — one short sentence.
    """

    category: str
    explanation: str
    recommendation: str

    def render(self) -> str:
        """Render the verdict as stable labelled lines.

        The single render used by the exception message tail, the hook event
        payload content and the log record; the labels are stable lowercase
        words integrators parse. An empty field yields no line.

        Returns:
            The rendered verdict — one line per non-empty field, joined with newlines.
        """
        fields = (
            ("category", self.category),
            ("explanation", self.explanation),
            ("recommendation", self.recommendation),
        )

        return "\n".join(f"{label}: {value}" for label, value in fields if value)


class ProductDefectError(PrettyplayError, AssertionError):
    """A real functional product defect: the expectation of an assertion step did not hold.

    The signal the test suite exists for: no retry, no healing — propagates to
    the test runner as a failing test. Derives from both :class:`PrettyplayError`
    and ``AssertionError``, so any runner counts it as a failure, never an error.

    Args:
        step_text: the sentence of the failed step.
        message: what exactly was expected and what was observed — the primary reason.
        verdict: the optional :class:`FailureVerdict`; ``None`` — the explicit
            absence when the LLM was unavailable, the failure never waits for it.
    """

    def __init__(self, step_text: str, message: str, verdict: FailureVerdict | None = None) -> None:
        self.step_text = step_text
        self.message = message
        self.verdict = verdict

        PrettyplayError.__init__(self, message)

    def __str__(self) -> str:
        if self.verdict is None:
            return self.message

        return self.message + "\n" + self.verdict.render()


class IncurableStepError(PrettyplayError):
    """An incurable step: regeneration cannot produce working code.

    Raised when the attempt budget is exhausted, the step text no longer
    matches the application reality, or the intent is ambiguous. An execution
    failure, not a failed check — derives from :class:`PrettyplayError` only,
    never from ``AssertionError``.

    Args:
        step_text: the sentence of the failed step.
        reason: the specific incurability cause — the primary reason.
        verdict: the optional :class:`FailureVerdict` — reused from a
            classification that already happened or requested at budget
            exhaustion; ``None`` when the LLM was unavailable.
    """

    def __init__(self, step_text: str, reason: str, verdict: FailureVerdict | None = None) -> None:
        self.step_text = step_text
        self.reason = reason
        self.verdict = verdict

        super().__init__(reason)

    @property
    def recommendation(self) -> str:
        """The recommended engineer action.

        Returns:
            The verdict recommendation when present, the built-in path guidance otherwise.
        """
        if self.verdict is not None:
            return self.verdict.recommendation

        return "reword the step or refresh the cache"

    def __str__(self) -> str:
        if self.verdict is not None:
            return self.reason + "\n" + self.verdict.render()

        return self.reason + "\nrecommendation: reword the step or refresh the cache"


class LlmUnavailableError(PrettyplayError):
    """LLM infrastructure failure: the provider service is unreachable or rejects the request.

    Blocks only code generation and healing; cached steps keep running. No
    retries.

    Args:
        message: the failure description naming the provider.
    """

    def __init__(self, message: str) -> None:
        self.message = message

        super().__init__(message)
