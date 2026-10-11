"""Tests for the normalize_step_text routine of the prettyplay.cache cell."""

import inspect

import pytest
from prettyplay.cache import StepIdentity, normalize_step_text
from prettyplay.cache import text as text_module


class TestNormalizeStepTextContract:
    """Contract tests: facade import, signature shape, removed internals."""

    def test_normalize_step_text_is_importable_from_facade(self) -> None:
        assert callable(normalize_step_text)

    def test_signature_is_single_str_argument(self) -> None:
        parameters = inspect.signature(normalize_step_text).parameters

        assert list(parameters) == ["text"]

    def test_returns_str(self) -> None:
        result = normalize_step_text("нажать войти")

        assert isinstance(result, str)

    def test_module_defines_no_removed_internals(self) -> None:
        assert not hasattr(text_module, "_WHITESPACE_RUN")
        assert not hasattr(text_module, "_TEMPLATE_MARKERS")


class TestNormalizeStepTextLogic:
    """Logic tests: the verbatim NFC+trim rule, empty inputs, distinctness."""

    def test_normalize_applies_nfc_and_trim_only(self) -> None:
        assert normalize_step_text("  Café ") == "Café"
        assert normalize_step_text("Click Sign in") == "Click Sign in"
        assert normalize_step_text("click  sign in") == "click  sign in"

    def test_normalize_is_idempotent(self) -> None:
        once = normalize_step_text("  Café  и  Нажать ")

        assert normalize_step_text(once) == once

    def test_normalize_keeps_case_and_whitespace_distinct(self) -> None:
        assert normalize_step_text("Click Sign in") != normalize_step_text("click  sign in ")

        first = StepIdentity(cache_key="k", step_type="action", normalized_text=normalize_step_text("Click Sign in"))
        second = StepIdentity(cache_key="k", step_type="action", normalized_text=normalize_step_text("click  sign in "))

        assert first.filename != second.filename

    def test_normalize_empty_and_whitespace_only(self) -> None:
        assert normalize_step_text("") == ""
        assert normalize_step_text("   ") == ""
        assert normalize_step_text("\n\t") == ""

    def test_distinct_sentences_stay_distinct(self) -> None:
        # a different step kind/language — a different address: "open" and "click" do not merge
        assert normalize_step_text("Открыть страницу") != normalize_step_text("нажать войти")

    def test_template_markers_are_plain_data(self) -> None:
        result = normalize_step_text("  Read {{ name }} into {% var out %}  ")

        assert result == "Read {{ name }} into {% var out %}"

    @pytest.mark.parametrize("marker", ["{{", "{%", "{#"])
    def test_each_marker_is_kept_verbatim(self, marker: str) -> None:
        result = normalize_step_text(f"Click {marker} X")

        assert marker in result
        assert "X" in result
