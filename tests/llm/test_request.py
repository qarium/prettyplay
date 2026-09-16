"""Tests for the shared request-field helpers of the prettyplay.llm cell."""

import inspect
from typing import ClassVar

import pytest
from prettyplay.llm import ScenarioStep
from prettyplay.llm._request import (
    CATEGORIES,
    build_classification_fields,
    build_compliance_fields,
    build_fields_text,
    build_group_diagnosis_fields,
    extract_code_block,
    parse_classification_line,
    unparsable_classification,
)

FENCED_CODE = "def step(page) -> None:\n    page.goto('https://example.com')\n"
USER_INSTRUCTIONS = "prefer data-test-id"
CHEAT_SHEET = "expect(locator).to_be_visible()"
STEP_CODE = "def step(page) -> None:\n    pass\n"
ATTEMPT_RECORD = "execution failed\nurl: https://a.example -> https://b.example\ncode:\n...\nerror:\nboom"


class TestExtractCodeBlock:
    """Logic tests: the markdown-fenced completion becomes executable step code."""

    def test_extract_with_python_language_tag(self) -> None:
        answer = f"```python\n{FENCED_CODE}```"

        assert extract_code_block(answer) == FENCED_CODE

    def test_extract_with_bare_fence(self) -> None:
        answer = f"```\n{FENCED_CODE}```"

        assert extract_code_block(answer) == FENCED_CODE

    def test_extract_first_block_when_prose_surrounds_it(self) -> None:
        answer = f"Вот код шага:\n\n```python\n{FENCED_CODE}```\n\nГотово."

        assert extract_code_block(answer) == FENCED_CODE

    def test_plain_code_passes_through(self) -> None:
        assert extract_code_block(FENCED_CODE) == FENCED_CODE

    def test_unclosed_fence_passes_through_as_is(self) -> None:
        answer = f"```python\n{FENCED_CODE}"

        assert extract_code_block(answer) == answer


class TestBuildFieldsTextContract:
    """Contract tests: the builder carries the fixed port parameter list."""

    def test_build_fields_text_accepts_the_port_parameter_list(self) -> None:
        parameters = inspect.signature(build_fields_text).parameters

        assert list(parameters) == [
            "user_instructions",
            "step_text",
            "step_type",
            "previous_steps",
            "group_prompt",
            "snapshot",
            "page_url",
            "cheat_sheet",
            "attempt_history",
            "recommendation",
            "guidance",
        ]
        assert parameters["step_type"].annotation is str
        assert parameters["previous_steps"].annotation == list[ScenarioStep]
        assert parameters["group_prompt"].annotation == str | None
        assert parameters["attempt_history"].annotation == list[str]

    def test_build_fields_text_drops_the_removed_regeneration_inputs(self) -> None:
        names = list(inspect.signature(build_fields_text).parameters)

        assert "existing_code" not in names  # the removed inputs are gone, not merely optional
        assert "error" not in names
        assert "guidance_history" not in names


class TestBuildFieldsTextStepTypeLine:
    """Logic tests: the STEP TYPE line directly above the STEP line."""

    def test_build_fields_text_renders_step_type_line_directly_above_step(self) -> None:
        text = build_fields_text(
            user_instructions="Prefer id attributes",
            step_text="open the page",
            step_type="assertion",
            previous_steps=[],
            group_prompt=None,
            snapshot="- snap",
            page_url=None,
            cheat_sheet="# sheet",
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert text.startswith("STEP TYPE: assertion\nSTEP:\nopen the page")  # no blank line between
        assert "PAGE URL" not in text  # None URL — no line
        assert "HISTORY" not in text  # empty history — no block
        assert "RECOMMENDATION" not in text
        assert "USER GUIDANCE" not in text


class TestBuildFieldsTextUserInstructions:
    """Logic tests: the USER INSTRUCTIONS block placement and omission."""

    def test_build_fields_text_places_user_instructions_after_cheat_sheet(self) -> None:
        text = build_fields_text(
            USER_INSTRUCTIONS,
            "нажать Войти",
            "action",
            [ScenarioStep(sentence="открыть страницу")],
            group_prompt=None,
            snapshot="- button 'Войти'",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert text.index("CHEAT SHEET:") < text.index("USER INSTRUCTIONS:")
        assert f"USER INSTRUCTIONS:\n{USER_INSTRUCTIONS}" in text

    def test_build_fields_text_omits_block_when_instructions_empty(self) -> None:
        text = build_fields_text(
            "",
            "нажать Войти",
            "action",
            [],
            group_prompt=None,
            snapshot="- button 'Войти'",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert "USER INSTRUCTIONS" not in text
        assert text.endswith(CHEAT_SHEET)  # the cheat sheet stays the closing block

    def test_build_fields_places_cheat_sheet_after_scenario_inputs_before_instructions(self) -> None:
        text = build_fields_text(
            "prefer role locators",
            "open the videos page",
            "action",
            [ScenarioStep(sentence="open the home page")],
            group_prompt=None,
            snapshot="- tree",
            page_url=None,
            cheat_sheet="…reference…",
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert (
            text.index("STEP TYPE: action\nSTEP:\n")
            < text.index("PREVIOUS STEPS:\n")
            < text.index("PAGE SNAPSHOT:\n")
            < text.index("CHEAT SHEET:\n…reference…")
            < text.index("USER INSTRUCTIONS:\nprefer role locators")
        )
        assert text.startswith("STEP TYPE: action\nSTEP:")
        assert ("PAGE" + " API") not in text  # the dead block header, assembled — no literal for the sweep


class TestBuildClassificationFieldsUserInstructions:
    """Logic tests: the USER INSTRUCTIONS block placement in classification fields."""

    def test_build_classification_fields_places_user_instructions_last(self) -> None:
        text = build_classification_fields(
            USER_INSTRUCTIONS,
            "нажать Войти",
            STEP_CODE,
            "AssertionError: boom",
            "- button 'Войти'",
        )

        assert text.endswith(f"USER INSTRUCTIONS:\n{USER_INSTRUCTIONS}")
        assert text.index("PAGE SNAPSHOT:") < text.index("USER INSTRUCTIONS:")

    def test_build_classification_fields_omits_block_when_instructions_empty(self) -> None:
        text = build_classification_fields("", "нажать Войти", STEP_CODE, "AssertionError: boom", "- button 'Войти'")

        assert "USER INSTRUCTIONS" not in text
        assert text.endswith("- button 'Войти'")  # the snapshot section stays the closing section


class TestBuildComplianceFieldsContract:
    """Contract tests: the compliance builder carries the fixed port parameter list."""

    def test_build_compliance_fields_accepts_the_port_parameter_list(self) -> None:
        parameters = inspect.signature(build_compliance_fields).parameters

        assert list(parameters) == ["user_instructions", "step_text", "step_type", "attempt_history", "code"]
        assert parameters["step_type"].annotation is str
        assert parameters["attempt_history"].annotation == list[str]


class TestBuildComplianceFields:
    """Logic tests: the four fixed blocks with the STEP TYPE line and the attempt history."""

    def test_build_compliance_fields_renders_four_blocks_with_step_type_line(self) -> None:
        text = build_compliance_fields(
            "Prefer id attributes",
            "the «Welcome back» message appears",
            "assertion",
            [ATTEMPT_RECORD],
            STEP_CODE,
        )

        assert (
            text.index("INSTRUCTIONS:")
            < text.index("STEP TYPE:")
            < text.index("STEP:")
            < text.index("ATTEMPT HISTORY:")
            < text.index("CODE:")
        )
        assert text.startswith("INSTRUCTIONS:")
        assert "STEP TYPE: assertion\nSTEP:" in text  # the STEP TYPE line rides inside the STEP block
        assert f"ATTEMPT HISTORY:\n{ATTEMPT_RECORD}" in text

    def test_build_compliance_fields_omits_attempt_history_block_when_empty(self) -> None:
        text = build_compliance_fields(
            "Prefer id attributes",
            "open the page",
            "action",
            [],
            STEP_CODE,
        )

        assert "ATTEMPT HISTORY" not in text
        assert text == (
            "INSTRUCTIONS:\nPrefer id attributes\n\nSTEP TYPE: action\nSTEP:\nopen the page\n\nCODE:\n" + STEP_CODE
        )

    def test_build_compliance_fields_renders_the_fixed_order_without_history(self) -> None:
        text = build_compliance_fields("i", "s", "action", [], "c")

        assert text == "INSTRUCTIONS:\ni\n\nSTEP TYPE: action\nSTEP:\ns\n\nCODE:\nc"  # one optional block


class TestBuildFieldsTextRegenerationInputs:
    """Logic tests: the HISTORY / RECOMMENDATION / USER GUIDANCE blocks."""

    def test_build_fields_renders_new_blocks_in_fixed_order(self) -> None:
        text = build_fields_text(
            "style",
            "нажать Войти",
            "action",
            [ScenarioStep(sentence="открыть страницу")],
            group_prompt=None,
            snapshot="- button 'Войти'",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=["h1", "h2"],
            recommendation="rec",
            guidance="do this",
        )

        assert (
            text.index("CHEAT SHEET:")
            < text.index("USER INSTRUCTIONS:")
            < text.index("HISTORY:")
            < text.index("RECOMMENDATION:")
            < text.index("USER GUIDANCE:")
        )
        assert "HISTORY:\nh1\nh2" in text  # entries joined with newlines

    def test_build_fields_omits_the_new_blocks_when_inputs_empty(self) -> None:
        text = build_fields_text(
            "",
            "нажать Войти",
            "action",
            [],
            group_prompt=None,
            snapshot="- button 'Войти'",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert "HISTORY" not in text
        assert "RECOMMENDATION" not in text
        assert "USER GUIDANCE" not in text
        assert text.endswith(CHEAT_SHEET)  # the cheat sheet stays the closing block


class TestBuildFieldsTextPageUrl:
    """Logic tests: the PAGE URL line in the scenario part, after the snapshot section."""

    def test_build_fields_places_page_url_line_after_snapshot(self) -> None:
        text = build_fields_text(
            user_instructions="",
            step_text="s",
            step_type="action",
            previous_steps=[],
            group_prompt=None,
            snapshot="- body",
            page_url="https://x.test/a",
            cheat_sheet="CS",
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert (
            text.index("STEP:\n")
            < text.index("PREVIOUS STEPS:\n")
            < text.index("PAGE SNAPSHOT:\n- body")
            < text.index("PAGE URL: https://x.test/a")
            < text.index("CHEAT SHEET:\nCS")
        )  # the URL is its own paragraph between the snapshot and the cheat sheet

    @pytest.mark.parametrize("page_url", [None, ""])
    def test_build_fields_omits_the_page_url_line_without_a_url(self, page_url: str | None) -> None:
        text = build_fields_text(
            user_instructions="",
            step_text="s",
            step_type="action",
            previous_steps=[],
            group_prompt=None,
            snapshot="- body",
            page_url=page_url,
            cheat_sheet="CS",
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert "PAGE URL" not in text


class TestBuildFieldsTextHistoryRecords:
    """Logic tests: the HISTORY block renders full multi-line attempt records verbatim."""

    def test_build_fields_text_renders_history_between_instructions_and_recommendation(self) -> None:
        text = build_fields_text(
            user_instructions="Prefer id",
            step_text="open the page",
            step_type="action",
            previous_steps=[],
            group_prompt=None,
            snapshot="- snap",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[ATTEMPT_RECORD],
            recommendation="use role locators",
            guidance="focus on the button",
        )

        assert (
            text.index("USER INSTRUCTIONS:")
            < text.index("HISTORY:")
            < text.index("RECOMMENDATION:")
            < text.index("USER GUIDANCE:")
        )
        assert "HISTORY:\nexecution failed\nurl: https://a.example -> https://b.example" in text

    def test_history_block_renders_full_multi_line_records(self) -> None:
        record1 = (
            "execution failed\n"
            "url: https://a.example -> https://b.example\n"
            'code:\ndef step(page) -> None:\n    page.get_by_role("button").hover()\n'
            "error:\nTimeoutError: click timed out"
        )
        record2 = (
            "rejected by the engineer, not executed\n"
            "url: https://s.example -> https://s.example\n"
            'code:\ndef step(page) -> None:\n    page.get_by_role("button").click()\n'
        )

        text = build_fields_text(
            "",
            "s",
            "action",
            [],
            group_prompt=None,
            snapshot="- body",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[record1, record2],
            recommendation=None,
            guidance=None,
        )

        assert text.endswith("HISTORY:\n" + record1 + "\n" + record2)  # both records verbatim, order preserved
        for line in (*record1.splitlines(), *record2.splitlines()):
            assert line in text  # every code and error line survives — no collapsing, no truncation


class TestTypedScenarioRecords:
    """Logic tests: the typed scenario records render marked and plain."""

    MIXED_RECORDS: ClassVar[list[ScenarioStep]] = [
        ScenarioStep(sentence="open the login page"),
        ScenarioStep(sentence="fill the email field", group_prompt="the order form group"),
    ]
    MARKED_RENDER = "PREVIOUS STEPS:\n- open the login page\n- fill the email field [group step — the order form group]"

    def test_typed_scenario_records_render_marked_and_plain(self) -> None:
        plain = build_fields_text(
            user_instructions="",
            step_text="submit the form",
            step_type="action",
            previous_steps=self.MIXED_RECORDS,
            group_prompt=None,
            snapshot="- snap",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        # the membership is a property of the record — rendered even without a current group framing
        assert self.MARKED_RENDER in plain
        assert "GROUP PROMPT" not in plain  # no framing without a group prompt

        framed = build_fields_text(
            user_instructions="",
            step_text="submit the form",
            step_type="action",
            previous_steps=self.MIXED_RECORDS,
            group_prompt="the order form group",
            snapshot="- snap",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        # the GROUP PROMPT block renders immediately before PREVIOUS STEPS — the section right above it
        assert "GROUP PROMPT:\nthe order form group\n\nPREVIOUS STEPS:" in framed
        assert framed.index("STEP:\nsubmit the form") < framed.index("GROUP PROMPT:")
        assert framed.index("GROUP PROMPT:") < framed.index("PREVIOUS STEPS:")
        assert framed.index("PREVIOUS STEPS:") < framed.index("PAGE SNAPSHOT:")
        # the same marked entries — the framing adds the block, never rewrites the records
        assert self.MARKED_RENDER in framed
        assert "[group step — the order form group]" in framed  # the group prompt verbatim inside the mark

    def test_ordinary_records_render_byte_identical_to_the_pre_change_render(self) -> None:
        legacy = (
            "STEP TYPE: action\nSTEP:\nsubmit the form\n\n"
            "PREVIOUS STEPS:\n- open the login page\n- fill the email field\n\n"
            f"PAGE SNAPSHOT:\n- snap\n\nCHEAT SHEET:\n{CHEAT_SHEET}"
        )  # the pinned pre-change render of ordinary records — the C13 regression pin

        text = build_fields_text(
            user_instructions="",
            step_text="submit the form",
            step_type="action",
            previous_steps=[
                ScenarioStep(sentence="open the login page"),
                ScenarioStep(sentence="fill the email field"),
            ],
            group_prompt=None,
            snapshot="- snap",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert text == legacy

    def test_empty_scenario_history_stays_explicit(self) -> None:
        text = build_fields_text(
            user_instructions="",
            step_text="s",
            step_type="action",
            previous_steps=[],
            group_prompt=None,
            snapshot="- snap",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert "PREVIOUS STEPS:\n(none)" in text


class TestBuildGroupDiagnosisFieldsContract:
    """Contract tests: the diagnosis builder carries the fixed port parameter list."""

    def test_build_group_diagnosis_fields_accepts_the_port_parameter_list(self) -> None:
        parameters = inspect.signature(build_group_diagnosis_fields).parameters

        assert list(parameters) == [
            "user_instructions",
            "group_prompt",
            "group_steps",
            "step_text",
            "attempt_history",
            "snapshot",
        ]
        assert parameters["group_prompt"].annotation is str
        assert parameters["group_steps"].annotation == list[str]
        assert parameters["attempt_history"].annotation == list[str]


class TestBuildGroupDiagnosisFields:
    """Logic tests: the diagnosis request sections in the fixed order."""

    GROUP_STEPS: ClassVar[list[str]] = [
        "accept the cookie banner\noutcome: passed\nurl: https://a.example -> https://a.example",
        "the status shows order confirmed\noutcome: failed\nurl: https://a.example -> https://b.example",
    ]

    def test_renders_the_fixed_order_with_instructions_last(self) -> None:
        text = build_group_diagnosis_fields(
            "answer strictly",
            "the checkout flow",
            self.GROUP_STEPS,
            "the status shows order confirmed",
            [ATTEMPT_RECORD],
            "- heading «Order»",
        )

        assert (
            text.index("GROUP PROMPT:\nthe checkout flow")
            < text.index("GROUP STEPS:\n")
            < text.index("STEP:\nthe status shows order confirmed")
            < text.index("HISTORY:\n")
            < text.index("PAGE SNAPSHOT:\n- heading «Order»")
            < text.index("USER INSTRUCTIONS:\nanswer strictly")
        )
        assert text.endswith("USER INSTRUCTIONS:\nanswer strictly")  # the block is appended last
        # every trace record verbatim — no collapsing, no truncation
        assert self.GROUP_STEPS[0] in text
        assert self.GROUP_STEPS[1] in text
        assert f"HISTORY:\n{ATTEMPT_RECORD}" in text

    def test_omits_instructions_and_history_blocks_when_empty(self) -> None:
        text = build_group_diagnosis_fields("", "the checkout flow", ["trace record"], "s", [], "- snap")

        assert "USER INSTRUCTIONS" not in text
        assert "HISTORY" not in text
        assert text.endswith("PAGE SNAPSHOT:\n- snap")  # the snapshot section stays the closing section
        assert "GROUP STEPS:\ntrace record" in text

    def test_empty_trace_list_stays_explicit(self) -> None:
        text = build_group_diagnosis_fields("", "g", [], "s", [], "- snap")

        assert "GROUP STEPS:\n(none)" in text


class TestParseClassificationFixableLabel:
    """Logic tests: the fixable label parses; unrecognized labels stay unparsable."""

    def test_parse_classification_accepts_fixable_label(self) -> None:
        parsed = parse_classification_line("fixable | ambiguous locator | use role locator")

        assert parsed == ("fixable", "ambiguous locator", "use role locator")
        assert "fixable" in CATEGORIES

    def test_unrecognized_label_still_falls_back_to_incurable(self) -> None:
        assert parse_classification_line("mystery | why | do something") is None
        assert unparsable_classification()["category"] == "incurable"
