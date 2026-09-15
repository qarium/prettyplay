"""Models of the prettyplay.llm cell: the failure classification verdict and the instruction compliance findings."""

import json

from pydantic import BaseModel, ConfigDict

from ..failures import ComplianceVerdictError

#: The frozen set of the three compliance priority labels.
COMPLIANCE_PRIORITIES = frozenset({"high", "medium", "low"})

#: The frozen set of the two compliance dimension labels.
COMPLIANCE_DIMENSIONS = frozenset({"instruction", "adequacy"})


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


class ComplianceFinding(BaseModel):
    """One finding of the instruction compliance verdict.

    Attributes:
        instruction: the verbatim quote the finding names — the violated
            instruction or the fragment of the step sentence the code
            fails to accomplish.
        priority: the finding priority: high, medium or low; only high
            blocks the candidate, in both dimensions.
        explanation: one short sentence why the code violates the
            instruction or fails the step.
        dimension: the finding dimension: instruction or adequacy —
            which side of the gate produced the finding.
    """

    model_config = ConfigDict(kw_only=True)

    instruction: str = ""
    priority: str = ""
    explanation: str = ""
    dimension: str = ""


def _answer_fragment(verdict_text: str) -> str:
    """Collapse the raw verdict answer to a diagnostic fragment.

    Args:
        verdict_text: the raw text answer of the verdict model.

    Returns:
        The whitespace-collapsed first 200 characters of the raw text.
    """
    return " ".join(verdict_text.split())[:200]


def _malformed(verdict_text: str) -> ComplianceVerdictError:
    """Build the loud failure of a malformed verdict answer.

    Args:
        verdict_text: the raw text answer that did not parse.

    Returns:
        The ComplianceVerdictError carrying a fragment of the raw answer.
    """
    return ComplianceVerdictError(
        "compliance verdict unparsable — expected a JSON list of findings with "
        "instruction, priority high|medium|low, explanation and dimension instruction|adequacy; "
        "received fragment: " + _answer_fragment(verdict_text)
    )


def parse_compliance_verdict(verdict_text: str) -> list[ComplianceFinding]:
    """Parse the raw answer of the compliance verdict request into findings.

    The strict single parsing point of the gate: anything but a JSON list of
    objects carrying a str instruction, a high|medium|low priority, a str
    explanation and an instruction|adequacy dimension is a malformed
    verdict — raised loudly, never waved through. An answer of the old
    shape, a finding without a dimension, is malformed too — never a
    silent pass. No fence unwrapping and no protective fallback (contrast
    :func:`~prettyplay.llm._request.parse_classification_line`): an
    unparsable verdict answer is a hard failure of the gate.

    Args:
        verdict_text: the raw text answer of the verdict model;
            whitespace-padded JSON is tolerated.

    Returns:
        The parsed findings; an empty list means compliant.

    Raises:
        ComplianceVerdictError: the answer is not valid JSON, not a list,
            or an item misses a field, carries a non-string field or names
            an unknown priority or dimension — the candidate stays
            unchecked and is never cached.
    """
    try:
        data = json.loads(verdict_text.strip())
    except ValueError:
        raise _malformed(verdict_text) from None

    if not isinstance(data, list):
        raise _malformed(verdict_text)

    findings: list[ComplianceFinding] = []

    for item in data:
        if not isinstance(item, dict):
            raise _malformed(verdict_text)

        instruction = item.get("instruction")
        priority = item.get("priority")
        explanation = item.get("explanation")
        dimension = item.get("dimension")

        if (
            not isinstance(instruction, str)
            or not isinstance(priority, str)
            or not isinstance(explanation, str)
            or not isinstance(dimension, str)
        ):
            raise _malformed(verdict_text)

        if priority not in COMPLIANCE_PRIORITIES:
            raise _malformed(verdict_text)

        if dimension not in COMPLIANCE_DIMENSIONS:
            raise _malformed(verdict_text)

        findings.append(
            ComplianceFinding(
                instruction=instruction, priority=priority, explanation=explanation, dimension=dimension
            )
        )

    return findings
