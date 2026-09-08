"""Thin callback contract for integrator-side reactions to step execution events.

The library calls the matching method synchronously while a step executes; the
base implementation of every method is a no-op — override only the events you
need. No event bus, no queuing, no delivery retries.
"""


class StepHooks:
    """Callback contract of the eight prettyplay events; every base method is a no-op."""

    def on_step_started(self, step_text: str, step_type: str) -> None:
        """A step started executing; ``step_type`` is action or assertion."""

    def on_step_passed(self, step_text: str, step_type: str) -> None:
        """The step finished successfully."""

    def on_step_failed(self, step_text: str, step_type: str, error: str) -> None:
        """The step failed; ``error`` is a short human-readable failure description."""

    def on_generation_started(self, step_text: str, attempt: int) -> None:
        """A code generation attempt started; ``attempt`` is the 1-based attempt number."""

    def on_healing_started(self, step_text: str, category: str) -> None:
        """Healing of a failed cached step started; ``category`` is rot, product_defect or incurable."""

    def on_healed(self, step_text: str, explanation: str) -> None:
        """The step was healed and the cache updated; ``explanation`` says why and what changed."""

    def on_cache_saved(self, step_text: str, filename: str) -> None:
        """Step code was written to the cache file ``filename``."""

    def on_cache_skipped(self, step_text: str, reason: str) -> None:
        """The cache write was skipped; ``reason`` names the cause, e.g. a read-only cache."""
