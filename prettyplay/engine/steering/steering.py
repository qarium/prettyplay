"""Interactive steering of a terminally stuck step: the engineer-in-the-loop REPL."""

import contextlib
import logging
import tempfile
from datetime import date
from pathlib import Path

from ...cache import CachedStep, StepCache, StepIdentity
from ...config import Config
from ...driver import PageFacade
from ...failures import ComplianceVerdictError, IncurableStepError, LLMUnavailableError
from ...llm import LLMProvider
from ...reporting import StepReporter
from ..compliance import check_step_compliance
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
- CHEAT SHEET: a compact reference of useful Playwright sync API idioms — guidance, not an allowlist; everything standard stays allowed
- USER INSTRUCTIONS: the project's binding code style guidance, when configured
- CODE: the existing step code that failed (regeneration requests only)
- ERROR: the failure description of the existing code (regeneration requests only)
- RECOMMENDATION: the diagnosis of the classification that preceded this regeneration, when present
- USER GUIDANCE: the engineer guidance message of the interactive steering, when present
- HISTORY: the accumulated steering turns, when present

Output exactly one Python code block with one function of the fixed form:

def step(page) -> None:
    ...

Rules:
- The function receives exactly one argument: the page — the genuine Playwright sync Page; the whole step runs inside the driver worker thread
- Import only from playwright.sync_api — no other imports, no other libraries
- Work through the standard Playwright sync API: locator factories, actions, waits, expect chains, plain asserts on immediate reads — everything standard is allowed; the CHEAT SHEET is guidance, never a boundary
- Assertions: for an assertion sentence end with a check — a waiting expect(...) chain for dynamic content, or an immediate read with a plain Python assert (assert locator.count() > 1)
- No fixed delays, no sleeps, no wait_for_timeout — locators and expect chains auto-wait
- The runtime owns the page lifecycle: never call page.close() or context.close()
- No stateful actions that outlive the step on the page shared by the whole test: page.route, page.clock, add_init_script, tracing, HAR, CDP — excluded from generated code; a cached step would poison every later step far from the cause
- Dialogs: capture with the stock means — with page.expect_event("dialog") as info: — perform the triggering action inside the block, read info.value.type, info.value.message, info.value.default_value, then info.value.accept() or info.value.dismiss()
- Popups and new tabs: capture with with page.expect_popup() as popup_info: — trigger the opening action inside the block, work through popup_info.value; page.bring_to_front() raises a page above the others
- Content inside an iframe goes through page.frame_locator(selector) — locate elements within the returned scope; nested frames chain
- Scrolling: locator.scroll_into_view_if_needed() and page.mouse.wheel(dx, dy) are the standard means
- RECOMMENDATION and USER GUIDANCE carry the diagnosis and the engineer's intent — follow them when they conflict with your first instinct
- USER INSTRUCTIONS are binding for everything below the safety core of these Rules: follow them when configured; silently ignoring an instruction is a violation
- The safety core of these Rules always outranks the instructions: the fixed function form, the import rule, the lifecycle rule, the stateful-action exclusions, no fixed delays. An instruction conflicting with a Rule or demanding a stateful action is unfollowable: never implement it silently — raise in the step code with the message "instruction conflicts with rule Y" naming the conflict, so the failure surfaces loudly
- Prefer-type instructions are conditional by their own wording: follow them when the page offers the option — best-effort with a graceful fallback is compliance
- The step must complete exactly what STEP says — nothing more, nothing less
- Output only the code block, no explanations"""

#: The compact standard Playwright sync API reference of every guided request;
#: guidance, not an allowlist — everything standard stays allowed.
#: Frozen mirror of ``.goga/usages/prompts/cheatsheet.md`` — the whole file, verbatim
#: (the practice has no ``---`` separator, so the whole-file rule is the only mirror
#: rule with no extraction logic to drift); the constant changes only together with
#: the file. A local copy of the engine constant, not an import — the same
#: frozen-mirror rule; no runtime read of ``.goga/`` ever happens.
CHEAT_SHEET = """# Playwright cheat sheet

The compact standard Playwright sync API reference carried by every step-code generation and regeneration request
of prettyplay — referenced by the engine and steering cells as the `cheat_sheet` practice; rendered by the provider
implementations as the leading CHEAT SHEET block of the user content. Guidance, not an allowlist: everything
standard stays allowed — the error-driven regeneration loop is the second line of defense against hallucinated
calls. Target audience: the generation model — a model that knows Playwright weakly writes a correct step from
this reference alone.

## Locator factories

    page.get_by_role("button", name="Sign in")
    page.get_by_label("Username")
    page.get_by_text("Welcome back")
    page.get_by_placeholder("Search")
    page.get_by_alt_text("Logo")
    page.get_by_title("Close")
    page.get_by_test_id("submit")
    page.locator("css selector | //xpath | [data-qa=row]")

## Narrowing

    locator.first / locator.last / locator.nth(2)
    locator.filter(has_text="Product X")
    locator.and_(other) / locator.or_(other)

## Actions

    .click() / .dblclick() / .click(button="right")
    .fill("text") / .clear() / .press("Enter") / .press("Control+A")
    .check() / .uncheck() / .hover() / .select_option("v")
    .drag_to(target) / .set_input_files("path.png")

## Navigation and waits

    page.goto(url) / page.go_back() / page.go_forward() / page.reload()
    page.wait_for_url("**/dashboard") / page.wait_for_load_state("networkidle")

## Waiting assertions — expect chains

    from playwright.sync_api import expect

    expect(locator).to_be_visible() / to_be_hidden()
    expect(locator).to_be_enabled() / to_be_checked()
    expect(locator).to_have_text("...") / to_contain_text("...")
    expect(locator).to_have_value("v") / to_have_attribute("href", "/docs")
    expect(page).to_have_url("**/dashboard") / to_have_title("Dashboard")

## Count forms — "the page shows a list of X"

    videos = page.get_by_role("listitem")
    expect(videos.first).to_be_visible()
    assert videos.count() > 1

An exact count is the rarer need: `expect(videos).to_have_count(3)`.

## Immediate reads with plain asserts

    assert locator.count() >= 1
    assert "Dashboard" in page.title()

## Dialogs

    with page.expect_event("dialog") as info:
        page.get_by_role("button", name="Delete").click()
    dialog = info.value
    dialog.type / dialog.message / dialog.default_value
    dialog.accept() / dialog.dismiss() / dialog.accept("the answer")

## Popups and new tabs

    with page.expect_popup() as popup_info:
        page.get_by_role("link", name="Open docs").click()
    popup = popup_info.value
    popup.bring_to_front()

## Frames

    frame = page.frame_locator("#checkout")
    frame.get_by_role("button", name="Pay").click()

## Scrolling

    locator.scroll_into_view_if_needed()
    page.mouse.wheel(0, 600)
"""

#: The local commands of the dialog — context services without an LLM request.
_LOCAL_COMMANDS = frozenset({"snapshot", "screenshot", "error", "code"})

#: Lines of the accessibility snapshot shown in the banner fragment.
_SNAPSHOT_FRAGMENT_LINES = 20

#: Prefix of the temporary screenshot file of a dialog.
_SCREENSHOT_PREFIX = "prettyplay-steering-"

#: The explanation of the ``on_healed`` event of an interactively healed step.
_HEALED_EXPLANATION = "healed interactively by engineer guidance"


class StepSteering:
    """Steers a terminally stuck step back to green through engineer guidance.

    The opt-in human-in-the-loop escape hatch opened by the step executor at
    the exact moment an ``IncurableStepError`` would propagate. The dialog
    shows the full failure context, takes one guidance line at a time and
    turns each into a regeneration request executed against the live page:
    every turn ends green — the candidate passes the instruction compliance
    gate, then the healed step is written back to the cache and reported —
    or red — the outcome joins the history of the next request. A high
    compliance finding is a red turn of its own: the violation joins the
    history and the prompt reopens, the candidate never reaches the cache.
    Local commands serve the context without the LLM; quit, EOF, SIGINT and
    an unreadable stdin at the prompt end the dialog declined, a provider
    failure and a gate hard failure end it, and no budget is ever consumed:
    the human in the loop is the bound.

    Attributes:
        _config: project settings; the generation instructions and the
            screenshot flag feed the guided requests.
        _provider: the LLM port implementation of the guided requests.
        _cache: the store the healed step is written back to.
        _reporter: the visibility point of the healed step.
        _screenshot_path: the path of the one temporary screenshot file of
            the current dialog; ``None`` — the dialog took no screenshot
            yet.
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
        self._screenshot_path: str | None = None

    def steer(
        self,
        failure: IncurableStepError,
        identity: StepIdentity,
        previous_steps: list[str],
        page: PageFacade,
    ) -> CachedStep | None:
        """Run the steering dialog over a terminal failure.

        The dialog renders the context banner once, then takes one guidance
        line at a time: local commands serve the context without the LLM, and
        every guidance message becomes one regeneration request executed
        against the live page. A green turn passes the instruction compliance
        gate before the write-back: an empty findings list heals; medium and
        low findings pass with a WARNING; a high finding never reaches the
        cache — the violation joins the history and the prompt reopens; a
        gate hard failure (the provider unavailable or a malformed verdict)
        ends the dialog declined after the gate failure line.

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
        self._screenshot_path = None  # a fresh dialog owns no screenshot file yet
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

            # the gate sits outside the execution try/except: its hard failures end the
            # dialog, they never degrade into a red turn of the executed candidate
            try:
                findings = check_step_compliance(self._config, self._provider, failure.step_text, code)
            except (LLMUnavailableError, ComplianceVerdictError) as gate_failure:
                print(f"compliance gate failed: {gate_failure}")
                logger.warning(
                    "compliance gate failed",
                    extra={"step_text": failure.step_text, "gate_failure": str(gate_failure)},
                )
                return None  # the green candidate stays unchecked — the original failure propagates

            high = next((finding for finding in findings if finding.priority == "high"), None)
            if high is not None:  # the violation never reaches the cache — steer the fix
                violation = f"violated instruction: {high.instruction} — {high.explanation}"
                print(f"compliance violation — not written back: {violation}")
                history.append(f"{message} => instruction violated: {_first_line(high.instruction)}")
                continue

            if findings:  # medium and low findings are visible, never blocking
                logger.warning(
                    "compliance findings passed",
                    extra={
                        "step_text": failure.step_text,
                        "findings": [
                            f"{finding.priority}: {finding.instruction} — {finding.explanation}" for finding in findings
                        ],
                    },
                )
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
            cheat_sheet=CHEAT_SHEET,
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
        """Write a full PNG to the one temporary file of the dialog; return its path.

        One file per dialog: the banner screenshot and every ``screenshot``
        command overwrite it — a dialog never accumulates temporary PNGs.

        Args:
            page: the live page facade of the test.

        Returns:
            The path of the written file; ``None`` when the interaction
            failed — its failure text was printed.
        """
        path = self._screenshot_path
        fresh = path is None  # the first screenshot of the dialog allocates the one file
        try:
            png = page.screenshot()
            if fresh:
                with tempfile.NamedTemporaryFile(prefix=_SCREENSHOT_PREFIX, suffix=".png", delete=False) as target:
                    path = target.name
                    target.write(png)
            else:  # every later screenshot of the dialog overwrites the one file
                Path(path).write_bytes(png)
        except Exception as failure:  # a dead page never kills the dialog
            if fresh and path is not None:
                with contextlib.suppress(OSError):
                    Path(path).unlink()  # a partial write leaves nothing worth inspecting
            print(f"screenshot unavailable: {failure}")
            return None

        self._screenshot_path = path
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
