"""Tests for the models of the prettyplay.llm cell."""

import pydantic
import pytest
from prettyplay.failures import ComplianceVerdictError, PrettyplayError
from prettyplay.llm import (
    ComplianceFinding,
    FailureClassification,
    GroupFailureClassification,
    ScenarioStep,
    parse_compliance_verdict,
    parse_group_failure_classification,
)


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


class TestScenarioStepContract:
    """Contract tests: facade import, kw_only frozen shape, empty defaults."""

    def test_is_importable_from_facade(self) -> None:
        assert isinstance(ScenarioStep, type)

    def test_is_listed_in_the_facade_all(self) -> None:
        import prettyplay.llm  # noqa: PLC0415 — cell facade check

        assert "ScenarioStep" in prettyplay.llm.__all__

    def test_is_pydantic_base_model(self) -> None:
        assert issubclass(ScenarioStep, pydantic.BaseModel)

    def test_is_kw_only(self) -> None:
        assert ScenarioStep.model_config.get("kw_only") is True

    def test_is_frozen(self) -> None:
        assert ScenarioStep.model_config.get("frozen") is True

    def test_positional_construction_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            ScenarioStep("open the login page", "the order form group")  # type: ignore[misc]

    def test_declares_exactly_two_fields_with_empty_defaults(self) -> None:
        assert set(ScenarioStep.model_fields) == {"sentence", "group_prompt"}

        record = ScenarioStep()

        assert record.sentence == ""
        assert record.group_prompt == ""

    def test_kw_only_construction_carries_both_parts(self) -> None:
        record = ScenarioStep(sentence="open the login page", group_prompt="the order form group")

        assert record.sentence == "open the login page"
        assert record.group_prompt == "the order form group"


class TestScenarioStepLogic:
    """Logic tests: the permanent-membership record is immutable."""

    def test_a_record_is_never_rewritten(self) -> None:
        record = ScenarioStep(sentence="open the login page")

        with pytest.raises(pydantic.ValidationError):
            record.sentence = "rewritten"  # type: ignore[misc]

    def test_ordinary_step_carries_the_empty_group_prompt(self) -> None:
        record = ScenarioStep(sentence="open the login page")

        assert record.group_prompt == ""


class TestGroupFailureClassificationContract:
    """Contract tests: facade import, kw_only shape, the five properties."""

    def test_is_importable_from_facade(self) -> None:
        assert isinstance(GroupFailureClassification, type)

    def test_is_listed_in_the_facade_all(self) -> None:
        import prettyplay.llm  # noqa: PLC0415 — cell facade check

        assert "GroupFailureClassification" in prettyplay.llm.__all__

    def test_parse_group_failure_classification_is_importable_from_facade(self) -> None:
        assert callable(parse_group_failure_classification)

    def test_parse_group_failure_classification_is_listed_in_the_facade_all(self) -> None:
        import prettyplay.llm  # noqa: PLC0415 — cell facade check

        assert "parse_group_failure_classification" in prettyplay.llm.__all__

    def test_is_pydantic_base_model(self) -> None:
        assert issubclass(GroupFailureClassification, pydantic.BaseModel)

    def test_is_kw_only(self) -> None:
        assert GroupFailureClassification.model_config.get("kw_only") is True

    def test_positional_construction_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            GroupFailureClassification("recoverable", "r", "e", "rec")  # type: ignore[misc]

    def test_declares_the_five_properties_with_degraded_defaulting_false(self) -> None:
        assert set(GroupFailureClassification.model_fields) == {
            "category",
            "root_cause",
            "earliest_step",
            "recommendation",
            "degraded",
        }

        verdict = GroupFailureClassification(
            category="recoverable", root_cause="r", earliest_step="e", recommendation="rec"
        )

        assert verdict.category == "recoverable"
        assert verdict.root_cause == "r"
        assert verdict.earliest_step == "e"
        assert verdict.recommendation == "rec"
        assert verdict.degraded is False

    def test_each_allowed_category_constructs(self) -> None:
        for category in ("recoverable", "product_defect", "incurable"):
            verdict = GroupFailureClassification(
                category=category, root_cause="r", earliest_step="e", recommendation="rec", degraded=True
            )

            assert verdict.category == category
            assert verdict.degraded is True  # the flag is library-set, never part of the model answer


class TestParseGroupFailureClassification:
    """Logic tests: the strict single parsing point with the conservative degradation."""

    def test_parse_group_failure_classification_valid_and_degraded(self) -> None:
        valid = (
            '{"category": "recoverable", "root_cause": "the fill step used a stale locator", '
            '"earliest_step": "fill the email field", "recommendation": "regenerate the row from the fill step"}'
        )

        verdict = parse_group_failure_classification(valid)

        assert verdict.category == "recoverable"
        assert verdict.root_cause == "the fill step used a stale locator"
        assert verdict.earliest_step == "fill the email field"
        assert verdict.recommendation == "regenerate the row from the fill step"
        assert verdict.degraded is False

        glitched = (
            "{'category': 'product_defect', 'root_cause': 'the form never submits', "
            "'earliest_step': 'submit the form', 'recommendation': 'report the defect',}"
        )

        verdict = parse_group_failure_classification(glitched)

        assert verdict.category == "product_defect"
        assert verdict.root_cause == "the form never submits"
        assert verdict.earliest_step == "submit the form"
        assert verdict.degraded is False

        prose = parse_group_failure_classification("the app is broken")

        assert prose.category == "incurable"  # never recoverable from a degraded path
        assert prose.root_cause == "the app is broken"  # the raw answer rides the verdict
        assert prose.earliest_step == ""
        assert prose.recommendation == "re-run the group step or check the provider answer"
        assert prose.degraded is True

        wrong_label = '{"category": "maybe", "root_cause": "r", "earliest_step": "e", "recommendation": "rec"}'

        verdict = parse_group_failure_classification(wrong_label)

        assert verdict.category == "incurable"
        assert verdict.root_cause == wrong_label
        assert verdict.earliest_step == ""
        assert verdict.degraded is True

    def test_salvages_a_fenced_diagnosis_answer(self) -> None:
        verdict = (
            '```json\n{"category": "incurable", "root_cause": "the root lives outside the group", '
            '"earliest_step": "open the inbox", "recommendation": "rework the group"}\n```'
        )

        parsed = parse_group_failure_classification(verdict)

        assert parsed.category == "incurable"
        assert parsed.root_cause == "the root lives outside the group"
        assert parsed.earliest_step == "open the inbox"
        assert parsed.degraded is False

    def test_tolerates_extra_fields_and_padding(self) -> None:
        verdict = (
            '  {"category": "recoverable", "root_cause": "r", "earliest_step": "e", '
            '"recommendation": "rec", "note": "chatty"}  '
        )

        parsed = parse_group_failure_classification(verdict)

        assert parsed.category == "recoverable"
        assert parsed.root_cause == "r"
        assert parsed.degraded is False

    def test_the_degraded_root_cause_carries_the_trimmed_raw_answer(self) -> None:
        parsed = parse_group_failure_classification("  the app is broken  ")

        assert parsed.root_cause == "the app is broken"

    @pytest.mark.parametrize(
        "verdict_text",
        [
            "",
            "   ",
            "not json at all — the app is broken",
            "[]",
            "3",
            '"a string answer"',
            # a missing field never validates — even a recoverable label never passes incomplete
            '{"category": "recoverable"}',
            '{"category": "recoverable", "root_cause": "r", "earliest_step": "e"}',
            # non-string fields and unknown labels stay hard degradations — the salvage repairs syntax, never semantics
            '{"category": "recoverable", "root_cause": 7, "earliest_step": "e", "recommendation": "rec"}',
            '{"category": "maybe", "root_cause": "r", "earliest_step": "e", "recommendation": "rec"}',
            '{"category": "Recoverable", "root_cause": "r", "earliest_step": "e", "recommendation": "rec"}',
            "```json\n[]\n```",
        ],
    )
    def test_every_unusable_answer_degrades_to_the_conservative_incurable(self, verdict_text: str) -> None:
        parsed = parse_group_failure_classification(verdict_text)

        assert parsed.category == "incurable"
        assert parsed.degraded is True
        assert parsed.earliest_step == ""
        assert parsed.recommendation == "re-run the group step or check the provider answer"
        assert parsed.root_cause == verdict_text.strip()

    def test_a_salvage_library_failure_degrades_too(self, monkeypatch) -> None:
        def broken_salvage(text: str) -> object:
            raise RuntimeError("salvage exploded")

        monkeypatch.setattr("prettyplay.llm.models.repair_loads", broken_salvage)

        parsed = parse_group_failure_classification(
            "{'category': 'recoverable', 'root_cause': 'r', 'earliest_step': 'e', 'recommendation': 'rec'}"
        )

        assert parsed.category == "incurable"  # a third-party exception never crosses the parse
        assert parsed.degraded is True

    def test_the_parse_never_raises(self) -> None:
        for text in ["", "[", "{", "null", "\\", '{"category": null}']:
            parse_group_failure_classification(text)  # every failure mode degrades, none raises

    def test_the_parse_is_deterministic_and_never_logs(self, caplog) -> None:
        text = "the app is broken"

        with caplog.at_level("WARNING"):
            first = parse_group_failure_classification(text)
            second = parse_group_failure_classification(text)

        assert first == second  # pure function — deterministic on the input text
        assert caplog.records == []  # the WARNING naming the degraded raw answer is logged by the calling engine
