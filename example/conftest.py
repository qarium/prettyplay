from pathlib import Path
from contextlib import ExitStack

import allure
import pytest
from prettyplay import BrowserConfig, PrettyConfig, PrettyPlay, StepHooks

CLASSIFICATION_INSTRUCTIONS = "Write explanations and recommendations in English"

GENERATION_INSTRUCTIONS = """
Requirements:
- Prefer to use `id` or `class` attributes in HTML document to find elements.
- Make text matching checks case-insensitive.

Constraints:
- Don't do confirmation checks of the action's completion.
- Don't use `if` statement in step code.
"""


class AllureStepHooks(StepHooks):
    def __init__(self):
        self._is_group = False
        self._stack = ExitStack()

    def on_group_started(self, group_prompt: str) -> None:
        self._is_group = True

        self._stack.enter_context(
            allure.step("[group] " + group_prompt),
        )

    def on_group_finished(self, group_prompt: str) -> None:  # noqa: ARG002 — the hook contract fixes the signature
        if self._is_group:
            self._is_group = False

            self._stack.close()
            self._stack = ExitStack()

    def on_step_started(self, step_text: str, step_type: str) -> None:
        self._stack.enter_context(
            allure.step(f"[{step_type}] " + step_text),
        )

    def on_step_finished(self, step_text: str, step_type: str, outcome: str) -> None:  # noqa: ARG002 — the hook contract fixes the signature
        if not self._is_group:
            self._stack.close()
            self._stack = ExitStack()


def pytest_addoption(parser):
    parser.addoption("--strict-mode", action="store_true", default=False, help="Strict mode for using cache only")
    parser.addoption("--interactive", action="store_true", default=False, help="Interactive step healing mode")


@pytest.fixture
def play(request):
    file_path = Path(request.node.path)
    original_name = request.node.originalname or request.node.name

    strict = request.config.getoption("--strict-mode")
    interactive = request.config.getoption("--interactive")

    if request.node.cls:
        cache_path = file_path.parent / file_path.stem / request.node.cls.__name__ / original_name
    else:
        cache_path = file_path.parent / file_path.stem / original_name

    cache_path = Path(cache_path).relative_to(Path.cwd())

    config = PrettyConfig(
        browser=BrowserConfig(
            name="chrome",
            headless=False,
            screen="fullscreen",
        ),
        strict=strict,
        interactive=interactive,
        # send_screenshots=True,
        provider="anthropic",
        base_url="https://api.z.ai/api/anthropic",
        generation_model="glm-5.1",
        # healing_attempts=3,
        # generation_attempts=5,
        classification_model="glm-5.3",
        classification_prompt=CLASSIFICATION_INSTRUCTIONS,
        generation_prompt=GENERATION_INSTRUCTIONS,
    )

    with PrettyPlay(request.node.name, str(cache_path), hooks=[AllureStepHooks()], config=config) as pretty:
        yield pretty
