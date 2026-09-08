"""Facade of the prettyplay root: the composition root of the library."""

from .runtime import PrettyplayRuntime, get_runtime

__all__ = ["PrettyplayRuntime", "get_runtime"]
