"""Facade of the prettyplay root: the composition root of the library."""

from .config import BrowserConfig, PrettyConfig
from .executor import StepExecutor
from .reporting import StepHooks
from .runtime import PrettyplayRuntime
from .scenario import PrettyPlay

__all__ = [  # noqa: RUF022 — the facade listing order is fixed by the root cell contract
    "PrettyPlay",
    "StepHooks",
    "PrettyConfig",
    "BrowserConfig",
    "PrettyplayRuntime",
    "StepExecutor",
]
