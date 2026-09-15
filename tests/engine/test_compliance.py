"""Tests for the two-dimension compliance gate of the prettyplay.engine cell."""

import re
import textwrap
from pathlib import Path

from prettyplay.config import Config
from prettyplay.engine.attempts import OUTCOME_FAILED_CHECK, OUTCOME_ORIGINAL, StepAttempt
from prettyplay.engine.compliance import COMPLIANCE_PROMPT, check_step_compliance
from prettyplay.llm import ComplianceFinding

ENGINE_CODEMANIFEST = Path(__file__).resolve().parents[2] / "prettyplay" / "engine" / "CODEMANIFEST"

GATE_CONFIG = Config(generation_prompt="Prefer id attributes")

STEP_CODE = "def step(page) -> None:\n    page.goto('https://example.com')\n"


class ComplianceStubProvider:
    """Stub LLM provider boundary for the gate routine: recorded verdicts, scripted answers."""

    def __init__(self, verdicts: list[list[ComplianceFinding] | Exception] | None = None) -> None:
        self.compliance_calls: list[dict[str, object]] = []
        self._verdicts = list(verdicts) if verdicts is not None else None

    def check_instruction_compliance(self, **kwargs: object) -> list[ComplianceFinding]:
        self.compliance_calls.append(dict(kwargs))
        outcome = self._verdicts.pop(0) if self._verdicts else []
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class TestComplianceGateContract:
    """Contract tests: facade import, prompt constant, routine signature."""

    def test_check_step_compliance_is_importable_from_facade(self) -> None:
        from prettyplay.engine import check_step_compliance as facade_routine  # noqa: PLC0415 — facade check

        assert facade_routine is check_step_compliance

    def test_check_step_compliance_accepts_step_type_and_attempt_history(self) -> None:
        provider = ComplianceStubProvider()

        findings = check_step_compliance(
            GATE_CONFIG,
            provider,
            step_text="open the page",
            step_type="action",
            code=STEP_CODE,
            attempt_history=[],
        )

        assert findings == []
        assert len(provider.compliance_calls) == 1  # keyword-callable with the new inputs

    def test_compliance_prompt_is_a_frozen_constant(self) -> None:
        assert COMPLIANCE_PROMPT.startswith("You verify generated step code on two dimensions")
        assert "- STEP TYPE: action or assertion" in COMPLIANCE_PROMPT
        assert "- ATTEMPT HISTORY: the verbatim record of every attempt of this step so far" in COMPLIANCE_PROMPT
        assert '"dimension": "instruction|adequacy"' in COMPLIANCE_PROMPT
        assert "Output only the JSON list, no other text" in COMPLIANCE_PROMPT


class TestCheckStepComplianceLogic:
    """Logic tests: the off switch, the empty-instructions guard, the request shape."""

    def test_check_step_compliance_returns_empty_with_zero_calls_when_off(self) -> None:
        provider = ComplianceStubProvider()
        config = Config(generation_approve=False, generation_prompt="Prefer id attributes")

        findings = check_step_compliance(config, provider, "open the page", "action", STEP_CODE, [])

        assert findings == []
        assert provider.compliance_calls == []  # the off switch makes zero provider calls

    def test_check_step_compliance_returns_empty_when_instructions_empty(self) -> None:
        provider = ComplianceStubProvider()
        config = Config(generation_approve=True, generation_prompt="")

        findings = check_step_compliance(config, provider, "open the page", "action", STEP_CODE, [])

        assert findings == []
        assert provider.compliance_calls == []  # empty instructions — the gate never runs

    def test_check_step_compliance_passes_practice_prompt_and_instructions(self) -> None:
        provider = ComplianceStubProvider()

        findings = check_step_compliance(GATE_CONFIG, provider, "open the page", "action", STEP_CODE, [])

        assert findings == []
        assert len(provider.compliance_calls) == 1
        call = provider.compliance_calls[0]
        assert call["prompt"] == COMPLIANCE_PROMPT  # the practice prompt, byte-equal
        assert call["user_instructions"] == "Prefer id attributes"
        assert call["step_text"] == "open the page"
        assert call["code"] == STEP_CODE

    def test_check_step_compliance_passes_step_type_and_rendered_history(self) -> None:
        provider = ComplianceStubProvider()
        record0 = StepAttempt(
            code="def step(page) -> None:\n    page.click('#sign-in-old')\n",
            error="old rot — the selector no longer resolves",
            outcome=OUTCOME_ORIGINAL,
            url_before="https://a.example",
            url_after="https://b.example",
        )
        record1 = StepAttempt(
            code="def step(page) -> None:\n    page.click('#sign-in-old')\n    page.wait_for_selector('#x')\n",
            error="AssertionError: #x not visible",
            outcome=OUTCOME_FAILED_CHECK,
            url_before="https://b.example",
            url_after="https://b.example",
        )

        findings = check_step_compliance(
            GATE_CONFIG, provider, "click the «Sign in» button", "action", STEP_CODE, [record0, record1]
        )

        assert findings == []
        call = provider.compliance_calls[0]
        assert call["step_type"] == "action"
        assert call["attempt_history"] == [record0.render(), record1.render()]  # rendered, verbatim records
        assert call["prompt"] == COMPLIANCE_PROMPT

    def test_check_step_compliance_returns_the_providers_findings(self) -> None:
        finding = ComplianceFinding(
            instruction="Prefer id attributes",
            priority="high",
            explanation="locates by text",
            dimension="instruction",
        )
        provider = ComplianceStubProvider(verdicts=[[finding]])

        findings = check_step_compliance(GATE_CONFIG, provider, "open the page", "action", "code", [])

        assert findings == [finding]


class TestCompliancePromptMirror:
    """Mirror test: the constant is the byte-equal copy of the CODEMANIFEST practice."""

    def test_compliance_prompt_mirror_matches_the_code_manifest_practice(self) -> None:
        manifest = ENGINE_CODEMANIFEST.read_text(encoding="utf-8")
        block = re.search(r"^  compliance_prompt: \|\n((?:    .*\n|\n)+)", manifest, flags=re.MULTILINE)
        assert block is not None  # the practice block exists

        practice = textwrap.dedent(block.group(1)).strip()

        assert practice == COMPLIANCE_PROMPT  # the frozen mirror — the constant changes only together with the manifest
