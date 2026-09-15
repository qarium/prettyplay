"""Facade of the prettyplay.driver cell: the Playwright sync driver of prettyplay."""

from .errors import is_pollable_failure
from .page import PageFacade
from .session import DriverSession

__all__ = [
    "DriverSession",
    "PageFacade",
    "is_pollable_failure",
]
