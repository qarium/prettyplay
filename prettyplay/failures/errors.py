"""The failure taxonomy of prettyplay: three distinct kinds, one library base.

Every failure the library raises derives from :class:`PrettyplayError`, so a
test suite catches any prettyplay failure with a single ``except`` clause at
its boundary. Each kind carries actionable fields instead of an opaque string.
"""


class PrettyplayError(Exception):
    """The common base of every library failure.

    Args:
        message: the failure description.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ProductDefectError(PrettyplayError):
    """A real functional product defect: the expectation of an assertion step did not hold.

    The signal the test suite exists for: no retry, no healing — propagates to
    the test runner as a failing test.

    Args:
        step_text: the sentence of the failed step.
        message: what exactly was expected and what was observed.
    """

    def __init__(self, step_text: str, message: str) -> None:
        self.step_text = step_text
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return f"product defect on step {self.step_text!r}: {self.message}"


class IncurableStepError(PrettyplayError):
    """An incurable step: regeneration cannot produce working code.

    Raised when the attempt budget is exhausted, the step text no longer
    matches the application reality, or the intent is ambiguous.

    Args:
        step_text: the sentence of the failed step.
        reason: the specific incurability cause.
        recommendation: the recommended engineer action, e.g. reword the step.
    """

    def __init__(self, step_text: str, reason: str, recommendation: str) -> None:
        self.step_text = step_text
        self.reason = reason
        self.recommendation = recommendation
        super().__init__(reason)

    def __str__(self) -> str:
        return f"incurable step {self.step_text!r}: {self.reason} (recommendation: {self.recommendation})"


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
