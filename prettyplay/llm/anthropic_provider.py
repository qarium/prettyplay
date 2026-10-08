"""The anthropic SDK implementation of the LLMProvider port."""

import os

from anthropic import Anthropic

from ..config import Config
from ..failures import LLMUnavailableError
from ._request import (
    build_classification_fields,
    build_compliance_fields,
    build_fields_text,
    build_group_diagnosis_fields,
    classify_anthropic_failure,
    encode_screenshot,
    extract_code_block,
    parse_classification_line,
    require_completion_text,
    send_with_retries,
    unparsable_classification,
)
from .models import (
    ComplianceFinding,
    FailureClassification,
    GroupFailureClassification,
    ScenarioStep,
    parse_compliance_verdict,
    parse_group_failure_classification,
)
from .provider import LLMProvider

#: The anthropic Messages API requires ``max_tokens`` on every request — the
#: SDK-forced completion cap the openai side has no analogue of. Sized so a
#: full multi-step step-code response never truncates (the openai
#: implementation sends no cap and defaults to the model maximum).
REQUEST_MAX_TOKENS = 4096


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
    """The LLMProvider implementation served by the anthropic SDK — full parity with :class:`OpenAIProvider`."""

    def __init__(self, config: Config) -> None:
        """Keep the config; the SDK client stays unconstructed until the first request.

        Args:
            config: project settings; the effective models and the optional
                base_url endpoint override come from it. The API key is
                read from the environment only and never logged.
        """
        self._config = config
        self._client: Anthropic | None = None

    def _get_client(self) -> Anthropic:
        """Construct the SDK client on the first request.

        Returns:
            The lazily constructed anthropic SDK client.

        Raises:
            LLMUnavailableError: the ANTHROPIC_API_KEY environment variable
                is missing or empty — all LLM operations are blocked.
        """
        if self._client is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY")

            if not api_key:
                raise LLMUnavailableError("llm unavailable: anthropic: ANTHROPIC_API_KEY is not set")

            self._client = Anthropic(api_key=api_key, base_url=self._config.base_url or None, max_retries=0)
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
        instruction: str,
        step_type: str,
        previous_steps: list[ScenarioStep],
        group_prompt: str | None,
        inputs: dict[str, str],
        declarations: list[str],
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
                applied verbatim as the system parameter.
            user_instructions: the project's code style instructions from the
                generation_prompt setting; empty — the request carries no
                instructions block, non-empty — rendered verbatim as a
                separate USER INSTRUCTIONS block of the user content,
                identically to the openai implementation.
            instruction: the prepared instruction of the step — the rendered
                plain-text sentence with actual values embedded; rendered as
                the STEP block; the raw template sentence never reaches the
                request.
            step_type: the type of the step; rendered as a STEP TYPE line
                immediately before the STEP line, identically to the openai
                implementation; takes no part in step addressing.
            previous_steps: the typed scenario records of the previous steps
                of the test, in execution order — each the prepared
                instruction recorded at the step's execution plus its
                permanent group membership; rendered as the PREVIOUS STEPS
                block with the group entries marked, identically to the
                openai implementation.
            group_prompt: the group prompt of the current step's group;
                None — an ordinary step, no GROUP PROMPT block; non-empty —
                rendered verbatim as a separate GROUP PROMPT block
                immediately before the PREVIOUS STEPS block, identically to
                the openai implementation; takes no part in step addressing.
            inputs: the call-local input bindings of the step; non-empty —
                rendered as the INPUTS block immediately after the STEP
                line, one ``name = value`` line per binding, identically to
                the openai implementation; empty — no block.
            declarations: the declared result names of the step; non-empty —
                rendered as the RESULTS block immediately after the INPUTS
                block stating the result contract — the code returns a
                dictionary of exactly the declared names to non-blank
                strings observed on the page — identically to the openai
                implementation; empty — no block, the
                success-without-result code form.
            snapshot: the accessibility snapshot of the current page.
            page_url: the current URL of the page; non-empty — rendered as
                its own PAGE URL line immediately after the PAGE SNAPSHOT
                block of the user content, identically to the openai
                implementation; None — no line; supplied by the engine and
                steering generation paths.
            screenshot: an optional PNG image of the page; passed only when
                the project enables screenshots.
            cheat_sheet: the compact standard Playwright sync API reference
                supplied by the calling engine — rendered as the CHEAT SHEET
                block after the scenario inputs of the user content,
                identically to the openai implementation; guidance, not an
                allowlist — everything standard stays allowed.
            attempt_history: the rendered per-step attempt records — every
                record a complete multi-line verbatim record composed by the
                calling engine, the original cached code anchored as record 0
                when it exists, the last record the code being fixed;
                non-empty — rendered as a separate HISTORY block after the
                USER INSTRUCTIONS block, every record verbatim, no
                collapsing, no size limits; empty — no block; the list takes
                the place of the former existing_code, error and
                guidance_history inputs; rendered identically to the openai
                implementation.
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
            LLMUnavailableError: the SDK client is unavailable or the
                service request failed.
        """
        text = build_fields_text(
            user_instructions=user_instructions,
            instruction=instruction,
            step_type=step_type,
            previous_steps=previous_steps,
            group_prompt=group_prompt,
            inputs=inputs,
            declarations=declarations,
            snapshot=snapshot,
            page_url=page_url,
            cheat_sheet=cheat_sheet,
            attempt_history=attempt_history,
            recommendation=recommendation,
            guidance=guidance,
        )

        client = self._get_client()
        request = {
            "model": self._config.effective_generation_model,
            "system": prompt,
            "max_tokens": REQUEST_MAX_TOKENS,
            "messages": [{"role": "user", "content": self._user_content(text, screenshot)}],
        }

        response = send_with_retries(
            "anthropic",
            "generation",
            self._config.llm_request_attempts,
            classify_anthropic_failure,
            lambda: client.messages.create(**request),
        )

        return extract_code_block(require_completion_text(_first_text_block(response), "anthropic"))

    def classify_step_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        step_text: str,
        code: str,
        error: str,
        snapshot: str,
        screenshot: bytes | None,
    ) -> FailureClassification:
        """Classify a failed cached step — the former classify_failure, renamed nominally.

        Args:
            prompt: the system prompt text supplied by the calling engine;
                applied verbatim as the system parameter.
            user_instructions: the project's classification guidance from the
                classification_prompt setting; empty — the request carries no
                instructions block, non-empty — rendered verbatim as a
                separate USER INSTRUCTIONS block placed last of the user
                content, identically to the openai implementation.
            step_text: the sentence of the failed step — the prepared
                instruction, never the raw template sentence; a non-template
                step passes its sentence unchanged.
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
        text = build_classification_fields(user_instructions, step_text, code, error, snapshot)

        client = self._get_client()
        request = {
            "model": self._config.effective_classification_model,
            "system": prompt,
            "max_tokens": REQUEST_MAX_TOKENS,
            "messages": [{"role": "user", "content": self._user_content(text, screenshot)}],
        }

        response = send_with_retries(
            "anthropic",
            "classification",
            self._config.llm_request_attempts,
            classify_anthropic_failure,
            lambda: client.messages.create(**request),
        )

        answer = require_completion_text(_first_text_block(response), "anthropic")
        parsed = parse_classification_line(answer)

        if parsed is None:
            return FailureClassification(**unparsable_classification())

        category, explanation, recommendation = parsed
        return FailureClassification(category=category, explanation=explanation, recommendation=recommendation)

    def classify_group_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        group_prompt: str,
        group_steps: list[str],
        previous_steps: list[ScenarioStep],
        step_text: str,
        attempt_history: list[str],
        snapshot: str,
        screenshot: bytes | None,
    ) -> GroupFailureClassification:
        """Diagnose a failed group step with the whole interaction in view.

        Args:
            prompt: the group diagnosis system prompt supplied by the calling
                engine; applied verbatim as the system parameter.
            user_instructions: the project's classification guidance from
                the classification_prompt setting; empty — the request
                carries no instructions block, non-empty — rendered verbatim
                as a separate USER INSTRUCTIONS block placed last of the
                user content, identically to the openai implementation.
            group_prompt: the group prompt of the diagnosed group, verbatim.
            group_steps: the composed verbatim traces of the group's steps
                in execution order — each the prepared instruction, the
                outcome and the URL before -> after transition, supplied by
                the calling engine.
            previous_steps: the typed scenario records of the previous steps
                of the test, in execution order — each the prepared
                instruction recorded at the step's execution plus its
                permanent group membership; rendered as the PREVIOUS STEPS
                block immediately before the GROUP STEPS block with the
                group entries marked, identically to the openai
                implementation; empty — no block.
            step_text: the prepared instruction of the failed step — never
                the raw template sentence; a non-template step passes its
                sentence unchanged.
            attempt_history: the rendered verbatim records of the failed
                step's attempt history; non-empty — rendered as a separate
                HISTORY block, every record verbatim, no collapsing, no size
                limits; empty — no block.
            snapshot: the accessibility snapshot of the current page.
            screenshot: an optional PNG image of the page; passed only when
                the project enables screenshots.

        Returns:
            The diagnosis verdict; a degraded answer carries the
            conservative incurable with the raw answer in root_cause — the
            block order GROUP PROMPT, optional PREVIOUS STEPS, GROUP STEPS,
            STEP, HISTORY, PAGE SNAPSHOT; an unusable answer degrades inside
            the provider, never raising across the port.

        Raises:
            LLMUnavailableError: the SDK client is unavailable or the
                service request failed.
        """
        text = build_group_diagnosis_fields(
            user_instructions=user_instructions,
            group_prompt=group_prompt,
            group_steps=group_steps,
            previous_steps=previous_steps,
            step_text=step_text,
            attempt_history=attempt_history,
            snapshot=snapshot,
        )

        client = self._get_client()
        request = {
            "model": self._config.effective_classification_model,
            "system": prompt,
            "max_tokens": REQUEST_MAX_TOKENS,
            "messages": [{"role": "user", "content": self._user_content(text, screenshot)}],
        }

        response = send_with_retries(
            "anthropic",
            "group diagnosis",
            self._config.llm_request_attempts,
            classify_anthropic_failure,
            lambda: client.messages.create(**request),
        )

        return parse_group_failure_classification(require_completion_text(_first_text_block(response), "anthropic"))

    def check_instruction_compliance(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        instruction: str,
        step_type: str,
        inputs: dict[str, str],
        declarations: list[str],
        code: str,
        attempt_history: list[str],
    ) -> list[ComplianceFinding]:
        """Check the successfully executed candidate code in two dimensions.

        Args:
            prompt: the gate system prompt text supplied by the calling
                engine; applied verbatim as the system parameter.
            user_instructions: the project's generation instructions from
                the generation_prompt setting; the calling engine
                guarantees non-empty — the gate never runs on empty
                instructions.
            instruction: the prepared plain-text instruction of the generated
                step — rendered as the STEP block; the raw template sentence
                never reaches the request.
            step_type: the type of the step; rendered as a STEP TYPE line
                immediately before the STEP line, identically to the openai
                implementation.
            inputs: the call-local input bindings of the step; non-empty —
                rendered as the INPUTS block immediately after the STEP
                block, one ``name = value`` line per binding, identically to
                the openai implementation; empty — no block.
            declarations: the reached capture names of the step; non-empty —
                rendered as the RESULTS block immediately after the INPUTS
                block stating the exact-key, observed non-blank string
                return contract, identically to the openai implementation;
                empty — no block, the success-without-result form.
            code: the successfully executed candidate code.
            attempt_history: the rendered per-step attempt records — the
                ground truth of what was already tried; non-empty — rendered
                as a separate ATTEMPT HISTORY block, every record verbatim,
                no collapsing, no size limits; empty — no block; rendered
                identically to the openai implementation.

        Returns:
            The parsed findings; an empty list means compliant — the block
            order INSTRUCTIONS, STEP, the optional INPUTS and RESULTS
            sections, ATTEMPT HISTORY, CODE; no fence unwrapping: a
            malformed verdict raises, never a silent pass.

        Raises:
            LLMUnavailableError: the SDK client is unavailable or the
                service request failed.
        """
        text = build_compliance_fields(
            user_instructions, instruction, step_type, inputs, declarations, attempt_history, code
        )

        client = self._get_client()
        request = {
            "model": self._config.effective_classification_model,
            "system": prompt,
            "max_tokens": REQUEST_MAX_TOKENS,
            "messages": [{"role": "user", "content": text}],
        }

        response = send_with_retries(
            "anthropic",
            "compliance verdict",
            self._config.llm_request_attempts,
            classify_anthropic_failure,
            lambda: client.messages.create(**request),
        )

        return parse_compliance_verdict(require_completion_text(_first_text_block(response), "anthropic"))
