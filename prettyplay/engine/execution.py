"""Execution of step code of the fixed form through the run primitive of the page handle."""

from ..driver import PageFacade


def run_step_code(code: str, page: PageFacade) -> dict[str, str] | None:
    """Execute step code of the fixed form against the page handle of the test.

    Args:
        code: the step code text produced by generation or loaded from the
            cache — compiled and resolved on the calling thread, Playwright
            untouched.
        page: the page handle of the current test — the whole step call
            crosses the worker boundary as one unit, the step receives the
            genuine sync Page.

    Returns:
        The step function's return as-is — the dictionary of declared names
        to observed strings for a step with declarations, None for a
        declaration-free step; plain data only.

    Raises:
        Exception: whatever the step code raises propagates as-is — never
            swallowed, translated or retried here; the engine classifies it.
    """
    namespace: dict[str, object] = {}
    # the engine contract: compile and resolve on the calling thread, Playwright untouched
    exec(compile(code, "<prettyplay-step>", "exec"), namespace)

    step_fn = namespace["step"]
    # the engine contract: one worker unit — the whole step against the genuine sync Page
    return page.run(step_fn)
