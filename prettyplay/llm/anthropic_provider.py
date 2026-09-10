"""The anthropic SDK implementation of the LLMProvider port."""

import os

from anthropic import Anthropic, AnthropicError

from ..config import Config
from ..failures import LLMUnavailableError
from ._request import (
    build_classification_fields,
    build_fields_text,
    encode_screenshot,
    extract_code_block,
    parse_classification_line,
    require_completion_text,
    unparsable_classification,
)
from .models import FailureClassification
from .provider import LLMProvider

REQUEST_MAX_TOKENS = 1024


def _first_text_block(response: object) -> str | None:
    """Extract the text of the first text block of an anthropic response.

    Args:
        response: the SDK response of a ``messages.create`` call.

    Returns:
        The text of the first text content block, or ``None`` when the
        response carries no text block at all (empty or non-text content).
    """
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            return getattr(block, "text", None)

    return None


class AnthropicProvider(LLMProvider):
    """The LLMProvider implementation served by the anthropic SDK.

    Full parity with :class:`OpenAIProvider`: the same operations, the same
    inputs, the same output shapes. The constructor reads no environment
    and constructs no client; the SDK client is created lazily on the first
    request, so the library starts without LLM credentials. Every service
    failure maps to :class:`~prettyplay.failures.LLMUnavailableError`
    naming the provider; the API key is read from the environment only and
    never logged.
    """

    def __init__(self, config: Config) -> None:
        """Keep the config; the SDK client stays unconstructed until the first request.

        Args:
            config: project settings; the effective models and the optional
                base_url endpoint override come from it.
        """
        self._config = config
        self._client: Anthropic | None = None

    def _get_client(self) -> Anthropic:
        """Construct the SDK client on the first request.

        Returns:
            The lazily constructed anthropic SDK client.

        Raises:
            LLMUnavailableError: the ANTHROPIC_API_KEY environment variable
                is missing or empty — generation and healing are blocked.
        """
        if self._client is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY")

            if not api_key:
                raise LLMUnavailableError("llm unavailable: anthropic: ANTHROPIC_API_KEY is not set")

            self._client = Anthropic(api_key=api_key, base_url=self._config.base_url or None)
        return self._client

    def _user_content(self, text: str, screenshot: bytes | None) -> str | list[dict]:
        """Wrap the request fields as an anthropic user content payload.

        Args:
            text: the plain-text request fields shared with the openai provider.
            screenshot: an optional PNG image of the page; passed only when
                the project enables screenshots.

        Returns:
            The plain text when no image is attached, otherwise the
            anthropic content block list with the base64 image block.
        """
        if screenshot is None:
            return text

        return [
            {"type": "text", "text": text},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": encode_screenshot(screenshot),
                },
            },
        ]

    def generate_step_code(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        step_text: str,
        previous_steps: list[str],
        snapshot: str,
        screenshot: bytes | None,
        page_api: str,
        existing_code: str | None,
        error: str | None,
    ) -> str:
        """Generate step code of the fixed form working only through the driver facade.

        Args:
            prompt: the system prompt text supplied by the calling engine;
                applied verbatim as the system parameter.
            user_instructions: the project's code style instructions from the
                generation_prompt setting; empty — the request carries no
                instructions block, non-empty — rendered verbatim as a
                separate USER INSTRUCTIONS block of the user content,
                identically to the openai implementation.
            step_text: the sentence of the step to generate.
            previous_steps: the sentences of the previous steps of the test,
                in execution order — scenario context.
            snapshot: the accessibility snapshot of the current page.
            screenshot: an optional PNG image of the page; passed only when
                the project enables screenshots.
            page_api: the exact page facade surface listing — the calls the
                model may use.
            existing_code: the existing step code that failed; non-empty only
                on regeneration requests.
            error: the failure description of the existing code; non-empty
                only on regeneration requests.

        Returns:
            The generated step code of the fixed form.

        Raises:
            LLMUnavailableError: the SDK client is unavailable or the
                service request failed.
        """
        text = build_fields_text(user_instructions, step_text, previous_steps, snapshot, page_api, existing_code, error)

        try:
            response = self._get_client().messages.create(
                model=self._config.effective_generation_model,
                system=prompt,
                max_tokens=REQUEST_MAX_TOKENS,
                messages=[{"role": "user", "content": self._user_content(text, screenshot)}],
            )
        except AnthropicError as sdk_error:
            raise LLMUnavailableError("llm unavailable: anthropic request failed") from sdk_error

        return extract_code_block(require_completion_text(_first_text_block(response), "anthropic"))

    def classify_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        step_text: str,
        code: str,
        error: str,
        snapshot: str,
        screenshot: bytes | None,
    ) -> FailureClassification:
        """Classify a failed cached step.

        Args:
            prompt: the system prompt text supplied by the calling engine;
                applied verbatim as the system parameter.
            step_text: the sentence of the failed step.
            code: the existing step code that failed.
            error: the human-readable description of the failure.
            snapshot: the accessibility snapshot of the current page.
            screenshot: an optional PNG image of the page; passed only when
                the project enables screenshots.

        Returns:
            The classification verdict; an unparsable or unknown answer maps
            protectively to the incurable category.

        Raises:
            LLMUnavailableError: the SDK client is unavailable or the
                service request failed.
        """
        text = build_classification_fields(step_text, code, error, snapshot)

        try:
            response = self._get_client().messages.create(
                model=self._config.effective_classification_model,
                system=prompt,
                max_tokens=REQUEST_MAX_TOKENS,
                messages=[{"role": "user", "content": self._user_content(text, screenshot)}],
            )
        except AnthropicError as sdk_error:
            raise LLMUnavailableError("llm unavailable: anthropic request failed") from sdk_error

        answer = require_completion_text(_first_text_block(response), "anthropic")
        parsed = parse_classification_line(answer)

        if parsed is None:
            return FailureClassification(**unparsable_classification())

        category, explanation, recommendation = parsed
        return FailureClassification(category=category, explanation=explanation, recommendation=recommendation)
