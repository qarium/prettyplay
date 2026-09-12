"""Tests for the shared request-field helpers of the prettyplay.llm cell."""

from prettyplay.llm._request import (
    CATEGORIES,
    build_classification_fields,
    build_fields_text,
    extract_code_block,
    parse_classification_line,
    unparsable_classification,
)

FENCED_CODE = "def step(page) -> None:\n    page.goto('https://example.com')\n"
USER_INSTRUCTIONS = "prefer data-test-id"


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


class TestBuildFieldsTextUserInstructions:
    """Logic tests: the USER INSTRUCTIONS block placement and omission."""

    def test_build_fields_text_places_user_instructions_after_page_api(self) -> None:
        text = build_fields_text(
            USER_INSTRUCTIONS,
            "нажать Войти",
            ["открыть страницу"],
            "- button 'Войти'",
            "page.get_by_role(role, name)",
            "def step(page) -> None:\n    pass\n",
            "AssertionError: boom",
            recommendation=None,
            guidance=None,
            guidance_history=[],
        )

        assert text.index("PAGE API:") < text.index("USER INSTRUCTIONS:") < text.index("CODE:")
        assert f"USER INSTRUCTIONS:\n{USER_INSTRUCTIONS}" in text

    def test_build_fields_text_omits_block_when_instructions_empty(self) -> None:
        text = build_fields_text(
            "",
            "нажать Войти",
            [],
            "- button 'Войти'",
            "page.get_by_role(role, name)",
            "def step(page) -> None:\n    pass\n",
            "AssertionError: boom",
            recommendation=None,
            guidance=None,
            guidance_history=[],
        )

        assert "USER INSTRUCTIONS" not in text
        assert text.index("PAGE API:") < text.index("CODE:")


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


class TestBuildFieldsTextSteeringInputs:
    """Logic tests: the RECOMMENDATION / USER GUIDANCE / HISTORY blocks after ERROR."""

    def test_build_fields_renders_new_blocks_in_fixed_order(self) -> None:
        text = build_fields_text(
            "style",
            "нажать Войти",
            ["открыть страницу"],
            "- button 'Войти'",
            "page.get_by_role(role, name)",
            "old code",
            "err",
            recommendation="rec",
            guidance="do this",
            guidance_history=["h1", "h2"],
        )

        assert (
            text.index("PAGE API:")
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
            "page.get_by_role(role, name)",
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
