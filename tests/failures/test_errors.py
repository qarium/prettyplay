"""Tests for the failure taxonomy of the prettyplay.failures cell."""

import inspect

import pytest
from prettyplay.failures import (
    FailureVerdict,
    IncurableStepError,
    LLMUnavailableError,
    PrettyplayError,
    ProductDefectError,
    __all__,
)


class TestFailuresContract:
    """Contract tests: facade import, subclassing, constructor signatures, fields."""

    def test_all_five_names_importable_from_facade(self) -> None:
        for name in (PrettyplayError, ProductDefectError, IncurableStepError, LLMUnavailableError, FailureVerdict):
            assert isinstance(name, type)

    def test_every_mutation_is_subclass_of_prettyplay_error(self) -> None:
        assert issubclass(ProductDefectError, PrettyplayError)
        assert issubclass(IncurableStepError, PrettyplayError)
        assert issubclass(LLMUnavailableError, PrettyplayError)

    def test_base_is_an_exception(self) -> None:
        assert issubclass(PrettyplayError, Exception)

    def test_base_signature_is_single_message(self) -> None:
        parameters = list(inspect.signature(PrettyplayError.__init__).parameters.values())[1:]  # drop self

        assert [parameter.name for parameter in parameters] == ["message"]

    def test_verdict_signature_is_three_fields(self) -> None:
        parameters = list(inspect.signature(FailureVerdict.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["category", "explanation", "recommendation"]

    def test_verdict_render_is_callable_method(self) -> None:
        assert callable(FailureVerdict.render)

    def test_product_defect_signature_is_step_text_message_verdict(self) -> None:
        parameters = list(inspect.signature(ProductDefectError.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["step_text", "message", "verdict"]
        assert parameters[2].default is None

    def test_incurable_signature_is_step_text_reason_verdict(self) -> None:
        parameters = list(inspect.signature(IncurableStepError.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["step_text", "reason", "verdict"]
        assert parameters[2].default is None

    def test_llm_unavailable_signature_is_single_message(self) -> None:
        parameters = list(inspect.signature(LLMUnavailableError.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["message"]

    def test_product_defect_is_assertion_and_library_error(self) -> None:
        assert issubclass(ProductDefectError, AssertionError)
        assert issubclass(ProductDefectError, PrettyplayError)

    def test_product_defect_properties(self) -> None:
        error = ProductDefectError("click Sign in", "expected the banner, observed none")

        assert error.step_text == "click Sign in"
        assert error.message == "expected the banner, observed none"
        assert error.verdict is None

    def test_incurable_properties(self) -> None:
        error = IncurableStepError("click Sign in", "budget exhausted")

        assert error.step_text == "click Sign in"
        assert error.reason == "budget exhausted"
        assert error.verdict is None

    def test_llm_unavailable_property(self) -> None:
        error = LLMUnavailableError("llm unavailable: openai: OPENAI_API_KEY is not set")

        assert error.message == "llm unavailable: openai: OPENAI_API_KEY is not set"

    def test_facade_all_lists_five_names(self) -> None:
        assert __all__ == [
            "FailureVerdict",
            "IncurableStepError",
            "LLMUnavailableError",
            "PrettyplayError",
            "ProductDefectError",
        ]


class TestFailureVerdictLogic:
    """Logic tests: the frozen value object and its stable render."""

    def test_render_lists_all_fields(self) -> None:
        verdict = FailureVerdict("rot", "the button was renamed", "refresh the cache")

        assert verdict.render().splitlines() == [
            "category: rot",
            "explanation: the button was renamed",
            "recommendation: refresh the cache",
        ]

    def test_render_skips_empty_fields(self) -> None:
        verdict = FailureVerdict("rot", "", "refresh the cache")

        assert verdict.render() == "category: rot\nrecommendation: refresh the cache"

    def test_verdict_is_frozen(self) -> None:
        verdict = FailureVerdict("rot", "the button was renamed", "refresh the cache")

        with pytest.raises(Exception):  # noqa: B017, PT011 — frozen dataclass raises FrozenInstanceError
            verdict.category = "incurable"


class TestFailuresLogic:
    """Logic tests: rendered messages, single-except boundary, actionable fields."""

    def test_product_defect_is_assertion_and_library_error_with_and_without_verdict(self) -> None:
        verdict = FailureVerdict("product_defect", "the total was wrong", "file a bug")

        with_verdict = ProductDefectError("step", "expected x, observed y", verdict)
        without_verdict = ProductDefectError("step", "expected x, observed y", None)

        assert isinstance(with_verdict, PrettyplayError)
        assert isinstance(with_verdict, AssertionError)
        assert isinstance(without_verdict, PrettyplayError)
        assert isinstance(without_verdict, AssertionError)

    def test_product_defect_str_without_verdict_is_plain_message(self) -> None:
        assert str(ProductDefectError("step", "expected x, observed y", None)) == "expected x, observed y"

    def test_product_defect_str_appends_verdict_render(self) -> None:
        verdict = FailureVerdict("product_defect", "the banner is gone", "rec")
        rendered = str(ProductDefectError("step", "expected x, observed y", verdict))

        assert rendered.startswith("expected x, observed y")
        assert "category: product_defect" in rendered
        assert "recommendation: rec" in rendered
        assert rendered.index("expected x, observed y") < rendered.index("category:")

    def test_incurable_recommendation_comes_from_verdict(self) -> None:
        error = IncurableStepError("s", "budget exhausted", FailureVerdict("incurable", "e", "reword the step"))

        assert error.recommendation == "reword the step"

    def test_incurable_fallback_recommendation_without_verdict(self) -> None:
        error = IncurableStepError("s", "budget exhausted", None)

        assert error.recommendation == "reword the step or refresh the cache"
        assert str(error).startswith("budget exhausted")
        assert "recommendation: reword the step or refresh the cache" in str(error)
        assert not isinstance(error, AssertionError)

    def test_incurable_str_appends_verdict_render(self) -> None:
        verdict = FailureVerdict("incurable", "the text is gone", "reword the step")
        rendered = str(IncurableStepError("s", "budget exhausted", verdict))

        assert rendered.startswith("budget exhausted")
        assert "category: incurable" in rendered
        assert "recommendation: reword the step" in rendered
        assert rendered.index("budget exhausted") < rendered.index("category:")

    def test_incurable_is_catchable_by_base(self) -> None:
        error = IncurableStepError("click Sign in", "budget exhausted", FailureVerdict("incurable", "e", "reword"))

        assert isinstance(error, PrettyplayError)  # one except clause at the suite boundary

    def test_single_except_clause_catches_every_mutation(self) -> None:
        mutations = [
            ProductDefectError("click Sign in", "expected the banner, observed none"),
            IncurableStepError("click Sign in", "budget exhausted"),
            LLMUnavailableError("llm unavailable: openai: OPENAI_API_KEY is not set"),
        ]

        for error in mutations:
            with pytest.raises(PrettyplayError) as excinfo:
                raise error

            assert excinfo.value is error

    def test_llm_unavailable_message_names_provider(self) -> None:
        message = "llm unavailable: openai: OPENAI_API_KEY is not set"

        assert LLMUnavailableError(message).message == message
        assert "openai" in str(LLMUnavailableError(message))

    def test_base_message_stored_as_attribute(self) -> None:
        error = PrettyplayError("something broke")

        assert error.message == "something broke"
        assert str(error) == "something broke"

    def test_product_defect_args_carry_primary_reason_only(self) -> None:
        error = ProductDefectError("step", "expected x, observed y", FailureVerdict("product_defect", "e", "rec"))

        assert error.args == ("expected x, observed y",)
