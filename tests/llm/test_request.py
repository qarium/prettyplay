"""Tests for the shared request-field helpers of the prettyplay.llm cell."""

import inspect

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
    """Contract tests: the builder carries the cheat_sheet slot at the fixed position."""

    def test_build_fields_text_accepts_cheat_sheet(self) -> None:
        parameters = inspect.signature(build_fields_text).parameters
        names = list(parameters)

        assert "cheat_sheet" in names
        assert "page_api" not in names
        assert names[names.index("snapshot") + 1] == "cheat_sheet"  # after the scenario inputs
        assert names[names.index("cheat_sheet") + 1] == "existing_code"
        assert parameters["cheat_sheet"].annotation is str


class TestBuildFieldsTextUserInstructions:
    """Logic tests: the USER INSTRUCTIONS block placement and omission."""

    def test_build_fields_text_places_user_instructions_after_cheat_sheet(self) -> None:
        text = build_fields_text(
            USER_INSTRUCTIONS,
            "нажать Войти",
            ["открыть страницу"],
            "- button 'Войти'",
            CHEAT_SHEET,
            "def step(page) -> None:\n    pass\n",
            "AssertionError: boom",
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
            CHEAT_SHEET,
            "def step(page) -> None:\n    pass\n",
            "AssertionError: boom",
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
            "…reference…",
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
        assert "PAGE API" not in text


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
            CHEAT_SHEET,
            "old code",
            "err",
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
            CHEAT_SHEET,
            "old code",
            "err",
            recommendation=None,
            guidance=None,
            guidance_history=[],
        )

        assert "RECOMMENDATION" not in text
        assert "USER GUIDANCE" not in text
        assert "HISTORY" not in text
        assert text.index("ERROR:") == text.rindex("ERROR:")  # ERROR stays the closing block


class TestParseClassificationFixableLabel:
    """Logic tests: the fixable label parses; unrecognized labels stay unparsable."""

    def test_parse_classification_accepts_fixable_label(self) -> None:
        parsed = parse_classification_line("fixable | ambiguous locator | use role locator")

        assert parsed == ("fixable", "ambiguous locator", "use role locator")
        assert "fixable" in CATEGORIES

    def test_unrecognized_label_still_falls_back_to_incurable(self) -> None:
        assert parse_classification_line("mystery | why | do something") is None
        assert unparsable_classification()["category"] == "incurable"
