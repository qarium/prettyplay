"""Facade of the prettyplay.failures cell: the failure taxonomy of the library."""

from .errors import (
    ComplianceVerdictError,
    ErrorParts,
    FailureVerdict,
    IncurableStepError,
    LLMUnavailableError,
    PrettyplayError,
    ProductDefectError,
    decompose_error_text,
    render_terminal_message,
)

__all__ = [
    "ComplianceVerdictError",
    "ErrorParts",
    "FailureVerdict",
    "IncurableStepError",
    "LLMUnavailableError",
    "PrettyplayError",
    "ProductDefectError",
    "decompose_error_text",
    "render_terminal_message",
]
