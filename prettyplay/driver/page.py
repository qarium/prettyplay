"""The internal runtime plumbing handle of a single test page."""

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

#: The one-pass structural registry collector: every interactive element of the
#: page (document order, open shadow roots included) with the first unique
#: selector of its candidate ladder — data-testid, id, name, aria-label, class
#: chain, parent-id-scoped CSS, structural XPath — computed wholly inside the
#: page, no round-trips. Bounds: 200 elements, 50 roots, shadow depth 4, 40
#: chars of visible text. Out of scope by design: iframe content and closed
#: shadow roots stay absent from the registry.
_STRUCTURE_SCRIPT = r"""() => {
  const LIMIT = 200;
  const TEXT_LIMIT = 40;
  const MAX_DEPTH = 4;
  const MAX_ROOTS = 50;
  const INTERACTIVE = "button, a, input, select, textarea, [role], [data-testid], [onclick]";
  const IDENT = /^[A-Za-z][A-Za-z0-9_-]*$/;

  const roots = [];
  const collectRoots = (root, depth) => {
    roots.push(root);
    if (depth >= MAX_DEPTH || roots.length >= MAX_ROOTS) {
      return;
    }
    for (const host of root.querySelectorAll("*")) {
      if (host.shadowRoot) {
        collectRoots(host.shadowRoot, depth + 1);
        if (roots.length >= MAX_ROOTS) {
          return;
        }
      }
    }
  };
  collectRoots(document, 0);

  const esc = (value) => value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  const identOf = (value) => (IDENT.test(value) ? value : null);
  const positionalIndex = (element) => {
    let index = 1;
    let sibling = element;
    while ((sibling = sibling.previousElementSibling)) {
      if (sibling.tagName === element.tagName) {
        index += 1;
      }
    }
    return index;
  };
  const uniqueCssInPage = (selector) => {
    let total = 0;
    for (const root of roots) {
      total += root.querySelectorAll(selector).length;
      if (total > 1) {
        return false;
      }
    }
    return total === 1;
  };
  const uniqueXpathInPage = (expression) => {
    const result = document.evaluate(
      expression.slice("xpath=".length), document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null
    );
    return result.snapshotLength === 1;
  };
  const structuralXpath = (element) => {
    const steps = [];
    let node = element;
    while (node !== document.documentElement) {
      steps.push(node.localName.toLowerCase() + "[" + positionalIndex(node) + "]");
      node = node.parentElement;
      if (!node) {
        return null;
      }
      if (node.id) {
        steps.push('//*[@id="' + esc(node.id) + '"]');
        return steps.reverse().join("/");
      }
      if (steps.length >= 10) {
        return null;
      }
    }
    steps.push("html[" + positionalIndex(node) + "]");
    return "/" + steps.reverse().join("/");
  };
  const candidatesOf = (element) => {
    const candidates = [];
    const attr = (name) => element.getAttribute(name);
    const testid = attr("data-testid");
    if (testid) {
      candidates.push({ selector: '[data-testid="' + esc(testid) + '"]', via: "testid" });
    }
    const id = attr("id");
    if (id) {
      candidates.push({ selector: identOf(id) ? "#" + id : '[id="' + esc(id) + '"]', via: "id" });
    }
    const name = attr("name");
    if (name) {
      candidates.push({ selector: '[name="' + esc(name) + '"]', via: "name" });
    }
    const ariaLabel = attr("aria-label");
    if (ariaLabel) {
      candidates.push({ selector: '[aria-label="' + esc(ariaLabel) + '"]', via: "aria-label" });
    }
    const classes = Array.from(element.classList).filter((cls) => IDENT.test(cls)).slice(0, 4);
    for (let count = 1; count <= classes.length; count += 1) {
      candidates.push({ selector: classes.slice(0, count).map((cls) => "." + cls).join(""), via: "class" });
    }
    const scope = element.closest("[id]");
    if (scope && scope !== element) {
      const scopeId = scope.getAttribute("id");
      const base = identOf(scopeId) ? "#" + scopeId : '[id="' + esc(scopeId) + '"]';
      const tag = element.localName.toLowerCase();
      candidates.push({ selector: base + " " + tag, via: "css" });
      candidates.push({ selector: base + " > " + tag + ":nth-of-type(" + positionalIndex(element) + ")", via: "css" });
    }
    const xpath = structuralXpath(element);
    if (xpath) {
      candidates.push({ selector: "xpath=" + xpath, via: "xpath" });
    }
    return candidates;
  };

  const records = [];
  for (const root of roots) {
    for (const element of root.querySelectorAll(INTERACTIVE)) {
      if (records.length >= LIMIT) {
        return records;
      }
      if (element.type === "hidden") {
        continue;
      }
      let rendered = true;
      try {
        rendered = element.getClientRects().length > 0;
      } catch (error) {
        rendered = false;
      }
      if (!rendered) {
        continue;
      }
      let chosen = { selector: "", via: "" };
      for (const candidate of candidatesOf(element)) {
        let unique = false;
        try {
          if (candidate.via === "xpath") {
            unique = uniqueXpathInPage(candidate.selector);
          } else {
            unique = uniqueCssInPage(candidate.selector);
          }
        } catch (error) {
          unique = false;
        }
        if (unique) {
          chosen = candidate;
          break;
        }
      }
      records.push({
        tag: element.localName.toLowerCase(),
        text: (element.textContent || "").replace(/\s+/g, " ").trim().slice(0, TEXT_LIMIT),
        id: element.id || "",
        testid: element.getAttribute("data-testid") || "",
        name: element.getAttribute("name") || "",
        aria_label: element.getAttribute("aria-label") || "",
        placeholder: element.getAttribute("placeholder") || "",
        classes: Array.from(element.classList).slice(0, 6).join(" ").slice(0, 80),
        selector: chosen.selector,
        via: chosen.via,
      });
    }
  }
  return records;
}"""


class PageFacade:
    """The internal runtime plumbing handle of a single test page — plumbing only, no proxies of page capabilities.

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

        Returns:
            The current URL of the page, read as one driver-thread unit; a
            plain string crosses back, no Playwright object.
        """
        return self._call(lambda: self._page.url)

    def run(self, action: Callable[[Page], _T]) -> _T:
        """Execute the callable wholly inside the driver worker thread — the only crossing point of the boundary.

        Args:
            action: the callable to execute; receives the genuine sync Page.

        Returns:
            Whatever ``action`` returns — plain data only; Playwright
            objects never cross back. The leftover-dialog pass runs after
            the action — it never raises and never masks the outcome; an
            exception inside the action propagates untouched.
        """

        return self._call(lambda: action(self._page))

    def _resolve_leftovers(self) -> None:
        """Run the deferred dialog pass of the driver-thread unit; never raises."""
        if self._router is not None:
            self._router.resolve_pending()

    def _call(self, fn: Callable[[], _T]) -> _T:
        """Run one callable in the driver thread with the leftover pass.

        Args:
            fn: the callable touching the wrapped Playwright objects.

        Returns:
            Whatever ``fn`` returns — the deferred dialog pass drains every
            unclaimed dialog after the callable, so no pending dialog
            survives the boundary.
        """

        def unit() -> _T:
            """Run fn and resolve the dialog leftovers afterwards."""
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

    def structure_registry(self) -> list[dict[str, str]]:
        """Capture the structural element registry of the page.

        One in-page pass collects every interactive element — the document
        tree plus open shadow roots — with its structural attributes and the
        first unique selector of its candidate ladder (data-testid, id, name,
        aria-label, class chain, parent-id-scoped CSS, structural XPath),
        verified in the same pass; iframe content and closed shadow roots
        stay absent by design.

        Returns:
            One plain record per interactive element in document order —
            plain JSON data only, never a Playwright object.
        """
        records = self._call(lambda: self._page.evaluate(_STRUCTURE_SCRIPT))
        return list(records)

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
    """The single dialog routing state of one browser context — the resolver of last resort at every unit tail.

    Attributes:
        accept_dialogs: the ``browser.accept_dialogs`` setting read once at
            context creation; ``True`` accepts unclaimed dialogs — the
            router is the resolver of last resort at every unit tail:
            accept on this setting, else an explicit dismiss.
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

        Args:
            dialog: the raw Playwright dialog fired on the page; no
                Playwright call happens inside the event dispatch, so the
                step's own in-step capture stays free to claim it.
        """
        self._pending.append(dialog)

    def resolve_pending(self) -> None:
        """Resolve recorded dialogs — the bounded tail pass of every driver-thread unit; never raises."""
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
