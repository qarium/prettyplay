"""Facade of the prettyplay.engine.groups cell: the diagnosis-driven recovery of step groups."""

from .diagnosis import classify_group_failure
from .outcome import GroupStepOutcome
from .recovery import GroupRecovery

__all__ = ["GroupRecovery", "GroupStepOutcome", "classify_group_failure"]
