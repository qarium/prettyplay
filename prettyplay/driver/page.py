"""The narrow, stable facade of a single test page and of one located element.

Minimal skeleton for Task 6: only the wrapper constructor the
:class:`~prettyplay.driver.session.DriverSession` hands out. The full facade
surface (locators, snapshot, screenshot, expectations) lands in Task 7 — the
driver facade is a backward-compatibility contract, so the class identity and
the constructor shape are fixed here first.
"""

from playwright.sync_api import BrowserContext, Page


class PageFacade:
    """The only page API the generated step code may use.

    Wraps one isolated browser context created by
    :class:`~prettyplay.driver.session.DriverSession`.

    Attributes:
        _page: the wrapped Playwright page.
        _context: the isolated context owning the page; ``close`` closes it.
    """

    def __init__(self, page: Page, context: BrowserContext) -> None:
        """Wrap one Playwright page of an isolated context.

        Args:
            page: the Playwright page object; never exposed through the facade.
            context: the isolated context of the page; the facade boundary.
        """
        self._page = page
        self._context = context


class LocatorFacade:
    """An auto-waiting handle of one located element.

    Skeleton for Task 6; the action and expectation methods land in Task 7.

    Attributes:
        _locator: the wrapped Playwright locator; never exposed through the facade.
    """

    def __init__(self, locator: object) -> None:
        """Wrap one Playwright locator.

        Args:
            locator: the Playwright locator object; never exposed through the facade.
        """
        self._locator = locator
