"""Models of the prettyplay.llm cell: the failure classification verdict."""

from pydantic import BaseModel, ConfigDict

#: The labels a classification category may take.
CATEGORY_ROT = "rot"
CATEGORY_PRODUCT_DEFECT = "product_defect"
CATEGORY_INCURABLE = "incurable"

#: The frozen set of the three classification labels.
CATEGORIES = frozenset({CATEGORY_ROT, CATEGORY_PRODUCT_DEFECT, CATEGORY_INCURABLE})


class FailureClassification(BaseModel):
    """The verdict of a failure classification.

    Says what kind of failure a failed cached step hit and what the engineer
    should do about it.

    Attributes:
        category: the classification label: rot, product_defect or incurable.
        explanation: why the failure got this category.
        recommendation: the recommended engineer action.
    """

    model_config = ConfigDict(kw_only=True)

    category: str
    explanation: str
    recommendation: str
