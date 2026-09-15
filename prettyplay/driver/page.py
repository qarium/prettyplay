"""The internal runtime plumbing handle of a single test page.

Not the API of generated step code: a step function runs against the genuine
Playwright sync ``Page`` inside the driver worker thread, and :meth:`PageFacade.run`
is the only crossing point of that worker boundary. Besides the run primitive
the handle carries exactly the runtime plumbing the library itself needs —
the current URL, the accessibility snapshot for the LLM inputs, the full-page
screenshot and the context close. No member proxies, delegates or re-exports
of page capabilities exist. When the page belongs to a live driver session,
every Playwright-touching operation is marshalled into the session's driver
thread; a handle built without a worker (hand-built in tests) calls Playwright
inline in the constructing thread.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from playwright.sync_api import BrowserContext, Dialog, Page

if TYPE_CHECKING:
    from .session import PlaywrightWorker

_T = TypeVar("_T")

logger = logging.getLogger("prettyplay")

# The drain bound of one resolver pass: a page that fires a fresh dialog for
# every resolution would keep the pass — and with it the whole driver-thread
# unit — alive forever; the excess rolls forward to the next unit tail instead.
_RESOLVE_PASS_LIMIT = 128


class PageFacade:
    """The internal runtime plumbing handle of a single test page.

    Wraps one isolated browser context created by
    :class:`~prettyplay.driver.session.DriverSession`; ``close`` closes the
    context and leaves the browser of the test running.

    Attributes:
        _page: the wrapped Playwright page; never exposed to the calling thread.
        _context: the isolated context owning the page; the handle boundary.
        _worker: the driver thread of the owning session; ``None`` for
            hand-built handles, which then call Playwright inline.
        _router: the dialog routing state shared by every page of the context;
            ``None`` for a handle without a session — no handler is registered,
            hence nothing is ever pending.
    """

    def __init__(self, page: Page, context: BrowserContext) -> None:
        """Wrap one Playwright page of an isolated context.

        Args:
            page: the Playwright page object; never exposed to the calling thread.
            context: the isolated context of the page; the handle boundary.
        """
        self._page = page
        self._context = context
        self._worker: PlaywrightWorker | None = None
        self._router: _DialogRouter | None = None

    @property
    def url(self) -> str:
        """The current URL of the page — an immediate read.

        Executes inside the driver worker thread as one unit: ``_call`` is the
        one-unit machinery behind :meth:`run` — with a worker it queues one
        unit on the driver thread and re-raises the outcome as-is; without a
        worker (hand-built in tests) it runs inline; the unit's ``finally``
        runs the deferred dialog pass. A plain string crosses back — no
        Playwright object leaves the worker thread.

        Returns:
            The current URL of the page.
        """
        return self._call(lambda: self._page.url)

    def run(self, action: Callable[[Page], _T]) -> _T:
        """Execute the callable wholly inside the driver worker thread.

        The only crossing point of the worker boundary: the action receives
        the genuine sync ``Page`` of this test and its outcome returns as-is;
        an exception inside the action propagates to the caller untouched.
        After the action completes or raises, the resolver-of-last-resort pass
        resolves every dialog left unclaimed by in-step captures — it never
        raises and never masks the action's outcome.

        Args:
            action: the callable to execute; receives the genuine sync Page.

        Returns:
            Whatever ``action`` returns — plain data only; Playwright objects
            never cross back through the boundary.
        """

        return self._call(lambda: action(self._page))

    def _resolve_leftovers(self) -> None:
        """Run the deferred dialog pass of the driver-thread unit; never raises.

        A handle without a session carries no registered handler, hence
        nothing pending — the no-op is correct.
        """
        if self._router is not None:
            self._router.resolve_pending()

    def _call(self, fn: Callable[[], _T]) -> _T:
        """Run one callable in the driver thread with the leftover pass.

        Every unit crossing the worker boundary — a run action and a
        plumbing call alike — pumps the driver event loop, so a dialog can
        be recorded while the callable executes; after it completes or
        raises, the resolver-of-last-resort pass drains every dialog left
        unclaimed by in-step captures, so no pending dialog survives the
        boundary.

        Args:
            fn: the callable touching the wrapped Playwright objects.

        Returns:
            Whatever ``fn`` returns.
        """

        def unit() -> _T:
            try:
                return fn()
            finally:
                self._resolve_leftovers()

        if self._worker is None:  # hand-built handle (tests): inline execution
            return unit()

        return self._worker.run(unit)  # one queued unit; outcome/error re-raised as-is

    def aria_snapshot(self) -> str:
        """Capture the accessibility-tree state of the page.

        Returns:
            The aria snapshot of the page body.
        """
        return self._call(lambda: self._page.locator("body").aria_snapshot())

    def screenshot(self) -> bytes:
        """Capture a full-page screenshot.

        Returns:
            The PNG image of the whole page as bytes.
        """
        return self._call(lambda: self._page.screenshot(full_page=True))

    def close(self) -> None:
        """Close the isolated context of the page; the test's browser keeps running."""
        self._call(self._context.close)


class _DialogRouter:
    """The single dialog routing state of one browser context.

    One router serves every page of the context: the session registers the
    ``record`` handler on each page through the context page event before any
    step code runs. Registering a ``dialog`` listener disables Playwright's
    implicit auto-dismiss, so the router is the resolver of last resort —
    every dialog no in-step stock capture claims is resolved exactly once at
    the tail of every driver-thread unit, the run action and the plumbing
    calls alike: accept on the ``accept_dialogs`` setting, else an explicit
    dismiss restoring the Playwright default.

    Attributes:
        accept_dialogs: the ``browser.accept_dialogs`` setting read once at
            context creation; ``True`` accepts unclaimed dialogs.
        _pending: the dialogs recorded by the routing handlers and not yet
            resolved; only the single worker thread touches it.
    """

    def __init__(self, accept_dialogs: bool) -> None:
        """Keep the setting; nothing is pending yet.

        Args:
            accept_dialogs: whether dialogs no in-step stock dialog capture
                claims are accepted automatically at the unit tail.
        """
        self.accept_dialogs = accept_dialogs
        self._pending: list[Dialog] = []

    def record(self, dialog: Dialog) -> None:
        """Record a dialog fired on any page of the context — pure bookkeeping.

        The per-page handler registered on ``page.on("dialog", ...)``; no
        Playwright call happens inside event dispatch, so the step's own
        in-step capture stays free to claim the dialog.

        Args:
            dialog: the raw Playwright dialog fired on the page.
        """
        self._pending.append(dialog)

    def resolve_pending(self) -> None:
        """Resolve recorded dialogs; never raises.

        The tail pass of every driver-thread unit, executed inside the
        worker thread. A dialog already resolved by an in-step stock
        capture raises the driver's already-handled error on the resolution
        attempt — it is skipped silently; any other resolution failure is
        logged and dropped so the pass never masks the outcome of the
        action. A chained dialog — the page firing the next one while the
        loop advances inside a resolution call — joins the back of the
        pending list and the same pass drains it: the pass drains until
        none is left.

        The drain is bounded: a page that fires a fresh dialog for every
        resolution would drain forever, holding the unit — and the calling
        thread waiting on it — alive with no timeout left to fire. The pass
        resolves at most ``_RESOLVE_PASS_LIMIT`` dialogs, then leaves the
        rest pending for the next unit tail and logs a warning: every unit
        terminates, and the failure surfaces through the engine timeouts.
        """
        resolved = 0
        while self._pending and resolved < _RESOLVE_PASS_LIMIT:
            dialog = self._pending.pop(0)  # FIFO — the unstarted tail stays ordered for the next unit tail
            resolved += 1
            try:
                if self.accept_dialogs:
                    dialog.accept()
                else:
                    dialog.dismiss()
            except Exception as failure:
                if "already handled" in str(failure):
                    continue  # the step's capture resolved it — never double-handle
                logger.warning("dialog resolution failed", extra={"error": str(failure)})
        if self._pending:  # the drain cap held the unit open — the rest waits for the next unit tail
            logger.warning(
                "dialog drain limit reached; the rest resolves at the next unit tail",
                extra={"pending": len(self._pending), "limit": _RESOLVE_PASS_LIMIT},
            )
