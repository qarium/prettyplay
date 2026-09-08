"""Tests for the failure taxonomy of the prettyplay.failures cell."""

import inspect

import pytest
from prettyplay.failures import (
    IncurableStepError,
    LlmUnavailableError,
    PrettyplayError,
    ProductDefectError,
    __all__,
)


class TestFailuresContract:
    """Contract tests: facade import, subclassing, constructor signatures, fields."""

    def test_all_four_names_importable_from_facade(self) -> None:
        for name in (PrettyplayError, ProductDefectError, IncurableStepError, LlmUnavailableError):
            assert isinstance(name, type)

    def test_every_mutation_is_subclass_of_prettyplay_error(self) -> None:
        assert issubclass(ProductDefectError, PrettyplayError)
        assert issubclass(IncurableStepError, PrettyplayError)
        assert issubclass(LlmUnavailableError, PrettyplayError)

    def test_base_is_an_exception(self) -> None:
        assert issubclass(PrettyplayError, Exception)

    def test_base_signature_is_single_message(self) -> None:
        parameters = list(inspect.signature(PrettyplayError.__init__).parameters.values())[1:]  # drop self

        assert [parameter.name for parameter in parameters] == ["message"]

    def test_product_defect_signature_is_step_text_and_message(self) -> None:
        parameters = list(inspect.signature(ProductDefectError.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["step_text", "message"]

    def test_incurable_signature_is_three_fields(self) -> None:
        parameters = list(inspect.signature(IncurableStepError.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["step_text", "reason", "recommendation"]

    def test_llm_unavailable_signature_is_single_message(self) -> None:
        parameters = list(inspect.signature(LlmUnavailableError.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["message"]

    def test_product_defect_properties(self) -> None:
        error = ProductDefectError("шаг", "ожидание не оправдалось")

        assert error.step_text == "шаг"
        assert error.message == "ожидание не оправдалось"

    def test_incurable_properties(self) -> None:
        error = IncurableStepError("шаг", "причина", "рекомендация")

        assert error.step_text == "шаг"
        assert error.reason == "причина"
        assert error.recommendation == "рекомендация"

    def test_llm_unavailable_property(self) -> None:
        error = LlmUnavailableError("llm unavailable: openai: OPENAI_API_KEY is not set")

        assert error.message == "llm unavailable: openai: OPENAI_API_KEY is not set"

    def test_facade_all_lists_four_names(self) -> None:
        assert __all__ == ["IncurableStepError", "LlmUnavailableError", "PrettyplayError", "ProductDefectError"]


class TestFailuresLogic:
    """Logic tests: rendered messages, single-except boundary, actionable fields."""

    def test_incurable_error_message_renders_all_fields(self) -> None:
        s = str(IncurableStepError("шаг", "причина", "рекомендация"))

        assert "шаг" in s
        assert "причина" in s
        assert "рекомендация" in s

    def test_incurable_is_catchable_by_base(self) -> None:
        error = IncurableStepError("шаг", "причина", "рекомендация")

        assert isinstance(error, PrettyplayError)  # единый except на границе suite

    def test_single_except_clause_catches_every_mutation(self) -> None:
        mutations = [
            ProductDefectError("шаг", "ожидание не оправдалось"),
            IncurableStepError("шаг", "причина", "рекомендация"),
            LlmUnavailableError("llm unavailable: openai: OPENAI_API_KEY is not set"),
        ]

        for error in mutations:
            with pytest.raises(PrettyplayError) as excinfo:
                raise error

            assert excinfo.value is error

    def test_product_defect_str_contains_step_and_message(self) -> None:
        s = str(ProductDefectError("шаг", "ожидание не оправдалось"))

        assert "шаг" in s
        assert "ожидание не оправдалось" in s

    def test_llm_unavailable_message_names_provider(self) -> None:
        message = "llm unavailable: openai: OPENAI_API_KEY is not set"

        assert LlmUnavailableError(message).message == message
        assert "openai" in str(LlmUnavailableError(message))

    def test_base_message_stored_as_attribute(self) -> None:
        error = PrettyplayError("что-то сломалось")

        assert error.message == "что-то сломалось"
        assert str(error) == "что-то сломалось"
