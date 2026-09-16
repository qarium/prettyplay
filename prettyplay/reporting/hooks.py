"""Thin callback contract for integrator-side reactions to step execution events.

The library calls the matching method synchronously while a step executes; the
base implementation of every method is a no-op — override only the events you
need. No event bus, no queuing, no delivery retries.
"""


class StepHooks:
    """Callback contract of the fourteen prettyplay events; every base method is a no-op."""

    def on_step_started(self, step_text: str, step_type: str) -> None:
        """A step started executing; ``step_type`` is action or assertion."""

    def on_step_passed(self, step_text: str, step_type: str) -> None:
        """The step finished successfully."""

    def on_step_failed(self, step_text: str, step_type: str, error: str) -> None:
        """The step failed; ``error`` is the full rendered failure message.

        ``error`` is the same structured text carried by the raised exception and
        the log record: the first line with the class name of the terminal failure
        and the authored reason, the ``---`` separated step/error section, the
        conditional received/cause/Call log details section and the unpadded
        verdict block; display it verbatim.
        """

    def on_step_verdict(self, step_text: str, category: str, explanation: str, recommendation: str) -> None:
        """The terminal failure of the step carried a verdict; fires after on_step_failed."""

    def on_step_finished(self, step_text: str, step_type: str, outcome: str) -> None:
        """The step ended — the closing event of every step, fired exactly once regardless of outcome."""

    def on_group_started(self, group_prompt: str) -> None:
        """A group block started; ``group_prompt`` is the group prompt, verbatim."""

    def on_group_passed(self, group_prompt: str) -> None:
        """The group block completed without an exception — a recovered group reports passed here."""

    def on_group_failed(self, group_prompt: str) -> None:
        """The group block exited through an exception — a failed step, a refused recovery or an
        author exception inside the block alike; the exception still propagates."""

    def on_group_finished(self, group_prompt: str) -> None:
        """The group block ended — the closing event of every group, fired exactly once
        regardless of outcome, after on_group_passed or on_group_failed."""

    def on_generation_started(self, step_text: str, attempt: int) -> None:
        """A code generation attempt started; ``attempt`` is the 1-based attempt number."""

    def on_healing_started(self, step_text: str, category: str) -> None:
        """Healing of a failed cached step started; ``category`` is rot, product_defect, fixable or
        incurable — a group recovery row reports the diagnosis label recoverable."""

    def on_healed(self, step_text: str, explanation: str) -> None:
        """The step was healed and the cache updated; ``explanation`` says why and what changed."""

    def on_cache_saved(self, step_text: str, filename: str) -> None:
        """Step code was written to the cache file ``filename``."""

    def on_cache_skipped(self, step_text: str, reason: str) -> None:
        """The cache write was skipped; ``reason`` names the cause, e.g. a read-only cache."""
