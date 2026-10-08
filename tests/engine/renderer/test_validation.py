"""Tests for the validate_step_result function of the prettyplay.engine.renderer cell."""

import inspect

import pytest
from prettyplay.engine.renderer import PreparedStep, validate_step_result


class TestValidateStepResultContract:
    """Contract tests: facade import, signature shape, return type."""

    def test_is_importable_from_facade(self) -> None:
        assert inspect.isfunction(validate_step_result)

    def test_is_listed_in_the_facade_all(self) -> None:
        import prettyplay.engine.renderer  # noqa: PLC0415 — cell facade check

        assert "validate_step_result" in prettyplay.engine.renderer.__all__

    def test_signature_matches_the_contract(self) -> None:
        parameters = inspect.signature(validate_step_result).parameters

        assert list(parameters) == ["prepared", "result"]

    def test_signature_types_match_the_contract(self) -> None:
        annotations = validate_step_result.__annotations__

        assert annotations["prepared"] is PreparedStep
        assert annotations["result"] is object
        assert annotations["return"] == dict[str, str]

    def test_returns_a_dict_for_a_declaration_free_none_result(self) -> None:
        result = validate_step_result(PreparedStep(), None)

        assert isinstance(result, dict)

    def test_accepts_any_object_as_the_result(self) -> None:
        prepared = PreparedStep(declarations=["name"])

        with pytest.raises(AssertionError):
            validate_step_result(prepared, "not a dictionary")


class TestValidateStepResultLogic:
    """Logic tests: exact-key acceptance, the violation matrix, value checks."""

    def test_validate_accepts_exact_declared_dictionary(self) -> None:
        prepared = PreparedStep(instruction="Read the item", inputs={}, declarations=["name", "kind"])

        captures = validate_step_result(prepared, {"kind": "book", "name": "Dune"})

        assert captures == {"name": "Dune", "kind": "book"}

    def test_validate_declaration_free_step_accepts_none(self) -> None:
        prepared = PreparedStep(instruction="click Sign in", inputs={}, declarations=[])

        captures = validate_step_result(prepared, None)

        assert captures == {}

    def test_validate_missing_and_unexpected_names_violate(self) -> None:
        prepared = PreparedStep(declarations=["a", "b"])

        with pytest.raises(AssertionError, match="missing 'b'"):
            validate_step_result(prepared, {"a": "x"})

        with pytest.raises(AssertionError, match="unexpected 'c'"):
            validate_step_result(prepared, {"a": "x", "b": "y", "c": "z"})

        with pytest.raises(AssertionError, match="missing result"):
            validate_step_result(prepared, None)

        with pytest.raises(AssertionError, match="unexpected result without declarations"):
            validate_step_result(PreparedStep(declarations=[]), {"a": "x"})

    def test_validate_blank_value_violates(self) -> None:
        prepared = PreparedStep(declarations=["a"])

        with pytest.raises(AssertionError, match="the result value of 'a' is blank"):
            validate_step_result(prepared, {"a": ""})

        with pytest.raises(AssertionError, match="the result value of 'a' is blank"):
            validate_step_result(prepared, {"a": "   "})

        assert validate_step_result(prepared, {"a": "  x  "}) == {"a": "  x  "}

    def test_validate_wrong_result_type_is_a_failed_check(self) -> None:
        prepared = PreparedStep(instruction="Read the name", inputs={}, declarations=["name"])

        for wrong in (["name"], 42):
            with pytest.raises(AssertionError, match="result must be a dictionary"):
                validate_step_result(prepared, wrong)

    def test_validate_non_string_value_violates(self) -> None:
        prepared = PreparedStep(declarations=["a"])

        for wrong in ({"a": 42}, {"a": True}, {"a": None}):
            with pytest.raises(AssertionError, match="the result value of 'a' must be a string"):
                validate_step_result(prepared, wrong)

    def test_validate_returns_an_independent_copy(self) -> None:
        result = {"name": "Dune"}

        captures = validate_step_result(PreparedStep(declarations=["name"]), result)

        assert captures is not result

        captures["name"] = "mutated"

        assert result == {"name": "Dune"}
