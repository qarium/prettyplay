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
    """Contract tests: the builder carries the page_url and cheat_sheet slots at their fixed positions."""

    def test_build_fields_text_accepts_cheat_sheet(self) -> None:
        parameters = inspect.signature(build_fields_text).parameters
        names = list(parameters)

        assert "cheat_sheet" in names
        assert ("page" + "_api") not in names  # the dead slot name, assembled — no literal for the sweep
        assert names[names.index("snapshot") + 1] == "page_url"  # after the scenario inputs
        assert names[names.index("page_url") + 1] == "cheat_sheet"
        assert names[names.index("cheat_sheet") + 1] == "existing_code"
        assert parameters["cheat_sheet"].annotation is str
        assert parameters["page_url"].annotation == parameters["existing_code"].annotation  # str | None


class TestBuildFieldsTextUserInstructions:
    """Logic tests: the USER INSTRUCTIONS block placement and omission."""

    def test_build_fields_text_places_user_instructions_after_cheat_sheet(self) -> None:
        text = build_fields_text(
            USER_INSTRUCTIONS,
            "нажать Войти",
            ["открыть страницу"],
            "- button 'Войти'",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            existing_code="def step(page) -> None:\n    pass\n",
            error="AssertionError: boom",
            recommendation=None,
            guidance=None,
            guidance_history=[],
        )

        assert text.index("CHEAT SHEET:") < text.index("USER INSTRUCTIONS:") < text.index("CODE:")
        assert f"USER INSTRUCTIONS:\n{USER_INSTRUCTIONS}" in text

    def test_build_fields_text_omits_block_when_instructions_empty(self) -> None:
        text = build_fields_text(
            "",
            "нажать Войти",
            [],
            "- button 'Войти'",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            existing_code="def step(page) -> None:\n    pass\n",
            error="AssertionError: boom",
            recommendation=None,
            guidance=None,
            guidance_history=[],
        )

        assert "USER INSTRUCTIONS" not in text
        assert text.index("CHEAT SHEET:") < text.index("CODE:")

    def test_build_fields_places_cheat_sheet_after_scenario_inputs_before_instructions(self) -> None:
        text = build_fields_text(
            "prefer role locators",
            "open the videos page",
            ["open the home page"],
            "- tree",
            page_url=None,
            cheat_sheet="…reference…",
            existing_code=None,
            error=None,
            recommendation=None,
            guidance=None,
            guidance_history=[],
        )

        assert (
            text.index("STEP:\n")
            < text.index("PREVIOUS STEPS:\n")
            < text.index("PAGE SNAPSHOT:\n")
            < text.index("CHEAT SHEET:\n…reference…")
            < text.index("USER INSTRUCTIONS:\nprefer role locators")
        )
        assert text.startswith("STEP:")
        assert ("PAGE" + " API") not in text  # the dead block header, assembled — no literal for the sweep


class TestBuildClassificationFieldsUserInstructions:
    """Logic tests: the USER INSTRUCTIONS block placement in classification fields."""

    def test_build_classification_fields_places_user_instructions_last(self) -> None:
        text = build_classification_fields(
            USER_INSTRUCTIONS,
            "нажать Войти",
            "def step(page) -> None:\n    pass\n",
            "AssertionError: boom",
            "- button 'Войти'",
        )

        assert text.endswith(f"USER INSTRUCTIONS:\n{USER_INSTRUCTIONS}")
        assert text.index("PAGE SNAPSHOT:") < text.index("USER INSTRUCTIONS:")

    def test_build_classification_fields_omits_block_when_instructions_empty(self) -> None:
        text = build_classification_fields(
            "", "нажать Войти", "def step(page) -> None:\n    pass\n", "AssertionError: boom", "- button 'Войти'"
        )

        assert "USER INSTRUCTIONS" not in text
        assert text.endswith("- button 'Войти'")  # the snapshot section stays the closing section


class TestBuildComplianceFields:
    """Contract and logic tests: the compliance request carries the fixed three blocks."""

    def test_build_compliance_fields_returns_the_fixed_block_order(self) -> None:
        text = build_compliance_fields(
            "prefer data-test-id",
            "нажать Войти",
            "def step(page) -> None:\n    pass\n",
        )

        assert text == (
            "INSTRUCTIONS:\nprefer data-test-id\n\nSTEP:\nнажать Войти\n\nCODE:\ndef step(page) -> None:\n    pass\n"
        )

    def test_build_compliance_fields_renders_every_block_regardless_of_content(self) -> None:
        text = build_compliance_fields("i", "s", "c")

        assert text == "INSTRUCTIONS:\ni\n\nSTEP:\ns\n\nCODE:\nc"  # no optional blocks


class TestBuildFieldsTextSteeringInputs:
    """Logic tests: the RECOMMENDATION / USER GUIDANCE / HISTORY blocks after ERROR."""

    def test_build_fields_renders_new_blocks_in_fixed_order(self) -> None:
        text = build_fields_text(
            "style",
            "нажать Войти",
            ["открыть страницу"],
            "- button 'Войти'",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            existing_code="old code",
            error="err",
            recommendation="rec",
            guidance="do this",
            guidance_history=["h1", "h2"],
        )

        assert (
            text.index("CHEAT SHEET:")
            < text.index("USER INSTRUCTIONS:")
            < text.index("CODE:")
            < text.index("ERROR:")
            < text.index("RECOMMENDATION:")
            < text.index("USER GUIDANCE:")
            < text.index("HISTORY:")
        )
        assert "HISTORY:\nh1\nh2" in text  # entries joined with newlines

    def test_build_fields_omits_the_new_blocks_when_inputs_empty(self) -> None:
        text = build_fields_text(
            "",
            "нажать Войти",
            [],
            "- button 'Войти'",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            existing_code="old code",
            error="err",
            recommendation=None,
            guidance=None,
            guidance_history=[],
        )

        assert "RECOMMENDATION" not in text
        assert "USER GUIDANCE" not in text
        assert "HISTORY" not in text
        assert text.index("ERROR:") == text.rindex("ERROR:")  # ERROR stays the closing block


class TestBuildFieldsTextPageUrl:
    """Logic tests: the PAGE URL line in the scenario part, after the snapshot section."""

    def test_build_fields_places_page_url_line_after_snapshot(self) -> None:
        text = build_fields_text(
            user_instructions="",
            step_text="s",
            previous_steps=[],
            snapshot="- body",
            page_url="https://x.test/a",
            cheat_sheet="CS",
            existing_code=None,
            error=None,
            recommendation=None,
            guidance=None,
            guidance_history=[],
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
            previous_steps=[],
            snapshot="- body",
            page_url=page_url,
            cheat_sheet="CS",
            existing_code=None,
            error=None,
            recommendation=None,
            guidance=None,
            guidance_history=[],
        )

        assert "PAGE URL" not in text


class TestBuildFieldsTextHistoryRecords:
    """Logic tests: the HISTORY block renders full multi-line turn records verbatim."""

    def test_history_block_renders_full_multi_line_records(self) -> None:
        record1 = (
            "engineer message: hover the menu first\n"
            'code:\ndef step(page) -> None:\n    page.get_by_role("button").hover()\n'
            "outcome: AssertionError: Locator expected to be visible\nActual value: display:none"
        )
        record2 = (
            "engineer message: click the item after the hover\n"
            'code:\ndef step(page) -> None:\n    page.get_by_role("button").click()\n'
            "outcome: rejected by the engineer, not executed"
        )

        text = build_fields_text(
            "",
            "s",
            [],
            "- body",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            existing_code="old code",
            error="err",
            recommendation=None,
            guidance="try hovering first",
            guidance_history=[record1, record2],
        )

        assert text.endswith("HISTORY:\n" + record1 + "\n" + record2)  # both records verbatim, order preserved
        for line in (*record1.splitlines(), *record2.splitlines()):
            assert line in text  # every code and outcome line survives — no collapsing, no truncation


class TestParseClassificationFixableLabel:
    """Logic tests: the fixable label parses; unrecognized labels stay unparsable."""

    def test_parse_classification_accepts_fixable_label(self) -> None:
        parsed = parse_classification_line("fixable | ambiguous locator | use role locator")

        assert parsed == ("fixable", "ambiguous locator", "use role locator")
        assert "fixable" in CATEGORIES

    def test_unrecognized_label_still_falls_back_to_incurable(self) -> None:
        assert parse_classification_line("mystery | why | do something") is None
        assert unparsable_classification()["category"] == "incurable"
