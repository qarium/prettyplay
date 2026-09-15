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
from ..attempts import (
    OUTCOME_COMPLIANCE_BLOCKED,
    OUTCOME_EXECUTION_FAILED,
    OUTCOME_FAILED_CHECK,
    OUTCOME_REJECTED,
    StepAttempt,
)
from ..compliance import check_step_compliance
from ..execution import run_step_code
from ..text import format_step_error

logger = logging.getLogger("prettyplay")

#: System prompt of every guided regeneration request of the steering dialog.
#: Frozen mirror of ``.goga/usages/prompts/generation.md`` (the section after the
#: ``---`` separator) — the single source of the prompt; the constant changes only
#: together with the file. A local copy of the engine constant, not an import:
#: frozen mirrors stay cell-owned, no runtime read of ``.goga/`` ever happens.
SYSTEM_PROMPT = """You generate executable Python code for one step of a web UI test.

Input you receive:
- STEP TYPE: action or assertion — the kind of the step
- STEP: the step sentence in a natural language
- PREVIOUS STEPS: the sentences of the previous steps of the test, in order
- PAGE SNAPSHOT: the accessibility snapshot of the current page
- PAGE URL: the current URL of the page, when present
- SCREENSHOT: an image of the page, when attached
- CHEAT SHEET: a compact reference of useful Playwright sync API idioms — guidance, not an allowlist; everything standard stays allowed
- USER INSTRUCTIONS: the project's binding code style guidance, when configured
- HISTORY: the verbatim record of every attempt of this step so far, when present — the original cached code first when it exists; each record carries the attempt outcome, the URL before -> after line, the complete candidate code and the complete error
- RECOMMENDATION: the diagnosis of the classification that preceded this regeneration, when present
- USER GUIDANCE: the engineer guidance message of the interactive steering, when present

Output exactly one Python code block with one function of the fixed form:

def step(page) -> None:
    ...

Rules:
- The function receives exactly one argument: the page — the genuine Playwright sync Page; the whole step runs inside the driver worker thread
- Import from playwright.sync_api and the Python standard library only — no third-party
  libraries; imports are global only: at the top level of the code block, before `def
  step`, never inside the function body
- Work through the standard Playwright sync API: locator factories, actions, waits, expect chains, plain asserts on immediate reads — everything standard is allowed; the CHEAT SHEET is guidance, never a boundary
- Assertions: for an assertion sentence end with a check — a waiting expect(...) chain for dynamic content, or an immediate read with a plain Python assert (assert locator.count() > 1)
- No fixed delays, no sleeps, no wait_for_timeout — locators and expect chains auto-wait
- The runtime owns the page lifecycle: never call page.close() or context.close()
- No stateful actions that outlive the step on the page shared by the whole test: page.route, page.clock, add_init_script, tracing, HAR, CDP — excluded from generated code; a cached step would poison every later step far from the cause
- Dialogs: capture with the stock means — with page.expect_event("dialog") as info: — perform the triggering action inside the block, read info.value.type, info.value.message, info.value.default_value, then info.value.accept() or info.value.dismiss()
- Popups and new tabs: capture with with page.expect_popup() as popup_info: — trigger the opening action inside the block, work through popup_info.value; page.bring_to_front() raises a page above the others
- Content inside an iframe goes through page.frame_locator(selector) — locate elements within the returned scope; nested frames chain
- Scrolling: locator.scroll_into_view_if_needed() and page.mouse.wheel(dx, dy) are the standard means
- The page state may already include the effects of prior attempts or manual intervention — the HISTORY records and their URL before -> after lines show what already happened. Your code must produce the step outcome itself: never rely on the current page state already satisfying the step; complete the action or the check even if the page looks done
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
    page.url  # the current URL — an immediate read beside the waiting forms

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
    assert "/dashboard" in page.url

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

#: The banner label column — every banner label aligns to the widest one,
#: ``commands:``. The banner's own presentation padding; the render text
#: inside stays unpadded.
_BANNER_LABEL_WIDTH = len("commands:")

#: Prefix of the temporary screenshot file of a dialog.
_SCREENSHOT_PREFIX = "prettyplay-steering-"

#: The explanation of the ``on_healed`` event of an interactively healed step.
_HEALED_EXPLANATION = "healed interactively by engineer guidance"


class StepSteering:
    """Steers a terminally stuck step back to green through engineer-approved turns.

    The opt-in human-in-the-loop escape hatch opened by the step executor at
    the exact moment an ``IncurableStepError`` would propagate. The dialog
    shows the full failure context — the terminal render, the current URL, a
    screenshot file — then takes one guidance line at a time and turns each
    into a regeneration request whose complete generated code shows at a
    strict approval gate: nothing executes unseen, only a bare ``y`` runs
    the candidate against the live page. The dialog joins the one shared
    per-step attempt history the executor passes in — the same record list
    the engine loops grew, anchored by the original failure — and appends
    one verbatim record per completed turn: a rejection (the same URL on
    both sides, the code never ran), a red execution, a compliance block
    alike. Every turn ends green — the candidate passes the two-dimension
    compliance gate judging from the step type and the shared history, then
    the healed step is written back to the cache and reported — or the
    prompt reopens with the grown history. Local commands serve the context
    without the LLM; quit, EOF, SIGINT and an unreadable stdin at either
    prompt end the dialog declined, a provider failure and a gate hard
    failure end it, and no budget is ever consumed: the human in the loop
    is the bound.

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

    def steer(  # noqa: PLR0913, PLR0917 — the signature is fixed by the steering contract
        self,
        failure: IncurableStepError,
        identity: StepIdentity,
        step_text: str,
        step_type: str,
        previous_steps: list[str],
        page: PageFacade,
        attempt_history: list[StepAttempt],
    ) -> CachedStep | None:
        """Run the steering dialog over a terminal failure.

        The dialog renders the context banner once, then takes one guidance
        line at a time: local commands serve the context without the LLM,
        and every guidance message becomes one regeneration request whose
        complete generated code shows at the strict ``run? [y/N]``
        approval gate — only a bare ``y`` executes it against the live
        page, nothing runs unseen. Every request carries the honest inputs
        — the raw step sentence, the step type — plus the rendered shared
        attempt history in place of any dialog-local turn history. A
        rejected turn, a failed turn and a blocked turn each append one
        complete record into the shared history — the URL pair brackets the
        turn, identical on both sides when the engineer rejected the
        candidate without execution — and the prompt reopens with the grown
        history. A green turn passes the two-dimension compliance gate
        before the write-back: an empty findings list heals; medium and low
        findings pass with a WARNING; a high finding of either dimension
        never reaches the cache — the violation joins the history and the
        prompt reopens; a gate hard failure (the provider unavailable or a
        malformed verdict) ends the dialog declined after the gate failure
        line.

        Args:
            failure: the terminal failure about to propagate — the source of
                the failed code, the underlying error and the verdict.
            identity: the address of the stuck step — the healed step is
                written back under it.
            step_text: the raw sentence of the stuck step as written by the
                engineer — carried into every guided request and the gate
                verbatim.
            step_type: action or assertion — carried into every guided
                request and the gate verdict.
            previous_steps: the sentences of the previous steps of the test —
                scenario context of the guided requests.
            page: the live page facade of the test.
            attempt_history: the shared per-step attempt history grown by
                the engine loops and anchored by record 0 — the dialog
                appends every completed turn to it; the history survives
                the dialog.

        Returns:
            The healed cached step on a successful approved turn; ``None`` —
            the dialog was declined or died: the caller propagates the
            original failure.

        Raises:
            KeyboardInterrupt: a SIGINT outside the prompts and the approval
                gate escapes directly — never swallowed into a turn or a
                heal.
        """
        self._screenshot_path = None  # a fresh dialog owns no screenshot file yet
        self._render_banner(failure, step_text, page)
        logger.info("steering_opened", extra={"step_text": step_text})

        while True:
            message = self._await_guidance(failure, step_text, page)
            if message is None:  # quit, EOF, SIGINT or an unreadable stdin — declined
                return None

            logger.info("steering_guidance", extra={"guidance": message})
            print("regenerating with USER GUIDANCE")

            try:
                code = self._guided_request(step_text, step_type, previous_steps, page, message, attempt_history)
            except LLMUnavailableError as outcome:
                print(f"provider unavailable: {outcome}")
                return None

            try:
                approved = self._confirm_run(code)
            except (EOFError, KeyboardInterrupt, OSError):  # a dead approval prompt declines the dialog
                logger.info("steering_declined", extra={"step_text": step_text})
                return None

            if not approved:  # the code never runs — one read, the same URL on both sides
                url = self._guarded_url(page) or ""
                attempt_history.append(_record(code, "", OUTCOME_REJECTED, url, url))
                continue

            url_before = self._guarded_url(page) or ""
            try:
                run_step_code(code, page)  # bare — the settle window never re-arms inside the dialog
            except Exception as outcome:  # a red turn returns to the prompt, never escapes
                print(f"turn failed: {outcome}")
                url_after = self._guarded_url(page) or ""
                label = OUTCOME_FAILED_CHECK if isinstance(outcome, AssertionError) else OUTCOME_EXECUTION_FAILED
                attempt_history.append(_record(code, format_step_error(outcome), label, url_before, url_after))
                continue
            url_after = self._guarded_url(page) or ""

            # the gate sits outside the execution try/except: its hard failures end the
            # dialog, they never degrade into a red turn of the executed candidate; the
            # history it judges holds every prior turn — the candidate rides the CODE block
            try:
                findings = check_step_compliance(
                    self._config, self._provider, step_text, step_type, code, attempt_history
                )
            except (LLMUnavailableError, ComplianceVerdictError) as gate_failure:
                print(f"compliance gate failed: {gate_failure}")
                logger.warning(
                    "compliance gate failed",
                    extra={"step_text": step_text, "gate_failure": str(gate_failure)},
                )
                return None  # the green candidate stays unchecked — the original failure propagates

            high = next((finding for finding in findings if finding.priority == "high"), None)
            if high is not None:  # the violation never reaches the cache — steer the fix
                violation = f"{high.dimension} violation: {high.instruction} — {high.explanation}"
                print(f"compliance violation — not written back: {violation}")
                attempt_history.append(_record(code, violation, OUTCOME_COMPLIANCE_BLOCKED, url_before, url_after))
                continue

            if findings:  # medium and low findings are visible, never blocking
                logger.warning(
                    "compliance findings passed",
                    extra={
                        "step_text": step_text,
                        "findings": [
                            f"{finding.priority} {finding.dimension}: {finding.instruction} — {finding.explanation}"
                            for finding in findings
                        ],
                    },
                )
            return self._write_back(step_text, identity, code)

    def _render_banner(self, failure: IncurableStepError, step_text: str, page: PageFacade) -> None:
        """Render the context banner of the dialog.

        The step header, the failed code, the full terminal render of the
        failure, the current URL and the path of a full screenshot written
        to a temporary file — no snapshot fragment: the ``snapshot``
        command prints the whole tree on demand, and the render already
        carries the verdict explanation and recommendation. Every page
        interaction is guarded: a failed one prints its own failure text
        and the banner continues.

        Args:
            failure: the terminal failure the dialog opens over — the source
                of the failed code and the terminal render.
            step_text: the raw sentence of the stuck step — the banner
                header names it.
            page: the live page facade of the test.
        """
        print(f'── step "{step_text}" — about to raise IncurableStepError ──')
        print(_banner_line("code:", failure.code))
        print(_banner_line("error:", str(failure)))

        url = self._guarded_url(page)

        if url is not None:
            print(_banner_line("url:", url))

        path = self._screenshot_file(page)

        if path is not None:
            print(_banner_line("shot:", path))

        print(_banner_line("commands:", "snapshot | screenshot | error | code | quit"))

    def _confirm_run(self, code: str) -> bool:
        """Show the complete generated code and read the strict approval answer.

        The approval gate of every turn: the candidate reaches the live page
        only after this returns ``True`` — a bare ``y``, nothing else
        executes.

        Args:
            code: the complete generated step code of this turn.

        Returns:
            ``True`` — the engineer approved the execution; ``False`` — any
            other answer.

        Raises:
            EOFError: the approval prompt hit the end of the input.
            KeyboardInterrupt: a SIGINT arrived at the approval prompt.
            OSError: the approval prompt cannot read stdin at all.
        """
        print("generated code:")
        print(code)

        return input("run? [y/N] ").strip() == "y"

    def _guarded_url(self, page: PageFacade) -> str | None:
        """Read the current URL; a failed interaction degrades to None.

        Args:
            page: the live page facade of the test.

        Returns:
            The current URL of the page; ``None`` when the read failed —
            its failure text was printed.
        """
        try:
            return page.url
        except Exception as failure:  # a dead page never kills the dialog
            print(f"url unavailable: {failure}")
            return None

    def _await_guidance(self, failure: IncurableStepError, step_text: str, page: PageFacade) -> str | None:
        """Read guidance lines until one is a real guidance message.

        Blank lines re-prompt — no LLM request, no history entry — and the
        local commands serve the context before the prompt reopens; only a
        genuine guidance message returns to the turn loop.

        Args:
            failure: the terminal failure the dialog opens over.
            step_text: the raw sentence of the stuck step — the decline log
                names it.
            page: the live page facade of the test.

        Returns:
            The raw guidance message; ``None`` — quit, EOF, SIGINT or an
            unreadable stdin ended the dialog declined.
        """
        while True:
            message = self._read_guidance(step_text)
            if message is None:
                return None

            command = message.strip()
            if not command:  # blank line — re-prompt, no LLM request, no history
                continue
            if command in _LOCAL_COMMANDS:
                self._serve_local_command(command, failure, page)
                continue

            return message

    def _read_guidance(self, step_text: str) -> str | None:
        """Read one guidance line from the prompt.

        Args:
            step_text: the raw sentence of the stuck step — the decline log
                names it.

        Returns:
            The raw guidance message; ``None`` — quit, EOF, SIGINT or an
            unreadable stdin ended the dialog declined.
        """
        try:
            message = input("guidance> ")
        except (EOFError, KeyboardInterrupt, OSError):  # an unreadable stdin (captured CI) declines like EOF
            logger.info("steering_declined", extra={"step_text": step_text})
            return None

        if message.strip() == "quit":
            logger.info("steering_declined", extra={"step_text": step_text})
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

    def _guided_request(  # noqa: PLR0913, PLR0917 — the fixed request inputs of the port signature
        self,
        step_text: str,
        step_type: str,
        previous_steps: list[str],
        page: PageFacade,
        guidance: str,
        attempt_history: list[StepAttempt],
    ) -> str:
        """Run one guided regeneration request against the provider.

        The fresh page state — the snapshot, the screenshot when the project
        sends them, the current URL read fresh per request — plus the honest
        inputs (the raw step sentence, the step type) and the rendered
        shared attempt history compose the request: record 0 anchors the
        original failure the engineer guidance refers to, every completed
        turn of the dialog rides its record after it, and the message
        itself rides the USER GUIDANCE block.

        Args:
            step_text: the raw sentence of the stuck step — carried
                verbatim.
            step_type: action or assertion — carried into the request.
            previous_steps: the sentences of the previous steps of the test.
            page: the live page facade of the test.
            guidance: the engineer guidance message of this turn.
            attempt_history: the shared per-step attempt history — rendered
                record by record into the HISTORY block of the request.

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
            step_text=step_text,
            step_type=step_type,
            previous_steps=previous_steps,
            snapshot=self._guarded_snapshot(page),
            page_url=self._guarded_url(page),
            screenshot=screenshot,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[record.render() for record in attempt_history],
            recommendation=None,  # the verdict diagnosis is banner-only — the live guidance replaces it
            guidance=guidance,
        )

    def _write_back(self, step_text: str, identity: StepIdentity, code: str) -> CachedStep:
        """Write the proven guided step back to the cache and report it healed.

        Args:
            step_text: the raw sentence of the stuck step — the healed event
                names it.
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
        stored = self._cache.save(step)

        self._reporter.emit("on_healed", {"step_text": step_text, "explanation": _HEALED_EXPLANATION})

        if stored:
            print("step green — healed step written to the cache")
        else:  # the skip reason rides the on_cache_skipped event — the console line never claims a write that failed
            print("step green — cache write skipped (best-effort cache)")

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


def _record(code: str, error: str, outcome: str, url_before: str, url_after: str) -> StepAttempt:
    """Compose one verbatim attempt record — the shape every turn-append site shares.

    The cell-local twin of the engine helper — the record shape is uniform
    across the engine loops and the dialog (resolved design decision 2).

    Args:
        code: the complete candidate code of the turn.
        error: the complete failure text of the turn; empty on no error.
        outcome: the outcome label constant of the turn.
        url_before: the page URL read immediately before the turn's execution.
        url_after: the page URL read immediately after the turn's execution.

    Returns:
        The immutable record appended to the shared per-step attempt history.
    """
    return StepAttempt(code=code, error=error, outcome=outcome, url_before=url_before, url_after=url_after)


def _banner_line(label: str, text: str) -> str:
    """Align one banner label with its value text.

    The label pads to the banner label column — the banner's own
    presentation padding; the render text inside stays unpadded. Multi-line
    values indent every continuation line to the value column.

    Args:
        label: the banner label including its colon.
        text: the value text of the line; its continuation lines indent to
            the value column.

    Returns:
        The aligned banner line with its continuation lines, joined with
        newlines.
    """
    value_column = " " * (_BANNER_LABEL_WIDTH + 1)
    head, *tail = text.splitlines() or [""]  # an empty value renders its label alone
    lines = [f"{label.ljust(_BANNER_LABEL_WIDTH)} {head}", *(value_column + line for line in tail)]

    return "\n".join(line.rstrip() for line in lines)
