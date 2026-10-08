"""The render point: step templates become prepared instructions with capture declarations."""

import re
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
        inputs: The call-local input bindings of this step; empty — none.
        declarations: The reached capture-tag names, in execution order; empty — no memory writes.
    """

    model_config = ConfigDict(kw_only=True, frozen=True)

    instruction: str = ""
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
    undefined values, the ``{% var %}`` capture extension — and renders it with
    the memory snapshot and the inputs namespace. All authoring errors raise
    ``PrettyplayError`` naming the problem and the offending name, before any
    browser execution.

    Args:
        text: The raw step sentence as written by the engineer — the template source.
        step_type: The step kind — action or assertion.
        memory: The test memory; the render reads its snapshot and never mutates it.
        vars: The call-local string inputs; None — none.

    Returns:
        The render product of the sentence.

    Raises:
        PrettyplayError: The template is malformed, a capture name is invalid or
            duplicated, a value is unavailable, or an assertion declares captures.
    """
    snapshot = memory.snapshot()
    inputs = {} if vars is None else dict(vars)

    environment = Environment(autoescape=False, undefined=StrictUndefined, extensions=[VarExtension])
    extension = next(ext for ext in environment.extensions.values() if isinstance(ext, VarExtension))

    try:
        template = environment.from_string(text)
    except TemplateSyntaxError as error:
        raise PrettyplayError(f"the step template is malformed: {error.message} (line {error.lineno})") from error

    try:
        instruction = template.render(snapshot, vars=inputs)
    except UndefinedError as error:
        name = _unavailable_name(error, inputs)

        raise PrettyplayError(f"the step template references an unavailable name: {name}") from error

    declarations = list(extension.declarations)

    if step_type == "assertion" and declarations:
        names = ", ".join(declarations)

        raise PrettyplayError(f"a step expectation cannot declare result captures: {names}")

    return PreparedStep(instruction=instruction, inputs=inputs, declarations=declarations)
