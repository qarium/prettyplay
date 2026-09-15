"""Tests for the shared request-field helpers of the prettyplay.llm cell."""

import inspect

import pytest
from prettyplay.llm._request import (
    CATEGORIES,
    build_classification_fields,
    build_compliance_fields,
    build_fields_text,
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
            "snapshot",
            "page_url",
            "cheat_sheet",
            "attempt_history",
            "recommendation",
            "guidance",
        ]
        assert parameters["step_type"].annotation is str
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
            ["открыть страницу"],
            "- button 'Войти'",
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
            "- button 'Войти'",
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
            ["open the home page"],
            "- tree",
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
            ["открыть страницу"],
            "- button 'Войти'",
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
            "- button 'Войти'",
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
            "- body",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[record1, record2],
            recommendation=None,
            guidance=None,
        )

        assert text.endswith("HISTORY:\n" + record1 + "\n" + record2)  # both records verbatim, order preserved
        for line in (*record1.splitlines(), *record2.splitlines()):
            assert line in text  # every code and error line survives — no collapsing, no truncation


class TestParseClassificationFixableLabel:
    """Logic tests: the fixable label parses; unrecognized labels stay unparsable."""

    def test_parse_classification_accepts_fixable_label(self) -> None:
        parsed = parse_classification_line("fixable | ambiguous locator | use role locator")

        assert parsed == ("fixable", "ambiguous locator", "use role locator")
        assert "fixable" in CATEGORIES

    def test_unrecognized_label_still_falls_back_to_incurable(self) -> None:
        assert parse_classification_line("mystery | why | do something") is None
        assert unparsable_classification()["category"] == "incurable"
