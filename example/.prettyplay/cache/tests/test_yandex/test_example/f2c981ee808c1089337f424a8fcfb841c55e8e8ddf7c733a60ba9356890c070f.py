STEP_TEXT = 'find results for "автоматизация ui тестирования"'
CACHE_KEY = 'test_example'
STEP_TYPE = 'action'
CREATED_AT = '2026-09-13'

def step(page) -> None:
    box = page.get_by_role("combobox", name="Запрос")
    box.fill("автоматизация UI тестирования")
    box.press("Enter")
    page.wait_for_load_state("load")

