"""Tests for the models of the prettyplay.llm cell."""

import pydantic
import pytest
from prettyplay.llm import FailureClassification


class TestFailureClassificationContract:
    """Contract tests: facade import, kw_only shape, property surface."""

    def test_is_importable_from_facade(self) -> None:
        assert isinstance(FailureClassification, type)

    def test_is_pydantic_base_model(self) -> None:
        assert issubclass(FailureClassification, pydantic.BaseModel)

    def test_is_kw_only(self) -> None:
        assert FailureClassification.model_config.get("kw_only") is True

    def test_positional_construction_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            FailureClassification("rot", "e", "r")  # type: ignore[misc]

    def test_declares_exactly_three_fields(self) -> None:
        assert set(FailureClassification.model_fields) == {"category", "explanation", "recommendation"}


class TestFailureClassificationLogic:
    """Logic tests: the verdict stores all three parts; labels construct."""

    def test_positive_stores_all_three_parts(self) -> None:
        classification = FailureClassification(category="rot", explanation="e", recommendation="r")

        assert classification.category == "rot"
        assert classification.explanation == "e"
        assert classification.recommendation == "r"

    @pytest.mark.parametrize("category", ["rot", "product_defect", "incurable"])
    def test_each_allowed_category_constructs(self, category: str) -> None:
        classification = FailureClassification(category=category, explanation="e", recommendation="r")

        assert classification.category == category
        assert isinstance(classification.category, str)

    def test_fields_are_required(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            FailureClassification(category="rot", explanation="e")
