"""The failure taxonomy of prettyplay: four distinct kinds, one library base.

Every failure the library raises derives from :class:`PrettyplayError`, so a
test suite catches any prettyplay failure with a single ``except`` clause at
its boundary. Each kind carries actionable fields instead of an opaque string.
A terminal failure renders one structured message — composed once, at
exception construction, through :func:`render_terminal_message` — and that
single render feeds the exception text, the log record and the
``on_step_failed`` hook payload; consumers never re-compose it.
"""

import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

#: The built-in path guidance rendered when a terminal failure carries no verdict.
_FALLBACK_GUIDANCE = "reword the step or refresh the cache"

#: Length of the longest verdict label — the fixed label column of the verdict block.
_VERDICT_LABEL_WIDTH = len("recommendation:")

#: The dotted-identifier class prefix of an error head — ``TimeoutError:``, ``Page.reload:``.
#: The whitespace-or-end requirement after the colon keeps ``net::ERR_…`` heads unrecognized.
_CLASS_HEAD = re.compile(r"^([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*):(?:\s+(.*))?$")

#: The fixed shape prefixes recognized in the error tail — by prefix only, never by position.
_SHAPE_PREFIXES = ("Actual value:", "Caused by:", "Call log:")


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
        category: the classification label: rot, product_defect, fixable or incurable.
        explanation: what happened on the page — one short sentence.
        recommendation: the recommended engineer action — one short sentence.
    """

    category: str
    explanation: str
    recommendation: str

    def render(self) -> str:
        """Render the verdict block of the structured terminal message.

        The explanation and recommendation values start at one column, aligned
        after the longest label; multi-line continuations indent to the same
        value column. The category is dropped — it travels in the structured
        fields of the ``on_step_verdict`` event, never in the render. An empty
        field yields no line.

        Returns:
            The rendered verdict block — one aligned line per non-empty field,
            joined with newlines; empty when both fields are empty.
        """
        width = _VERDICT_LABEL_WIDTH  # fixed regardless of which fields are present
        lines = []

        for label, value in (("explanation", self.explanation), ("recommendation", self.recommendation)):
            if not value:
                continue
            continuation = "\n" + " " * (width + 1)
            lines.append(f"{label}:".ljust(width) + " " + value.replace("\n", continuation))

        return "\n".join(lines)


class ErrorParts(BaseModel):
    """The decomposed parts of a terminal failure's underlying error.

    The data shape :func:`render_terminal_message` renders: the class prefix
    and headline of the error text plus the detail parts recognized by their
    fixed shapes (see the ``playwright`` practice). No behavior beyond the
    data shape.

    Args:
        class_name: the exception class prefix of the underlying error; empty —
            the text carries none.
        reason: the underlying error headline — the expectation of a failed
            check or the message head of a typed error.
        received: the actual-value detail; empty — absent.
        cause: the error-cause detail; empty — absent.
        call_log: the Call log block; empty — absent.
    """

    model_config = ConfigDict(kw_only=True)

    class_name: str = ""
    reason: str = ""
    received: str = ""
    cause: str = ""
    call_log: str = ""


def _consume_actual_value(lines: list[str], start: int) -> tuple[str, int]:
    """Collect the received detail starting at an ``Actual value:`` line.

    The value is the text after the prefix plus the continuation lines that
    follow — consumed while they are non-blank and not a recognized shape
    line, joined verbatim.

    Args:
        lines: the full text, split into lines.
        start: the index of the ``Actual value:`` line.

    Returns:
        The received detail and the index of the first unconsumed line.
    """
    collected = [lines[start][len("Actual value:") :].strip()]
    index = start + 1

    while index < len(lines):
        follower = lines[index]
        if follower == "" or follower.startswith(_SHAPE_PREFIXES):
            break
        collected.append(follower)
        index += 1

    return "\n".join(collected), index


def _consume_call_log(lines: list[str], start: int) -> tuple[str, int]:
    """Collect the Call log block starting at a ``Call log:`` line.

    The block is every following line that is blank or indented, kept
    verbatim with the trailing blanks trimmed; it ends at a non-indented
    non-blank line or the end of the text.

    Args:
        lines: the full text, split into lines.
        start: the index of the ``Call log:`` line.

    Returns:
        The Call log block and the index of the first unconsumed line.
    """
    block = []
    index = start + 1

    while index < len(lines):
        follower = lines[index]
        if follower != "" and not follower[0].isspace():
            break
        block.append(follower)
        index += 1

    while block and block[-1] == "":
        block.pop()

    return "\n".join(block), index


def decompose_error_text(error: str) -> ErrorParts:
    """Decompose the full underlying error text of a failed step into the render parts.

    Pure recognition of the playwright failure-message anatomy (see the
    ``playwright`` practice): the dotted-identifier class prefix of the first
    line, then — in the remainder — the detail shapes by their fixed prefixes
    only, never by position. An empty text yields all-empty parts;
    unrecognized shapes leave their parts empty. Never raises on any input.

    Args:
        error: the full underlying error text as formatted by the engine
            error-text policy; empty — all parts empty.

    Returns:
        The decomposed parts.
    """
    if error == "":
        return ErrorParts()

    lines = error.splitlines()
    class_name = ""
    reason = ""
    received = ""
    cause = ""
    call_log = ""

    head = _CLASS_HEAD.match(lines[0])
    if head:
        class_name = head[1]
        reason = head[2] or ""
    else:
        reason = lines[0]

    index = 1

    while index < len(lines):
        line = lines[index]

        if line.startswith("Actual value:"):
            received, index = _consume_actual_value(lines, index)
            continue

        if line.startswith("Caused by:"):
            cause = line[len("Caused by:") :].strip()
            index += 1
            continue

        if line.startswith("Call log:"):
            call_log, index = _consume_call_log(lines, index)
            continue

        index += 1

    return ErrorParts(class_name=class_name, reason=reason, received=received, cause=cause, call_log=call_log)


def render_terminal_message(reason: str, step_text: str, error: str, verdict: FailureVerdict | None) -> str:
    """Compose the single structured render of a terminal failure.

    The one text used by the exception message, the log record and the
    ``on_step_failed`` hook payload — consumers never re-compose it.

    Args:
        reason: the primary reason — the first line of the render; authored
            without colons.
        step_text: the sentence of the failed step; empty — no step line.
        error: the full underlying error text of the failed step code; empty —
            no error line.
        verdict: the optional :class:`FailureVerdict`; ``None`` or an empty
            render — no verdict block.

    Returns:
        The rendered message: the reason verbatim, then the ``---`` separated
        ``step:``/``error:`` block when either field is non-empty, then the
        ``---`` separated verdict block when the verdict renders non-empty.
    """
    lines = [reason]

    if step_text or error:
        lines.append("---")
        if step_text:
            lines.append(f"step: {step_text}")
        if error:
            lines.append(f"error: {error}")

    if verdict is not None:
        block = verdict.render()
        if block:
            lines += ["---", block]

    return "\n".join(lines)


class ProductDefectError(PrettyplayError, AssertionError):
    """A real functional product defect: the expectation of an assertion step did not hold.

    The signal the test suite exists for: no retry, no healing — propagates to
    the test runner as a failing test. Derives from both :class:`PrettyplayError`
    and ``AssertionError``, so any runner counts it as a failure, never an error.

    Args:
        step_text: the sentence of the failed step.
        message: what exactly was expected and what was observed — the primary reason.
        error: the full underlying error text of the failed step code; empty —
            the render carries no error line.
        verdict: the optional :class:`FailureVerdict`; ``None`` — the explicit
            absence when the LLM was unavailable, the failure never waits for it.
    """

    def __init__(
        self,
        step_text: str,
        message: str,
        error: str = "",
        verdict: FailureVerdict | None = None,
    ) -> None:
        self.step_text = step_text
        self.message = message
        self.error = error
        self.verdict = verdict

        # Exception.__init__ directly: routing through PrettyplayError.__init__
        # would overwrite the public message attribute with the full render.
        Exception.__init__(self, render_terminal_message(message, step_text, error, verdict))


class IncurableStepError(PrettyplayError):
    """An incurable step: regeneration cannot produce working code.

    Raised when the attempt budget is exhausted, the step text no longer
    matches the application reality, the intent is ambiguous, or strict mode
    forbids generation. An execution failure, not a failed check — derives
    from :class:`PrettyplayError` only, never from ``AssertionError``.

    Args:
        step_text: the sentence of the failed step.
        reason: the specific incurability cause — the primary reason.
        error: the full underlying error text of the failed step code; empty —
            the render carries no error line.
        code: the step code that terminally failed; empty — unknown. Filled by
            the raiser — the cached step code on the healing and strict failure
            paths, the last candidate code on the generation path. A field for
            programmatic consumers only: never rendered, never carried by hook
            or log payloads.
        verdict: the optional :class:`FailureVerdict` — reused from a
            classification that already happened or requested at budget
            exhaustion; ``None`` when the LLM was unavailable.
    """

    def __init__(
        self,
        step_text: str,
        reason: str,
        error: str = "",
        code: str = "",
        verdict: FailureVerdict | None = None,
    ) -> None:
        self.step_text = step_text
        self.reason = reason
        # Exception.__init__ directly (as in ProductDefectError); message keeps
        # the base-class attribute contract — the primary reason, not the render.
        self.message = reason
        self.error = error
        self.code = code
        self.verdict = verdict

        # Render-only fallback verdict: keeps the message actionable without a
        # verdict; the verdict attribute stays None — on_step_verdict never
        # fires for the fallback.
        render_verdict = verdict if verdict is not None else FailureVerdict("incurable", "", _FALLBACK_GUIDANCE)

        Exception.__init__(self, render_terminal_message(reason, step_text, error, render_verdict))

    @property
    def recommendation(self) -> str:
        """The recommended engineer action.

        Returns:
            The verdict recommendation when present, the built-in path guidance otherwise.
        """
        if self.verdict is not None:
            return self.verdict.recommendation

        return _FALLBACK_GUIDANCE


class LLMUnavailableError(PrettyplayError):
    """LLM infrastructure failure: the provider service is unreachable or rejects the request.

    Blocks only code generation and healing; cached steps keep running. No
    retries.

    Args:
        message: the failure description naming the provider.
    """

    def __init__(self, message: str) -> None:
        self.message = message

        super().__init__(message)


class ComplianceVerdictError(PrettyplayError):
    """The compliance gate could not obtain a usable verdict: the provider answer did not
    parse into findings. The successfully executed candidate stays unchecked and is never
    cached — a loud hard failure, never a silent pass.

    Args:
        message: the rendered actionable text — names the compliance gate, the
            parse failure and a fragment of the raw verdict answer.
    """

    def __init__(self, message: str) -> None:
        self.message = message

        super().__init__(message)
