"""Facade of the prettyplay.driver cell: the Playwright sync driver of prettyplay."""

from .errors import is_pollable_failure
from .page import DialogFacade, FrameFacade, LocatorFacade, PageFacade
from .session import DriverSession

__all__ = [
    "DialogFacade",
    "DriverSession",
    "FrameFacade",
    "LocatorFacade",
    "PageFacade",
    "is_pollable_failure",
]
