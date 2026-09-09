"""Shared fixtures of the prettyplay test suite."""

import pytest


def _toml_value(value) -> str:
    """Render a setting value as a TOML literal (str, bool, int supported)."""
    if isinstance(value, bool):
        return "true" if value else "false"

    return repr(value)


@pytest.fixture
def write_pyproject(tmp_path):
    """Return a helper writing a ``[tool.prettyplay]`` pyproject.toml into tmp_path.

    The helper serializes the given settings as TOML key = value lines inside
    the ``[tool.prettyplay]`` section and returns the written file path.
    """

    def _write(**settings) -> str:
        lines = ["[tool.prettyplay]"]
        lines.extend(f"{name} = {_toml_value(value)}" for name, value in settings.items())
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("\n".join(lines) + "\n", encoding="utf-8")

        return str(pyproject)

    return _write
