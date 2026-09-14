"""The unified LLM port of the library and the provider factory."""

from ..config import Config
from .models import ComplianceFinding, FailureClassification


class LLMProvider:
    """The single LLM port: step code generation, failure classification and the compliance verdict.

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
        page_url: str | None,
        screenshot: bytes | None,
        cheat_sheet: str,
        existing_code: str | None,
        error: str | None,
        recommendation: str | None,
        guidance: str | None,
        guidance_history: list[str],
    ) -> str:
        """Generate step code of the fixed form working through the standard Playwright sync API.

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
            page_url: the current URL of the page; non-empty — rendered by
                the provider implementations as its own PAGE URL line
                immediately after the PAGE SNAPSHOT block of the user
                content, identically in both; None — no line; supplied by
                the interactive steering only.
            screenshot: an optional PNG image of the page; passed only when
                the project enables screenshots.
            cheat_sheet: the compact standard Playwright sync API reference
                supplied by the calling engine — rendered as the CHEAT SHEET
                block after the scenario inputs of the user content,
                identically in both implementations; guidance, not an
                allowlist — everything standard stays allowed.
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
            guidance_history: the accumulated steering turns — each a
                complete multi-line turn record: the engineer message, the
                complete generated code, the complete outcome; composed by
                the calling steering; non-empty — rendered as a separate
                HISTORY block after the USER GUIDANCE block, every record
                verbatim, no collapsing, no size limits; empty — no block.

        Returns:
            The generated step code of the fixed form, working through the
            standard Playwright sync API — imports from playwright.sync_api
            and the Python standard library only, global at the top level of
            the code block.

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

    def check_instruction_compliance(
        self,
        prompt: str,
        user_instructions: str,
        step_text: str,
        code: str,
    ) -> list[ComplianceFinding]:
        """Check the successfully executed candidate code against the project user instructions.

        The compliance verdict request of the gate — the third port
        operation, in absolute parity across the implementations.

        Args:
            prompt: the gate system prompt text supplied by the calling
                engine; applied verbatim as the system message.
            user_instructions: the project's generation instructions
                supplied by the calling engine from the generation_prompt
                setting; the calling engine guarantees non-empty — the gate
                never runs on empty instructions.
            step_text: the sentence of the generated step.
            code: the successfully executed candidate code.

        Returns:
            The parsed findings; an empty list means compliant.

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
