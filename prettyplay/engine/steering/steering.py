"""Interactive steering of a terminally stuck step: the engineer-in-the-loop REPL."""

import contextlib
import logging
import tempfile
from datetime import date
from pathlib import Path

from ...cache import CachedStep, StepCache, StepIdentity
from ...config import Config
from ...driver import PageFacade
from ...failures import IncurableStepError, LLMUnavailableError
from ...llm import LLMProvider
from ...reporting import StepReporter
from ..execution import run_step_code

logger = logging.getLogger("prettyplay")

#: System prompt of every guided regeneration request of the steering dialog.
#: Frozen mirror of ``.goga/usages/prompts/generation.md`` (the section after the
#: ``---`` separator) — the single source of the prompt; the constant changes only
#: together with the file. A local copy of the engine constant, not an import:
#: frozen mirrors stay cell-owned, no runtime read of ``.goga/`` ever happens.
SYSTEM_PROMPT = """You generate executable Python code for one step of a web UI test.

Input you receive:
- STEP: the step sentence in a natural language
- PREVIOUS STEPS: the sentences of the previous steps of the test, in order
- PAGE SNAPSHOT: the accessibility snapshot of the current page
- SCREENSHOT: an image of the page, when attached
- PAGE API: the exact surface listing of the page facade — call nothing outside it
- USER INSTRUCTIONS: the project's code style guidance, when configured
- CODE: the existing step code that failed (regeneration requests only)
- ERROR: the failure description of the existing code (regeneration requests only)
- RECOMMENDATION: the diagnosis of the classification that preceded this regeneration, when present
- USER GUIDANCE: the engineer guidance message of the interactive steering, when present
- HISTORY: the accumulated steering turns, when present

Output exactly one Python code block with one function of the fixed form:

def step(page) -> None:
    ...

Rules:
- The function receives exactly one argument: the page facade — the Playwright-mirroring page API. Never import anything, never use other libraries
- Work only through the page API: the request carries the exact surface listing of the page facade — call nothing outside it
- For an assertion sentence end with an expectation call; for an action sentence perform the actions
- Assertions happen only through the expectation calls of the facade — never a Python assert on a locator, never SDK-style state reads
- Dialogs: when the step verifies or steers a dialog, capture it — with page.expect_dialog() as dialog: — perform the triggering action inside the block, read dialog.message and dialog.type, then dialog.accept() or dialog.dismiss()
- Popups and new tabs: capture the opened page — with page.expect_popup() as popup: — trigger the opening action inside the block, work through the popup facade; bring_to_front() raises a page above the others
- Content inside an iframe goes through page.frame_locator(selector) — locate elements within the returned frame
- Scroll abilities exist for scenario scrolling: bring an element into view, scroll by an amount, to the page end or start, inside a scrollable container
- No fixed delays, no sleeps, no explicit waits — the facade waits itself
- RECOMMENDATION and USER GUIDANCE carry the diagnosis and the engineer's intent — follow them when they conflict with your first instinct
- The step must complete exactly what STEP says — nothing more, nothing less
- Output only the code block, no explanations"""

#: Frozen surface listing of the driver facade — the only calls step code may make.
#: Mirrors ``prettyplay/driver/.usages/facade.md`` verbatim; the driver facade is a
#: parity contract of the Playwright sync API, so this constant changes only
#: together with it. A local copy of the engine constant, not an import — the
#: same frozen-mirror rule. ``page.close()`` stays out: it is a runtime method
#: of PrettyPlay, not of step code.
PAGE_API_SURFACE = """page.goto(url)                                — navigate and wait for the load state
page.go_back()                                — browser-history back
page.go_forward()                             — browser-history forward
page.reload()                                 — reload and wait for the load state
page.wait_for_url(url)                        — wait until the URL matches a glob pattern
page.wait_for_load_state(state)               — wait for load, domcontentloaded or networkidle
page.expect_url(url)                          — assert the URL matches a glob pattern
page.expect_title(title)                      — assert the title contains
page.get_by_role(role, name)                  — element by aria role and accessible name
page.get_by_label(label)                      — element by associated label
page.get_by_text(text)                        — element by visible text
page.get_by_placeholder(placeholder)          — input by placeholder text
page.get_by_alt_text(alt)                     — image by alt text
page.get_by_title(title)                      — element by title attribute
page.get_by_test_id(test_id)                  — element by data-testid
page.locator(selector)                        — element by any selector — CSS, XPath, attribute
page.expect_dialog()                          — context manager — the block performs the triggering action; yields the DialogFacade
page.expect_popup()                           — context manager — the block performs the opening action; yields the popup as a full PageFacade
page.bring_to_front()                         — raise this page above the others — the switching primitive
page.pages                                    — the open pages of the context, each a full PageFacade
page.frame_locator(selector)                  — the locating scope of one iframe — yields a FrameFacade
page.aria_snapshot()                          — accessibility-tree page state
page.screenshot()                             — full-page PNG bytes
page.url                                      — current URL
page.scroll_to_element(element)               — bring an element into the viewport (works inside scrollable ancestors)
page.scroll_down(pixels)                      — scroll the page down by an amount
page.scroll_up(pixels)                        — scroll the page up by an amount
page.scroll_to_bottom()                       — scroll to the end of the page
page.scroll_to_top()                          — scroll to the start of the page
page.scroll_into_view(element, container)     — bring an element into view inside a specific scrollable container
page.scroll_container_down(container, pixels) — scroll a scrollable container down by an amount
page.scroll_container_up(container, pixels)   — scroll a scrollable container up by an amount
dialog.accept(prompt_text) — accept; prompt_text answers a prompt dialog (empty — no answer)
dialog.dismiss()           — dismiss
dialog.type                — alert, confirm, prompt or beforeunload
dialog.message             — the dialog message
dialog.default_value       — the prompt prefill of a prompt dialog
frame.get_by_role(role, name) — and the whole get_by_* family — locate inside the iframe
frame.locator(selector)                                       — any selector inside the iframe
frame.frame_locator(selector)                                 — the scope of a nested iframe
element.first                         — the first match — positional narrowing
element.last                          — the last match — positional narrowing
element.nth(index)                    — the match at a 0-based index; negative counts from the end
element.filter(has_text=..., has_not_text=..., has=..., has_not=...) — narrow by content — all predicates optional
element.or_(other)                    — union locator — matches either; when both branches may match, compose positional narrowing (first, last, nth) to satisfy strict mode
element.and_(other)                   — intersection locator — matches both
element.click(button)                 — click; empty button = left, "right" = right button
element.dblclick()                    — double click
element.fill(value)                   — set input text
element.clear()                       — clear the input
element.press(key)                    — press a key or combination, e.g. "Enter", "Control+A"
element.check()                       — check a checkbox or radio
element.uncheck()                     — uncheck
element.hover()                       — hover
element.select_option(value)          — choose an option
element.drag_to(target)               — drag onto another element
element.set_input_files(path)         — upload one file by filesystem path
element.expect_visible()              — assert visible
element.expect_hidden()               — assert hidden
element.expect_text(text)             — assert text contains (substring, whitespace-normalized)
element.expect_enabled()              — assert enabled
element.expect_value(value)           — assert the input value
element.expect_checked()              — assert the checkbox/radio state
element.expect_count(count)           — assert the matched element count
element.expect_attribute(name, value) — assert the attribute value"""

#: The local commands of the dialog — context services without an LLM request.
_LOCAL_COMMANDS = frozenset({"snapshot", "screenshot", "error", "code"})

#: Lines of the accessibility snapshot shown in the banner fragment.
_SNAPSHOT_FRAGMENT_LINES = 20

#: Prefix of the temporary screenshot files the dialog writes.
_SCREENSHOT_PREFIX = "prettyplay-steering-"

#: The explanation of the ``on_healed`` event of an interactively healed step.
_HEALED_EXPLANATION = "healed interactively by engineer guidance"


class StepSteering:
    """Steers a terminally stuck step back to green through engineer guidance.

    The opt-in human-in-the-loop escape hatch opened by the step executor at
    the exact moment an ``IncurableStepError`` would propagate. The dialog
    shows the full failure context, takes one guidance line at a time and
    turns each into a regeneration request executed against the live page:
    every turn ends green — the healed step is written back to the cache and
    reported — or red — the outcome joins the history of the next request.
    Local commands serve the context without the LLM; quit, EOF, SIGINT and
    an unreadable stdin at the prompt end the dialog declined, a provider
    failure ends it, and no budget is ever consumed: the human in the loop
    is the bound.

    Attributes:
        _config: project settings; the generation instructions and the
            screenshot flag feed the guided requests.
        _provider: the LLM port implementation of the guided requests.
        _cache: the store the healed step is written back to.
        _reporter: the visibility point of the healed step.
    """

    def __init__(
        self,
        config: Config,
        provider: LLMProvider,
        cache: StepCache,
        reporter: StepReporter | None,
    ) -> None:
        """Keep the collaborators of the steering dialog.

        Args:
            config: project settings; ``generation_prompt`` renders into every
                guided request, ``send_screenshots`` attaches page images.
            provider: the LLM port implementation of the guided requests.
            cache: the store the healed step is written back to.
            reporter: the visibility point of the healed step; ``None`` — the
                hook-less default reporter, so an omitted reporter never
                breaks the healed-step report.
        """
        self._config = config
        self._provider = provider
        self._cache = cache
        self._reporter = reporter if reporter is not None else StepReporter([])

    def steer(
        self,
        failure: IncurableStepError,
        identity: StepIdentity,
        previous_steps: list[str],
        page: PageFacade,
    ) -> CachedStep | None:
        """Run the steering dialog over a terminal failure.

        Args:
            failure: the terminal failure about to propagate — the source of
                the step sentence, the failed code, the underlying error and
                the verdict.
            identity: the address of the stuck step — the healed step is
                written back under it.
            previous_steps: the sentences of the previous steps of the test —
                scenario context of the guided requests.
            page: the live page facade of the test.

        Returns:
            The healed cached step on a successful guided execution; ``None``
            — the dialog was declined or died: the caller propagates the
            original failure.

        Raises:
            KeyboardInterrupt: a SIGINT outside the prompt escapes directly —
                never swallowed into a turn or a heal.
        """
        history: list[str] = []
        self._render_banner(failure, page)
        logger.info("steering_opened", extra={"step_text": failure.step_text})

        while True:
            message = self._read_guidance(failure)
            if message is None:  # quit, EOF, SIGINT or an unreadable stdin — declined
                return None

            command = message.strip()
            if not command:  # blank line — re-prompt, no LLM request, no history
                continue
            if command in _LOCAL_COMMANDS:
                self._serve_local_command(command, failure, page)
                continue

            logger.info("steering_guidance", extra={"guidance": message})
            print("regenerating with USER GUIDANCE — executing against the live page")

            try:
                code = self._guided_request(failure, previous_steps, page, message, history)
            except LLMUnavailableError as outcome:
                print(f"provider unavailable: {outcome}")
                return None

            try:
                run_step_code(code, page)  # bare — the settle window never re-arms inside the dialog
            except Exception as outcome:  # a red turn returns to the prompt, never escapes
                print(f"turn failed: {outcome}")
                history.append(f"{message} => {_first_line(str(outcome))}")
                continue

            return self._write_back(failure, identity, code)

    def _render_banner(self, failure: IncurableStepError, page: PageFacade) -> None:
        """Render the context banner of the dialog.

        The step sentence, the failed code, the underlying error, the verdict
        with its recommendation when present, a fragment of the fresh
        accessibility snapshot and the path of a full screenshot written to a
        temporary file. Every page interaction is guarded: a failed one
        prints its own failure text and the banner continues.

        Args:
            failure: the terminal failure the dialog opens over.
            page: the live page facade of the test.
        """
        print(f'── step "{failure.step_text}" — about to raise IncurableStepError ──')
        print(f"intent:   {failure.step_text}")
        print("code:")
        print(failure.code)
        print(f"error:    {failure.error}")
        if failure.verdict is not None:
            print(f"verdict:  {failure.verdict.category} — {failure.verdict.explanation}")
            print(f"          recommendation: {failure.verdict.recommendation}")
        print("snapshot:")
        print(_snapshot_fragment(self._guarded_snapshot(page)))
        path = self._screenshot_file(page)
        if path is not None:
            print(f"screenshot: {path}")
        print("commands: snapshot | screenshot | error | code | quit")

    def _read_guidance(self, failure: IncurableStepError) -> str | None:
        """Read one guidance line from the prompt.

        Args:
            failure: the terminal failure the dialog opens over — the source
                of the step sentence of the decline record.

        Returns:
            The raw guidance message; ``None`` — quit, EOF, SIGINT or an
            unreadable stdin ended the dialog declined.
        """
        try:
            message = input("guidance> ")
        except (EOFError, KeyboardInterrupt, OSError):  # an unreadable stdin (captured CI) declines like EOF
            logger.info("steering_declined", extra={"step_text": failure.step_text})
            return None

        if message.strip() == "quit":
            logger.info("steering_declined", extra={"step_text": failure.step_text})
            return None

        return message

    def _serve_local_command(self, command: str, failure: IncurableStepError, page: PageFacade) -> None:
        """Serve one local context command without an LLM request.

        Args:
            command: the command name — one of snapshot, screenshot, error,
                code.
            failure: the terminal failure the dialog opens over.
            page: the live page facade of the test.
        """
        if command == "snapshot":
            print("snapshot:")
            print(self._guarded_snapshot(page))
            return
        if command == "screenshot":
            path = self._screenshot_file(page)
            if path is not None:
                print(path)
            return
        if command == "error":
            print(f"error:    {failure.error}")
            return
        print("code:")  # the code command — the last of the fixed set
        print(failure.code)

    def _guided_request(
        self,
        failure: IncurableStepError,
        previous_steps: list[str],
        page: PageFacade,
        guidance: str,
        history: list[str],
    ) -> str:
        """Run one guided regeneration request against the provider.

        Args:
            failure: the terminal failure the dialog opens over — the source
                of the step sentence, the failed code and the error.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade of the test.
            guidance: the engineer guidance message of this turn.
            history: the accumulated steering turns of the dialog so far.

        Returns:
            The generated step code of the fixed form.

        Raises:
            LLMUnavailableError: the provider request failed; the caller ends
                the dialog.
        """
        screenshot = self._guarded_screenshot_bytes(page) if self._config.send_screenshots else None

        return self._provider.generate_step_code(
            prompt=SYSTEM_PROMPT,
            user_instructions=self._config.generation_prompt,
            step_text=failure.step_text,
            previous_steps=previous_steps,
            snapshot=self._guarded_snapshot(page),
            screenshot=screenshot,
            page_api=PAGE_API_SURFACE,
            existing_code=failure.code,
            error=failure.error,
            recommendation=None,  # the verdict diagnosis is banner-only — the live guidance replaces it
            guidance=guidance,
            guidance_history=history,
        )

    def _write_back(self, failure: IncurableStepError, identity: StepIdentity, code: str) -> CachedStep:
        """Write the proven guided step back to the cache and report it healed.

        Args:
            failure: the terminal failure the dialog opened over — the source
                of the step sentence of the event.
            identity: the address of the stuck step.
            code: the step code that just worked on the live page.

        Returns:
            The healed cached step, already stored and reported.
        """
        step = CachedStep(
            identity=identity,
            code=code,
            created_at=date.today().isoformat(),  # noqa: DTZ011 — calendar date of the healed step
        )
        self._cache.save(step)
        self._reporter.emit("on_healed", {"step_text": failure.step_text, "explanation": _HEALED_EXPLANATION})
        if self._cache.writable:  # save is best-effort — a read-only cache skipped the write loudly
            print("step green — healed step written to the cache")
        else:
            print("step green — cache write skipped (read-only cache)")
        return step

    def _guarded_snapshot(self, page: PageFacade) -> str:
        """Read the accessibility snapshot; a failed interaction degrades to empty.

        Args:
            page: the live page facade of the test.

        Returns:
            The full accessibility snapshot; empty when the interaction
            failed — its failure text was printed.
        """
        try:
            return page.aria_snapshot()
        except Exception as failure:  # a dead page never kills the dialog
            print(f"snapshot unavailable: {failure}")
            return ""

    def _screenshot_file(self, page: PageFacade) -> str | None:
        """Write a full PNG to the system temporary directory and return its path.

        Args:
            page: the live page facade of the test.

        Returns:
            The path of the written file; ``None`` when the interaction
            failed — its failure text was printed.
        """
        path: str | None = None
        try:
            png = page.screenshot()
            with tempfile.NamedTemporaryFile(prefix=_SCREENSHOT_PREFIX, suffix=".png", delete=False) as target:
                path = target.name
                target.write(png)
        except Exception as failure:  # a dead page never kills the dialog
            if path is not None:
                with contextlib.suppress(OSError):
                    Path(path).unlink()  # a partial write leaves nothing worth inspecting
            print(f"screenshot unavailable: {failure}")
            return None

        return path

    def _guarded_screenshot_bytes(self, page: PageFacade) -> bytes | None:
        """Read the screenshot bytes of a guided request; a failed interaction degrades to None.

        Args:
            page: the live page facade of the test.

        Returns:
            The full-page PNG bytes; ``None`` when the interaction failed —
            its failure text was printed.
        """
        try:
            return page.screenshot()
        except Exception as failure:  # a dead page never kills the dialog
            print(f"screenshot unavailable: {failure}")
            return None


def _snapshot_fragment(snapshot: str) -> str:
    """Return the first lines of a snapshot — the banner fragment.

    Args:
        snapshot: the full accessibility snapshot text.

    Returns:
        The first lines of the snapshot, joined with newlines; empty when the
        snapshot itself is empty.
    """
    return "\n".join(snapshot.splitlines()[:_SNAPSHOT_FRAGMENT_LINES])


def _first_line(text: str) -> str:
    """Return the first line of a failure text — the history-entry tail.

    Args:
        text: the full failure text of a red turn.

    Returns:
        The text up to the first newline; the whole text when single-line.
    """
    return text.partition("\n")[0]
