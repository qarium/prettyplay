"""Shared fixtures of the prettyplay test suite."""

from types import SimpleNamespace
from unittest import mock

import pytest
from prettyplay.cache import StepIdentity, normalize_step_text
from prettyplay.engine.groups import GroupStepOutcome
from prettyplay.llm import ScenarioStep

#: The group prompt of the shared cross-cell fixtures — the checkout flow of the group scenarios.
FIXTURE_GROUP_PROMPT = "the checkout flow"


@pytest.fixture
def scenario_records() -> list[ScenarioStep]:
    """The typed scenario context of the cross-cell tests — a mix of ordinary and group entries.

    The membership is a property of each record: the group entries keep
    their group prompt, the ordinary entries stay empty — exactly the shape
    the executor's ``_scenario`` appends and every engine request renders.
    """
    return [
        ScenarioStep(sentence="open the shop page"),
        ScenarioStep(sentence="accept the cookie banner", group_prompt=FIXTURE_GROUP_PROMPT),
        ScenarioStep(sentence="fill the email field", group_prompt=FIXTURE_GROUP_PROMPT),
    ]


@pytest.fixture
def group_traces() -> list[GroupStepOutcome]:
    """The verbatim trace records of a three-step group — two passed steps and the failed last one.

    The recovery-ready shape the executor hands to the group recovery: the
    sentences and outcomes are honest, each record carries the cache
    identity the recovery resolves its row from.
    """

    def _trace(sentence: str, step_type: str, outcome: str) -> GroupStepOutcome:
        return GroupStepOutcome(
            sentence=sentence,
            step_type=step_type,
            tries=None,
            delay=None,
            outcome=outcome,
            url_before="https://shop.example.com/checkout",
            url_after="https://shop.example.com/checkout",
            identity=StepIdentity(
                cache_key="tests/test_checkout.py",
                step_type=step_type,
                normalized_text=normalize_step_text(sentence),
            ),
        )

    return [
        _trace("accept the cookie banner", "action", "passed"),
        _trace("fill the email field", "action", "passed"),
        _trace("submit the form", "action", "failed"),
    ]


@pytest.fixture(autouse=True)
def _no_runtime_atexit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test-built runtime out of the real process ``atexit`` registry.

    Each ``PrettyplayRuntime`` registers its close with ``atexit``; without
    this isolation the suite would accumulate live exit hooks — and the
    runtimes they pin — for every test-built object until interpreter exit.
    """
    monkeypatch.setattr(
        "prettyplay.runtime.atexit",
        SimpleNamespace(register=mock.Mock(name="atexit_register"), unregister=mock.Mock(name="atexit_unregister")),
    )


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
