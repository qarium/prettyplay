import logging
import sys
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
- Submit search forms by pressing Enter inside the input field, not by clicking a submit button.

Constraints:
- Don't do confirmation checks of the action's completion.
- Don't use `if` statement in step code.
"""

_RESERVED_RECORD_FIELDS = set(logging.LogRecord("n", 0, "p", 0, "m", (), None).__dict__) | {"message", "asctime"}
_HUMAN_READABLE_EVENTS = frozenset(
    {
        "step_results_declared",
        "step_inputs",
        "step_candidate_code",
        "step_cached_code",
        "step_captured",
    }
)


class EventFormatter(logging.Formatter):
    """Append event payloads unless the message already renders the execution context."""

    def format(self, record: logging.LogRecord) -> str:
        """Render console text without duplicating human-readable execution context.

        Args:
            record: The log record, including its structured context.

        Returns:
            The formatted message, with payload fields for other event types.
        """
        message = super().format(record)
        event = getattr(record, "event", None)

        if isinstance(event, str) and event in _HUMAN_READABLE_EVENTS:
            return message

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_RECORD_FIELDS and not key.startswith("_")
        }

        if not extras:
            return message

        payload = " ".join(f"{key}={value!r}" for key, value in sorted(extras.items()))

        return f"{message} | {payload}"


def _configure_prettyplay_logging() -> None:
    logger = logging.getLogger("prettyplay")
    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(EventFormatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))

    logger.addHandler(handler)


_configure_prettyplay_logging()


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
        send_screenshots=True,
        provider="anthropic",
        base_url="https://api.z.ai/api/anthropic",
        generation_model="glm-5.3",
        # the diagnosis kicks in after 2 blind attempts instead of the library default 3 — the
        # diagnosed regeneration passes first try far more often than a third blind retry
        generation_attempts=2,
        # a wrong locator fails a candidate in 3s instead of the page default 30s —
        # every candidate restores the baseline after itself, replay keeps the page default
        probe_timeout=3,
        # the endpoint occasionally storms empty completions — two extra sends absorb it
        llm_request_attempts=10,
        # healing_attempts=3,
        classification_model="glm-5.3",
        classification_prompt=CLASSIFICATION_INSTRUCTIONS,
        generation_prompt=GENERATION_INSTRUCTIONS,
    )

    prettyplay = PrettyPlay(request.node.name, str(cache_path), config=config)
    prettyplay.add_hooks(AllureStepHooks(prettyplay))

    with prettyplay as pretty:
        yield pretty
