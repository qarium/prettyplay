STEP_TEXT = 'open https://ya.ru'
CACHE_KEY = 'test_example'
STEP_TYPE = 'action'
CREATED_AT = '2026-09-13'

def step(page) -> None:
    page.goto("https://ya.ru")

