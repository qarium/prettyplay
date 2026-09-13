from pathlib import Path

import allure
import pytest
from prettyplay import BrowserConfig, PrettyConfig, PrettyPlay, StepHooks


class AllureStepHooks(StepHooks):
    def __init__(self):
        self._step = None

    def on_step_started(self, step_text: str, step_type: str) -> None:
        self._step = allure.step(f"[{step_type}] " + step_text)
        self._step.__enter__()

    def on_step_finished(self, step_text: str, step_type: str, outcome: str) -> None:
        if self._step is not None:
            self._step.__exit__(None, None, None)


def pytest_addoption(parser):
    parser.addoption(
        "--interactive",
        action="store_true",
        default=False,
        help="Interactive step healing mode"
    )


@pytest.fixture
def play(request):
    file_path = Path(request.node.path)
    original_name = request.node.originalname or request.node.name

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
        interactive=interactive,
        send_screenshots=True,
        provider="anthropic",
        base_url="https://api.z.ai/api/anthropic",
        generation_model="glm-5.1",
        classification_model="glm-5.3",
        classification_prompt="Write explanations and recommendations in English",
        generation_prompt="Prefer to use id attributes in HTML documents to find elements. "
                          "Make text matching checks case-insensitive.",
    )

    with PrettyPlay(request.node.name, str(cache_path),
                    hooks=[AllureStepHooks()], config=config) as pretty:
        yield pretty
