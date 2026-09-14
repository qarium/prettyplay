"""Tests for the internal page handle (PageFacade.run) and the dialog router of the prettyplay.driver cell."""

import collections.abc
import inspect
import logging
import threading
import typing
from typing import get_type_hints

import prettyplay.driver
import pytest
from playwright.sync_api import Error
from prettyplay.driver import PageFacade
from prettyplay.driver.page import _RESOLVE_PASS_LIMIT, _DialogRouter
from prettyplay.driver.session import PlaywrightWorker


class FakeBodyLocator:
    """Fake ``page.locator("body")``: yields the recorded aria snapshot."""

    def __init__(self, snapshot: str = "- heading Адреса") -> None:
        self._snapshot = snapshot
        self.calls: list[tuple[str, ...]] = []

    def aria_snapshot(self) -> str:
        self.calls.append(("aria_snapshot",))
        return self._snapshot


class FakeRawPage:
    """Fake genuine sync Page handed to run actions; records the plumbing calls."""

    def __init__(self, snapshot: str = "- heading Адреса") -> None:
        self.calls: list[tuple[str, ...]] = []
        self.context = FakeContext()
        self._body = FakeBodyLocator(snapshot)

    def locator(self, selector: str) -> FakeBodyLocator:
        self.calls.append(("locator", selector))
        if selector == "body":
            return self._body
        raise AssertionError(f"the handle locates only the body, got {selector!r}")

    def screenshot(self, full_page: bool = False) -> bytes:
        self.calls.append(("screenshot", full_page))
        return b"png-bytes"


class FakeContext:
    """Fake isolated browser context; records ``close``."""

    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeRawDialog:
    """Fake Playwright dialog behind the router; mirrors the driver's handled-state guard.

    Fields: ``message``; ``state`` in {"open", "accepted", "dismissed"}. The
    resolution methods set the state or raise the driver's already-handled
    error when the dialog is not open — the same text the installed Playwright
    driver raises on a double resolution.
    """

    def __init__(self, message: str = "") -> None:
        self.message = message
        self.state = "open"
        self.accept_calls = 0
        self.dismiss_calls = 0

    def accept(self, prompt_text: str | None = None) -> None:
        if self.state != "open":
            raise Error("Cannot accept dialog which is already handled!")
        self.state = "accepted"
        self.accept_calls += 1

    def dismiss(self) -> None:
        if self.state != "open":
            raise Error("Cannot dismiss dialog which is already handled!")
        self.state = "dismissed"
        self.dismiss_calls += 1


class TargetClosedDialog(FakeRawDialog):
    """Fake dialog whose resolution fails with the target-closed driver error."""

    def accept(self, prompt_text: str | None = None) -> None:
        raise Error("Target closed")

    def dismiss(self) -> None:
        raise Error("Target closed")


class BrokenTransportDialog(FakeRawDialog):
    """Fake dialog whose resolution fails with a non-Playwright exception."""

    def accept(self, prompt_text: str | None = None) -> None:
        raise RuntimeError("transport broke")

    def dismiss(self) -> None:
        raise RuntimeError("transport broke")


class ChainedDialog(FakeRawDialog):
    """Fake dialog whose resolution fires the next dialog of the chain.

    The page opens the next alert the moment the previous one closes, so
    the routing handler records a fresh dialog while the resolver's own
    ``accept`` call is still pumping the event loop.
    """

    def __init__(self, router: _DialogRouter, message: str = "chained?") -> None:
        super().__init__(message)
        self._router = router

    def accept(self, prompt_text: str | None = None) -> None:
        super().accept(prompt_text)
        self._router.record(FakeRawDialog("next?"))  # dispatched mid-resolution


class EndlessChainDialog(FakeRawDialog):
    """Fake dialog whose resolution always fires another of its own kind.

    The dialog-bomb page: an endless ``while (true) alert()`` loop that
    opens the next alert the moment any resolution resumes the page JS —
    the pending list never empties on its own.
    """

    def __init__(self, router: _DialogRouter, message: str = "again?") -> None:
        super().__init__(message)
        self._router = router

    def accept(self, prompt_text: str | None = None) -> None:
        super().accept(prompt_text)
        self._router.record(EndlessChainDialog(self._router))  # the page never stops


class ThreadRecordingDialog(FakeRawDialog):
    """Fake dialog recording the thread its resolution runs on."""

    def __init__(self) -> None:
        super().__init__("which thread?")
        self.resolved_on: int | None = None

    def accept(self, prompt_text: str | None = None) -> None:
        self.resolved_on = threading.get_ident()

    def dismiss(self) -> None:
        self.resolved_on = threading.get_ident()


def make_handle(page: object | None = None, context: object | None = None) -> PageFacade:
    """Build a hand-built PageFacade over fakes; the context defaults to the fake page's own."""
    page = page if page is not None else FakeRawPage()
    return PageFacade(page, context if context is not None else page.context)  # type: ignore[attr-defined]


class TestPageFacadeContract:
    """Contract tests: facade exports, member set, run signature."""

    def test_driver_all_exports_match_contract(self) -> None:
        assert set(prettyplay.driver.__all__) == {
            "DriverSession",
            "PageFacade",
            "is_pollable_failure",
        }

    def test_mirror_facades_no_longer_importable_from_the_facade(self) -> None:
        # the dead names are assembled — no literal survives the series-end leftover sweep
        for name in ("Locator" + "Facade", "Dialog" + "Facade", "Frame" + "Facade"):
            assert not hasattr(prettyplay.driver, name), name  # the mirror family is gone

    def test_page_handle_surface_matches_contract(self) -> None:
        public = {name for name in dir(PageFacade) if not name.startswith("_")}

        assert public == {"run", "aria_snapshot", "screenshot", "close"}  # plumbing, not a surface

    def test_deleted_members_are_gone(self) -> None:
        for name in (
            "url",
            "pages",
            "goto",
            "get_by_role",
            "get_by_label",
            "get_by_text",
            "locator",
            "frame_locator",
            "expect" + "_dialog",  # assembled — no literal for the series-end sweep
            "expect_popup",
            "scroll_to_element",
            "scroll_down",
        ):
            assert not hasattr(PageFacade, name), name  # deleted outright — no mirror residue

    def test_run_signature_matches_contract(self) -> None:
        assert list(inspect.signature(PageFacade.run).parameters) == ["self", "action"]

    def test_run_annotations_match_contract(self) -> None:
        hints = get_type_hints(PageFacade.run)

        assert typing.get_origin(hints["action"]) is collections.abc.Callable  # a Callable hint
        assert isinstance(hints["return"], typing.TypeVar)  # a TypeVar return — the outcome as-is

    def test_kept_member_signatures_match_contract(self) -> None:
        assert list(inspect.signature(PageFacade.aria_snapshot).parameters) == ["self"]
        assert list(inspect.signature(PageFacade.screenshot).parameters) == ["self"]
        assert list(inspect.signature(PageFacade.close).parameters) == ["self"]


class TestPageFacadeLogic:
    """Logic tests: delegation of the kept plumbing members to the wrapped page."""

    def test_aria_snapshot_delegates_to_body_locator(self) -> None:
        page = FakeRawPage(snapshot="- heading Профиль")
        handle = make_handle(page)

        snapshot = handle.aria_snapshot()

        assert page.calls == [("locator", "body")]
        assert page._body.calls == [("aria_snapshot",)]
        assert snapshot == "- heading Профиль"

    def test_screenshot_requests_full_page_and_returns_bytes(self) -> None:
        page = FakeRawPage()
        handle = make_handle(page)

        image = handle.screenshot()

        assert page.calls == [("screenshot", True)]
        assert image == b"png-bytes"

    def test_close_closes_context_not_browser(self) -> None:
        page = FakeRawPage()
        handle = make_handle(page)

        handle.close()

        assert page.context.close_calls == 1
        assert page.calls == []  # no page calls — only context.close()

    def test_kept_members_of_a_live_handle_marshal_to_the_driver_thread(self) -> None:
        worker = PlaywrightWorker()
        worker.start()
        page = FakeRawPage()
        handle = make_handle(page)
        handle._worker = worker
        seen_threads: list[int] = []

        original_snapshot = page._body.aria_snapshot

        def recording_snapshot() -> str:
            seen_threads.append(threading.get_ident())
            return original_snapshot()

        page._body.aria_snapshot = recording_snapshot  # type: ignore[method-assign]
        handle.aria_snapshot()
        handle.screenshot()
        worker.close()

        assert seen_threads  # the snapshot ran — through the worker
        assert all(ident != threading.get_ident() for ident in seen_threads)  # never the calling thread


class TestRunPrimitive:
    """Logic tests: the run/resolver suite — the worker-boundary crossing and the deferred dialog pass."""

    def test_run_executes_the_action_wholly_inside_the_worker_thread(self) -> None:
        worker = PlaywrightWorker()
        worker.start()
        fake_raw_page = FakeRawPage()
        handle = make_handle(fake_raw_page)
        handle._worker = worker
        seen: dict[str, object] = {}

        def action(page: object) -> str:
            seen["thread"] = threading.get_ident()
            seen["page"] = page
            return "done"

        result = handle.run(action)
        pump_ident = handle.run(lambda _page: threading.get_ident())  # a second unit on the same pump
        assert worker._thread is not None
        assert worker._thread.is_alive()  # the worker served both units and keeps running
        worker.close()

        assert result == "done"
        assert seen["thread"] != threading.get_ident()  # never the calling thread
        assert seen["thread"] == pump_ident  # exactly the pump thread of the worker
        assert seen["page"] is fake_raw_page  # the genuine raw page, nothing wrapped

    def test_run_passes_the_genuine_page_and_returns_the_outcome_as_is(self) -> None:
        raw = object()
        handle = make_handle(raw, FakeContext())
        received: list[object] = []

        def action(page: object) -> int:
            received.append(page)
            return 42

        outcome = handle.run(action)

        assert received == [raw]  # the identity of the raw page, captured inside the action
        assert outcome == 42  # the outcome returns as-is

    def test_run_resolves_unclaimed_dialogs_at_the_unit_boundary__accept(self) -> None:
        handle = make_handle(FakeRawPage(), FakeContext())
        router = _DialogRouter(accept_dialogs=True)
        handle._router = router
        dialog = FakeRawDialog("delete?")
        router.record(dialog)  # the routing handler fired before the unit ended

        result = handle.run(lambda _page: "ok")

        assert result == "ok"
        assert dialog.state == "accepted"  # accept_dialogs True → the resolver accepted it
        assert router._pending == []  # the pending list cleared for the next unit

    def test_run_resolves_unclaimed_dialogs_at_the_unit_boundary__dismiss(self) -> None:
        handle = make_handle(FakeRawPage(), FakeContext())
        router = _DialogRouter(accept_dialogs=False)
        handle._router = router
        dialog = FakeRawDialog("leave?")
        router.record(dialog)

        result = handle.run(lambda _page: "ok")

        assert result == "ok"
        assert dialog.state == "dismissed"  # the explicit dismiss restoring the Playwright default
        assert router._pending == []

    def test_run_never_touches_a_dialog_the_step_captured(self) -> None:
        handle = make_handle(FakeRawPage(), FakeContext())
        router = _DialogRouter(accept_dialogs=True)
        handle._router = router
        dialog = FakeRawDialog("delete?")
        router.record(dialog)  # the handler recorded it — an in-step capture also claimed it

        def action(page: object) -> str:
            dialog.accept()  # the step's own stock capture resolves the dialog first
            return "green"

        result = handle.run(action)

        assert result == "green"
        assert dialog.state == "accepted"  # resolved once — by the step, not the router
        assert dialog.accept_calls == 1  # the resolver hit already-handled and skipped silently

    def test_run_resolver_failure_never_masks_the_action_outcome(self, caplog: pytest.LogCaptureFixture) -> None:
        handle = make_handle(FakeRawPage(), FakeContext())
        router = _DialogRouter(accept_dialogs=True)
        handle._router = router
        router.record(TargetClosedDialog("delete?"))  # the page died mid-resolution

        def action(page: object) -> None:
            raise AssertionError("videos not listed")

        with (
            caplog.at_level(logging.WARNING, logger="prettyplay"),
            pytest.raises(AssertionError, match="videos not listed") as raised,
        ):
            handle.run(action)

        assert "videos not listed" in str(raised.value)  # the action's failure reached the caller
        failures = [
            record
            for record in caplog.records
            if record.name == "prettyplay"
            and record.levelno == logging.WARNING
            and record.getMessage() == "dialog resolution failed"
        ]
        assert len(failures) == 1  # exactly one WARNING — the resolver dropped its own failure
        assert failures[0].error == "Target closed"

    def test_run_without_a_router_is_a_plain_pass_through(self) -> None:
        handle = make_handle(FakeRawPage(), FakeContext())
        handle._router = None  # a handle without a session: no handler, nothing pending

        assert handle.run(lambda _page: 7) == 7

    def test_resolver_clears_pending_for_the_next_unit(self) -> None:
        handle = make_handle(FakeRawPage(), FakeContext())
        router = _DialogRouter(accept_dialogs=True)
        handle._router = router
        first = FakeRawDialog("first?")
        router.record(first)

        handle.run(lambda _page: "one")
        assert router._pending == []  # run 1 drained its own dialog

        second = FakeRawDialog("second?")
        router.record(second)
        handle.run(lambda _page: "two")

        assert first.accept_calls == 1  # never double-resolved across units
        assert first.state == "accepted"
        assert second.state == "accepted"  # run 2 resolved only its own dialog
        assert second.accept_calls == 1

    def test_run_resolves_unclaimed_dialogs_wholly_inside_the_worker_thread(self) -> None:
        worker = PlaywrightWorker()
        worker.start()
        handle = make_handle(FakeRawPage())
        handle._worker = worker
        router = _DialogRouter(accept_dialogs=True)
        handle._router = router
        dialog = ThreadRecordingDialog()
        router.record(dialog)

        pump_ident = handle.run(lambda _page: threading.get_ident())  # the pump thread of the worker
        handle.run(lambda _page: "ok")
        worker.close()

        assert dialog.resolved_on is not None  # the tail pass ran
        assert dialog.resolved_on == pump_ident  # resolution belongs to the worker pump thread
        assert dialog.resolved_on != threading.get_ident()  # never the calling thread

    def test_resolver_drains_chained_dialogs_within_one_unit(self) -> None:
        handle = make_handle(FakeRawPage(), FakeContext())
        router = _DialogRouter(accept_dialogs=True)
        handle._router = router
        chained = ChainedDialog(router)
        router.record(chained)

        result = handle.run(lambda _page: "ok")

        assert result == "ok"
        assert chained.state == "accepted"  # the recorded dialog resolved
        assert chained.accept_calls == 1
        assert router._pending == []  # the chain recorded mid-resolution drained in the same pass

    def test_resolver_pass_is_bounded_on_an_endless_dialog_chain(self, caplog: pytest.LogCaptureFixture) -> None:
        handle = make_handle(FakeRawPage(), FakeContext())
        router = _DialogRouter(accept_dialogs=True)
        handle._router = router
        router.record(EndlessChainDialog(router))  # every resolution fires the next dialog

        with caplog.at_level(logging.WARNING, logger="prettyplay"):
            result = handle.run(lambda _page: "ok")

        assert result == "ok"  # the unit terminated — the outcome survives the dialog bomb
        assert len(router._pending) == 1  # only the dialog of the last resolution rolls forward
        capped = [
            record
            for record in caplog.records
            if record.name == "prettyplay"
            and record.levelno == logging.WARNING
            and record.getMessage() == "dialog drain limit reached; the rest resolves at the next unit tail"
        ]
        assert len(capped) == 1  # the bound is loud, never a silent hang
        assert capped[0].limit == _RESOLVE_PASS_LIMIT  # 128 resolutions, then the pass stops
        assert capped[0].pending == 1

        handle.run(lambda _page: "next")  # the next unit makes its own bounded progress
        assert len(router._pending) == 1  # still bounded — no unit ever runs forever

    def test_resolver_pass_is_bounded_inside_one_large_batch(self, caplog: pytest.LogCaptureFixture) -> None:
        handle = make_handle(FakeRawPage(), FakeContext())
        router = _DialogRouter(accept_dialogs=True)
        handle._router = router
        batch = [FakeRawDialog(f"#{number}") for number in range(_RESOLVE_PASS_LIMIT + 40)]
        for dialog in batch:  # one unit tail meets the whole dialog storm pre-queued
            router.record(dialog)

        with caplog.at_level(logging.WARNING, logger="prettyplay"):
            result = handle.run(lambda _page: "ok")

        assert result == "ok"  # the unit terminated inside the bound
        accepted = [dialog for dialog in batch if dialog.state == "accepted"]
        assert len(accepted) == _RESOLVE_PASS_LIMIT  # exactly the limit, never the whole batch
        assert router._pending == batch[_RESOLVE_PASS_LIMIT:]  # the unstarted tail rolls forward untouched
        capped = [
            record
            for record in caplog.records
            if record.name == "prettyplay"
            and record.levelno == logging.WARNING
            and record.getMessage() == "dialog drain limit reached; the rest resolves at the next unit tail"
        ]
        assert len(capped) == 1  # the bound is loud, never a silent overrun
        assert capped[0].pending == 40
        assert capped[0].limit == _RESOLVE_PASS_LIMIT

        handle.run(lambda _page: "next")  # the rolled-forward tail resolves in its own bounded unit
        assert router._pending == []
        assert all(dialog.state == "accepted" for dialog in batch)

    def test_run_never_touches_a_dismissed_dialog_the_step_captured(self) -> None:
        handle = make_handle(FakeRawPage(), FakeContext())
        router = _DialogRouter(accept_dialogs=False)
        handle._router = router
        dialog = FakeRawDialog("leave?")
        router.record(dialog)  # the handler recorded it — an in-step capture also claimed it

        def action(page: object) -> str:
            dialog.dismiss()  # the step's own stock capture dismissed the dialog first
            return "green"

        result = handle.run(action)

        assert result == "green"
        assert dialog.state == "dismissed"  # resolved once — by the step, not the router
        assert dialog.dismiss_calls == 1  # the dismiss-branch already-handled skip held too

    def test_resolver_failure_of_a_non_playwright_kind_never_masks_the_action_outcome(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        handle = make_handle(FakeRawPage(), FakeContext())
        router = _DialogRouter(accept_dialogs=True)
        handle._router = router
        router.record(BrokenTransportDialog("delete?"))  # the transport died under the resolution

        def action(page: object) -> None:
            raise AssertionError("videos not listed")

        with (
            caplog.at_level(logging.WARNING, logger="prettyplay"),
            pytest.raises(AssertionError, match="videos not listed"),
        ):
            handle.run(action)

        failures = [
            record
            for record in caplog.records
            if record.name == "prettyplay"
            and record.levelno == logging.WARNING
            and record.getMessage() == "dialog resolution failed"
        ]
        assert len(failures) == 1  # logged and dropped — never raised past the unit
        assert failures[0].error == "transport broke"

    def test_plumbing_calls_drain_recorded_dialogs_at_their_tail(self) -> None:
        page = FakeRawPage()
        handle = make_handle(page)
        router = _DialogRouter(accept_dialogs=True)
        handle._router = router
        before = FakeRawDialog("recorded before the call?")
        router.record(before)
        mid_call = FakeRawDialog("dispatched while the call pumps the loop?")
        original_snapshot = page._body.aria_snapshot

        def recording_snapshot() -> str:
            router.record(mid_call)  # the event loop dispatches the dialog mid-call
            return original_snapshot()

        page._body.aria_snapshot = recording_snapshot  # type: ignore[method-assign]

        snapshot = handle.aria_snapshot()
        handle.screenshot()
        handle.close()

        assert snapshot == "- heading Адреса"  # the call itself still returned its outcome
        assert before.state == "accepted"  # pending before the call — drained at the tail
        assert mid_call.state == "accepted"  # recorded mid-call — drained by the same tail
        assert router._pending == []  # no dialog survives the plumbing boundary

    def test_plumbing_call_drains_dialogs_on_the_worker_thread(self) -> None:
        worker = PlaywrightWorker()
        worker.start()
        handle = make_handle(FakeRawPage())
        handle._worker = worker
        router = _DialogRouter(accept_dialogs=True)
        handle._router = router
        dialog = ThreadRecordingDialog()
        router.record(dialog)

        pump_ident = handle.run(lambda _page: threading.get_ident())
        handle.aria_snapshot()
        worker.close()

        assert dialog.resolved_on == pump_ident  # the plumbing tail ran on the worker pump thread
