"""Shared request-field building and transport failure classification for the LLM providers."""

import base64
import logging
import math
import random
import re
import time
from collections.abc import Callable
from typing import NamedTuple, TypeVar

import anthropic
import openai
from pydantic import BaseModel, ConfigDict

from ..failures import LLMUnavailableError
from .models import ScenarioStep

logger = logging.getLogger("prettyplay")

#: The response type of one SDK request send — the generic pass-through type of the retry loop.
T = TypeVar("T")

#: The labels a classification category may take.
CATEGORY_ROT = "rot"
CATEGORY_PRODUCT_DEFECT = "product_defect"
CATEGORY_FIXABLE = "fixable"
CATEGORY_INCURABLE = "incurable"

#: The frozen set of the four classification labels.
CATEGORIES = frozenset({CATEGORY_ROT, CATEGORY_PRODUCT_DEFECT, CATEGORY_FIXABLE, CATEGORY_INCURABLE})

#: The transport failure labels of the retryable family.
TRANSPORT_CONNECTION = "connection"
TRANSPORT_TIMEOUT = "timeout"
TRANSPORT_RATE_LIMIT = "rate_limit"
TRANSPORT_SERVER_ERROR = "server_error"

#: The transport failure labels of the permanent family.
TRANSPORT_AUTHENTICATION = "authentication"
TRANSPORT_PERMISSION_DENIED = "permission_denied"
TRANSPORT_INVALID_REQUEST = "invalid_request"
TRANSPORT_NOT_FOUND = "not_found"
TRANSPORT_QUOTA_EXHAUSTED = "quota_exhausted"

#: The frozen set of the four retryable transport labels.
RETRYABLE_TRANSPORT_CATEGORIES = frozenset(
    {TRANSPORT_CONNECTION, TRANSPORT_TIMEOUT, TRANSPORT_RATE_LIMIT, TRANSPORT_SERVER_ERROR}
)

#: The frozen set of the five permanent transport labels.
PERMANENT_TRANSPORT_CATEGORIES = frozenset(
    {
        TRANSPORT_AUTHENTICATION,
        TRANSPORT_PERMISSION_DENIED,
        TRANSPORT_INVALID_REQUEST,
        TRANSPORT_NOT_FOUND,
        TRANSPORT_QUOTA_EXHAUSTED,
    }
)

#: The HTTP status of a request timeout — neither SDK carries a 408 subclass.
_STATUS_REQUEST_TIMEOUT = 408

#: The HTTP status of a rate-limited request.
_STATUS_RATE_LIMIT = 429

#: The inclusive bounds of the HTTP server-error family.
_STATUS_SERVER_ERROR_FLOOR = 500
_STATUS_SERVER_ERROR_CEILING = 599


class _TransportLadder(NamedTuple):
    """The per-SDK exception classes and quota labels of one classification ladder."""

    status_error: type[Exception]
    timeout_error: type[Exception]
    connection_error: type[Exception]
    rate_limit_error: type[Exception]
    permanent: tuple[tuple[type[Exception], str], ...]
    quota_labels: frozenset[str]


#: The openai evidence ladder — the quota body labels and the permanent classes checked first.
_OPENAI_LADDER = _TransportLadder(
    status_error=openai.APIStatusError,
    timeout_error=openai.APITimeoutError,
    connection_error=openai.APIConnectionError,
    rate_limit_error=openai.RateLimitError,
    permanent=(
        (openai.AuthenticationError, TRANSPORT_AUTHENTICATION),
        (openai.PermissionDeniedError, TRANSPORT_PERMISSION_DENIED),
        (openai.BadRequestError, TRANSPORT_INVALID_REQUEST),
        (openai.NotFoundError, TRANSPORT_NOT_FOUND),
    ),
    quota_labels=frozenset({"insufficient_quota"}),
)

#: The anthropic evidence ladder — billing_error is the explicit quota signal of the SDK.
_ANTHROPIC_LADDER = _TransportLadder(
    status_error=anthropic.APIStatusError,
    timeout_error=anthropic.APITimeoutError,
    connection_error=anthropic.APIConnectionError,
    rate_limit_error=anthropic.RateLimitError,
    permanent=(
        (anthropic.AuthenticationError, TRANSPORT_AUTHENTICATION),
        (anthropic.PermissionDeniedError, TRANSPORT_PERMISSION_DENIED),
        (anthropic.BadRequestError, TRANSPORT_INVALID_REQUEST),
        (anthropic.NotFoundError, TRANSPORT_NOT_FOUND),
    ),
    quota_labels=frozenset({"billing_error"}),
)


class TransportFailureClassification(BaseModel):
    """The verdict of one transport failure classification of an LLM request.

    Attributes:
        category: the transport failure label — one of the closed nine-label
            set; the retryable family: connection, timeout, rate_limit and
            server_error; the permanent family: authentication,
            permission_denied, invalid_request, not_found and
            quota_exhausted; the classifiers are the only producers, so the
            label is always one of the nine — an unrecognized failure
            classifies permanent before reaching this type.
        retry_after: the parsed Retry-After seconds of the failure response;
            None — the header is absent or malformed.
    """

    model_config = ConfigDict(kw_only=True)

    category: str = ""
    retry_after: float | None = None

    @property
    def retryable(self) -> bool:
        """Return whether the category belongs to the retryable family.

        Returns:
            True for the retryable labels — the retry-or-raise decision of
            the retry loop; False for the permanent labels and the empty
            default category.
        """
        return self.category in RETRYABLE_TRANSPORT_CATEGORIES


def classify_openai_failure(error: Exception) -> TransportFailureClassification:
    """Classify one failed openai request send into a transport verdict.

    Args:
        error: the exception raised by one openai SDK request send; any
            exception classifies — a never-recognized failure is never
            blindly retried.

    Returns:
        The transport verdict. The permanent evidence matches first — an
        explicitly exhausted quota (the insufficient_quota body evidence,
        even under a retryable status such as 429), authentication failure,
        permission denial, invalid request and not found; a permanent cause
        always wins over a retryable status. Otherwise the retryable
        evidence matches — timeout, connection failure, rate limit, HTTP
        408 and any HTTP status 500 through 599. An exception matching no
        known signal classifies invalid_request. The verdict carries the
        parsed decimal Retry-After seconds of the failure response — None
        when the header is absent or malformed.
    """
    return TransportFailureClassification(
        category=_transport_category(error, _OPENAI_LADDER),
        retry_after=_extract_retry_after(error),
    )


def classify_anthropic_failure(error: Exception) -> TransportFailureClassification:
    """Classify one failed anthropic request send into a transport verdict.

    The ladder mirrors ``classify_openai_failure`` rule by rule onto the
    anthropic exception hierarchy — the same nine-label set, the same
    permanent-precedence rule, the same Retry-After handling; the quota
    evidence of this SDK is the billing_error body label.

    Args:
        error: the exception raised by one anthropic SDK request send; any
            exception classifies — a never-recognized failure is never
            blindly retried.

    Returns:
        The transport verdict. The permanent evidence matches first — an
        explicitly exhausted quota (the billing_error body evidence, even
        under a retryable status such as 429), authentication failure,
        permission denial, invalid request and not found; a permanent cause
        always wins over a retryable status. Otherwise the retryable
        evidence matches — timeout, connection failure, rate limit, HTTP
        408 and any HTTP status 500 through 599 (the anthropic 529/503/504
        responses included). An exception matching no known signal
        classifies invalid_request. The verdict carries the parsed decimal
        Retry-After seconds of the failure response — None when the header
        is absent or malformed (the non-standard retry-after-ms variant
        stays unparsed).
    """
    return TransportFailureClassification(
        category=_transport_category(error, _ANTHROPIC_LADDER),
        retry_after=_extract_retry_after(error),
    )


def _transport_category(error: Exception, ladder: _TransportLadder) -> str:
    """Decide the transport category of one exception through the evidence ladder.

    Args:
        error: the exception raised by one SDK request send.
        ladder: the per-SDK evidence classes and quota labels.

    Returns:
        The permanent label when permanent evidence matches — always
        first; otherwise the retryable label when retryable evidence
        matches; otherwise invalid_request — the permanent fallback.
    """
    permanent = _permanent_transport_category(error, ladder)

    if permanent is not None:
        return permanent

    retryable = _retryable_transport_category(error, ladder)

    return retryable if retryable is not None else TRANSPORT_INVALID_REQUEST


def _permanent_transport_category(error: Exception, ladder: _TransportLadder) -> str | None:
    """Match the permanent evidence first; a permanent cause always wins over a retryable status."""
    if not isinstance(error, ladder.status_error):
        return None

    body_evidence = [getattr(error, "code", None), getattr(error, "type", None)]
    body = getattr(error, "body", None)

    if isinstance(body, dict):
        body_evidence.extend((body.get("code"), body.get("type")))
        nested_error = body.get("error")

        if isinstance(nested_error, dict):
            body_evidence.extend((nested_error.get("code"), nested_error.get("type")))

    if any(isinstance(label, str) and label in ladder.quota_labels for label in body_evidence):
        return TRANSPORT_QUOTA_EXHAUSTED

    for error_class, category in ladder.permanent:
        if isinstance(error, error_class):
            return category

    return None


def _retryable_transport_category(error: Exception, ladder: _TransportLadder) -> str | None:
    """Match the retryable evidence; None — the exception carries no retryable signal."""
    if isinstance(error, ladder.status_error):
        if isinstance(error, ladder.rate_limit_error) or getattr(error, "status_code", None) == _STATUS_RATE_LIMIT:
            return TRANSPORT_RATE_LIMIT

        status = getattr(error, "status_code", None)

        if status == _STATUS_REQUEST_TIMEOUT:
            return TRANSPORT_TIMEOUT
        if isinstance(status, int) and _STATUS_SERVER_ERROR_FLOOR <= status <= _STATUS_SERVER_ERROR_CEILING:
            return TRANSPORT_SERVER_ERROR

        return None

    transport_errors = ((ladder.timeout_error, TRANSPORT_TIMEOUT), (ladder.connection_error, TRANSPORT_CONNECTION))

    for error_class, category in transport_errors:
        if isinstance(error, error_class):
            return category

    return None


def _extract_retry_after(error: Exception) -> float | None:
    """Extract the decimal Retry-After seconds of the failure response.

    Args:
        error: the exception raised by one SDK request send.

    Returns:
        The parsed header seconds, or None when the failure response, the
        header or the decimal value is absent — HTTP-dates and the
        anthropic retry-after-ms variant stay unparsed; the extraction is
        category-independent.
    """
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    get_header = getattr(headers, "get", None)

    if get_header is None:
        return None

    try:
        seconds = float(get_header("retry-after"))
    except (TypeError, ValueError):
        return None

    return seconds if math.isfinite(seconds) else None


#: The inclusive cap of one transport retry pause, in seconds.
_TRANSPORT_PAUSE_CAP = 10.0

#: Attempt five is the first whose uncapped base delay exceeds the pause cap.
_TRANSPORT_BASE_CAP_ATTEMPT = 5

#: The jitter fraction of the base delay — random.uniform draws up to this share on top.
_TRANSPORT_JITTER_FRACTION = 0.25


def compute_transport_pause(failed_attempt: int, retry_after: float | None) -> float:
    """Compute the wait before the next transport retry of one LLM request.

    The base delay is one second doubled per prior failure, capped at ten —
    the sequence 1, 2, 4, 8, 10, 10… seconds; a random jitter of up to a
    quarter of the base is added and the result is capped back at ten
    seconds. A valid Retry-After — positive and at most ten seconds —
    raises the pause to the indicated wait when it exceeds the computed
    delay; a value above ten never reaches this routine as a wait — the
    retry loop terminates before computing a pause.

    Args:
        failed_attempt: the one-based number of the send that just failed.
        retry_after: the parsed Retry-After seconds of the failure
            response; None or a non-positive value — no indicated wait.

    Returns:
        The pause in seconds — a float in the interval (0, 10].
    """
    base = _TRANSPORT_PAUSE_CAP if failed_attempt >= _TRANSPORT_BASE_CAP_ATTEMPT else 2.0 ** (failed_attempt - 1)

    pause = min(base + random.uniform(0.0, base * _TRANSPORT_JITTER_FRACTION), _TRANSPORT_PAUSE_CAP)

    if retry_after is not None and 0.0 < retry_after <= _TRANSPORT_PAUSE_CAP:
        pause = max(pause, retry_after)

    return pause


def send_with_retries(
    provider: str,
    operation: str,
    attempts: int,
    classify: Callable[[Exception], TransportFailureClassification],
    send: Callable[[], T],
) -> T:
    """Send one LLM request through the bounded transport retry loop.

    One logical LLM attempt of the port — generation, classification,
    group diagnosis or compliance verdict alike — resends the identical
    SDK request through this loop up to the send budget, the initial
    send included. A success returns the send response as is. A failure
    is classified first: a permanent category terminates immediately
    with the cause chained; a Retry-After above the ten second cap
    terminates before any pause is computed; the last send of the budget
    terminates with the cause chained. Otherwise the loop computes the
    pause, emits exactly one WARNING record per retry — provider,
    operation, attempt number, error category and delay; never secrets,
    never request or response contents — waits, and runs the next
    attempt. KeyboardInterrupt during a wait propagates without another
    retry; the engine attempt budgets are never consulted.

    Args:
        provider: the provider label for logs and errors — openai or
            anthropic.
        operation: the operation label for logs — generation,
            classification, group diagnosis or compliance verdict.
        attempts: the total send budget, the initial send included;
            1 disables retries.
        classify: the provider-specific transport failure classifier.
        send: the closure performing exactly one SDK request.

    Returns:
        The successful response of ``send``, passed through untouched.

    Raises:
        LLMUnavailableError: a permanent provider rejection, a
            Retry-After above the ten second cap, or the exhaustion of
            the send budget — always chained to the original SDK error.
    """
    for attempt in range(1, attempts + 1):
        try:
            return send()
        except Exception as error:
            failure = classify(error)

            if not failure.retryable:
                raise LLMUnavailableError(
                    f"llm unavailable: {provider} request failed permanently: {failure.category}"
                ) from error

            if failure.retry_after is not None and failure.retry_after > _TRANSPORT_PAUSE_CAP:
                raise LLMUnavailableError(
                    f"llm unavailable: {provider} asked to wait {failure.retry_after:g} seconds"
                    " — above the 10 second retry cap, not retrying"
                ) from error

            if attempt == attempts:
                raise LLMUnavailableError(
                    f"llm unavailable: {provider} request failed after {attempts} attempts"
                ) from error

            pause = compute_transport_pause(attempt, failure.retry_after)

            logger.warning(
                "llm request retry",
                extra={
                    "provider": provider,
                    "operation": operation,
                    "attempt": attempt,
                    "category": failure.category,
                    "delay": pause,
                },
            )

            time.sleep(pause)

    raise AssertionError(f"the retry loop of {provider} {operation} always returns or raises")


#: Field count of the one-line classification verdict.
VERDICT_FIELD_COUNT = 3

#: A fenced completion block: three backticks, an optional language tag, the body, the closing fence.
_FENCED_BLOCK = re.compile(r"```[a-zA-Z0-9_+-]*[ \t]*\r?\n(.*?)```", re.DOTALL)


def extract_code_block(answer: str) -> str:
    """Return the step code of a completion, unwrapping the markdown fence.

    Args:
        answer: the non-empty completion text of a generation request.

    Returns:
        The code of the fixed form: the body of the first fenced block, or
        the answer itself when it carries no closed fence — an unfenced
        code answer stays executable.
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
    """Render the scenario context section; an empty history stays explicit."""
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
