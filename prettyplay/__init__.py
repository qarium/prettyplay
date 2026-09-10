"""Facade of the prettyplay root: the composition root of the library."""

from .config import BrowserConfig, PrettyConfig
from .executor import StepExecutor
from .runtime import PrettyplayRuntime
from .scenario import PrettyTest

__all__ = [  # noqa: RUF022 — the facade listing order is fixed by the root cell contract
    "PrettyTest",
    "PrettyConfig",
    "BrowserConfig",
    "PrettyplayRuntime",
    "StepExecutor",
]
