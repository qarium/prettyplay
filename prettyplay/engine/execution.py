"""Execution of step code of the fixed form against the page facade of the test."""

from ..driver import PageFacade


def run_step_code(code: str, page: PageFacade) -> None:
    """Execute step code of the fixed form against the page facade of the test.

    The code is compiled and loaded in an isolated namespace; the step
    function of the fixed form — the single callable named ``step`` — is
    resolved and called with the page facade. A failure inside the step code
    propagates to the caller as-is: the engine classifies it, this routine
    never swallows or retries. No module is registered in ``sys.modules`` and
    no provider or network beyond the page itself is touched.

    Args:
        code: the step code text produced by generation or loaded from the cache.
        page: the page facade of the current test.
    """
    namespace: dict[str, object] = {}
    # the engine contract: exec of the fixed-form step code in an isolated namespace
    exec(compile(code, "<prettyplay-step>", "exec"), namespace)

    fn = namespace["step"]
    fn(page)
