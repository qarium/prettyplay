STEP_TEXT = 'open https://google.com'
CACHE_KEY = 'test_google_search'
STEP_TYPE = 'action'
CREATED_AT = '2026-09-13'

def step(page) -> None:
    page.goto("https://google.com")
    page.expect_url("https://www.google.com/")

