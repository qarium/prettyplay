STEP_TEXT = 'the results page contains the text "тест"'
CACHE_KEY = 'test_example'
STEP_TYPE = 'assertion'
CREATED_AT = '2026-09-13'

def step(page) -> None:
    page.locator("body").expect_text("тест", ignore_case=True)

