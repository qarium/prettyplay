"""The render point: step templates become prepared instructions with capture declarations."""

import re
import secrets
from typing import ClassVar

from jinja2 import Environment, StrictUndefined, UndefinedError, nodes
from jinja2.exceptions import TemplateSyntaxError
from jinja2.ext import Extension
from jinja2.parser import Parser
from pydantic import BaseModel, ConfigDict

from ...failures import PrettyplayError
from .memory import StepMemory

#: The Jinja error text of an attribute miss on the inputs namespace — ``'dict object' has
#: no attribute 'x'``. The vars namespace is the only plain-dict root of the render context,
#: so a miss names the qualified ``vars.x`` form.
_ATTRIBUTE_MISS = re.compile(r"^'dict object' has no attribute '([^']+)'$")


class PreparedStep(BaseModel):
    """The render product of one step sentence — what the agent cycle works with after preparation.

    Args:
        instruction: The prepared plain-text instruction with actual values embedded.
        addressing_text: The addressing text — the same rendered sentence with the
            reached capture tags kept verbatim; what the caller builds the cache
            identity from.
        inputs: The call-local input bindings of this step; empty — none.
        declarations: The reached capture-tag names, in execution order; empty — no memory writes.
    """

    model_config = ConfigDict(kw_only=True, frozen=True)

    instruction: str = ""
    addressing_text: str = ""
    inputs: dict[str, str] = {}
    declarations: list[str] = []

    @property
    def has_declarations(self) -> bool:
        """Report whether the step declared any result captures.

        Returns:
            Whether at least one capture tag was reached during rendering.
        """
        return bool(self.declarations)


class VarExtension(Extension):
    """The ``{% var name %}`` capture-declaration tag of step templates.

    A reached tag records its name into the per-render declaration list of the
    extension instance and renders to empty text — it declares a result slot,
    it supplies no value. One instance lives in one environment, and one
    environment serves one render, so the declaration list is per-render.
    """

    tags: ClassVar[set[str]] = {"var"}

    def __init__(self, environment: Environment) -> None:
        """Construct the extension with an empty per-render declaration list.

        Args:
            environment: The Jinja environment this extension is registered in.
        """
        super().__init__(environment)

        self.declarations: list[str] = []

    def parse(self, parser: Parser) -> nodes.Output:
        """Parse one capture tag into an output node that records its name when reached.

        Args:
            parser: The active Jinja parser positioned at the ``var`` tag token.

        Returns:
            The output node rendering to empty text and recording the capture name.

        Raises:
            PrettyplayError: The token after ``var`` is not a single Jinja identifier.
        """
        tag_token = parser.stream.expect("name:var")
        name_token = next(parser.stream)

        if name_token.type != "name":
            raise PrettyplayError(
                f"the var capture tag expects a single Jinja identifier name, got {name_token.value!r}"
            )

        call = self.call_method("_record", [nodes.Const(name_token.value)], lineno=tag_token.lineno)

        return nodes.Output([call]).set_lineno(tag_token.lineno)  # type: ignore[return-value]

    def _record(self, name: str) -> str:
        """Record one reached capture name and render to empty text.

        Args:
            name: The capture name reached during rendering.

        Returns:
            The empty text the tag renders to.

        Raises:
            PrettyplayError: The name is the reserved ``vars`` namespace or is already recorded.
        """
        if name == "vars":
            raise PrettyplayError("the capture name 'vars' is reserved for the call inputs namespace")

        if name in self.declarations:
            raise PrettyplayError(f"the capture name {name!r} is declared twice in one step")

        self.declarations.append(name)

        return ""


#: The tag grammar of the source scan — tag begins with the optional whitespace-control
#: characters Jinja accepts (``-``, ``+``, ``~``), the block and variable ends, the
#: ``{% var name %}`` shape, and one leading identifier. Jinja validates names.
_TAG_BEGIN = re.compile(r"\{[{%#][-+~]?")
_VAR_TAG = re.compile(r"\{%[-+~]?\s*var\s+([^\s%}]+)\s*[-+~]?%\}")
_BLOCK_END = re.compile(r"[-+~]?%\}")
_VARIABLE_END = re.compile(r"[-+~]?\}\}")
_RAW_BLOCK_END = re.compile(r"\s*[-+~]?%\}")
_RAW_END = re.compile(r"\{%[-+~]?\s*endraw(?![A-Za-z0-9_])")
_LEADING_IDENTIFIER = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)")


def _string_end(source: str, start: int) -> int:
    """Find the index just past the closing quote of the string literal at ``start``.

    Args:
        source: The template source being scanned.
        start: The index of the opening quote.

    Returns:
        The index just past the matching closing quote — the source length when
        the string is unterminated.
    """
    quote = source[start]
    cursor = start + 1

    while cursor < len(source):
        if source[cursor] == quote:
            backslashes = 0
            escaped = cursor - 1

            while escaped > start and source[escaped] == "\\":
                backslashes += 1
                escaped -= 1

            if backslashes % 2 == 0:
                return cursor + 1

        cursor += 1

    return cursor


def _skip_quoted(source: str, position: int, end: re.Pattern[str]) -> int:
    """Find the end of one tag, stepping over the quoted strings inside it.

    Args:
        source: The template source being scanned.
        position: The first index after the tag-begin marker.
        end: The tag-end pattern — ``%}``- or ``}}``-shaped.

    Returns:
        The index just past the tag end — the source length when the tag never ends.
    """
    cursor = position

    while cursor < len(source):
        character = source[cursor]

        if character in {"'", '"'}:
            cursor = _string_end(source, cursor)

            continue

        match = end.match(source, cursor)

        if match is not None:
            return match.end()

        cursor += 1

    return cursor


def _var_tag_spans(source: str) -> list[str]:
    """Collect the exact source spans of every ``{% var ... %}`` tag, in parse order.

    The scan mirrors the Jinja lexer closely enough to agree with what the parser
    reaches: quoted strings inside tags never end a tag, ``{% raw %}`` contents and
    ``{# ... #}`` comments are data, and only blocks of the exact ``var``-tag shape
    the capture extension parses are collected — in source order, which is the
    parse order of the single-pass parser.

    Args:
        source: The raw step sentence — the template source, verbatim.

    Returns:
        The verbatim tag spans, one per ``{% var ... %}`` tag of the source.
    """
    spans: list[str] = []
    position = 0

    while (begin := _TAG_BEGIN.search(source, position)) is not None:
        cursor = begin.end()

        if begin.group(0)[1] == "#":
            comment_end = source.find("#}", cursor)
            position = len(source) if comment_end < 0 else comment_end + 2
            continue

        if begin.group(0)[1] == "{":
            position = _skip_quoted(source, cursor, _VARIABLE_END)
            continue

        tag = _VAR_TAG.match(source, begin.start())

        if tag is not None:
            spans.append(tag.group(0))
            position = tag.end()
            continue

        word = _LEADING_IDENTIFIER.match(source, cursor)

        if word is None:
            break

        if word.group(1) == "raw":
            raw_end = _RAW_END.search(source, word.end())

            if raw_end is None:
                break

            closing = _RAW_BLOCK_END.match(source, raw_end.end())

            if closing is None:
                break

            position = closing.end()
            continue

        position = _skip_quoted(source, word.end(), _BLOCK_END)

    return spans


def _new_marker(occurrence: int) -> str:
    """Build one unique opaque marker standing for a reached capture occurrence.

    Args:
        occurrence: The zero-based index of the reached capture within this render.

    Returns:
        A fresh marker string — unique and unpredictable inside one render.
    """
    return f"capture {occurrence} {secrets.token_hex(8)}"


class _MarkedVarExtension(VarExtension):
    """The capture extension of the addressing render — a reached tag emits a unique marker.

    A reached ``{% var name %}`` runs the reserved/duplicate checks and the
    declaration recording of the base extension, then returns a unique opaque
    marker instead of the empty text: the single render output carries one marker
    per reached occurrence, and the post-render pass removes the markers for the
    instruction and replaces them with their recorded tag source spans for the
    addressing text. One instance lives in one environment, and one environment
    serves one render, so the span queue and the marker map are per-render.
    """

    def __init__(self, environment: Environment) -> None:
        """Construct the extension with an empty span queue and marker map.

        Args:
            environment: The Jinja environment this extension is registered in.
        """
        super().__init__(environment)

        self.spans: list[str] = []
        self.markers: dict[str, str] = {}

    def parse(self, parser: Parser) -> nodes.Output:
        """Parse one capture tag into an output node carrying its exact source span.

        Args:
            parser: The active Jinja parser positioned at the ``var`` tag token.

        Returns:
            The output node emitting the occurrence marker and recording the
            capture name and the tag source span when reached.

        Raises:
            PrettyplayError: The token after ``var`` is not a single Jinja identifier.
        """
        tag_token = parser.stream.expect("name:var")
        name_token = next(parser.stream)

        if name_token.type != "name":
            raise PrettyplayError(
                f"the var capture tag expects a single Jinja identifier name, got {name_token.value!r}"
            )

        span = self.spans.pop(0) if self.spans else ""

        call = self.call_method("_record", [nodes.Const(name_token.value), nodes.Const(span)], lineno=tag_token.lineno)

        return nodes.Output([call]).set_lineno(tag_token.lineno)  # type: ignore[return-value]

    def _record(self, name: str, span: str) -> str:
        """Record one reached capture occurrence and emit its unique marker.

        Args:
            name: The capture name reached during rendering.
            span: The verbatim source span of this tag, bound at parse time.

        Returns:
            The marker standing for this reached occurrence in the render output.

        Raises:
            PrettyplayError: The name is the reserved ``vars`` namespace or is already recorded.
        """
        super()._record(name)

        marker = _new_marker(len(self.markers))
        self.markers[marker] = span

        return marker


def _restore_tag_sources(output: str, markers: dict[str, str]) -> tuple[str, str]:
    """Derive the instruction and the addressing text from one marker-carrying output.

    Args:
        output: The single rendered text with one marker per reached capture tag.
        markers: The per-render map of emitted markers to their tag source spans.

    Returns:
        The instruction — the markers removed, the clean sentence for LLM
        requests — and the addressing text — the markers replaced by their
        tag source spans, the ready layer every event and log record carries
        and the cache identity addresses by.

    Raises:
        PrettyplayError: A marker appears in the output more than once, or its tag
            source span was not recovered — the two texts would disagree.
    """
    instruction = output
    addressing_text = output

    for marker, span in markers.items():
        occurrences = output.count(marker)

        if occurrences != 1 or not span:
            raise PrettyplayError(
                f"the step render could not restore a capture tag source: "
                f"its marker appeared {occurrences} times in the output"
            )

        instruction = instruction.replace(marker, "")
        addressing_text = addressing_text.replace(marker, span)

    return instruction, addressing_text


def _unavailable_name(error: UndefinedError, inputs: dict[str, str]) -> str:
    """Name the unavailable value of one render failure.

    Args:
        error: The undefined-value error raised by the render.
        inputs: The call-local input bindings of the render.

    Returns:
        The unavailable name — the qualified ``vars.x`` form for a miss on the
        inputs namespace, the Jinja diagnostic text otherwise.
    """
    match = _ATTRIBUTE_MISS.match(str(error))

    if match and match.group(1) not in inputs:
        return f"'vars.{match.group(1)}' is undefined"

    return str(error)


def render_step(text: str, step_type: str, memory: StepMemory, vars: dict[str, str] | None) -> PreparedStep:
    """Render one step sentence from a snapshot of memory and call inputs into a prepared step.

    Compiles the sentence through a fresh Jinja environment — plain text, strict
    undefined values, the ``{% var %}`` capture extension — and renders it exactly
    once with the memory snapshot and the inputs namespace: both texts of the
    product come from that one evaluation, so they observe the same values and
    the same branch decisions. All authoring errors raise ``PrettyplayError``
    naming the problem and the offending name, before any browser execution.

    Args:
        text: The raw step sentence as written by the engineer — the template source.
        step_type: The step kind — action or assertion.
        memory: The test memory; the render reads its snapshot and never mutates it.
        vars: The call-local string inputs; None — none.

    Returns:
        The render product of the sentence — the instruction and the addressing
        text of one render.

    Raises:
        PrettyplayError: The template is malformed, a capture name is invalid or
            duplicated, a value is unavailable, an assertion declares captures, or
            the rendered output collided with a capture marker.
    """
    snapshot = memory.snapshot()
    inputs = {} if vars is None else dict(vars)

    environment = Environment(autoescape=False, undefined=StrictUndefined, extensions=[_MarkedVarExtension])
    extension = next(ext for ext in environment.extensions.values() if isinstance(ext, _MarkedVarExtension))
    extension.spans = _var_tag_spans(text)

    try:
        template = environment.from_string(text)
    except TemplateSyntaxError as error:
        raise PrettyplayError(f"the step template is malformed: {error.message} (line {error.lineno})") from error

    try:
        output = template.render(snapshot, vars=inputs)
    except UndefinedError as error:
        name = _unavailable_name(error, inputs)

        raise PrettyplayError(f"the step template references an unavailable name: {name}") from error
    except PrettyplayError:
        raise
    except Exception as error:
        raise PrettyplayError(f"the step template {text!r} failed to evaluate: {error}") from error

    instruction, addressing_text = _restore_tag_sources(output, extension.markers)

    declarations = list(extension.declarations)

    if step_type == "assertion" and declarations:
        names = ", ".join(declarations)

        raise PrettyplayError(f"a step expectation cannot declare result captures: {names}")

    return PreparedStep(
        instruction=instruction, addressing_text=addressing_text, inputs=inputs, declarations=declarations
    )
