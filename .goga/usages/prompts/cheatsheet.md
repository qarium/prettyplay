# Playwright cheat sheet

The compact standard Playwright sync API reference carried by every step-code generation and regeneration request
of prettyplay — referenced by the engine and steering cells as the `cheat_sheet` practice; rendered by the provider
implementations as the leading CHEAT SHEET block of the user content. Guidance, not an allowlist: everything
standard stays allowed — the error-driven regeneration loop is the second line of defense against hallucinated
calls. Target audience: the generation model — a model that knows Playwright weakly writes a correct step from
this reference alone.

## Locator factories

    page.get_by_role("button", name="Sign in")
    page.get_by_label("Username")
    page.get_by_text("Welcome back")
    page.get_by_placeholder("Search")
    page.get_by_alt_text("Logo")
    page.get_by_title("Close")
    page.get_by_test_id("submit")
    page.locator("css selector | //xpath | [data-qa=row]")

## Narrowing

    locator.first / locator.last / locator.nth(2)
    locator.filter(has_text="Product X")
    locator.and_(other) / locator.or_(other)

## Actions

    .click() / .dblclick() / .click(button="right")
    .fill("text") / .clear() / .press("Enter") / .press("Control+A")
    .check() / .uncheck() / .hover() / .select_option("v")
    .drag_to(target) / .set_input_files("path.png")

## Navigation and waits

    page.goto(url) / page.go_back() / page.go_forward() / page.reload()
    page.wait_for_url("**/dashboard") / page.wait_for_load_state("networkidle")

## Waiting assertions — expect chains

    from playwright.sync_api import expect

    expect(locator).to_be_visible() / to_be_hidden()
    expect(locator).to_be_enabled() / to_be_checked()
    expect(locator).to_have_text("...") / to_contain_text("...")
    expect(locator).to_have_value("v") / to_have_attribute("href", "/docs")
    expect(page).to_have_url("**/dashboard") / to_have_title("Dashboard")

## Count forms — "the page shows a list of X"

    videos = page.get_by_role("listitem")
    expect(videos.first).to_be_visible()
    assert videos.count() > 1

An exact count is the rarer need: `expect(videos).to_have_count(3)`.

## Immediate reads with plain asserts

    assert locator.count() >= 1
    assert "Dashboard" in page.title()

## Dialogs

    with page.expect_event("dialog") as info:
        page.get_by_role("button", name="Delete").click()
    dialog = info.value
    dialog.type / dialog.message / dialog.default_value
    dialog.accept() / dialog.dismiss() / dialog.accept("the answer")

## Popups and new tabs

    with page.expect_popup() as popup_info:
        page.get_by_role("link", name="Open docs").click()
    popup = popup_info.value
    popup.bring_to_front()

## Frames

    frame = page.frame_locator("#checkout")
    frame.get_by_role("button", name="Pay").click()

## Scrolling

    locator.scroll_into_view_if_needed()
    page.mouse.wheel(0, 600)
