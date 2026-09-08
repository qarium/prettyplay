"""The narrow, stable facade of a single test page and of one located element.

The facade is the single page API the generated step code may work through —
a backward-compatibility contract: it may only grow, never rename or remove.
No raw Playwright object crosses the boundary; every return value is a plain
``str``/``bytes`` or another facade. Auto-wait lives inside Playwright, so the
facade never sleeps and never applies fixed delays.
"""

from __future__ import annotations

from playwright.sync_api import BrowserContext, Locator, Page, expect


class PageFacade:
    """The only page API the generated step code may use.

    Wraps one isolated browser context created by
    :class:`~prettyplay.driver.session.DriverSession`; ``close`` closes the
    context and leaves the shared browser of the run alive.

    Attributes:
        _page: the wrapped Playwright page; never exposed through the facade.
        _context: the isolated context owning the page; the facade boundary.
    """

    def __init__(self, page: Page, context: BrowserContext) -> None:
        """Wrap one Playwright page of an isolated context.

        Args:
            page: the Playwright page object; never exposed through the facade.
            context: the isolated context of the page; the facade boundary.
        """
        self._page = page
        self._context = context

    @property
    def url(self) -> str:
        """The current URL of the page."""
        return self._page.url

    def open(self, url: str) -> None:
        """Navigate to the URL and wait for the load event.

        Args:
            url: the address to open.
        """
        self._page.goto(url)

    def find_by_role(self, role: str, name: str) -> LocatorFacade:
        """Find an element by its aria role and accessible name.

        Args:
            role: the aria role of the element, e.g. ``button``.
            name: the accessible name of the element.

        Returns:
            The facade of the located element.
        """
        return LocatorFacade(self._page.get_by_role(role, name=name))

    def find_by_label(self, label: str) -> LocatorFacade:
        """Find a form element by its associated label.

        Args:
            label: the text of the label associated with the element.

        Returns:
            The facade of the located element.
        """
        return LocatorFacade(self._page.get_by_label(label))

    def find_by_text(self, text: str) -> LocatorFacade:
        """Find an element by its visible text.

        Args:
            text: the visible text of the element.

        Returns:
            The facade of the located element.
        """
        return LocatorFacade(self._page.get_by_text(text))

    def aria_snapshot(self) -> str:
        """Capture the accessibility-tree state of the page.

        Returns:
            The aria snapshot of the page body.
        """
        return self._page.locator("body").aria_snapshot()

    def screenshot(self) -> bytes:
        """Capture a full-page screenshot.

        Returns:
            The PNG image of the whole page as bytes.
        """
        return self._page.screenshot(full_page=True)

    def close(self) -> None:
        """Close the isolated context of the page; the browser of the run stays alive."""
        self._context.close()


class LocatorFacade:
    """An auto-waiting handle of one located element.

    Actions and expectations delegate to the wrapped locator; expectations go
    through Playwright ``expect`` and raise ``AssertionError`` on failure, so a
    broken expectation reaches failure classification untouched.

    Attributes:
        _locator: the wrapped Playwright locator; never exposed through the facade.
    """

    def __init__(self, locator: Locator) -> None:
        """Wrap one Playwright locator.

        Args:
            locator: the Playwright locator object; never exposed through the facade.
        """
        self._locator = locator

    def click(self) -> None:
        """Click the element with auto-wait."""
        self._locator.click()

    def fill(self, value: str) -> None:
        """Set the input text of the element.

        Args:
            value: the text to type into the element.
        """
        self._locator.fill(value)

    def select_option(self, value: str) -> None:
        """Choose one option of the element.

        Args:
            value: the value of the option to choose.
        """
        self._locator.select_option(value)

    def expect_visible(self) -> None:
        """Assert the element is visible."""
        expect(self._locator).to_be_visible()

    def expect_text(self, text: str) -> None:
        """Assert the element contains the text.

        Args:
            text: the text the element must contain.
        """
        expect(self._locator).to_contain_text(text)

    def expect_enabled(self) -> None:
        """Assert the element is enabled."""
        expect(self._locator).to_be_enabled()
