"""Tests for the normalize_step_text routine of the prettyplay.cache cell."""

import inspect

import pytest
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


class TestNormalizeTemplateSplitContract:
    """Contract tests: the template/ordinary addressing split."""

    def test_template_sentence_keeps_case_verbatim(self) -> None:
        assert normalize_step_text("read {{ Name }}") != normalize_step_text("read {{ name }}")

    @pytest.mark.parametrize("marker", ["{{", "{%", "{#"])
    def test_each_marker_triggers_template_mode(self, marker: str) -> None:
        result = normalize_step_text(f"Click {marker} X")

        assert "X" in result

    def test_template_sentence_keeps_internal_whitespace(self) -> None:
        result = normalize_step_text("Read {{  name   }} into {% var out %}")

        assert "{{  name   }}" in result

    def test_ordinary_sentence_stays_on_collapsing_pipeline(self) -> None:
        assert normalize_step_text("  Click   Sign In ") == "click sign in"


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

    def test_normalize_template_sentence_addresses_verbatim(self) -> None:
        result = normalize_step_text("  Read {{ name }} into {% var out %}  ")

        assert result == "Read {{ name }} into {% var out %}"

        assert normalize_step_text("read {{ Name }}") != normalize_step_text("read {{ name }}")

    def test_normalize_comment_marker_sentence_is_template(self) -> None:
        result = normalize_step_text("{# note #} Click Sign in")

        assert result == "{# note #} Click Sign in"
