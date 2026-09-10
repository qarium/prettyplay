"""Tests for the normalize_step_text routine of the prettyplay.cache cell."""

import inspect

from prettyplay.cache import normalize_step_text


class TestNormalizeStepTextContract:
    """Contract tests: facade import, signature shape."""

    def test_normalize_step_text_is_importable_from_facade(self) -> None:
        assert callable(normalize_step_text)

    def test_signature_is_single_str_argument(self) -> None:
        parameters = inspect.signature(normalize_step_text).parameters

        assert list(parameters) == ["text"]

    def test_returns_str(self) -> None:
        result = normalize_step_text("нажать войти")

        assert isinstance(result, str)


class TestNormalizeStepTextLogic:
    """Logic tests: equivalence pipeline, empty inputs."""

    def test_normalize_step_text_equivalence(self) -> None:
        assert normalize_step_text("  Нажать   Войти ") == normalize_step_text("нажать войти") == "нажать войти"

        assert normalize_step_text("Нажать Войти") != normalize_step_text("Click Login")

    def test_normalize_empty_and_whitespace_only(self) -> None:
        assert normalize_step_text("") == ""
        assert normalize_step_text("   ") == ""
        assert normalize_step_text("\n\t") == ""

    def test_internal_whitespace_runs_collapse_to_single_space(self) -> None:
        result = normalize_step_text("шаг\tс\nразными\r\nпробелами")

        assert result == "шаг с разными пробелами"

    def test_distinct_sentences_stay_distinct(self) -> None:
        # a different step kind/language — a different address: "open" and "click" do not merge
        assert normalize_step_text("Открыть страницу") != normalize_step_text("нажать войти")
