"""Cross-cell integration tests: the group replay, the strict isolation and the frozen prompt mirrors."""

import contextlib
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest import mock

import pytest
from prettyplay import PrettyPlay, StepGroup
from prettyplay.cache import CachedStep, StepCache, StepIdentity, normalize_step_text
from prettyplay.config import Config
from prettyplay.engine.generator import CHEAT_SHEET as ENGINE_CHEAT_SHEET
from prettyplay.engine.generator import SYSTEM_PROMPT as ENGINE_SYSTEM_PROMPT
from prettyplay.engine.groups.diagnosis import GROUP_DIAGNOSIS_PROMPT
from prettyplay.engine.steering.steering import CHEAT_SHEET, SYSTEM_PROMPT
from prettyplay.failures import ProductDefectError
from prettyplay.llm import (
    ComplianceFinding,
    FailureClassification,
    GroupFailureClassification,
    LLMProvider,
    ScenarioStep,
)
from prettyplay.llm._request import build_fields_text
from prettyplay.reporting import StepHooks, StepReporter

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_ROOT = REPO_ROOT / ".goga" / "usages" / "prompts"
GENERATION_PRACTICE = PROMPTS_ROOT / "step_generation.md"
CHEAT_SHEET_PRACTICE = PROMPTS_ROOT / "step_cheatsheet.md"
GROUP_DIAGNOSIS_PRACTICE = PROMPTS_ROOT / "group_diagnosis.md"

GROUP_PROMPT = "the checkout flow"
COOKIE_STEP = "accept the cookie banner"
FILL_STEP = "fill the email field"
STATUS_STEP = "the status shows order confirmed"

COOKIE_CODE = "def step(page) -> None:\n    page.get_by_role('button', name='Accept').click()\n"
FILL_CODE = "def step(page) -> None:\n    page.get_by_label('Email').fill('a@b.c')\n"
STATUS_CODE = "def step(page) -> None:\n    page.get_by_text('Order confirmed').expect_visible()\n"
WORKING_CODE = "def step(page) -> None:\n    page.goto('https://shop.example.com/order')\n"


class FakeLocator:
    """Fake locator boundary recording element calls into the log of the owning page."""

    def __init__(self, calls: list[tuple[str, ...]]) -> None:
        self._calls = calls

    def click(self) -> None:
        self._calls.append(("click",))

    def fill(self, value: str) -> None:
        self._calls.append(("fill", value))

    def expect_visible(self) -> None:
        self._calls.append(("expect_visible",))


class FakePage:
    """Fake page facade: the run primitive against itself, the snapshot and a fixed URL.

    A rotted UI is simulated by the ``broken_lookups`` set — the named lookup
    method raises, exactly as a vanished element does on a real page.
    """

    def __init__(self, broken_lookups: frozenset[str] | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.close_count = 0
        self._broken_lookups = broken_lookups or frozenset()

    def close(self) -> None:
        self.close_count += 1

    def get_by_role(self, role: str, name: str) -> FakeLocator:
        return self._lookup("get_by_role", (role, name))

    def get_by_label(self, label: str) -> FakeLocator:
        return self._lookup("get_by_label", (label,))

    def get_by_text(self, text: str) -> FakeLocator:
        return self._lookup("get_by_text", (text,))

    def goto(self, url: str) -> None:
        self.calls.append(("goto", url))

    def run(self, action: Callable[[object], object]) -> object:
        """The run primitive: executes the action against the fake itself, as a hand-built handle does."""
        return action(self)

    def aria_snapshot(self) -> str:
        return "body: main"

    def screenshot(self) -> bytes:
        return b"png"

    @property
    def url(self) -> str:
        return "https://shop.example.com/checkout"

    def _lookup(self, method: str, args: tuple[str, ...]) -> FakeLocator:
        """Record the lookup and fail it when the rotted UI no longer has the element."""
        self.calls.append((method, *args))
        if method in self._broken_lookups:
            raise AssertionError("element not found")
        return FakeLocator(self.calls)


class ForbiddenProvider(LLMProvider):
    """Stub provider failing the run the moment any port operation is called."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_step_code(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str = "",
        step_text: str = "",
        step_type: str = "",
        previous_steps: list[str] | None = None,
        group_prompt: str | None = None,
        snapshot: str = "",
        page_url: str | None = None,
        screenshot: bytes | None = None,
        cheat_sheet: str = "",
        attempt_history: list[str] | None = None,
        recommendation: str | None = None,
        guidance: str | None = None,
    ) -> str:
        self.calls += 1
        raise AssertionError("provider must not be called")

    def classify_step_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        step_text: str,
        code: str,
        error: str,
        snapshot: str,
        screenshot: bytes | None,
    ) -> FailureClassification:
        self.calls += 1
        raise AssertionError("provider must not be called")

    def classify_group_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        group_prompt: str,
        group_steps: list[str],
        step_text: str,
        attempt_history: list[str],
        snapshot: str,
        screenshot: bytes | None,
    ) -> GroupFailureClassification:
        self.calls += 1
        raise AssertionError("provider must not be called")

    def check_instruction_compliance(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        step_text: str,
        step_type: str,
        code: str,
        attempt_history: list[str] | None = None,
    ) -> list[ComplianceFinding]:
        self.calls += 1
        raise AssertionError("provider must not be called")


class RecordingProvider(LLMProvider):
    """Stub provider recording generation requests; the strict classification is scripted."""

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.generation_requests: list[dict[str, object]] = []
        self.calls = 0
        self.classification_step_texts: list[str] = []

    def generate_step_code(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str = "",
        step_text: str = "",
        step_type: str = "",
        previous_steps: list[str] | None = None,
        group_prompt: str | None = None,
        snapshot: str = "",
        page_url: str | None = None,
        screenshot: bytes | None = None,
        cheat_sheet: str = "",
        attempt_history: list[str] | None = None,
        recommendation: str | None = None,
        guidance: str | None = None,
    ) -> str:
        self.generation_requests.append(
            {
                "step_text": step_text,
                "step_type": step_type,
                "previous_steps": list(previous_steps or []),  # copy: the scenario context lives on
                "group_prompt": group_prompt,
            }
        )
        if not self.answers:
            raise AssertionError("stub provider has no generation answers left")
        return self.answers.pop(0)

    def classify_step_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        step_text: str,
        code: str,
        error: str,
        snapshot: str,
        screenshot: bytes | None,
    ) -> FailureClassification:
        self.calls += 1
        self.classification_step_texts.append(step_text)
        return FailureClassification(
            category="product_defect",
            explanation="the confirmation line is genuinely missing",
            recommendation="file a bug",
        )

    def classify_group_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        group_prompt: str,
        group_steps: list[str],
        step_text: str,
        attempt_history: list[str],
        snapshot: str,
        screenshot: bytes | None,
    ) -> GroupFailureClassification:
        raise AssertionError("provider must not diagnose — strict mode never recovers")

    def check_instruction_compliance(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        step_text: str,
        step_type: str,
        code: str,
        attempt_history: list[str] | None = None,
    ) -> list[ComplianceFinding]:
        return []  # compliant by default — the gate passes


class RecorderHook(StepHooks):
    """Hook recording every step-cycle event into a shared ``events`` list for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, str | int]]] = []

    def on_step_started(self, step_text: str, step_type: str) -> None:
        self.events.append(("on_step_started", {"step_text": step_text, "step_type": step_type}))

    def on_step_passed(self, step_text: str, step_type: str) -> None:
        self.events.append(("on_step_passed", {"step_text": step_text, "step_type": step_type}))

    def on_step_failed(self, step_text: str, step_type: str, error: str) -> None:
        self.events.append(("on_step_failed", {"step_text": step_text, "step_type": step_type, "error": error}))

    def on_step_verdict(self, step_text: str, category: str, explanation: str, recommendation: str) -> None:
        self.events.append(
            (
                "on_step_verdict",
                {
                    "step_text": step_text,
                    "category": category,
                    "explanation": explanation,
                    "recommendation": recommendation,
                },
            )
        )

    def on_step_finished(self, step_text: str, step_type: str, outcome: str) -> None:
        self.events.append(("on_step_finished", {"step_text": step_text, "step_type": step_type, "outcome": outcome}))

    def on_generation_started(self, step_text: str, attempt: int) -> None:
        self.events.append(("on_generation_started", {"step_text": step_text, "attempt": attempt}))

    def on_healing_started(self, step_text: str, category: str) -> None:
        self.events.append(("on_healing_started", {"step_text": step_text, "category": category}))

    def on_healed(self, step_text: str, explanation: str) -> None:
        self.events.append(("on_healed", {"step_text": step_text, "explanation": explanation}))

    def on_cache_saved(self, step_text: str, filename: str) -> None:
        self.events.append(("on_cache_saved", {"step_text": step_text, "filename": filename}))

    def on_cache_skipped(self, step_text: str, reason: str) -> None:
        self.events.append(("on_cache_skipped", {"step_text": step_text, "reason": reason}))


@contextlib.contextmanager
def installed_test(
    cache_root: Path,
    provider: LLMProvider,
    page: FakePage,
    cache_key: str,
    config: Config | None = None,
) -> Iterator[PrettyPlay]:
    """Build one PrettyPlay on a tmp cache with stubbed provider and page boundaries.

    The optional ``config`` replaces the default cache-only configuration —
    the strict isolation case builds a strict test through the same wiring.
    """
    effective = config if config is not None else Config(cache_root=str(cache_root))
    with (
        mock.patch("prettyplay.scenario.load_config", return_value=effective),
        mock.patch("prettyplay.runtime.create_provider", return_value=provider),
    ):
        test = PrettyPlay(cache_key)
        with mock.patch.object(test._runtime, "open_page", return_value=page):
            yield test


def seed_step(
    cache_root: Path,
    step_text: str,
    code: str,
    *,
    cache_key: str,
    step_type: str = "action",
) -> StepIdentity:
    """Pre-write a step file so the scenario runs the cache-hit path without the LLM."""
    identity = StepIdentity(
        cache_key=cache_key,
        step_type=step_type,
        normalized_text=normalize_step_text(step_text),
    )
    StepCache(Config(cache_root=str(cache_root)), None, StepReporter(hooks=[])).save(
        CachedStep(identity=identity, code=code, created_at="2026-09-08")
    )
    return identity


def test_group_replay_is_llm_free_and_strict_never_recovers(tmp_path: Path) -> None:
    """SC7: a cached group replays with no LLM call; strict mode keeps its classification-only path."""
    # case A — non-strict: the three cached group steps replay green with zero provider calls
    provider = ForbiddenProvider()
    page = FakePage()
    hook = RecorderHook()
    seed_step(tmp_path, COOKIE_STEP, COOKIE_CODE, cache_key="checkout-flow")
    seed_step(tmp_path, FILL_STEP, FILL_CODE, cache_key="checkout-flow")
    seed_step(tmp_path, STATUS_STEP, STATUS_CODE, cache_key="checkout-flow", step_type="assertion")

    with installed_test(tmp_path, provider, page, "checkout-flow") as test:
        test.add_hooks(hook)
        with test.group(GROUP_PROMPT) as group:
            group.step(COOKIE_STEP)
            group.step(FILL_STEP)
            group.expect(STATUS_STEP)
        test.close()

    assert provider.calls == 0  # group membership changes no cache address and no replay behavior
    assert [trace.sentence for trace in group.traces] == [COOKIE_STEP, FILL_STEP, STATUS_STEP]
    assert [trace.outcome for trace in group.traces] == ["passed", "passed", "passed"]  # one record per step
    assert [event for event, _payload in hook.events].count("on_step_passed") == 3  # steps green
    assert all(
        payload["outcome"] == "passed"
        for event, payload in hook.events
        if event == "on_step_finished"  # every step closed green — nothing was generated or healed
    )
    assert page.calls == [
        ("get_by_role", "button", "Accept"),
        ("click",),
        ("get_by_label", "Email"),
        ("fill", "a@b.c"),
        ("get_by_text", "Order confirmed"),
        ("expect_visible",),
    ]  # the three cached codes executed — the replay is behaviorally today's

    # case B — strict: a failed cached group step classifies only; the recovery never runs
    strict_root = tmp_path / "strict"
    strict_root.mkdir()
    strict_provider = RecordingProvider([])
    strict_page = FakePage(broken_lookups=frozenset({"get_by_text"}))  # the confirmation line rotted
    seed_step(strict_root, COOKIE_STEP, COOKIE_CODE, cache_key="checkout-flow")
    seed_step(strict_root, STATUS_STEP, STATUS_CODE, cache_key="checkout-flow", step_type="assertion")

    with installed_test(
        strict_root,
        strict_provider,
        strict_page,
        "checkout-flow",
        config=Config(strict=True, cache_root=str(strict_root)),
    ) as test:
        entered_group: list[StepGroup] = []

        def run_strict_group() -> None:
            """Run the cached two-step group — the assertion step fails its rotted replay."""
            with test.group(GROUP_PROMPT) as strict_group:
                entered_group.append(strict_group)  # captured on entry — the failing step never returns
                strict_group.step(COOKIE_STEP)
                strict_group.expect(STATUS_STEP)

        recover = mock.Mock(name="recover")
        with (
            mock.patch.object(test._executor._recovery, "recover", recover),
            pytest.raises(
                ProductDefectError  # the strict classification outcome raised by kind
            ),
        ):
            run_strict_group()
        strict_group = entered_group[0]
        test.close()

    assert recover.called is False  # strict never opens a recovery cycle — no diagnosis, no row
    assert strict_provider.calls == 1  # classify_step_failure is the only LLM call of the strict path
    assert strict_provider.classification_step_texts == [STATUS_STEP]
    assert [trace.outcome for trace in strict_group.traces] == ["passed"]  # no failed record — no group routing


def _git(*arguments: str) -> str:
    """Run one git query in the repository and return its stdout."""
    return subprocess.run(["git", *arguments], cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout


def _rename_record(practice: Path) -> tuple[str, str, str]:
    """The (score, old path, commit) of the rename git recorded for the practice file.

    Walks the rename records of the prompts directory and picks the one whose
    new path is the file — the single rename the plan's R100 pin refers to.
    """
    listing = _git("log", "--diff-filter=R", "--name-status", "--format=%H", "--", str(PROMPTS_ROOT))
    commit = ""
    for line in listing.splitlines():
        if not line.startswith(("R", "C")):
            commit = line.strip() if line.strip() else commit
            continue
        status, old_path, new_path = line.split("\t")
        if new_path == str(practice.relative_to(REPO_ROOT)):
            return status, old_path, commit

    raise AssertionError(f"no rename record found for {practice}")


def test_prompt_mirrors_after_rename() -> None:
    """C13: the frozen mirrors never drift from the practice files; the rename changed no byte."""
    generation_practice = GENERATION_PRACTICE.read_text(encoding="utf-8")
    cheat_sheet_practice = CHEAT_SHEET_PRACTICE.read_text(encoding="utf-8")
    diagnosis_practice = GROUP_DIAGNOSIS_PRACTICE.read_text(encoding="utf-8")

    # the mirrors of the three cells — the section after --- for the prompts, the whole file for the sheet
    assert generation_practice.split("---", 1)[1].strip() == ENGINE_SYSTEM_PROMPT  # generator
    assert diagnosis_practice.split("---", 1)[1].strip() == GROUP_DIAGNOSIS_PROMPT  # groups diagnosis
    assert cheat_sheet_practice == ENGINE_CHEAT_SHEET  # the whole cheat sheet, verbatim
    assert SYSTEM_PROMPT == ENGINE_SYSTEM_PROMPT  # steering mirrors the identical constants
    assert CHEAT_SHEET == ENGINE_CHEAT_SHEET

    # the git record: both renames were detected at 100% similarity — no byte changed with the name
    for practice, current in (
        (GENERATION_PRACTICE, generation_practice),
        (CHEAT_SHEET_PRACTICE, cheat_sheet_practice),
    ):
        status, old_path, commit = _rename_record(practice)
        assert status == "R100"  # rename detection saw identical content at the rename commit
        pre_rename = _git("show", f"{commit}~1:{old_path}")
        assert pre_rename == current  # and nothing drifted since — the constants pin the same bytes


def test_typed_scenario_context_flows_end_to_end(
    tmp_path: Path,
    scenario_records: list[ScenarioStep],
) -> None:
    """The typed context end to end: a group entry stays marked outside its group (permanent membership)."""
    provider = RecordingProvider(answers=[WORKING_CODE])
    page = FakePage()
    seed_step(tmp_path, "open the shop page", WORKING_CODE, cache_key="checkout-flow")
    seed_step(tmp_path, COOKIE_STEP, COOKIE_CODE, cache_key="checkout-flow")

    with installed_test(tmp_path, provider, page, "checkout-flow") as test:
        test.step("open the shop page")  # ordinary step — cached replay
        with test.group(GROUP_PROMPT) as group:
            group.step(COOKIE_STEP)  # group step — cached replay inside the block
        test.step("place the order")  # ordinary step — a miss, the generation records the context
        test.close()

    # the third step's request carried the typed records: the ordinary entry plain, the group entry marked
    request = provider.generation_requests[0]
    assert request["step_text"] == "place the order"
    assert request["group_prompt"] is None  # an ordinary step again — no framing of its own
    assert request["previous_steps"] == scenario_records[:2]  # membership is a property of the record
    assert request["previous_steps"][1].group_prompt == GROUP_PROMPT

    # the provider-side render of exactly those records: the marked group entry, no GROUP PROMPT block
    rendered = build_fields_text(
        user_instructions="",
        step_text="place the order",
        step_type="action",
        previous_steps=list(request["previous_steps"]),
        group_prompt=None,
        snapshot="body: main",
        page_url="https://shop.example.com/checkout",
        cheat_sheet=CHEAT_SHEET,
        attempt_history=[],
        recommendation=None,
        guidance=None,
    )
    assert "GROUP PROMPT:" not in rendered  # the current step is ordinary — no framing block
    assert "- open the shop page\n" in rendered  # the ordinary entry plain (C13)
    assert f"- {COOKIE_STEP} [group step — {GROUP_PROMPT}]" in rendered  # marked outside its group
