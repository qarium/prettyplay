"""The verbatim trace record of a group step: the unit the GROUP STEPS block renders."""

from pydantic import BaseModel, ConfigDict

from ...cache import StepIdentity


class GroupStepOutcome(BaseModel):
    """One verbatim trace record of a group step's execution — never rewritten or truncated.

    Attributes:
        sentence: the raw sentence of the group step, verbatim.
        step_type: the step kind: action or assertion.
        tries: the declared retry count of the step; None — the step is
            governed by the global polling settings.
        delay: the declared start pause of the step in seconds; None — no
            pause.
        outcome: the execution outcome: passed or failed.
        url_before: the page URL read immediately before the step's
            execution.
        url_after: the page URL read immediately after the step's execution.
        identity: the cache address of the step — recorded by the executor
            when the trace is appended; the addressing metadata of the row
            mechanics, never rendered into the GROUP STEPS block.
    """

    model_config = ConfigDict(kw_only=True, frozen=True)

    sentence: str = ""
    step_type: str = ""
    tries: int | None = None
    delay: float | None = None
    outcome: str = ""
    url_before: str = ""
    url_after: str = ""
    identity: StepIdentity

    def render(self) -> str:
        """Render the complete verbatim trace — the unit the GROUP STEPS block renders.

        Returns:
            The multi-line trace text — the pinned three-line format:
            sentence, outcome label, URL pair; the identity never renders.
        """
        return f"{self.sentence}\noutcome: {self.outcome}\nurl: {self.url_before} -> {self.url_after}"
