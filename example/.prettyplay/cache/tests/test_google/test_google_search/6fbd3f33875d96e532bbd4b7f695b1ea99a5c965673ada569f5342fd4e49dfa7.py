STEP_TEXT = 'find results for "ui testing automation"'
CACHE_KEY = 'test_google_search'
STEP_TYPE = 'action'
CREATED_AT = '2026-09-13'

def step(page) -> None:
    page.get_by_role("combobox", name="Найти").fill("UI testing automation")
    page.get_by_role("combobox", name="Найти").press("Enter")
    page.wait_for_load_state("load")

