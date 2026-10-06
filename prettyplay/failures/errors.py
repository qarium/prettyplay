"""The failure taxonomy of prettyplay: four distinct kinds, one library base."""

import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

#: The built-in path guidance rendered when a terminal failure carries no verdict.
_FALLBACK_GUIDANCE = "reword the step or refresh the cache"

#: The dotted-identifier class prefix of an error head — ``TimeoutError:``, ``Page.reload:``.
#: The whitespace-or-end requirement after the colon keeps ``net::ERR_…`` heads unrecognized.
_CLASS_HEAD = re.compile(r"^([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*):(?:\s+(.*))?$")

#: The fixed shape prefixes recognized in the error tail — by prefix only, never by position.
_SHAPE_PREFIXES = ("Actual value:", "Caused by:", "Call log:")


class PrettyplayError(Exception):
    """The common base of every library failure — one except clause catches them all.

    Args:
        message: the failure description.
    """

    def __init__(self, message: str) -> None:
        self.message = message

        super().__init__(message)


@dataclass(frozen=True)
class FailureVerdict:
    """The engine-built verdict of a terminal step failure, carried by the errors that stop the run.

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

        Returns:
            The rendered verdict block — one line per non-empty field at
            column zero; empty when both fields are empty. The category
            travels in the ``on_step_verdict`` event fields, never here.
        """
        lines = []

        for label, value in (("explanation", self.explanation), ("recommendation", self.recommendation)):
            if value:
                indented = value.replace("\n", "\n  ")
                lines.append(f"{label}: {indented}")

        return "\n".join(lines)


class ErrorParts(BaseModel):
    """The decomposed parts of a terminal failure's underlying error — the data shape of the single render.

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

    Args:
        lines: the full text, split into lines.
        start: the index of the ``Actual value:`` line.

    Returns:
        The received detail — the text after the prefix plus the following
        non-blank lines, verbatim — and the first unconsumed index.
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

    Args:
        lines: the full text, split into lines.
        start: the index of the ``Call log:`` line.

    Returns:
        The Call log block — the following blank or indented lines, verbatim
        — and the first unconsumed index.
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

    Args:
        error: the full underlying error text as formatted by the engine
            error-text policy; empty — all parts empty.

    Returns:
        The decomposed parts — the class prefix of the first line plus the
        detail shapes by fixed prefix, never by position; never raises.
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


def render_terminal_message(
    error_class: str,
    reason: str,
    step_text: str,
    error: str,
    verdict: FailureVerdict | None,
) -> str:
    """Compose the single structured render of a terminal failure.

    Args:
        error_class: the short class name of the terminal failure — the first
            line's prefix; ``type(self).__qualname__`` at the call site.
        reason: the primary reason — authored without colons; the first line
            after the class name.
        step_text: the sentence of the failed step; empty — no step line.
        error: the full underlying error text of the failed step code; empty —
            no error line.
        verdict: the optional :class:`FailureVerdict`; ``None`` or an empty
            render — no verdict block.

    Returns:
        The one structured render of the terminal failure — the fixed block
        order, shared by the exception text, the log record and the
        ``on_step_failed`` payload; never re-composed.
    """
    parts = decompose_error_text(error)
    lines = [f"{error_class}: {reason}" if reason else error_class]
    headline = f"{parts.class_name}: {parts.reason}" if parts.class_name else parts.reason

    if step_text or headline:
        lines.append("---")
        if step_text:
            lines.append(f"step: {step_text}")
        if headline:
            lines.append(f"error: {headline}")

    if parts.received or parts.cause or parts.call_log:
        lines.append("---")
        if parts.received:
            lines.append(f"received: {parts.received}")
        if parts.cause:
            lines.append(f"cause: {parts.cause}")
        if parts.call_log:
            lines += ["Call log:", *parts.call_log.splitlines()]

    block = verdict.render() if verdict is not None else ""

    if block:
        lines += ["---", block]

    return "\n".join(lines)


class ProductDefectError(PrettyplayError, AssertionError):
    """A real functional product defect — the assertion expectation did not hold: no retry, no healing.

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
        # The first line carries the SHORT class name of the raised type —
        # type(self).__qualname__ stays correct under subclassing.
        Exception.__init__(self, render_terminal_message(type(self).__qualname__, message, step_text, error, verdict))


class IncurableStepError(PrettyplayError):
    """An incurable step: regeneration cannot produce working code — an execution failure, never a failed check.

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
        # fires for the fallback. The first line carries the SHORT class name
        # of the raised type — type(self).__qualname__ stays correct under
        # subclassing.
        render_verdict = verdict if verdict is not None else FailureVerdict("incurable", "", _FALLBACK_GUIDANCE)

        Exception.__init__(
            self, render_terminal_message(type(self).__qualname__, reason, step_text, error, render_verdict)
        )

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
    """LLM infrastructure failure: the provider is unreachable or rejects the request — cached steps keep running.

    Args:
        message: the failure description naming the provider.
    """

    def __init__(self, message: str) -> None:
        self.message = message

        super().__init__(message)


class ComplianceVerdictError(PrettyplayError):
    """The compliance gate verdict did not parse into findings — the executed candidate stays unchecked, never cached.

    Args:
        message: the rendered actionable text — names the compliance gate, the
            parse failure and a fragment of the raw verdict answer.
    """

    def __init__(self, message: str) -> None:
        self.message = message

        super().__init__(message)
