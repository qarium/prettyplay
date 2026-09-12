"""The narrow, stable facade of a single test page and of one located element.

The facade is the single page API the generated step code may work through —
a backward-compatibility contract: it may only grow, never rename or remove.
No raw Playwright object crosses the boundary; every return value is a plain
``str``/``bytes`` or another facade. Auto-wait lives inside Playwright, so the
facade never sleeps and never applies fixed delays. When the page belongs to a
live driver session, every Playwright call is marshalled into the session's
driver thread; a facade built without a worker (hand-built in tests) calls
Playwright inline in the constructing thread.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from playwright.sync_api import BrowserContext, Locator, Page, expect

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

    def open(self, url: str) -> None:
        """Navigate to the URL and wait for the load event.

        Args:
            url: the address to open.
        """
        self._call(lambda: self._page.goto(url))

    def find_by_role(self, role: str, name: str) -> LocatorFacade:
        """Find an element by its aria role and accessible name.

        Args:
            role: the aria role of the element, e.g. ``button``.
            name: the accessible name of the element.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._page.get_by_role(role, name=name))
        return self._wrap_locator(locator)

    def find_by_label(self, label: str) -> LocatorFacade:
        """Find a form element by its associated label.

        Args:
            label: the text of the label associated with the element.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._page.get_by_label(label))
        return self._wrap_locator(locator)

    def find_by_text(self, text: str) -> LocatorFacade:
        """Find an element by its visible text.

        Args:
            text: the visible text of the element.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._page.get_by_text(text))
        return self._wrap_locator(locator)

    def find_by_attribute(self, name: str, value: str) -> LocatorFacade:
        """Find an element by the value of one of its attributes.

        Intended for data-* attributes (e.g. ``data-test-id``); the CSS engine
        handles the attribute selector natively and the returned handle
        auto-waits exactly like the other locating methods.

        Args:
            name: the full attribute name, e.g. ``data-test-id``.
            value: the attribute value to match.

        Returns:
            The facade of the located element.
        """
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        locator = self._call(lambda: self._page.locator(f'[{name}="{escaped}"]'))
        return self._wrap_locator(locator)

    def find_by_css(self, selector: str) -> LocatorFacade:
        """Find an element by a CSS selector.

        The selector is passed through verbatim — escaping belongs to the
        caller, a universal escaping would break ``>``/``+`` combinators.

        Args:
            selector: a valid CSS selector expression, e.g. ``form > button.primary``.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._page.locator(selector))
        return self._wrap_locator(locator)

    def find_by_xpath(self, xpath: str) -> LocatorFacade:
        """Find an element by an XPath expression.

        The explicit ``xpath=`` engine prefix keeps every expression uniform:
        Playwright sniffs XPath implicitly only via a ``//`` or ``..`` prefix,
        so an expression such as ``*[@id='main']`` would otherwise silently go
        to the CSS engine.

        Args:
            xpath: a valid XPath expression, e.g. ``//button[@type='submit']``.

        Returns:
            The facade of the located element.
        """
        locator = self._call(lambda: self._page.locator(f"xpath={xpath}"))
        return self._wrap_locator(locator)

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
