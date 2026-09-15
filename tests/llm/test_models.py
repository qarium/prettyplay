"""Tests for the models of the prettyplay.llm cell."""

import pydantic
import pytest
from prettyplay.failures import ComplianceVerdictError, PrettyplayError
from prettyplay.llm import ComplianceFinding, FailureClassification, parse_compliance_verdict


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


class TestComplianceFindingContract:
    """Contract tests: facade import, kw_only shape, empty defaults, no validation."""

    def test_is_importable_from_facade(self) -> None:
        assert isinstance(ComplianceFinding, type)

    def test_is_listed_in_the_facade_all(self) -> None:
        import prettyplay.llm  # noqa: PLC0415 — cell facade check

        assert "ComplianceFinding" in prettyplay.llm.__all__

    def test_parse_compliance_verdict_is_importable_from_facade(self) -> None:
        assert callable(parse_compliance_verdict)

    def test_parse_compliance_verdict_is_listed_in_the_facade_all(self) -> None:
        import prettyplay.llm  # noqa: PLC0415 — cell facade check

        assert "parse_compliance_verdict" in prettyplay.llm.__all__

    def test_is_pydantic_base_model(self) -> None:
        assert issubclass(ComplianceFinding, pydantic.BaseModel)

    def test_is_kw_only(self) -> None:
        assert ComplianceFinding.model_config.get("kw_only") is True

    def test_positional_construction_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            ComplianceFinding("i", "high", "e")  # type: ignore[misc]

    def test_declares_exactly_four_fields_with_empty_defaults(self) -> None:
        assert set(ComplianceFinding.model_fields) == {"instruction", "priority", "explanation", "dimension"}

        finding = ComplianceFinding()

        assert finding.instruction == ""
        assert finding.priority == ""
        assert finding.explanation == ""
        assert finding.dimension == ""

    def test_accepts_the_dimension_keyword(self) -> None:
        finding = ComplianceFinding(instruction="i", priority="high", explanation="e", dimension="adequacy")

        assert finding.dimension == "adequacy"
        assert isinstance(finding.dimension, str)

    def test_carries_no_priority_validation(self) -> None:
        finding = ComplianceFinding(instruction="i", priority="critical", explanation="e")

        assert finding.priority == "critical"  # the parse fails loudly before anything invalid reaches the type

    def test_carries_no_dimension_validation(self) -> None:
        finding = ComplianceFinding(instruction="i", priority="high", explanation="e", dimension="quality")

        assert finding.dimension == "quality"  # the parse fails loudly before anything invalid reaches the type


class TestParseComplianceVerdict:
    """Logic tests: the strict single parsing point of the gate."""

    def test_parse_compliance_verdict_parses_findings(self) -> None:
        verdict = """  [
            {"instruction": "Prefer id attributes", "priority": "high", "explanation": "locates by text",
             "dimension": "instruction"},
            {"instruction": "Keep steps short", "priority": "low", "explanation": "three statements",
             "dimension": "adequacy"}
        ]  """

        findings = parse_compliance_verdict(verdict)

        assert len(findings) == 2
        assert findings[0].priority == "high"
        assert findings[0].instruction == "Prefer id attributes"
        assert findings[0].explanation == "locates by text"
        assert findings[0].dimension == "instruction"
        assert findings[1].priority == "low"
        assert findings[1].instruction == "Keep steps short"
        assert findings[1].explanation == "three statements"
        assert findings[1].dimension == "adequacy"

    @pytest.mark.parametrize(
        "verdict_text",
        [
            "not json at all",
            '{"instruction": "x", "priority": "high", "explanation": "e"}',
            "[1]",
            '[{"priority": "high", "explanation": "e"}]',
            '[{"instruction": "i", "priority": "critical", "explanation": "e"}]',
            # a valid dimension and an unknown priority — the priority check itself fires
            '[{"instruction": "i", "priority": "critical", "explanation": "e", "dimension": "instruction"}]',
            '[{"instruction": 7, "priority": "high", "explanation": "e"}]',
            # a fenced empty list is malformed — an emptiness reached only through the salvage never passes
            "```json\n[]\n```",
            # a fenced finding without a dimension is malformed — the salvage repairs syntax, never semantics
            '```json\n[{"instruction": "i", "priority": "high", "explanation": "e"}]\n```',
            # a salvaged-to-empty answer is malformed — only an explicitly valid [] passes
            "[",
            "[] trailing prose",
            # a truncated answer loses its dimension to the salvage — malformed
            '[{"instruction": "Prefer id attributes", "priority": "high", "explanation": "locates by text"',
        ],
    )
    def test_parse_compliance_verdict_malformed_variants(self, verdict_text: str) -> None:
        with pytest.raises(ComplianceVerdictError) as excinfo:
            parse_compliance_verdict(verdict_text)

        assert "compliance verdict unparsable" in str(excinfo.value)
        assert isinstance(excinfo.value, PrettyplayError)

    def test_parse_compliance_verdict_salvages_the_dropped_quote_glitch(self) -> None:
        verdict = (
            '[{"instruction": "Accept all the terms", priority": "medium", '
            '"explanation": "The code clicks a button consenting only to cookie/data use '
            "for the described purposes, which may not be the 'accept all' terms.\", "
            '"dimension": "instruction"}]'
        )

        findings = parse_compliance_verdict(verdict)

        assert len(findings) == 1
        assert findings[0].instruction == "Accept all the terms"
        assert findings[0].priority == "medium"
        assert findings[0].explanation.startswith("The code clicks a button")
        assert findings[0].dimension == "instruction"

    def test_parse_compliance_verdict_salvages_single_quotes_and_trailing_comma(self) -> None:
        verdict = (
            "[{'instruction': 'Prefer id attributes', 'priority': 'high', "
            "'explanation': 'locates by text', 'dimension': 'instruction'},]"
        )

        findings = parse_compliance_verdict(verdict)

        assert len(findings) == 1
        assert findings[0].instruction == "Prefer id attributes"
        assert findings[0].priority == "high"
        assert findings[0].explanation == "locates by text"
        assert findings[0].dimension == "instruction"

    def test_parse_compliance_verdict_salvages_a_fenced_findings_list(self) -> None:
        verdict = (
            '```json\n[{"instruction": "Prefer id attributes", "priority": "low", '
            '"explanation": "chatty", "dimension": "instruction"}]\n```'
        )

        findings = parse_compliance_verdict(verdict)

        assert len(findings) == 1
        assert findings[0].priority == "low"
        assert findings[0].dimension == "instruction"

    def test_salvage_keeps_the_semantic_gates_strict(self) -> None:
        # a salvageable syntax shape carrying an unknown priority — still a hard failure
        verdict = (
            "[{'instruction': 'Prefer id attributes', 'priority': 'critical', "
            "'explanation': 'locates by text', 'dimension': 'instruction'},]"
        )

        with pytest.raises(ComplianceVerdictError):
            parse_compliance_verdict(verdict)

    def test_a_salvage_library_failure_is_a_malformed_verdict(self, monkeypatch) -> None:
        def broken_salvage(text: str) -> object:
            raise RuntimeError("salvage exploded")

        monkeypatch.setattr("prettyplay.llm.models.repair_loads", broken_salvage)

        with pytest.raises(ComplianceVerdictError):
            parse_compliance_verdict("[{'instruction': 'i'}")

    def test_malformed_message_carries_the_raw_fragment(self) -> None:
        with pytest.raises(ComplianceVerdictError) as excinfo:
            parse_compliance_verdict("not json at all")

        assert "not json at all" in str(excinfo.value)

    def test_parse_compliance_verdict_empty_list_means_compliant(self) -> None:
        assert parse_compliance_verdict("[]") == []

    def test_parse_compliance_verdict_accepts_both_dimensions(self) -> None:
        text = (
            '[{"instruction": "Prefer id attributes", "priority": "high", "explanation": "locates by text",'
            ' "dimension": "instruction"}, '
            '{"instruction": "click the «Sign in» button", "priority": "low", "explanation": "only checks state",'
            ' "dimension": "adequacy"}]'
        )

        findings = parse_compliance_verdict(text)

        assert len(findings) == 2
        assert findings[0].dimension == "instruction"
        assert findings[0].priority == "high"
        assert findings[1].dimension == "adequacy"
        assert findings[1].priority == "low"

    def test_parse_compliance_verdict_rejects_old_shape_without_dimension(self) -> None:
        text = '[{"instruction": "Prefer id attributes", "priority": "high", "explanation": "locates by text"}]'

        with pytest.raises(ComplianceVerdictError) as excinfo:
            parse_compliance_verdict(text)

        assert "dimension" in str(excinfo.value)
        assert "Prefer id attributes" in str(excinfo.value)  # a fragment of the raw answer rides the error

    def test_parse_compliance_verdict_rejects_unknown_dimension(self) -> None:
        text = '[{"instruction": "x", "priority": "high", "explanation": "y", "dimension": "quality"}]'

        with pytest.raises(ComplianceVerdictError):
            parse_compliance_verdict(text)

    def test_parse_compliance_verdict_tolerates_extra_keys_and_padding(self) -> None:
        verdict = (
            '  [ {"instruction": "i", "priority": "medium", "explanation": "e", "dimension": "instruction",'
            ' "note": "chatty"} ]  '
        )

        findings = parse_compliance_verdict(verdict)

        assert len(findings) == 1
        assert findings[0].instruction == "i"
        assert findings[0].priority == "medium"
        assert findings[0].explanation == "e"
        assert findings[0].dimension == "instruction"

    def test_parse_compliance_verdict_tolerates_empty_string_field_values(self) -> None:
        verdict = '[{"instruction": "", "priority": "high", "explanation": "", "dimension": "adequacy"}]'

        findings = parse_compliance_verdict(verdict)

        assert len(findings) == 1
        assert findings[0].instruction == ""
        assert findings[0].dimension == "adequacy"

    def test_parse_compliance_verdict_collapses_the_fragment_whitespace(self) -> None:
        with pytest.raises(ComplianceVerdictError) as excinfo:
            parse_compliance_verdict("not   json\n\nat   all")

        assert "not json at all" in str(excinfo.value)  # whitespace-collapsed fragment
