"""Shared request-field building for the LLM provider implementations."""

import base64
import re

from ..failures import LLMUnavailableError
from .models import ScenarioStep

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
    step_type: str,
    previous_steps: list[ScenarioStep],
    group_prompt: str | None,
    snapshot: str,
    page_url: str | None,
    cheat_sheet: str,
    attempt_history: list[str],
    recommendation: str | None,
    guidance: str | None,
) -> str:
    """Build the plain-text generation request fields shared by both providers.

    Args:
        user_instructions: the project's code style instructions from the
            generation_prompt setting; empty — the request carries no
            instructions block, non-empty — rendered verbatim as a separate
            USER INSTRUCTIONS block after the CHEAT SHEET block.
        step_text: the raw sentence of the step to generate, as passed by
            the calling engine — never the normalized addressing form.
        step_type: the type of the step; rendered as a STEP TYPE line
            immediately before the STEP line, inside the scenario section.
        previous_steps: the typed scenario records of the previous steps of
            the test, in execution order — each the raw sentence plus its
            permanent group membership; an entry carrying a group prompt
            renders marked as a group step, an ordinary entry renders its
            sentence alone, identically whether or not this request carries
            a group framing.
        group_prompt: the group prompt of the current step's group; None —
            an ordinary step, no GROUP PROMPT block; non-empty — rendered
            verbatim as a separate GROUP PROMPT block immediately before
            the PREVIOUS STEPS block.
        snapshot: the accessibility snapshot of the current page.
        page_url: the current URL of the page; non-empty — rendered as its
            own PAGE URL line immediately after the PAGE SNAPSHOT section;
            None or empty — no line.
        cheat_sheet: the compact standard Playwright sync API reference
            supplied by the calling engine — guidance, not an allowlist.
        attempt_history: the rendered per-step attempt records — every
            record a complete multi-line verbatim record composed by the
            calling engine, the original cached code anchored as record 0
            when it exists, the last record the code being fixed;
            non-empty — rendered as a separate HISTORY block after the
            USER INSTRUCTIONS block with the records joined by newlines,
            every record verbatim, no collapsing, no size limits; empty —
            no block; the list takes the place of the former
            existing_code, error and guidance_history inputs.
        recommendation: the diagnosis of the classification that preceded
            the regeneration; non-empty — rendered as a separate
            RECOMMENDATION block after the HISTORY block, None — no block.
        guidance: the engineer guidance message of the interactive steering;
            non-empty — rendered as a separate USER GUIDANCE block, None — no
            block.

    Returns:
        The request fields as one text with the STEP TYPE line, the STEP
        section, the optional GROUP PROMPT section, the PREVIOUS STEPS /
        PAGE SNAPSHOT sections, the optional PAGE URL line, the CHEAT SHEET
        section and the optional USER INSTRUCTIONS / HISTORY /
        RECOMMENDATION / USER GUIDANCE sections — a non-empty input renders
        its named block.
    """
    sections = [
        f"STEP TYPE: {step_type}\nSTEP:\n{step_text}",
        *([f"GROUP PROMPT:\n{group_prompt}"] if group_prompt else []),
        _format_previous_steps(previous_steps),
        f"PAGE SNAPSHOT:\n{snapshot}",
        *([f"PAGE URL: {page_url}"] if page_url else []),
        f"CHEAT SHEET:\n{cheat_sheet}",
    ]

    if user_instructions:
        sections.append(f"USER INSTRUCTIONS:\n{user_instructions}")
    if attempt_history:
        sections.append("HISTORY:\n" + "\n".join(attempt_history))
    if recommendation:
        sections.append(f"RECOMMENDATION:\n{recommendation}")
    if guidance:
        sections.append(f"USER GUIDANCE:\n{guidance}")

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


def build_group_diagnosis_fields(  # noqa: PLR0913, PLR0917 — the parameters mirror the fixed port signature
    user_instructions: str,
    group_prompt: str,
    group_steps: list[str],
    step_text: str,
    attempt_history: list[str],
    snapshot: str,
) -> str:
    """Build the plain-text group diagnosis request fields shared by both providers.

    Args:
        user_instructions: the project's classification guidance from the
            classification_prompt setting; empty — the request carries no
            instructions block, non-empty — rendered verbatim as a separate
            USER INSTRUCTIONS block placed last of the user content,
            identically in both implementations.
        group_prompt: the group prompt of the diagnosed group, verbatim.
        group_steps: the composed verbatim trace records of the group's
            steps in execution order — each the sentence, the outcome and
            the URL before -> after transition, supplied by the calling
            engine.
        step_text: the raw sentence of the failed step.
        attempt_history: the rendered per-step attempt records of the
            failed step — every record a complete multi-line verbatim
            record composed by the calling engine; non-empty — rendered as
            a separate HISTORY block with the records joined by newlines,
            every record verbatim, no collapsing, no size limits; empty —
            no block.
        snapshot: the accessibility snapshot of the current page.

    Returns:
        The request fields as one text with the GROUP PROMPT, GROUP STEPS,
        STEP, HISTORY (when non-empty) and PAGE SNAPSHOT sections and the
        optional USER INSTRUCTIONS section last — the screenshot rides the
        SDK image part of the request, never this text.
    """
    sections = [
        f"GROUP PROMPT:\n{group_prompt}",
        _format_group_steps(group_steps),
        f"STEP:\n{step_text}",
        *(["HISTORY:\n" + "\n".join(attempt_history)] if attempt_history else []),
        f"PAGE SNAPSHOT:\n{snapshot}",
    ]

    if user_instructions:
        sections.append(f"USER INSTRUCTIONS:\n{user_instructions}")  # last

    return "\n\n".join(sections)


def build_compliance_fields(
    user_instructions: str,
    step_text: str,
    step_type: str,
    attempt_history: list[str],
    code: str,
) -> str:
    """Build the plain-text compliance verdict request fields shared by both providers.

    Args:
        user_instructions: the project's generation instructions from the
            generation_prompt setting; the calling engine guarantees
            non-empty — the gate never runs on empty instructions, so the
            block always renders.
        step_text: the raw sentence of the generated step.
        step_type: the type of the step; rendered as a STEP TYPE line
            immediately before the STEP line, inside the STEP block.
        attempt_history: the rendered per-step attempt records — the ground
            truth of what was already tried; non-empty — rendered as a
            separate ATTEMPT HISTORY block with the records joined by
            newlines, every record verbatim; empty — no block.
        code: the successfully executed candidate code.

    Returns:
        The request fields as one text with INSTRUCTIONS, STEP (with its
        STEP TYPE line), ATTEMPT HISTORY and CODE sections in this fixed
        order — the ATTEMPT HISTORY block omitted when the history is
        empty, identically in both implementations.
    """
    sections = [
        f"INSTRUCTIONS:\n{user_instructions}",
        f"STEP TYPE: {step_type}\nSTEP:\n{step_text}",
    ]

    if attempt_history:
        sections.append("ATTEMPT HISTORY:\n" + "\n".join(attempt_history))
    sections.append(f"CODE:\n{code}")

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


def _format_previous_steps(previous_steps: list[ScenarioStep]) -> str:
    """Render the scenario context section; an empty history stays explicit.

    The group membership is a property of the record: an entry carrying a
    group prompt renders marked as a group step, an ordinary entry renders
    its sentence alone — identically whether or not the surrounding request
    carries a group framing.
    """
    if not previous_steps:
        return "PREVIOUS STEPS:\n(none)"

    listed = "\n".join(_previous_step_line(record) for record in previous_steps)

    return f"PREVIOUS STEPS:\n{listed}"


def _previous_step_line(record: ScenarioStep) -> str:
    """Render one scenario record — the sentence, marked when it carries group membership."""
    if record.group_prompt:
        return f"- {record.sentence} [group step — {record.group_prompt}]"

    return f"- {record.sentence}"


def _format_group_steps(group_steps: list[str]) -> str:
    """Render the group trace records section; an empty trace list stays explicit."""
    if not group_steps:
        return "GROUP STEPS:\n(none)"

    return "GROUP STEPS:\n" + "\n".join(group_steps)
