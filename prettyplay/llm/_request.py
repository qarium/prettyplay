"""Shared request-field building for the LLM provider implementations."""

import base64


def build_fields_text(  # noqa: PLR0913, PLR0917 — the parameters mirror the fixed port signature
    step_text: str,
    previous_steps: list[str],
    snapshot: str,
    page_api: str,
    existing_code: str | None,
    error: str | None,
) -> str:
    """Build the plain-text generation request fields shared by both providers.

    Args:
        step_text: the sentence of the step to generate.
        previous_steps: the sentences of the previous steps of the test, in
            execution order — scenario context.
        snapshot: the accessibility snapshot of the current page.
        page_api: the exact page facade surface listing.
        existing_code: the existing step code that failed; non-empty only on
            regeneration requests.
        error: the failure description of the existing code; non-empty only
            on regeneration requests.

    Returns:
        The request fields as one text with STEP / PREVIOUS STEPS /
        PAGE SNAPSHOT / PAGE API sections and, on regeneration requests,
        CODE / ERROR sections.
    """
    sections = [
        f"STEP:\n{step_text}",
        _format_previous_steps(previous_steps),
        f"PAGE SNAPSHOT:\n{snapshot}",
        f"PAGE API:\n{page_api}",
    ]
    if existing_code is not None:
        sections.append(f"CODE:\n{existing_code}")
    if error is not None:
        sections.append(f"ERROR:\n{error}")
    return "\n\n".join(sections)


def build_classification_fields(step_text: str, code: str, error: str, snapshot: str) -> str:
    """Build the plain-text classification request fields shared by both providers.

    Args:
        step_text: the sentence of the failed step.
        code: the existing step code that failed.
        error: the human-readable description of the failure.
        snapshot: the accessibility snapshot of the current page.

    Returns:
        The request fields as one text with STEP / CODE / ERROR / PAGE
        SNAPSHOT sections.
    """
    return "\n\n".join(
        [
            f"STEP:\n{step_text}",
            f"CODE:\n{code}",
            f"ERROR:\n{error}",
            f"PAGE SNAPSHOT:\n{snapshot}",
        ]
    )


def encode_screenshot(screenshot: bytes) -> str:
    """Encode a PNG screenshot as the base64 payload of a content block.

    Args:
        screenshot: the raw PNG image bytes of the page.

    Returns:
        The base64 text of the image.
    """
    return base64.b64encode(screenshot).decode("ascii")


def parse_classification_line(answer: str) -> tuple[str, str, str] | None:
    """Parse the one-line classification answer of the form ``category | explanation | recommendation``.

    Args:
        answer: the raw completion text.

    Returns:
        The stripped (category, explanation, recommendation) triple, or None
        when the answer is not a line of the expected shape or names no
        known category — the caller applies the protective default.
    """
    categories = {"rot", "product_defect", "incurable"}
    verdict_field_count = 3

    for line in answer.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = [part.strip() for part in stripped.split("|")]
        if len(parts) == verdict_field_count and parts[0] in categories:
            return parts[0], parts[1], parts[2]
        return None

    return None


def _format_previous_steps(previous_steps: list[str]) -> str:
    """Render the scenario context section; an empty history stays explicit."""
    if not previous_steps:
        return "PREVIOUS STEPS:\n(none)"
    listed = "\n".join(f"- {sentence}" for sentence in previous_steps)
    return f"PREVIOUS STEPS:\n{listed}"
