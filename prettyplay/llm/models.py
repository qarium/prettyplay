"""Models of the prettyplay.llm cell: the classification verdicts, the compliance findings and the scenario records."""

import json

from json_repair import loads as repair_loads
from pydantic import BaseModel, ConfigDict

from ..failures import ComplianceVerdictError

#: The frozen set of the three compliance priority labels.
COMPLIANCE_PRIORITIES = frozenset({"high", "medium", "low"})

#: The frozen set of the two compliance dimension labels.
COMPLIANCE_DIMENSIONS = frozenset({"instruction", "adequacy"})

#: The frozen set of the three group diagnosis category labels.
GROUP_CATEGORIES = frozenset({"recoverable", "product_defect", "incurable"})

#: The recommendation a degraded group diagnosis answer carries.
DEGRADED_GROUP_RECOMMENDATION = "re-run the group step or check the provider answer"


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


class GroupFailureClassification(BaseModel):
    """The verdict of a group diagnosis: what kind of failure it is, why, where it stems from and what to do.

    Attributes:
        category: the diagnosis label: recoverable (the affected steps of
            the group can be regenerated and the run fixed), product_defect
            (the application is genuinely broken — never healed green),
            incurable (the root cannot be reached from inside the group, or
            regeneration cannot help); a degraded answer carries the
            conservative incurable.
        root_cause: why the failure got this category; a degraded verdict
            carries the raw answer here.
        earliest_step: the verbatim sentence quote of the earliest affected
            step as answered.
        recommendation: the recommended regeneration or engineer action.
        degraded: whether the parse degraded the raw answer to the
            conservative incurable; False on every parsed answer, True only
            on the degradation path — a library-set flag, never part of the
            model answer; the calling engine logs its WARNING from this flag.
    """

    model_config = ConfigDict(kw_only=True)

    category: str
    root_cause: str
    earliest_step: str
    recommendation: str
    degraded: bool = False


class ScenarioStep(BaseModel):
    """One record of the scenario context of a test — the unit every PREVIOUS STEPS block renders.

    Attributes:
        sentence: the raw step sentence as written by the engineer, verbatim
            — never the normalized addressing form.
        group_prompt: the group prompt of the step's group; empty — an
            ordinary step; non-empty — the verbatim group prompt; the
            membership is permanent for the lifetime of the test context.
    """

    model_config = ConfigDict(kw_only=True, frozen=True)

    sentence: str = ""
    group_prompt: str = ""


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

    The strict single parsing point of the gate: the answer must resolve to
    a JSON list of objects carrying a str instruction, a high|medium|low
    priority, a str explanation and an instruction|adequacy dimension. A
    JSON syntax failure is salvaged once through the ``json_repair``
    library — a verdict model glitching a quote, a comma or a bracket does
    not kill the run (see ``.goga/usages/cooks/json_repair.md``). Anything
    the salvage still cannot shape into the required list of objects, and
    any semantically invalid finding — a missing field, a non-string field,
    an unknown priority or dimension label, an answer of the old shape —
    is a malformed verdict raised loudly, never waved through. An empty
    findings list passes only from an explicitly valid JSON ``[]`` answer:
    an emptiness synthesized by the salvage is malformed too, so no
    unchecked candidate ever rides a repaired-to-empty verdict.

    Args:
        verdict_text: the raw text answer of the verdict model;
            whitespace-padded JSON is tolerated.

    Returns:
        The parsed findings; an empty list means compliant.

    Raises:
        ComplianceVerdictError: the answer resolves to neither the required
            shape nor a repairable equivalent — not a list, an item misses a
            field, carries a non-string field or names an unknown priority
            or dimension — the candidate stays unchecked and is never
            cached.
    """
    text = verdict_text.strip()
    try:
        data = json.loads(text)
    except ValueError:
        try:
            data = repair_loads(text)
        except Exception:  # a salvage failure is a malformed verdict — a third-party error never crosses the parse
            raise _malformed(verdict_text) from None

        if data == []:  # an emptiness synthesized by the salvage — only an explicitly valid [] passes
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
            ComplianceFinding(instruction=instruction, priority=priority, explanation=explanation, dimension=dimension)
        )

    return findings


def _degraded_diagnosis(text: str) -> GroupFailureClassification:
    """Build the conservative verdict of an unusable diagnosis answer.

    Args:
        text: the trimmed raw answer that did not validate.

    Returns:
        The GroupFailureClassification carrying the conservative incurable,
        the raw answer in root_cause and the degraded flag set.
    """
    return GroupFailureClassification(
        category="incurable",
        root_cause=text,
        earliest_step="",
        recommendation=DEGRADED_GROUP_RECOMMENDATION,
        degraded=True,
    )


def parse_group_failure_classification(verdict_text: str) -> GroupFailureClassification:
    """Parse the raw answer of the group diagnosis request into the verdict.

    The strict single parsing point of the group diagnosis with the
    conservative degradation: the answer must resolve to a JSON object
    carrying a str category of the recoverable|product_defect|incurable set
    and str root_cause, earliest_step and recommendation fields. A JSON
    syntax failure is salvaged once through the ``json_repair`` library —
    a diagnosis model glitching a quote, a comma or a fence does not kill
    the run (see ``.goga/usages/cooks/json_repair.md``); the salvage
    repairs syntax only, the semantic validation applies to a salvaged
    answer identically. Anything else — prose, a non-object shape, a
    missing or non-string field, an unknown category label, a failure of
    the salvage library itself — never raises and never grants
    regeneration: it degrades conservatively to the incurable verdict with
    the raw answer carried in ``root_cause`` and the ``degraded`` flag set,
    so the calling engine can log its WARNING.

    Args:
        verdict_text: the raw text answer of the diagnosis model;
            whitespace-padded JSON is tolerated.

    Returns:
        The parsed verdict; ``degraded`` is False on every parsed answer
        and True only on the degradation path.
    """
    text = verdict_text.strip()
    data: object = None

    try:
        data = json.loads(text)
    except ValueError:
        try:
            data = repair_loads(text)  # syntax salvage of a model glitch
        except Exception:  # a salvage failure degrades — a third-party exception never crosses the parse
            return _degraded_diagnosis(text)

    if isinstance(data, dict):
        category = data.get("category")
        root_cause = data.get("root_cause")
        earliest_step = data.get("earliest_step")
        recommendation = data.get("recommendation")

        if (
            isinstance(category, str)
            and isinstance(root_cause, str)
            and isinstance(earliest_step, str)
            and isinstance(recommendation, str)
            and category in GROUP_CATEGORIES
        ):
            return GroupFailureClassification(
                category=category,
                root_cause=root_cause,
                earliest_step=earliest_step,
                recommendation=recommendation,
            )

    return _degraded_diagnosis(text)
