"""Facade of the prettyplay.driver cell: the Playwright sync driver of prettyplay."""

from .page import LocatorFacade, PageFacade
from .session import DriverSession

__all__ = ["DriverSession", "LocatorFacade", "PageFacade"]
