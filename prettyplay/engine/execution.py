"""Execution of step code of the fixed form through the run primitive of the page handle."""

from ..driver import PageFacade


def run_step_code(code: str, page: PageFacade) -> None:
    """Execute step code of the fixed form against the page handle of the test.

    The code is compiled and loaded in an isolated namespace and the step
    function of the fixed form — the single callable named ``step`` — is
    resolved on the calling thread, Playwright untouched. The whole
    step-function call then crosses the worker boundary as one unit through
    the run primitive of the page handle: the step receives the genuine sync
    Page and works through the standard Playwright sync API. An exception
    raised by the step code propagates to the caller as-is: the engine
    classifies it, this routine never swallows, translates or retries. No
    module is registered in ``sys.modules`` and no provider or network beyond
    the page itself is touched.

    Args:
        code: the step code text produced by generation or loaded from the cache.
        page: the page handle of the current test — the carrier of the worker boundary.
    """
    namespace: dict[str, object] = {}
    # the engine contract: compile and resolve on the calling thread, Playwright untouched
    exec(compile(code, "<prettyplay-step>", "exec"), namespace)

    step_fn = namespace["step"]
    # the engine contract: one worker unit — the whole step against the genuine sync Page
    page.run(step_fn)
