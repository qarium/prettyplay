"""Shared request-field building for the LLM provider implementations."""

import base64
import re

from ..failures import LLMUnavailableError

#: The labels a classification category may take.
CATEGORY_ROT = "rot"
CATEGORY_PRODUCT_DEFECT = "product_defect"
CATEGORY_FIXABLE = "fixable"
CATEGORY_INCURABLE = "incurable"

#: The frozen set of the four classification labels.
CATEGORIES = frozenset({CATEGORY_ROT, CATEGORY_PRODUCT_DEFECT, CATEGORY_FIXABLE, CATEGORY_INCURABLE})

#: Field count of the one-line classification verdict.
VERDICT_FIELD_COUNT = 3

#: A fenced completion block: three backticks, an optional language tag, the body, the closing fence.
_FENCED_BLOCK = re.compile(r"```[a-zA-Z0-9_+-]*[ \t]*\r?\n(.*?)```", re.DOTALL)


def extract_code_block(answer: str) -> str:
    """Return the step code of a completion, unwrapping the markdown fence.

    Models answer generation requests with a fenced python block even when told
    to output only code, so the first fenced block of `answer` is the code; an
    answer with no closed fence is passed through verbatim — an unfenced code
    answer stays executable, an unparsable one keeps failing downstream.

    Args:
        answer: the non-empty completion text of a generation request.

    Returns:
        The code of the fixed form: the body of the first fenced block, or the
        answer itself when it carries no closed fence.
    """
    match = _FENCED_BLOCK.search(answer)

    if match is None:
        return answer

    return match.group(1)


def require_completion_text(text: str | None, provider: str) -> str:
    """Return the completion text, refusing an empty answer as a service failure.

    Args:
        text: the raw text extracted from the provider response; ``None`` or an
            empty string means the service returned no completion body.
        provider: the provider name for the failure message.

    Returns:
        The non-empty completion text.

    Raises:
        LLMUnavailableError: the completion body is missing — a null/empty
            content is an infrastructure shape, not a step verdict, so it maps
            to the same taxonomy as any other service failure.
    """
    if not text:
        raise LLMUnavailableError(f"llm unavailable: {provider} returned empty completion")

    return text


def build_fields_text(  # noqa: PLR0913, PLR0917 — the parameters mirror the fixed port signature
    user_instructions: str,
    step_text: str,
    previous_steps: list[str],
    snapshot: str,
    page_url: str | None,
    cheat_sheet: str,
    existing_code: str | None,
    error: str | None,
    recommendation: str | None,
    guidance: str | None,
    guidance_history: list[str],
) -> str:
    """Build the plain-text generation request fields shared by both providers.

    Args:
        user_instructions: the project's code style instructions from the
            generation_prompt setting; empty — the request carries no
            instructions block, non-empty — rendered verbatim as a separate
            USER INSTRUCTIONS block after the CHEAT SHEET block.
        step_text: the sentence of the step to generate.
        previous_steps: the sentences of the previous steps of the test, in
            execution order — scenario context.
        snapshot: the accessibility snapshot of the current page.
        page_url: the current URL of the page; non-empty — rendered as its
            own PAGE URL line immediately after the PAGE SNAPSHOT section;
            None or empty — no line.
        cheat_sheet: the compact standard Playwright sync API reference
            supplied by the calling engine — guidance, not an allowlist.
        existing_code: the existing step code that failed; non-empty only on
            regeneration requests.
        error: the failure description of the existing code; non-empty only on
            regeneration requests.
        recommendation: the diagnosis of the classification that preceded the
            regeneration; non-empty — rendered as a separate RECOMMENDATION
            block after the CODE and ERROR blocks, None — no block.
        guidance: the engineer guidance message of the interactive steering;
            non-empty — rendered as a separate USER GUIDANCE block, None — no
            block.
        guidance_history: the accumulated steering turns — each a complete
            multi-line turn record: the engineer message, the complete
            generated code, the complete outcome; composed by the calling
            steering; non-empty — rendered as a separate HISTORY block after
            the USER GUIDANCE block with the records joined by newlines,
            every record verbatim, no collapsing, no size limits; empty — no
            block.

    Returns:
        The request fields as one text with STEP / PREVIOUS STEPS /
        PAGE SNAPSHOT sections, the optional PAGE URL line, the CHEAT SHEET
        section, the optional USER INSTRUCTIONS section and, on regeneration
        and steering requests, CODE / ERROR / RECOMMENDATION /
        USER GUIDANCE / HISTORY sections — a non-empty input renders its
        named block.
    """
    sections = [
        f"STEP:\n{step_text}",
        _format_previous_steps(previous_steps),
        f"PAGE SNAPSHOT:\n{snapshot}",
        *([f"PAGE URL: {page_url}"] if page_url else []),
        f"CHEAT SHEET:\n{cheat_sheet}",
    ]

    if user_instructions:
        sections.append(f"USER INSTRUCTIONS:\n{user_instructions}")
    if existing_code is not None:
        sections.append(f"CODE:\n{existing_code}")
    if error is not None:
        sections.append(f"ERROR:\n{error}")
    if recommendation:
        sections.append(f"RECOMMENDATION:\n{recommendation}")
    if guidance:
        sections.append(f"USER GUIDANCE:\n{guidance}")
    if guidance_history:
        sections.append("HISTORY:\n" + "\n".join(guidance_history))

    return "\n\n".join(sections)


def build_classification_fields(user_instructions: str, step_text: str, code: str, error: str, snapshot: str) -> str:
    """Build the plain-text classification request fields shared by both providers.

    Args:
        user_instructions: the project's classification guidance from the
            classification_prompt setting; empty — the request carries no
            instructions block, non-empty — rendered verbatim as a separate
            USER INSTRUCTIONS block placed last of the user content,
            identically in both implementations.
        step_text: the sentence of the failed step.
        code: the existing step code that failed.
        error: the human-readable description of the failure.
        snapshot: the accessibility snapshot of the current page.

    Returns:
        The request fields as one text with STEP / CODE / ERROR / PAGE
        SNAPSHOT sections and the optional USER INSTRUCTIONS section last.
    """
    sections = [
        f"STEP:\n{step_text}",
        f"CODE:\n{code}",
        f"ERROR:\n{error}",
        f"PAGE SNAPSHOT:\n{snapshot}",
    ]

    if user_instructions:
        sections.append(f"USER INSTRUCTIONS:\n{user_instructions}")  # last

    return "\n\n".join(sections)


def build_compliance_fields(user_instructions: str, step_text: str, code: str) -> str:
    """Build the plain-text compliance verdict request fields shared by both providers.

    Args:
        user_instructions: the project's generation instructions from the
            generation_prompt setting; the calling engine guarantees
            non-empty — the gate never runs on empty instructions, so the
            block always renders.
        step_text: the sentence of the generated step.
        code: the successfully executed candidate code.

    Returns:
        The request fields as one text with INSTRUCTIONS / STEP / CODE
        sections in this fixed order — no optional blocks, identically in
        both implementations.
    """
    sections = [
        f"INSTRUCTIONS:\n{user_instructions}",
        f"STEP:\n{step_text}",
        f"CODE:\n{code}",
    ]

    return "\n\n".join(sections)


def encode_screenshot(screenshot: bytes) -> str:
    """Encode a PNG screenshot as the base64 payload of a content block.

    Args:
        screenshot: the raw PNG image bytes of the page.

    Returns:
        The base64 text of the image.
    """
    return base64.b64encode(screenshot).decode("ascii")


def openai_user_content(text: str, screenshot: bytes | None) -> str | list[dict]:
    """Wrap the request fields as an openai user content payload.

    Args:
        text: the plain-text request fields shared with the anthropic provider.
        screenshot: an optional PNG image of the page; passed only when the
            project enables screenshots.

    Returns:
        The plain text when no image is attached, otherwise the openai
        content block list with the data-URI image block.
    """
    if screenshot is None:
        return text

    return [
        {"type": "text", "text": text},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{encode_screenshot(screenshot)}"},
        },
    ]


def unparsable_classification() -> dict[str, str]:
    """Return the protective verdict fields for an unparsable provider answer.

    Returns:
        The incurable fallback verdict fields; both providers construct the
        same defaults, so the field set is shared.
    """
    return {
        "category": CATEGORY_INCURABLE,
        "explanation": "classification verdict unparsable",
        "recommendation": "re-run the step or check the provider answer",
    }


def parse_classification_line(answer: str) -> tuple[str, str, str] | None:
    """Parse the one-line classification answer of the form ``category | explanation | recommendation``.

    Args:
        answer: the raw completion text.

    Returns:
        The stripped (category, explanation, recommendation) triple, or None
        when the answer is not a line of the expected shape or names no
        known category — the caller applies the protective default.
    """
    line = next((stripped for stripped in (line.strip() for line in answer.splitlines()) if stripped), "")
    parts = [part.strip() for part in line.split("|")]

    if len(parts) == VERDICT_FIELD_COUNT and parts[0] in CATEGORIES:
        return parts[0], parts[1], parts[2]

    return None


def _format_previous_steps(previous_steps: list[str]) -> str:
    """Render the scenario context section; an empty history stays explicit."""
    if not previous_steps:
        return "PREVIOUS STEPS:\n(none)"

    listed = "\n".join(f"- {sentence}" for sentence in previous_steps)

    return f"PREVIOUS STEPS:\n{listed}"
