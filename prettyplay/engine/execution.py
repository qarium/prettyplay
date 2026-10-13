"""Execution of step code of the fixed form through the run primitive of the page handle."""

from contextlib import contextmanager

from playwright.sync_api import Page

from ..driver import PageFacade

#: The Playwright library default action timeout of a genuine page, in milliseconds —
#: the public API has no getter, so the baseline restore names the value explicitly.
_PLAYWRIGHT_DEFAULT_TIMEOUT_MS = 30_000.0


@contextmanager
def _temporary_timeout(page: PageFacade | Page, timeout_ms: float, baseline_ms: float):
    page.set_default_timeout(timeout_ms)

    try:
        yield
    finally:
        # unconditional restore — the probe bound never outlives its candidate
        page.set_default_timeout(baseline_ms)


def run_step_code(
    code: str,
    page: PageFacade,
    *,
    action_timeout_ms: float | None = None,
    baseline_timeout_ms: float = _PLAYWRIGHT_DEFAULT_TIMEOUT_MS,
) -> dict[str, str] | None:
    """Execute step code of the fixed form against the page handle of the test.

    Args:
        code: the step code text produced by generation or loaded from the
            cache — compiled and resolved on the calling thread, Playwright
            untouched.
        page: the page handle of the current test — the whole step call
            crosses the worker boundary as one unit, the step receives the
            genuine sync Page.
        action_timeout_ms: the probe bound of a candidate execution — the
            page default action timeout set inside the worker right before
            the step call, so a wrong locator fails fast instead of burning
            the page default; None — the page default stays untouched.
        baseline_timeout_ms: the restore target of the probe bound, in
            milliseconds — the page default the finally of the probe head
            re-establishes after the candidate; the default — the Playwright
            library default (30 s); the calling loops pass the configured
            browser timeout baseline.

    Returns:
        The step function's return as-is — the dictionary of declared names
        to observed strings for a step with declarations, None for a
        declaration-free step; plain data only.

    Raises:
        Exception: whatever the step code raises propagates as-is — never
            swallowed, translated or retried here; the engine classifies it.
    """
    namespace: dict[str, object] = {}  # self-contained code: the page argument and the allowed imports only

    # the engine contract: compile and resolve on the calling thread, Playwright untouched
    exec(compile(code, "<prettyplay-step>", "exec"), namespace)

    step_fn = namespace["step"]

    target = step_fn

    if action_timeout_ms is not None:

        def probe(page: object) -> object:
            with _temporary_timeout(page, action_timeout_ms, baseline_timeout_ms):
                return step_fn(page)

        target = probe

    # the engine contract: one worker unit — the whole step against the genuine sync Page
    return page.run(target)
