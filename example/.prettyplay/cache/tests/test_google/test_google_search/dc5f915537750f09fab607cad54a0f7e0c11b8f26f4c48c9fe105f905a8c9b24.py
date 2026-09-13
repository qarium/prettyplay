STEP_TEXT = 'the results page contains the text "test"'
CACHE_KEY = 'test_google_search'
STEP_TYPE = 'assertion'
CREATED_AT = '2026-09-13'

def step(page) -> None:
    page.locator("body").expect_text("test")

