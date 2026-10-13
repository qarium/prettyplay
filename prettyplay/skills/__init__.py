"""Facade of the skills cell: packaged domain skills behind a cached read."""

from __future__ import annotations

from importlib.resources import files

__all__ = ["load_skill"]

_cache: dict[str, str] = {}


def load_skill(name: str) -> str:
    """Read a packaged skill by name — the content is cached after the first read.

    Args:
        name: the skill directory name under this package (e.g. ``"playwright"``).

    Returns:
        The verbatim content of the skill's ``SKILL.md``.

    Raises:
        FileNotFoundError: the named skill directory holds no ``SKILL.md``.
    """
    if name not in _cache:
        _cache[name] = (files(__package__) / name / "SKILL.md").read_text(encoding="utf-8")

    return _cache[name]
