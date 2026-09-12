"""The unified LLM port of the library and the provider factory."""

from ..config import Config
from .models import FailureClassification


class LLMProvider:
    """The single LLM port: step code generation and failure classification.

    One contract, two interchangeable SDK implementations selected by
    configuration — the provider choice is never a capability difference.
    The port itself is never instantiated at runtime; implementations own
    one completion request per attempt (attempt budgets live in the calling
    engine) and map every service failure to
    :class:`~prettyplay.failures.LLMUnavailableError` naming the provider.
    """

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
        recommendation: str | None,
        guidance: str | None,
        guidance_history: list[str],
    ) -> str:
        """Generate step code of the fixed form working only through the driver facade.

        Args:
            prompt: the system prompt text supplied by the calling engine;
                applied verbatim as the system message.
            user_instructions: the project's code style instructions supplied
                by the calling engine from the generation_prompt setting;
                empty — the request carries no instructions block, non-empty —
                rendered verbatim as a separate USER INSTRUCTIONS block of the
                user content, identically in both implementations.
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
            recommendation: the diagnosis of the classification that preceded
                the regeneration; non-empty — rendered as a separate
                RECOMMENDATION block after the CODE and ERROR blocks,
                None — no block.
            guidance: the engineer guidance message of the interactive
                steering; non-empty — rendered as a separate USER GUIDANCE
                block, None — no block.
            guidance_history: the accumulated steering turns — each a rendered
                guidance-and-outcome line; non-empty — rendered as a separate
                HISTORY block after the USER GUIDANCE block, empty — no block.

        Returns:
            The generated step code of the fixed form.

        Raises:
            NotImplementedError: the port itself carries no implementation.
        """
        raise NotImplementedError("LLMProvider is a port; use create_provider() to select an implementation")

    def classify_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        step_text: str,
        code: str,
        error: str,
        snapshot: str,
        screenshot: bytes | None,
    ) -> FailureClassification:
        """Classify a failed cached step.

        Args:
            prompt: the system prompt text supplied by the calling engine;
                applied verbatim as the system message.
            user_instructions: the project's classification guidance supplied
                by the calling engine from the classification_prompt setting;
                empty — the request carries no instructions block, non-empty —
                rendered verbatim as a separate USER INSTRUCTIONS block placed
                last of the user content, identically in both implementations.
            step_text: the sentence of the failed step.
            code: the existing step code that failed.
            error: the human-readable description of the failure.
            snapshot: the accessibility snapshot of the current page.
            screenshot: an optional PNG image of the page; passed only when
                the project enables screenshots.

        Returns:
            The classification verdict.

        Raises:
            NotImplementedError: the port itself carries no implementation.
        """
        raise NotImplementedError("LLMProvider is a port; use create_provider() to select an implementation")


def create_provider(config: Config) -> LLMProvider:
    """Select and construct the LLM provider from configuration.

    Args:
        config: project settings; the provider setting selects the SDK
            implementation.

    Returns:
        The selected provider implementation.

    Raises:
        ValueError: the provider setting names no supported provider.
    """
    # deferred: the implementations subclass the port defined in this module,
    # so a top-level import here would be circular
    from .anthropic_provider import AnthropicProvider  # noqa: PLC0415
    from .openai_provider import OpenAIProvider  # noqa: PLC0415

    if config.provider == "openai":
        return OpenAIProvider(config)

    if config.provider == "anthropic":
        return AnthropicProvider(config)

    raise ValueError(f"unsupported provider {config.provider!r}: expected one of openai, anthropic")
