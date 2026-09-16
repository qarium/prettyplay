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
        step_type: str,
        previous_steps: list[str],
        snapshot: str,
        page_url: str | None,
        screenshot: bytes | None,
        cheat_sheet: str,
        attempt_history: list[str],
        recommendation: str | None,
        guidance: str | None,
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
            step_text: the raw sentence of the step to generate, as passed by
                the calling engine — never the normalized addressing form.
            step_type: the type of the step; rendered as a STEP TYPE line
                immediately before the STEP line, identically in both
                implementations; takes no part in step addressing.
            previous_steps: the sentences of the previous steps of the test,
                in execution order — scenario context.
            snapshot: the accessibility snapshot of the current page.
            page_url: the current URL of the page; non-empty — rendered by
                the provider implementations as its own PAGE URL line
                immediately after the PAGE SNAPSHOT block of the user
                content, identically in both; None — no line; supplied by
                the engine and steering generation paths.
            screenshot: an optional PNG image of the page; passed only when
                the project enables screenshots.
            cheat_sheet: the compact standard Playwright sync API reference
                supplied by the calling engine — rendered as the CHEAT SHEET
                block after the scenario inputs of the user content,
                identically in both implementations; guidance, not an
                allowlist — everything standard stays allowed.
            attempt_history: the rendered per-step attempt records — every
                record a complete multi-line verbatim record composed by the
                calling engine, the original cached code anchored as record 0
                when it exists, the last record the code being fixed;
                non-empty — rendered as a separate HISTORY block after the
                USER INSTRUCTIONS block, every record verbatim, no
                collapsing, no size limits; empty — no block; the list takes
                the place of the former existing_code, error and
                guidance_history inputs.
            recommendation: the diagnosis of the classification that preceded
                the regeneration; non-empty — rendered as a separate
                RECOMMENDATION block after the HISTORY block, None — no
                block.
            guidance: the engineer guidance message of the interactive
                steering; non-empty — rendered as a separate USER GUIDANCE
                block, None — no block.

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

    def check_instruction_compliance(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        step_text: str,
        step_type: str,
        code: str,
        attempt_history: list[str],
    ) -> list[ComplianceFinding]:
        """Check the successfully executed candidate code in two dimensions.

        One verdict request per successfully executed candidate, judging
        instruction compliance and step adequacy in one request — the third
        port operation, in absolute parity across the implementations. The
        user content carries four blocks in the fixed order INSTRUCTIONS,
        STEP (with its STEP TYPE line), ATTEMPT HISTORY and CODE,
        identically in both implementations; the request goes through the
        effective classification model.

        Args:
            prompt: the gate system prompt text supplied by the calling
                engine; applied verbatim as the system message.
            user_instructions: the project's generation instructions
                supplied by the calling engine from the generation_prompt
                setting; the calling engine guarantees non-empty — the gate
                never runs on empty instructions.
            step_text: the raw sentence of the generated step, as passed by
                the calling engine — never the normalized addressing form.
            step_type: the type of the step; rendered as a STEP TYPE line
                immediately before the STEP line, identically in both
                implementations.
            code: the successfully executed candidate code.
            attempt_history: the rendered per-step attempt records — the
                ground truth of what was already tried; non-empty — rendered
                as a separate ATTEMPT HISTORY block, every record verbatim,
                no collapsing, no size limits; empty — no block.

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
