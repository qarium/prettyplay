"""Tests of the structural element registry pipeline: the record model, parsing, rendering, guarded capture."""

import logging

import pytest
from prettyplay.engine.structure import (
    ElementRecord,
    capture_structure_registry,
    parse_element_records,
    render_structure_registry,
)


def make_record(**overrides: str) -> ElementRecord:
    """Build one registry record with the defaults a verified button carries."""
    base = {
        "tag": "button",
        "text": "Sign in",
        "id": "login-submit",
        "testid": "",
        "name": "",
        "aria_label": "",
        "placeholder": "",
        "classes": "",
        "selector": "#login-submit",
        "via": "id",
    }
    return ElementRecord(**{**base, **overrides})


class FakePage:
    """Fake PageFacade: yields the recorded raw collector output or raises the recorded failure."""

    def __init__(self, raw: object = None, failure: Exception | None = None) -> None:
        self._raw = raw if raw is not None else []
        self._failure = failure
        self.calls = 0

    def structure_registry(self) -> object:
        self.calls += 1
        if self._failure is not None:
            raise self._failure
        return self._raw


class TestElementRecord:
    """Contract tests: the record model and its descriptor ladder."""

    def test_descriptor_prefers_the_visible_text(self) -> None:
        assert make_record().descriptor == "Sign in"

    def test_descriptor_falls_through_the_ladder(self) -> None:
        silent = make_record(text="", aria_label="Submit", placeholder="login", name="go")
        assert silent.descriptor == "Submit"

        unlabelled = make_record(text="", aria_label="", placeholder="login", name="go")
        assert unlabelled.descriptor == "login"

        bare = make_record(text="", aria_label="", placeholder="", name="go")
        assert bare.descriptor == "go"

    def test_descriptor_of_a_silent_element_is_empty(self) -> None:
        assert make_record(text="", aria_label="", placeholder="", name="").descriptor == ""


class TestParseElementRecords:
    """Logic tests: the collector output becomes records; malformed entries drop loudly."""

    def test_parses_the_collector_records_in_order(self) -> None:
        raw = [
            {"tag": "input", "id": "search", "selector": "#search", "via": "id"},
            {"tag": "button", "text": "Sign in", "selector": '[data-testid="go"]', "via": "testid"},
        ]

        records = parse_element_records(raw)

        assert [(record.tag, record.selector) for record in records] == [
            ("input", "#search"),
            ("button", '[data-testid="go"]'),
        ]

    def test_non_string_values_and_unknown_keys_are_dropped(self) -> None:
        records = parse_element_records([{"tag": "button", "text": "Go", "rects": 4, "nested": {"a": 1}}])

        assert len(records) == 1
        assert records[0].text == "Go"

    def test_a_non_list_payload_parses_to_nothing_with_a_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="prettyplay"):
            records = parse_element_records({"tag": "button"})

        assert records == []
        assert any(record.getMessage().startswith("structure registry malformed") for record in caplog.records)

    def test_a_non_dict_entry_drops_with_a_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="prettyplay"):
            records = parse_element_records(["button", {"tag": "a", "selector": "#x", "via": "id"}])

        assert len(records) == 1  # the dict survived, the string dropped
        assert any("record malformed" in record.getMessage() for record in caplog.records)


class TestRenderStructureRegistry:
    """Logic tests: the rendered PAGE STRUCTURE block body."""

    def test_renders_one_line_per_record_with_selector_and_rung(self) -> None:
        rendered = render_structure_registry(
            [
                make_record(),
                make_record(tag="input", text="Search", selector='[name="q"]', via="name", id="", testid=""),
            ]
        )

        assert rendered == "\n".join(
            [
                '- button "Sign in" -> #login-submit (id)',
                '- input "Search" -> [name="q"] (name)',
            ]
        )

    def test_a_record_without_a_selector_renders_the_text_only_marker(self) -> None:
        rendered = render_structure_registry([make_record(selector="", via="", text="Read more")])

        assert rendered == '- button "Read more" -> text only'

    def test_the_descriptor_escapes_embedded_quotes(self) -> None:
        rendered = render_structure_registry([make_record(text='Click "go" now')])

        assert rendered == "- button \"Click 'go' now\" -> #login-submit (id)"

    def test_an_empty_registry_renders_an_empty_block_body(self) -> None:
        assert render_structure_registry([]) == ""


class TestCaptureStructureRegistry:
    """Logic tests: the guarded read of the live page facade."""

    def test_captures_parses_and_renders_in_one_call(self) -> None:
        page = FakePage(raw=[{"tag": "button", "text": "Go", "selector": "#go", "via": "id"}])

        rendered = capture_structure_registry(page)

        assert page.calls == 1  # exactly one registry read — the single driver unit
        assert rendered == '- button "Go" -> #go (id)'

    def test_a_failed_read_degrades_to_empty_with_a_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        page = FakePage(failure=RuntimeError("target closed"))

        with caplog.at_level(logging.WARNING, logger="prettyplay"):
            rendered = capture_structure_registry(page)

        assert rendered == ""  # the request carries no PAGE STRUCTURE block — the old behavior
        warnings = [record for record in caplog.records if record.getMessage() == "structure registry unavailable"]
        assert len(warnings) == 1
        assert warnings[0].error == "target closed"

    def test_an_empty_page_renders_an_empty_registry(self) -> None:
        assert capture_structure_registry(FakePage(raw=[])) == ""
