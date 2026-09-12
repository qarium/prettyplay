"""Models of the prettyplay.llm cell: the failure classification verdict."""

from pydantic import BaseModel, ConfigDict


class FailureClassification(BaseModel):
    """The verdict of a failure classification.

    Says what kind of failure a failed cached step hit and what the engineer
    should do about it.

    Attributes:
        category: the classification label: rot, product_defect, fixable or
            incurable — fixable: the step code is at fault (an ambiguous or
            wrong locator or strategy) while the intent stays satisfiable;
            regeneration for the same intent can help.
        explanation: why the failure got this category.
        recommendation: the recommended engineer action.
    """

    model_config = ConfigDict(kw_only=True)

    category: str
    explanation: str
    recommendation: str
