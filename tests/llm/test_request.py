"""Tests for the shared request-field helpers of the prettyplay.llm cell."""

from prettyplay.llm._request import build_classification_fields, build_fields_text, extract_code_block

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
