from contextlib import ExitStack
from pathlib import Path

import allure
import pytest
from playwright.sync_api import Error as PlaywrightError
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


class AllureStepWrapper:
    def __init__(self, title):
        self.step = allure.step(title)
        self.failed_exception = None

    def __enter__(self):
        self.step.__enter__()
        return self

    def fail(self, reason, *, cls=AssertionError):
        self.failed_exception = cls(reason)

    def __exit__(self, exc_type, exc_val, exc_tb):
        error_to_raise = exc_type or self.failed_exception

        if error_to_raise:
            return self.step.__exit__(AssertionError, error_to_raise, exc_tb)

        return self.step.__exit__(None, None, None)


class AllureStepHooks(StepHooks):
    def __init__(self, play: PrettyPlay):
        self._play = play

        self._step = None

        self._step_stack = ExitStack()
        self._group_stack = ExitStack()

    def on_group_started(self, group_prompt: str) -> None:
        self._group_stack.enter_context(
            allure.step("[group] " + group_prompt),
        )

    def on_group_finished(self, group_prompt: str) -> None:  # noqa: ARG002 — the hook contract fixes the signature
        self._group_stack.close()
        self._group_stack = ExitStack()

    def on_step_started(self, step_text: str, step_type: str) -> None:
        self._step = AllureStepWrapper(f"[{step_type}] " + step_text)
        self._step_stack.enter_context(self._step)

    def on_step_failed(self, step_text: str, step_type: str, error: str) -> None:  # noqa: ARG002 — the hook contract fixes the signature
        self._step.fail(error, cls=AssertionError if step_type == "assertion" else Exception)

        try:
            screenshot_bytes = self._play.get_screenshot()

            allure.attach(
                screenshot_bytes,
                name="screenshot.png",
                attachment_type=allure.attachment_type.PNG,
            )
        except PlaywrightError:
            pass

    def on_step_finished(self, step_text: str, step_type: str, outcome: str) -> None:  # noqa: ARG002 — the hook contract fixes the signature
        self._step_stack.close()
        self._step_stack = ExitStack()


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

    prettyplay = PrettyPlay(request.node.name, str(cache_path), config=config)
    prettyplay.add_hooks(AllureStepHooks(prettyplay))

    with prettyplay as pretty:
        yield pretty
