"""The Playwright-mirroring facade of a single test page and of one located element.

The facade is the single page API the generated step code may work through —
a mirror of the Playwright sync API at page/locator level. The declared
non-mirror families: the prettyplay scroll extras kept under their own names,
the method-style ``expect_*`` expectation names replacing Playwright's chained
``expect(...).to_be_*()`` model, and the ``expect_dialog`` capture constructor
(implemented over Playwright's ``expect_event("dialog")``). The excluded
capabilities — routing, direct ``evaluate`` exposure, CDP, clock, HAR, tracing
and raw input devices — are absent. No raw Playwright object crosses the
boundary; every return value is a plain ``str``/``bytes`` or another facade.
Auto-wait lives inside Playwright, so the facade never sleeps and never applies
fixed delays. When the page belongs to a live driver session, every Playwright
call is marshalled into the session's driver thread; a facade built without a
worker (hand-built in tests) calls Playwright inline in the constructing
thread.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from playwright.sync_api import BrowserContext, Dialog, FrameLocator, Locator, Page, expect

if TYPE_CHECKING:
    from .session import PlaywrightWorker

_T = TypeVar("_T")

_SCROLL_INTO_VIEW_JS = """(el, target) => {
    const cr = el.getBoundingClientRect();
    const tr = target.getBoundingClientRect();
    el.scrollTop += tr.top - cr.top - (el.clientHeight - tr.height) / 2;
}"""


class PageFacade:
    """The only page API the generated step code may use.

    Wraps one isolated browser context created by
    :class:`~prettyplay.driver.session.DriverSession`; ``close`` closes the
    context and leaves the browser of the test running.

    Attributes:
        _page: the wrapped Playwright page; never exposed through the facade.
        _context: the isolated context owning the page; the facade boundary.
        _worker: the driver thread of the owning session; ``None`` for
            hand-built facades, which then call Playwright inline.
    """

    def __init__(self, page: Page, context: BrowserContext) -> None:
        """Wrap one Playwright page of an isolated context.

        Args:
            page: the Playwright page object; never exposed through the facade.
            context: the isolated context of the page; the facade boundary.
        """
        self._page = page
        self._context = context
        self._worker: PlaywrightWorker | None = None

    def _call(self, fn: Callable[[], _T]) -> _T:
        """Run one Playwright-touching callable in the driver thread.

        Args:
            fn: the callable touching the wrapped Playwright objects.

        Returns:
            Whatever ``fn`` returns.
        """
        if self._worker is None:
            return fn()

        return self._worker.run(fn)

    @property
    def url(self) -> str:
        """The current URL of the page."""
        return self._call(lambda: self._page.url)

    @property
    def pages(self) -> list[PageFacade]:
        """The open pages of this page's context — popups and new tabs included."""
        raw_pages = self._call(lambda: list(self._context.pages))
        return [self._wrap_page(raw_page) for raw_page in raw_pages]

    def goto(self, url: str) -> None:
        """Navigate to the URL and wait for the load state.

        Args:
            url: the address to navigate to.
        """
        self._call(lambda: self._page.goto(url))

    def go_back(self) -> None:
        """Go back through the browser history and wait for the load state."""
        self._call(self._page.go_back)

    def go_forward(self) -> None:
        """Go forward through the browser history and wait for the load state."""
        self._call(self._page.go_forward)

    def reload(self) -> None:
        """Reload the page and wait for the load state."""
        self._call(self._page.reload)

    def wait_for_url(self, url: str) -> None:
        """Wait until the page URL matches the glob pattern.

        Args:
            url: the glob pattern the URL must match, e.g. ``**/dashboard``.
        """
        self._call(lambda: self._page.wait_for_url(url))

    def wait_for_load_state(self, state: str) -> None:
        """Wait for the page to reach the load state.

        Args:
            state: the load state to wait for — ``load``, ``domcontentloaded``
                or ``networkidle``.
        """
        self._call(lambda: self._page.wait_for_load_state(state))

    def expect_url(self, url: str) -> None:
        """Assert the URL matches the glob pattern — auto-waiting.

        Args:
            url: the glob pattern the URL must match.
        """
        self._call(lambda: expect(self._page).to_have_url(url))

    def expect_title(self, title: str) -> None:
        """Assert the title contains the text — auto-waiting.

        Args:
            title: the text the title must contain.
        """
        pattern = re.compile(f".*{re.escape(title)}.*", re.DOTALL)
        self._call(lambda: expect(self._page).to_have_title(pattern))

    def get_by_role(self, role: str, name: str = "") -> LocatorFacade:
        """Locate an element by its aria role and accessible name.

        Args:
            role: the aria role of the element, e.g. ``button``.
            name: the accessible name of the element; empty — match by role
                alone.

        Returns:
            The facade of the located element.
        """
        if name == "":
            locator = self._call(lambda: self._page.get_by_role(role))
        else:
            locator = self._call(lambda: self._page.get_by_role(role, name=name))
        return self._wrap_locator(locator)

    def get_by_label(self, label: str) -> LocatorFacade:
        """Locate a form element by its associated label.

        Args:
            label: the text of the label associated with the element.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._page.get_by_label(label))
        return self._wrap_locator(locator)

    def get_by_text(self, text: str) -> LocatorFacade:
        """Locate an element by its visible text.

        Args:
            text: the visible text of the element.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._page.get_by_text(text))
        return self._wrap_locator(locator)

    def get_by_placeholder(self, placeholder: str) -> LocatorFacade:
        """Locate an input element by its placeholder text.

        Args:
            placeholder: the placeholder text of the input.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._page.get_by_placeholder(placeholder))
        return self._wrap_locator(locator)

    def get_by_alt_text(self, alt: str) -> LocatorFacade:
        """Locate an image element by its alt text.

        Args:
            alt: the alternative text of the image.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._page.get_by_alt_text(alt))
        return self._wrap_locator(locator)

    def get_by_title(self, title: str) -> LocatorFacade:
        """Locate an element by its title attribute.

        Args:
            title: the value of the title attribute.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._page.get_by_title(title))
        return self._wrap_locator(locator)

    def get_by_test_id(self, test_id: str) -> LocatorFacade:
        """Locate an element by its test id.

        Args:
            test_id: the value of the default ``data-testid`` attribute.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._page.get_by_test_id(test_id))
        return self._wrap_locator(locator)

    def locator(self, selector: str) -> LocatorFacade:
        """Locate an element by any selector.

        The selector passes through verbatim — CSS, XPath (including the
        explicit ``xpath=`` form) and attribute selectors alike; no
        facade-side sniffing or rewriting.

        Args:
            selector: any Playwright selector expression, e.g.
                ``form > button.primary``.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._page.locator(selector))
        return self._wrap_locator(locator)

    def bring_to_front(self) -> None:
        """Raise this page above the other pages of the context."""
        self._call(self._page.bring_to_front)

    def frame_locator(self, selector: str) -> FrameFacade:
        """Return the locating scope of one iframe of the page.

        Args:
            selector: the selector of the iframe element.

        Returns:
            The facade of the frame scope.
        """
        frame = self._call(lambda: self._page.frame_locator(selector))
        facade = FrameFacade(frame)
        facade._worker = self._worker
        return facade

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

    def scroll_to_element(self, element: LocatorFacade) -> None:
        """Scroll the page so the element enters the viewport.

        Works inside the nearest scrollable ancestor when the element lives in
        a scrollable container; the scrolled state is awaited by the follow-up
        locators and expectations, never by a delay.

        Args:
            element: the located element to bring into view.
        """
        self._call(element._locator.scroll_into_view_if_needed)

    def scroll_down(self, pixels: int) -> None:
        """Scroll the page down by an amount.

        Args:
            pixels: a positive scroll amount in CSS pixels.
        """
        self._call(lambda: self._page.mouse.wheel(0, pixels))

    def scroll_up(self, pixels: int) -> None:
        """Scroll the page up by an amount.

        Args:
            pixels: a positive scroll amount in CSS pixels.
        """
        self._call(lambda: self._page.mouse.wheel(0, -pixels))

    def scroll_to_bottom(self) -> None:
        """Scroll the page to its end."""
        self._call(lambda: self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)"))

    def scroll_to_top(self) -> None:
        """Scroll the page to its start."""
        self._call(lambda: self._page.evaluate("window.scrollTo(0, 0)"))

    def scroll_into_view(self, element: LocatorFacade, container: LocatorFacade) -> None:
        """Bring the element into the visible area of the specific scrollable container.

        For nested scrollables where the nearest-ancestor behavior of
        ``scroll_to_element`` is not enough. The target is resolved through
        ``element_handle()`` (which auto-waits) and passed to the container
        evaluation as the live handle argument.

        Args:
            element: the located element to bring into view.
            container: the located scrollable container, e.g. a carousel.
        """

        def scroll() -> None:
            handle = element._locator.element_handle()
            container._locator.evaluate(_SCROLL_INTO_VIEW_JS, handle)

        self._call(scroll)

    def scroll_container_down(self, container: LocatorFacade, pixels: int) -> None:
        """Scroll the scrollable container down by an amount.

        Args:
            container: the located scrollable container.
            pixels: a positive scroll amount in CSS pixels.
        """
        self._call(lambda: container._locator.evaluate("(el, px) => { el.scrollTop += px; }", pixels))

    def scroll_container_up(self, container: LocatorFacade, pixels: int) -> None:
        """Scroll the scrollable container up by an amount.

        Args:
            container: the located scrollable container.
            pixels: a positive scroll amount in CSS pixels.
        """
        self._call(lambda: container._locator.evaluate("(el, px) => { el.scrollTop -= px; }", pixels))

    def close(self) -> None:
        """Close the isolated context of the page; the test's browser keeps running."""
        self._call(self._context.close)

    def _wrap_locator(self, locator: Locator) -> LocatorFacade:
        """Wrap a located element, inheriting the driver thread boundary.

        Args:
            locator: the Playwright locator object; never exposed.

        Returns:
            The facade of the located element.
        """
        facade = LocatorFacade(locator)
        facade._worker = self._worker

        return facade

    def _wrap_page(self, page: Page) -> PageFacade:
        """Wrap a page of this context, inheriting the driver thread boundary.

        Args:
            page: the Playwright page object; never exposed through the facade.

        Returns:
            The facade of the page.
        """
        facade = PageFacade(page, self._context)
        facade._worker = self._worker

        return facade


class LocatorFacade:
    """An auto-waiting handle of one located element.

    Actions and expectations delegate to the wrapped locator; expectations go
    through Playwright ``expect`` and raise ``AssertionError`` on failure, so a
    broken expectation reaches failure classification untouched.

    Attributes:
        _locator: the wrapped Playwright locator; never exposed through the facade.
        _worker: the driver thread inherited from the page facade that created
            this handle; ``None`` for hand-built handles, which then call
            Playwright inline.
    """

    def __init__(self, locator: Locator) -> None:
        """Wrap one Playwright locator.

        Args:
            locator: the Playwright locator object; never exposed through the facade.
        """
        self._locator = locator
        self._worker: PlaywrightWorker | None = None

    def _call(self, fn: Callable[[], _T]) -> _T:
        """Run one Playwright-touching callable in the driver thread.

        Args:
            fn: the callable touching the wrapped Playwright objects.

        Returns:
            Whatever ``fn`` returns.
        """
        if self._worker is None:
            return fn()

        return self._worker.run(fn)

    def click(self, button: str = "") -> None:
        """Click the element, waiting for actionability.

        Args:
            button: the mouse button — empty for the left button, ``right`` for
                the right button, ``middle`` for the middle button.
        """
        self._call(lambda: self._locator.click(button=button or "left"))

    def dblclick(self) -> None:
        """Double-click the element, waiting for actionability."""
        self._call(self._locator.dblclick)

    def fill(self, value: str) -> None:
        """Set the text input value of the element.

        Args:
            value: the text to type into the element.
        """
        self._call(lambda: self._locator.fill(value))

    def clear(self) -> None:
        """Clear the text input value of the element."""
        self._call(self._locator.clear)

    def press(self, key: str) -> None:
        """Press a single key or a key combination on the element, waiting for actionability.

        Args:
            key: the key name or combination, e.g. ``Enter`` or ``Control+A``.
        """
        self._call(lambda: self._locator.press(key))

    def check(self) -> None:
        """Check the checkbox or radio button, waiting for actionability."""
        self._call(self._locator.check)

    def uncheck(self) -> None:
        """Uncheck the checkbox or radio button, waiting for actionability."""
        self._call(self._locator.uncheck)

    def hover(self) -> None:
        """Hover the element, waiting for actionability."""
        self._call(self._locator.hover)

    def select_option(self, value: str) -> None:
        """Select the option with the value in a list or combo box.

        Args:
            value: the value of the option to choose.
        """
        self._call(lambda: self._locator.select_option(value))

    def drag_to(self, target: LocatorFacade) -> None:
        """Drag this element onto the target element, auto-waiting both endpoints.

        Args:
            target: the located drop target element.
        """
        self._call(lambda: self._locator.drag_to(target._locator))

    def set_input_files(self, path: str) -> None:
        """Upload one file to the file input.

        Args:
            path: the filesystem path of the file to upload.
        """
        self._call(lambda: self._locator.set_input_files(path))

    def expect_visible(self) -> None:
        """Assert the element is visible."""
        self._call(lambda: expect(self._locator).to_be_visible())

    def expect_hidden(self) -> None:
        """Assert the element is hidden."""
        self._call(lambda: expect(self._locator).to_be_hidden())

    def expect_text(self, text: str) -> None:
        """Assert the element contains the text.

        Args:
            text: the text the element must contain.
        """
        self._call(lambda: expect(self._locator).to_contain_text(text))

    def expect_enabled(self) -> None:
        """Assert the element is enabled."""
        self._call(lambda: expect(self._locator).to_be_enabled())

    def expect_value(self, value: str) -> None:
        """Assert the element input value equals the value.

        Args:
            value: the exact input value the element must have.
        """
        self._call(lambda: expect(self._locator).to_have_value(value))

    def expect_checked(self) -> None:
        """Assert the checkbox or radio is checked."""
        self._call(lambda: expect(self._locator).to_be_checked())

    def expect_count(self, count: int) -> None:
        """Assert the locator resolves to exactly the count elements.

        Args:
            count: the number of elements the locator must match.
        """
        self._call(lambda: expect(self._locator).to_have_count(count))

    def expect_attribute(self, name: str, value: str) -> None:
        """Assert the attribute of the element equals the value.

        Args:
            name: the attribute name to read.
            value: the exact attribute value to expect.
        """
        self._call(lambda: expect(self._locator).to_have_attribute(name, value))


class DialogFacade:
    """The wrapped dialog captured by ``expect_dialog`` — step-controlled handling.

    Accept and dismiss resolve the dialog exactly once; the step decides, the
    ``accept_dialogs`` setting never applies to a captured dialog.

    Attributes:
        _dialog: the wrapped Playwright dialog; never exposed through the facade.
        _worker: the driver thread inherited from the page facade that captured
            the dialog; ``None`` for hand-built facades, which then call
            Playwright inline.
    """

    def __init__(self, dialog: Dialog) -> None:
        """Wrap one Playwright dialog.

        Args:
            dialog: the Playwright dialog object; never exposed through the facade.
        """
        self._dialog = dialog
        self._worker: PlaywrightWorker | None = None

    def _call(self, fn: Callable[[], _T]) -> _T:
        """Run one Playwright-touching callable in the driver thread.

        Args:
            fn: the callable touching the wrapped Playwright objects.

        Returns:
            Whatever ``fn`` returns.
        """
        if self._worker is None:
            return fn()

        return self._worker.run(fn)

    @property
    def type(self) -> str:
        """The dialog kind: alert, confirm, prompt or beforeunload."""
        return self._call(lambda: self._dialog.type)

    @property
    def message(self) -> str:
        """The message text of the dialog."""
        return self._call(lambda: self._dialog.message)

    @property
    def default_value(self) -> str:
        """The pre-filled answer of a prompt dialog; empty for the other kinds."""
        return self._call(lambda: self._dialog.default_value)

    def accept(self, prompt_text: str = "") -> None:
        """Accept the dialog.

        Args:
            prompt_text: the answer to send for a prompt dialog; empty — accept
                without an answer.
        """
        self._call(lambda: self._dialog.accept() if prompt_text == "" else self._dialog.accept(prompt_text=prompt_text))

    def dismiss(self) -> None:
        """Dismiss the dialog."""
        self._call(self._dialog.dismiss)


class FrameFacade:
    """The frame-scoped locator factory — locating inside one iframe.

    Nested frames chain: the ``frame_locator`` of a frame returns the scope of
    the nested iframe. Elements located through the scope behave exactly like
    page content — the same auto-wait, the same driver-thread boundary.

    Attributes:
        _frame_locator: the wrapped Playwright frame locator; never exposed
            through the facade.
        _worker: the driver thread inherited from the page facade that created
            the scope; ``None`` for hand-built scopes, which then call
            Playwright inline.
    """

    def __init__(self, frame_locator: FrameLocator) -> None:
        """Wrap one Playwright frame locator.

        Args:
            frame_locator: the Playwright frame locator object; never exposed
                through the facade.
        """
        self._frame_locator = frame_locator
        self._worker: PlaywrightWorker | None = None

    def _call(self, fn: Callable[[], _T]) -> _T:
        """Run one Playwright-touching callable in the driver thread.

        Args:
            fn: the callable touching the wrapped Playwright objects.

        Returns:
            Whatever ``fn`` returns.
        """
        if self._worker is None:
            return fn()

        return self._worker.run(fn)

    def get_by_role(self, role: str, name: str = "") -> LocatorFacade:
        """Locate one element inside the frame by its aria role and accessible name.

        Args:
            role: the aria role of the element, e.g. ``button``.
            name: the accessible name of the element; empty — match by role alone.

        Returns:
            The facade of the located element.
        """
        if name == "":
            locator = self._call(lambda: self._frame_locator.get_by_role(role))
        else:
            locator = self._call(lambda: self._frame_locator.get_by_role(role, name=name))
        return self._wrap_locator(locator)

    def get_by_label(self, label: str) -> LocatorFacade:
        """Locate one element inside the frame by its associated label.

        Args:
            label: the text of the label associated with the element.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._frame_locator.get_by_label(label))
        return self._wrap_locator(locator)

    def get_by_text(self, text: str) -> LocatorFacade:
        """Locate one element inside the frame by its visible text.

        Args:
            text: the visible text of the element.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._frame_locator.get_by_text(text))
        return self._wrap_locator(locator)

    def get_by_placeholder(self, placeholder: str) -> LocatorFacade:
        """Locate one input inside the frame by its placeholder text.

        Args:
            placeholder: the placeholder text of the input.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._frame_locator.get_by_placeholder(placeholder))
        return self._wrap_locator(locator)

    def get_by_alt_text(self, alt: str) -> LocatorFacade:
        """Locate one image inside the frame by its alt text.

        Args:
            alt: the alternative text of the image.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._frame_locator.get_by_alt_text(alt))
        return self._wrap_locator(locator)

    def get_by_title(self, title: str) -> LocatorFacade:
        """Locate one element inside the frame by its title attribute.

        Args:
            title: the value of the title attribute.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._frame_locator.get_by_title(title))
        return self._wrap_locator(locator)

    def get_by_test_id(self, test_id: str) -> LocatorFacade:
        """Locate one element inside the frame by its data-testid value.

        Args:
            test_id: the value of the default ``data-testid`` attribute.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._frame_locator.get_by_test_id(test_id))
        return self._wrap_locator(locator)

    def locator(self, selector: str) -> LocatorFacade:
        """Locate one element inside the frame by any selector.

        The selector passes through verbatim — CSS, XPath (including the
        explicit ``xpath=`` form) and attribute selectors alike; no
        facade-side sniffing or rewriting.

        Args:
            selector: any Playwright selector expression.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._frame_locator.locator(selector))
        return self._wrap_locator(locator)

    def frame_locator(self, selector: str) -> FrameFacade:
        """Return the locating scope of a nested iframe inside this frame.

        Args:
            selector: the selector of the nested iframe element.

        Returns:
            The facade of the nested frame scope.
        """
        nested = self._call(lambda: self._frame_locator.frame_locator(selector))
        facade = FrameFacade(nested)
        facade._worker = self._worker

        return facade

    def _wrap_locator(self, locator: Locator) -> LocatorFacade:
        """Wrap a located element, inheriting the driver thread boundary.

        Args:
            locator: the Playwright locator object; never exposed.

        Returns:
            The facade of the located element.
        """
        facade = LocatorFacade(locator)
        facade._worker = self._worker

        return facade
