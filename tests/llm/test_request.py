"""Tests for the shared request-field helpers of the prettyplay.llm cell."""

import inspect
import logging
from collections.abc import Callable
from types import SimpleNamespace
from typing import ClassVar, TypeVar

import anthropic
import openai
import pytest
from prettyplay.failures import LLMUnavailableError
from prettyplay.llm import ScenarioStep
from prettyplay.llm._request import (
    CATEGORIES,
    PERMANENT_TRANSPORT_CATEGORIES,
    RETRYABLE_TRANSPORT_CATEGORIES,
    TransportFailureClassification,
    build_classification_fields,
    build_compliance_fields,
    build_fields_text,
    build_group_diagnosis_fields,
    classify_anthropic_failure,
    classify_openai_failure,
    compute_transport_pause,
    extract_code_block,
    parse_classification_line,
    send_with_retries,
    unparsable_classification,
)

FENCED_CODE = "def step(page) -> None:\n    page.goto('https://example.com')\n"
USER_INSTRUCTIONS = "prefer data-test-id"
CHEAT_SHEET = "expect(locator).to_be_visible()"
STEP_CODE = "def step(page) -> None:\n    pass\n"
ATTEMPT_RECORD = "execution failed\nurl: https://a.example -> https://b.example\ncode:\n...\nerror:\nboom"


def make_status_error(error_class: type[Exception], status: int, headers: dict | None = None) -> Exception:
    """Build an SDK status error over a faked response for the classification tests."""
    response = SimpleNamespace(status_code=status, headers=headers or {}, request=SimpleNamespace())

    return error_class("boom", response=response, body=None)


class TestExtractCodeBlock:
    """Logic tests: the markdown-fenced completion becomes executable step code."""

    def test_extract_with_python_language_tag(self) -> None:
        answer = f"```python\n{FENCED_CODE}```"

        assert extract_code_block(answer) == FENCED_CODE

    def test_extract_with_bare_fence(self) -> None:
        answer = f"```\n{FENCED_CODE}```"

        assert extract_code_block(answer) == FENCED_CODE

    def test_extract_first_block_when_prose_surrounds_it(self) -> None:
        answer = f"Вот код шага:\n\n```python\n{FENCED_CODE}```\n\nГотово."

        assert extract_code_block(answer) == FENCED_CODE

    def test_plain_code_passes_through(self) -> None:
        assert extract_code_block(FENCED_CODE) == FENCED_CODE

    def test_unclosed_fence_passes_through_as_is(self) -> None:
        answer = f"```python\n{FENCED_CODE}"

        assert extract_code_block(answer) == answer


class TestBuildFieldsTextContract:
    """Contract tests: the builder carries the fixed port parameter list."""

    def test_build_fields_text_accepts_the_port_parameter_list(self) -> None:
        parameters = inspect.signature(build_fields_text).parameters

        assert list(parameters) == [
            "user_instructions",
            "step_text",
            "step_type",
            "previous_steps",
            "group_prompt",
            "snapshot",
            "page_url",
            "cheat_sheet",
            "attempt_history",
            "recommendation",
            "guidance",
        ]
        assert parameters["step_type"].annotation is str
        assert parameters["previous_steps"].annotation == list[ScenarioStep]
        assert parameters["group_prompt"].annotation == str | None
        assert parameters["attempt_history"].annotation == list[str]

    def test_build_fields_text_drops_the_removed_regeneration_inputs(self) -> None:
        names = list(inspect.signature(build_fields_text).parameters)

        assert "existing_code" not in names  # the removed inputs are gone, not merely optional
        assert "error" not in names
        assert "guidance_history" not in names


class TestBuildFieldsTextStepTypeLine:
    """Logic tests: the STEP TYPE line directly above the STEP line."""

    def test_build_fields_text_renders_step_type_line_directly_above_step(self) -> None:
        text = build_fields_text(
            user_instructions="Prefer id attributes",
            step_text="open the page",
            step_type="assertion",
            previous_steps=[],
            group_prompt=None,
            snapshot="- snap",
            page_url=None,
            cheat_sheet="# sheet",
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert text.startswith("STEP TYPE: assertion\nSTEP:\nopen the page")  # no blank line between
        assert "PAGE URL" not in text  # None URL — no line
        assert "HISTORY" not in text  # empty history — no block
        assert "RECOMMENDATION" not in text
        assert "USER GUIDANCE" not in text


class TestBuildFieldsTextUserInstructions:
    """Logic tests: the USER INSTRUCTIONS block placement and omission."""

    def test_build_fields_text_places_user_instructions_after_cheat_sheet(self) -> None:
        text = build_fields_text(
            USER_INSTRUCTIONS,
            "нажать Войти",
            "action",
            [ScenarioStep(sentence="открыть страницу")],
            group_prompt=None,
            snapshot="- button 'Войти'",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert text.index("CHEAT SHEET:") < text.index("USER INSTRUCTIONS:")
        assert f"USER INSTRUCTIONS:\n{USER_INSTRUCTIONS}" in text

    def test_build_fields_text_omits_block_when_instructions_empty(self) -> None:
        text = build_fields_text(
            "",
            "нажать Войти",
            "action",
            [],
            group_prompt=None,
            snapshot="- button 'Войти'",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert "USER INSTRUCTIONS" not in text
        assert text.endswith(CHEAT_SHEET)  # the cheat sheet stays the closing block

    def test_build_fields_places_cheat_sheet_after_scenario_inputs_before_instructions(self) -> None:
        text = build_fields_text(
            "prefer role locators",
            "open the videos page",
            "action",
            [ScenarioStep(sentence="open the home page")],
            group_prompt=None,
            snapshot="- tree",
            page_url=None,
            cheat_sheet="…reference…",
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert (
            text.index("STEP TYPE: action\nSTEP:\n")
            < text.index("PREVIOUS STEPS:\n")
            < text.index("PAGE SNAPSHOT:\n")
            < text.index("CHEAT SHEET:\n…reference…")
            < text.index("USER INSTRUCTIONS:\nprefer role locators")
        )
        assert text.startswith("STEP TYPE: action\nSTEP:")
        assert ("PAGE" + " API") not in text  # the dead block header, assembled — no literal for the sweep


class TestBuildClassificationFieldsUserInstructions:
    """Logic tests: the USER INSTRUCTIONS block placement in classification fields."""

    def test_build_classification_fields_places_user_instructions_last(self) -> None:
        text = build_classification_fields(
            USER_INSTRUCTIONS,
            "нажать Войти",
            STEP_CODE,
            "AssertionError: boom",
            "- button 'Войти'",
        )

        assert text.endswith(f"USER INSTRUCTIONS:\n{USER_INSTRUCTIONS}")
        assert text.index("PAGE SNAPSHOT:") < text.index("USER INSTRUCTIONS:")

    def test_build_classification_fields_omits_block_when_instructions_empty(self) -> None:
        text = build_classification_fields("", "нажать Войти", STEP_CODE, "AssertionError: boom", "- button 'Войти'")

        assert "USER INSTRUCTIONS" not in text
        assert text.endswith("- button 'Войти'")  # the snapshot section stays the closing section


class TestBuildComplianceFieldsContract:
    """Contract tests: the compliance builder carries the fixed port parameter list."""

    def test_build_compliance_fields_accepts_the_port_parameter_list(self) -> None:
        parameters = inspect.signature(build_compliance_fields).parameters

        assert list(parameters) == ["user_instructions", "step_text", "step_type", "attempt_history", "code"]
        assert parameters["step_type"].annotation is str
        assert parameters["attempt_history"].annotation == list[str]


class TestBuildComplianceFields:
    """Logic tests: the four fixed blocks with the STEP TYPE line and the attempt history."""

    def test_build_compliance_fields_renders_four_blocks_with_step_type_line(self) -> None:
        text = build_compliance_fields(
            "Prefer id attributes",
            "the «Welcome back» message appears",
            "assertion",
            [ATTEMPT_RECORD],
            STEP_CODE,
        )

        assert (
            text.index("INSTRUCTIONS:")
            < text.index("STEP TYPE:")
            < text.index("STEP:")
            < text.index("ATTEMPT HISTORY:")
            < text.index("CODE:")
        )
        assert text.startswith("INSTRUCTIONS:")
        assert "STEP TYPE: assertion\nSTEP:" in text  # the STEP TYPE line rides inside the STEP block
        assert f"ATTEMPT HISTORY:\n{ATTEMPT_RECORD}" in text

    def test_build_compliance_fields_omits_attempt_history_block_when_empty(self) -> None:
        text = build_compliance_fields(
            "Prefer id attributes",
            "open the page",
            "action",
            [],
            STEP_CODE,
        )

        assert "ATTEMPT HISTORY" not in text
        assert text == (
            "INSTRUCTIONS:\nPrefer id attributes\n\nSTEP TYPE: action\nSTEP:\nopen the page\n\nCODE:\n" + STEP_CODE
        )

    def test_build_compliance_fields_renders_the_fixed_order_without_history(self) -> None:
        text = build_compliance_fields("i", "s", "action", [], "c")

        assert text == "INSTRUCTIONS:\ni\n\nSTEP TYPE: action\nSTEP:\ns\n\nCODE:\nc"  # one optional block


class TestBuildFieldsTextRegenerationInputs:
    """Logic tests: the HISTORY / RECOMMENDATION / USER GUIDANCE blocks."""

    def test_build_fields_renders_new_blocks_in_fixed_order(self) -> None:
        text = build_fields_text(
            "style",
            "нажать Войти",
            "action",
            [ScenarioStep(sentence="открыть страницу")],
            group_prompt=None,
            snapshot="- button 'Войти'",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=["h1", "h2"],
            recommendation="rec",
            guidance="do this",
        )

        assert (
            text.index("CHEAT SHEET:")
            < text.index("USER INSTRUCTIONS:")
            < text.index("HISTORY:")
            < text.index("RECOMMENDATION:")
            < text.index("USER GUIDANCE:")
        )
        assert "HISTORY:\nh1\nh2" in text  # entries joined with newlines

    def test_build_fields_omits_the_new_blocks_when_inputs_empty(self) -> None:
        text = build_fields_text(
            "",
            "нажать Войти",
            "action",
            [],
            group_prompt=None,
            snapshot="- button 'Войти'",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert "HISTORY" not in text
        assert "RECOMMENDATION" not in text
        assert "USER GUIDANCE" not in text
        assert text.endswith(CHEAT_SHEET)  # the cheat sheet stays the closing block


class TestBuildFieldsTextPageUrl:
    """Logic tests: the PAGE URL line in the scenario part, after the snapshot section."""

    def test_build_fields_places_page_url_line_after_snapshot(self) -> None:
        text = build_fields_text(
            user_instructions="",
            step_text="s",
            step_type="action",
            previous_steps=[],
            group_prompt=None,
            snapshot="- body",
            page_url="https://x.test/a",
            cheat_sheet="CS",
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert (
            text.index("STEP:\n")
            < text.index("PREVIOUS STEPS:\n")
            < text.index("PAGE SNAPSHOT:\n- body")
            < text.index("PAGE URL: https://x.test/a")
            < text.index("CHEAT SHEET:\nCS")
        )  # the URL is its own paragraph between the snapshot and the cheat sheet

    @pytest.mark.parametrize("page_url", [None, ""])
    def test_build_fields_omits_the_page_url_line_without_a_url(self, page_url: str | None) -> None:
        text = build_fields_text(
            user_instructions="",
            step_text="s",
            step_type="action",
            previous_steps=[],
            group_prompt=None,
            snapshot="- body",
            page_url=page_url,
            cheat_sheet="CS",
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert "PAGE URL" not in text


class TestBuildFieldsTextHistoryRecords:
    """Logic tests: the HISTORY block renders full multi-line attempt records verbatim."""

    def test_build_fields_text_renders_history_between_instructions_and_recommendation(self) -> None:
        text = build_fields_text(
            user_instructions="Prefer id",
            step_text="open the page",
            step_type="action",
            previous_steps=[],
            group_prompt=None,
            snapshot="- snap",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[ATTEMPT_RECORD],
            recommendation="use role locators",
            guidance="focus on the button",
        )

        assert (
            text.index("USER INSTRUCTIONS:")
            < text.index("HISTORY:")
            < text.index("RECOMMENDATION:")
            < text.index("USER GUIDANCE:")
        )
        assert "HISTORY:\nexecution failed\nurl: https://a.example -> https://b.example" in text

    def test_history_block_renders_full_multi_line_records(self) -> None:
        record1 = (
            "execution failed\n"
            "url: https://a.example -> https://b.example\n"
            'code:\ndef step(page) -> None:\n    page.get_by_role("button").hover()\n'
            "error:\nTimeoutError: click timed out"
        )
        record2 = (
            "rejected by the engineer, not executed\n"
            "url: https://s.example -> https://s.example\n"
            'code:\ndef step(page) -> None:\n    page.get_by_role("button").click()\n'
        )

        text = build_fields_text(
            "",
            "s",
            "action",
            [],
            group_prompt=None,
            snapshot="- body",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[record1, record2],
            recommendation=None,
            guidance=None,
        )

        assert text.endswith("HISTORY:\n" + record1 + "\n" + record2)  # both records verbatim, order preserved
        for line in (*record1.splitlines(), *record2.splitlines()):
            assert line in text  # every code and error line survives — no collapsing, no truncation


class TestTypedScenarioRecords:
    """Logic tests: the typed scenario records render marked and plain."""

    MIXED_RECORDS: ClassVar[list[ScenarioStep]] = [
        ScenarioStep(sentence="open the login page"),
        ScenarioStep(sentence="fill the email field", group_prompt="the order form group"),
    ]
    MARKED_RENDER = "PREVIOUS STEPS:\n- open the login page\n- fill the email field [group step — the order form group]"

    def test_typed_scenario_records_render_marked_and_plain(self) -> None:
        plain = build_fields_text(
            user_instructions="",
            step_text="submit the form",
            step_type="action",
            previous_steps=self.MIXED_RECORDS,
            group_prompt=None,
            snapshot="- snap",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        # the membership is a property of the record — rendered even without a current group framing
        assert self.MARKED_RENDER in plain
        assert "GROUP PROMPT" not in plain  # no framing without a group prompt

        framed = build_fields_text(
            user_instructions="",
            step_text="submit the form",
            step_type="action",
            previous_steps=self.MIXED_RECORDS,
            group_prompt="the order form group",
            snapshot="- snap",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        # the GROUP PROMPT block renders immediately before PREVIOUS STEPS — the section right above it
        assert "GROUP PROMPT:\nthe order form group\n\nPREVIOUS STEPS:" in framed
        assert framed.index("STEP:\nsubmit the form") < framed.index("GROUP PROMPT:")
        assert framed.index("GROUP PROMPT:") < framed.index("PREVIOUS STEPS:")
        assert framed.index("PREVIOUS STEPS:") < framed.index("PAGE SNAPSHOT:")
        # the same marked entries — the framing adds the block, never rewrites the records
        assert self.MARKED_RENDER in framed
        assert "[group step — the order form group]" in framed  # the group prompt verbatim inside the mark

    def test_ordinary_records_render_byte_identical_to_the_pre_change_render(self) -> None:
        legacy = (
            "STEP TYPE: action\nSTEP:\nsubmit the form\n\n"
            "PREVIOUS STEPS:\n- open the login page\n- fill the email field\n\n"
            f"PAGE SNAPSHOT:\n- snap\n\nCHEAT SHEET:\n{CHEAT_SHEET}"
        )  # the pinned pre-change render of ordinary records — the C13 regression pin

        text = build_fields_text(
            user_instructions="",
            step_text="submit the form",
            step_type="action",
            previous_steps=[
                ScenarioStep(sentence="open the login page"),
                ScenarioStep(sentence="fill the email field"),
            ],
            group_prompt=None,
            snapshot="- snap",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert text == legacy

    def test_empty_scenario_history_stays_explicit(self) -> None:
        text = build_fields_text(
            user_instructions="",
            step_text="s",
            step_type="action",
            previous_steps=[],
            group_prompt=None,
            snapshot="- snap",
            page_url=None,
            cheat_sheet=CHEAT_SHEET,
            attempt_history=[],
            recommendation=None,
            guidance=None,
        )

        assert "PREVIOUS STEPS:\n(none)" in text


class TestBuildGroupDiagnosisFieldsContract:
    """Contract tests: the diagnosis builder carries the fixed port parameter list."""

    def test_build_group_diagnosis_fields_accepts_the_port_parameter_list(self) -> None:
        parameters = inspect.signature(build_group_diagnosis_fields).parameters

        assert list(parameters) == [
            "user_instructions",
            "group_prompt",
            "group_steps",
            "step_text",
            "attempt_history",
            "snapshot",
        ]
        assert parameters["group_prompt"].annotation is str
        assert parameters["group_steps"].annotation == list[str]
        assert parameters["attempt_history"].annotation == list[str]


class TestBuildGroupDiagnosisFields:
    """Logic tests: the diagnosis request sections in the fixed order."""

    GROUP_STEPS: ClassVar[list[str]] = [
        "accept the cookie banner\noutcome: passed\nurl: https://a.example -> https://a.example",
        "the status shows order confirmed\noutcome: failed\nurl: https://a.example -> https://b.example",
    ]

    def test_renders_the_fixed_order_with_instructions_last(self) -> None:
        text = build_group_diagnosis_fields(
            "answer strictly",
            "the checkout flow",
            self.GROUP_STEPS,
            "the status shows order confirmed",
            [ATTEMPT_RECORD],
            "- heading «Order»",
        )

        assert (
            text.index("GROUP PROMPT:\nthe checkout flow")
            < text.index("GROUP STEPS:\n")
            < text.index("STEP:\nthe status shows order confirmed")
            < text.index("HISTORY:\n")
            < text.index("PAGE SNAPSHOT:\n- heading «Order»")
            < text.index("USER INSTRUCTIONS:\nanswer strictly")
        )
        assert text.endswith("USER INSTRUCTIONS:\nanswer strictly")  # the block is appended last
        # every trace record verbatim — no collapsing, no truncation
        assert self.GROUP_STEPS[0] in text
        assert self.GROUP_STEPS[1] in text
        assert f"HISTORY:\n{ATTEMPT_RECORD}" in text

    def test_omits_instructions_and_history_blocks_when_empty(self) -> None:
        text = build_group_diagnosis_fields("", "the checkout flow", ["trace record"], "s", [], "- snap")

        assert "USER INSTRUCTIONS" not in text
        assert "HISTORY" not in text
        assert text.endswith("PAGE SNAPSHOT:\n- snap")  # the snapshot section stays the closing section
        assert "GROUP STEPS:\ntrace record" in text

    def test_empty_trace_list_stays_explicit(self) -> None:
        text = build_group_diagnosis_fields("", "g", [], "s", [], "- snap")

        assert "GROUP STEPS:\n(none)" in text


class TestParseClassificationFixableLabel:
    """Logic tests: the fixable label parses; unrecognized labels stay unparsable."""

    def test_parse_classification_accepts_fixable_label(self) -> None:
        parsed = parse_classification_line("fixable | ambiguous locator | use role locator")

        assert parsed == ("fixable", "ambiguous locator", "use role locator")
        assert "fixable" in CATEGORIES

    def test_unrecognized_label_still_falls_back_to_incurable(self) -> None:
        assert parse_classification_line("mystery | why | do something") is None
        assert unparsable_classification()["category"] == "incurable"


class TestTransportFailureClassificationContract:
    """Contract tests: the verdict model shape — two keyword fields, one computed property."""

    def test_constructible_with_keyword_category_and_retry_after(self) -> None:
        failure = TransportFailureClassification(category="rate_limit", retry_after=7.5)

        assert failure.category == "rate_limit"
        assert failure.retry_after == 7.5

    def test_both_fields_carry_empty_defaults(self) -> None:
        failure = TransportFailureClassification()

        assert failure.category == ""
        assert failure.retry_after is None

    def test_retryable_is_a_property_not_a_constructor_field(self) -> None:
        assert isinstance(TransportFailureClassification.retryable, property)
        assert "retryable" not in TransportFailureClassification.model_fields
        assert "retryable" not in inspect.signature(TransportFailureClassification).parameters

    def test_module_exposes_the_transport_label_constants(self) -> None:
        assert frozenset({"connection", "timeout", "rate_limit", "server_error"}) == RETRYABLE_TRANSPORT_CATEGORIES
        assert (
            frozenset({"authentication", "permission_denied", "invalid_request", "not_found", "quota_exhausted"})
            == PERMANENT_TRANSPORT_CATEGORIES
        )
        assert not RETRYABLE_TRANSPORT_CATEGORIES & PERMANENT_TRANSPORT_CATEGORIES  # the families are disjoint


class TestTransportFailureClassification:
    """Logic tests: the retryable truth table of the closed nine-label set."""

    @pytest.mark.parametrize(
        ("category", "expected"),
        [
            pytest.param("connection", True, id="connection"),
            pytest.param("timeout", True, id="timeout"),
            pytest.param("rate_limit", True, id="rate_limit"),
            pytest.param("server_error", True, id="server_error"),
            pytest.param("authentication", False, id="authentication"),
            pytest.param("permission_denied", False, id="permission_denied"),
            pytest.param("invalid_request", False, id="invalid_request"),
            pytest.param("not_found", False, id="not_found"),
            pytest.param("quota_exhausted", False, id="quota_exhausted"),
        ],
    )
    def test_transport_failure_classification_model_shape_and_retryable_truth_table(
        self, category: str, expected: bool
    ) -> None:
        failure = TransportFailureClassification(category=category)

        assert failure.retryable is expected

    def test_empty_default_category_is_not_retryable(self) -> None:
        failure = TransportFailureClassification()

        assert failure.category == ""
        assert failure.retryable is False  # the empty default sits outside the retryable family

    def test_positional_construction_fails_before_field_validation(self) -> None:
        with pytest.raises(TypeError):
            TransportFailureClassification("connection")


CLASSIFIERS: list[pytest.param] = [
    pytest.param(classify_openai_failure, id="openai"),
    pytest.param(classify_anthropic_failure, id="anthropic"),
]


class TestClassifiersContract:
    """Contract tests: one exception in, one verdict out — the classifiers never raise."""

    @pytest.mark.parametrize("classifier", CLASSIFIERS)
    def test_classifier_signature_is_error_to_verdict(
        self, classifier: Callable[[Exception], TransportFailureClassification]
    ) -> None:
        parameters = inspect.signature(classifier).parameters

        assert list(parameters) == ["error"]
        assert parameters["error"].annotation is Exception
        assert classifier.__annotations__["return"] is TransportFailureClassification

    @pytest.mark.parametrize("classifier", CLASSIFIERS)
    def test_classifier_returns_a_verdict_for_an_arbitrary_exception(
        self, classifier: Callable[[Exception], TransportFailureClassification]
    ) -> None:
        failure = classifier(ValueError("boom"))

        assert isinstance(failure, TransportFailureClassification)


class TestClassifyFailures:
    """Logic tests: the transport classification ladders of both providers."""

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            pytest.param(openai.APIConnectionError(request=SimpleNamespace()), "connection", id="connection"),
            pytest.param(openai.APITimeoutError(request=SimpleNamespace()), "timeout", id="sdk-timeout"),
            pytest.param(make_status_error(openai.RateLimitError, 429), "rate_limit", id="rate-limit"),
            pytest.param(make_status_error(openai.APIStatusError, 408), "timeout", id="http-408-timeout"),
            pytest.param(
                make_status_error(openai.InternalServerError, 500), "server_error", id="http-500-server-error"
            ),
            pytest.param(make_status_error(openai.APIStatusError, 599), "server_error", id="http-599-server-error"),
        ],
    )
    def test_classify_openai_failure_maps_the_retryable_family(self, error: Exception, expected: str) -> None:
        failure = classify_openai_failure(error)

        assert failure.category == expected
        assert failure.retryable is True
        assert failure.retry_after is None

    @pytest.mark.parametrize(
        ("classifier", "sdk"),
        [
            pytest.param(classify_openai_failure, openai, id="openai"),
            pytest.param(classify_anthropic_failure, anthropic, id="anthropic"),
        ],
    )
    @pytest.mark.parametrize(
        ("error_class", "status", "expected"),
        [
            pytest.param("AuthenticationError", 401, "authentication", id="authentication"),
            pytest.param("PermissionDeniedError", 403, "permission_denied", id="permission-denied"),
            pytest.param("BadRequestError", 400, "invalid_request", id="invalid-request"),
            pytest.param("NotFoundError", 404, "not_found", id="not-found"),
        ],
    )
    def test_classify_failures_map_the_permanent_family(
        self,
        classifier: Callable[[Exception], TransportFailureClassification],
        sdk: object,
        error_class: str,
        status: int,
        expected: str,
    ) -> None:
        failure = classifier(make_status_error(getattr(sdk, error_class), status))

        assert failure.category == expected
        assert failure.retryable is False

    def test_classify_openai_failure_quota_beats_retryable_status(self) -> None:
        error = make_status_error(openai.RateLimitError, 429)
        error.code = "insufficient_quota"  # the body evidence the SDK parses onto the exception

        failure = classify_openai_failure(error)

        assert failure.category == "quota_exhausted"
        assert failure.retryable is False

    @pytest.mark.parametrize(
        ("classifier", "sdk"),
        [
            pytest.param(classify_openai_failure, openai, id="openai"),
            pytest.param(classify_anthropic_failure, anthropic, id="anthropic"),
        ],
    )
    def test_generic_http_429_is_retryable(
        self, classifier: Callable[[Exception], TransportFailureClassification], sdk: object
    ) -> None:
        failure = classifier(make_status_error(sdk.APIStatusError, 429))

        assert failure.category == "rate_limit"
        assert failure.retryable is True

    def test_classify_anthropic_failure_billing_error_is_permanent_quota(self) -> None:
        error = make_status_error(anthropic.RateLimitError, 429)
        error.type = "billing_error"  # the explicit anthropic quota signal, under a retryable status

        failure = classify_anthropic_failure(error)

        assert failure.category == "quota_exhausted"
        assert failure.retryable is False

    @pytest.mark.parametrize(
        ("classifier", "rate_limit_class"),
        [
            pytest.param(classify_openai_failure, openai.RateLimitError, id="openai"),
            pytest.param(classify_anthropic_failure, anthropic.RateLimitError, id="anthropic"),
        ],
    )
    @pytest.mark.parametrize(
        ("header_value", "expected"),
        [
            pytest.param("7", 7.0, id="integer-seconds"),
            pytest.param("2.5", 2.5, id="decimal-seconds"),
            pytest.param("0", 0.0, id="zero-seconds"),
            pytest.param("-3", -3.0, id="negative-seconds"),
            pytest.param("Wed, 21 Oct 2015 07:28:00 GMT", None, id="http-date"),
            pytest.param(None, None, id="missing-header"),
        ],
    )
    def test_classify_failures_parse_retry_after_seconds(
        self,
        classifier: Callable[[Exception], TransportFailureClassification],
        rate_limit_class: type[Exception],
        header_value: str | None,
        expected: float | None,
    ) -> None:
        headers = {} if header_value is None else {"retry-after": header_value}

        failure = classifier(make_status_error(rate_limit_class, 429, headers))

        assert failure.retry_after == expected
        assert failure.category == "rate_limit"
        assert failure.retryable is True

    @pytest.mark.parametrize("classifier", CLASSIFIERS)
    @pytest.mark.parametrize(
        "error_factory",
        [
            pytest.param(lambda: ValueError("boom"), id="plain-value-error"),
            pytest.param(lambda: make_status_error(openai.ConflictError, 409), id="openai-conflict-409"),
        ],
    )
    def test_classify_failures_unrecognized_exception_is_permanent_invalid_request(
        self,
        classifier: Callable[[Exception], TransportFailureClassification],
        error_factory: Callable[[], Exception],
    ) -> None:
        failure = classifier(error_factory())

        assert failure.category == "invalid_request"
        assert failure.retryable is False


class TestComputeTransportPauseContract:
    """Contract tests: the delay-policy signature — two scalars in, one float out."""

    def test_signature_is_failed_attempt_and_retry_after_to_float(self) -> None:
        parameters = inspect.signature(compute_transport_pause).parameters

        assert list(parameters) == ["failed_attempt", "retry_after"]
        assert parameters["failed_attempt"].annotation is int
        assert parameters["retry_after"].annotation == float | None
        assert compute_transport_pause.__annotations__["return"] is float

    def test_returns_a_float_for_the_first_failed_attempt(self) -> None:
        assert isinstance(compute_transport_pause(1, None), float)


class TestComputeTransportPause:
    """Logic tests: the base sequence, the jitter bounds and the Retry-After lift."""

    def test_compute_transport_pause_base_sequence_jitter_and_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("random.uniform", lambda _a, _b: 0.0)

        assert [compute_transport_pause(n, None) for n in range(1, 8)] == [1.0, 2.0, 4.0, 8.0, 10.0, 10.0, 10.0]

    def test_compute_transport_pause_remains_capped_for_large_attempt_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("random.uniform", lambda _a, _b: 0.0)

        assert compute_transport_pause(1026, None) == 10.0

    def test_compute_transport_pause_jitter_bounds_and_final_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("random.uniform", lambda _a, b: b)

        assert compute_transport_pause(1, None) == 1.25  # base plus the full quarter jitter
        assert compute_transport_pause(5, None) == 10.0  # the cap dominates the jittered 12.5

    def test_compute_transport_pause_retry_after_lifts_within_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("random.uniform", lambda _a, _b: 0.0)

        lifts = [
            compute_transport_pause(1, 5.0),
            compute_transport_pause(3, 2.0),
            compute_transport_pause(1, 0.0),
            compute_transport_pause(1, None),
        ]

        assert lifts == [5.0, 4.0, 1.0, 1.0]  # zero Retry-After is ignored, a smaller one never shortens


class TestSendWithRetriesContract:
    """Contract tests: the retry-loop signature — five parameters, generic pass-through."""

    def test_signature_is_provider_operation_attempts_classify_send(self) -> None:
        parameters = inspect.signature(send_with_retries).parameters
        returned = send_with_retries.__annotations__["return"]

        assert list(parameters) == ["provider", "operation", "attempts", "classify", "send"]
        assert parameters["provider"].annotation is str
        assert parameters["operation"].annotation is str
        assert parameters["attempts"].annotation is int
        assert parameters["classify"].annotation == Callable[[Exception], TransportFailureClassification]
        assert parameters["send"].annotation == Callable[[], returned]
        assert isinstance(returned, TypeVar)  # generic — the response type of send passes through

    def test_generic_passthrough_returns_the_send_response(self) -> None:
        def never_classify(error: Exception) -> TransportFailureClassification:
            pytest.fail("a successful send is never classified")

        assert send_with_retries("openai", "generation", 3, never_classify, lambda: "ok") == "ok"


class TestSendWithRetries:
    """Logic tests (positive): the pass-through and the retry-then-succeed cycle."""

    def test_send_with_retries_success_returns_response_without_side_effects(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        sent: list[int] = []
        sleeps: list[float] = []

        def send() -> str:
            sent.append(1)
            return "ok"

        def never_classify(error: Exception) -> TransportFailureClassification:
            pytest.fail("must not classify")

        monkeypatch.setattr("time.sleep", sleeps.append)

        result = send_with_retries("openai", "generation", 3, never_classify, send)

        assert result == "ok"
        assert sent == [1]
        assert sleeps == []
        assert caplog.records == []

    def test_send_with_retries_retries_then_succeeds_with_two_warnings(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        response = object()
        outcomes: list[object] = [
            anthropic.APIConnectionError(request=SimpleNamespace()),
            anthropic.APIConnectionError(request=SimpleNamespace()),
            response,
        ]
        calls: list[int] = []
        sleeps: list[float] = []

        def send() -> object:
            calls.append(1)
            outcome = outcomes.pop(0)

            if isinstance(outcome, Exception):
                raise outcome

            return outcome

        monkeypatch.setattr("time.sleep", sleeps.append)
        monkeypatch.setattr("random.uniform", lambda _a, _b: 0.0)
        caplog.set_level(logging.WARNING, logger="prettyplay")

        result = send_with_retries("anthropic", "group diagnosis", 3, classify_anthropic_failure, send)

        assert result is response
        assert len(calls) == 3
        assert sleeps == [1.0, 2.0]
        assert len(caplog.records) == 2
        first, second = caplog.records
        assert first.name == "prettyplay"
        assert first.levelname == "WARNING"
        assert first.provider == "anthropic"
        assert first.operation == "group diagnosis"
        assert first.attempt == 1
        assert first.category == "connection"
        assert first.delay == 1.0
        assert second.attempt == 2
        assert second.delay == 2.0


class TestSendWithRetriesTerminal:
    """Logic tests (negative): the three terminal branches and the wait interrupt."""

    def test_send_with_retries_permanent_failure_terminates_immediately(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        error = make_status_error(openai.AuthenticationError, 401)
        calls: list[int] = []
        sleeps: list[float] = []

        def send() -> object:
            calls.append(1)
            raise error

        monkeypatch.setattr("time.sleep", sleeps.append)

        with pytest.raises(LLMUnavailableError) as excinfo:
            send_with_retries("openai", "generation", 3, classify_openai_failure, send)

        assert "openai" in str(excinfo.value)
        assert "authentication" in str(excinfo.value)
        assert excinfo.value.__cause__ is error
        assert len(calls) == 1
        assert sleeps == []
        assert caplog.records == []

    def test_send_with_retries_over_cap_retry_after_terminates_before_any_pause(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        error = make_status_error(openai.RateLimitError, 429, {"retry-after": "30"})
        calls: list[int] = []
        sleeps: list[float] = []

        def send() -> object:
            calls.append(1)
            raise error

        monkeypatch.setattr("time.sleep", sleeps.append)

        with pytest.raises(LLMUnavailableError) as excinfo:
            send_with_retries("openai", "generation", 3, classify_openai_failure, send)

        assert "10 second retry cap" in str(excinfo.value)
        assert excinfo.value.__cause__ is error
        assert len(calls) == 1
        assert sleeps == []
        assert caplog.records == []

    def test_send_with_retries_exhaustion_raises_with_cause_and_attempt_count(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        calls: list[int] = []
        sleeps: list[float] = []
        errors: list[Exception] = []

        def send() -> object:
            calls.append(1)
            error = anthropic.APIConnectionError(request=SimpleNamespace())
            errors.append(error)
            raise error

        monkeypatch.setattr("time.sleep", sleeps.append)
        monkeypatch.setattr("random.uniform", lambda _a, _b: 0.0)
        caplog.set_level(logging.WARNING, logger="prettyplay")

        with pytest.raises(LLMUnavailableError) as excinfo:
            send_with_retries("anthropic", "generation", 3, classify_anthropic_failure, send)

        assert "after 3 attempts" in str(excinfo.value)
        assert excinfo.value.__cause__ is errors[-1]
        assert len(calls) == 3
        assert sleeps == [1.0, 2.0]
        assert len(caplog.records) == 2  # the terminal attempt logs nothing

    def test_send_with_retries_single_attempt_disables_retries(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        calls: list[int] = []
        sleeps: list[float] = []

        def send() -> object:
            calls.append(1)
            raise anthropic.APIConnectionError(request=SimpleNamespace())

        monkeypatch.setattr("time.sleep", sleeps.append)

        with pytest.raises(LLMUnavailableError):
            send_with_retries("anthropic", "generation", 1, classify_anthropic_failure, send)

        assert len(calls) == 1
        assert sleeps == []
        assert caplog.records == []

    def test_send_with_retries_keyboard_interrupt_during_wait_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[int] = []

        def send() -> object:
            calls.append(1)
            raise anthropic.APIConnectionError(request=SimpleNamespace())

        def interrupted(pause: float) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr("time.sleep", interrupted)

        with pytest.raises(KeyboardInterrupt):
            send_with_retries("anthropic", "generation", 3, classify_anthropic_failure, send)

        assert len(calls) == 1


class TestSendWithRetriesEdges:
    """Logic tests (edge): the budget ceiling, the branch precedence and the log hygiene."""

    def test_send_with_retries_never_sends_more_than_the_budget(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        calls: list[int] = []
        sleeps: list[float] = []

        def send() -> object:
            calls.append(1)
            raise anthropic.APIConnectionError(request=SimpleNamespace())

        monkeypatch.setattr("time.sleep", sleeps.append)
        monkeypatch.setattr("random.uniform", lambda _a, _b: 0.0)
        caplog.set_level(logging.WARNING, logger="prettyplay")

        with pytest.raises(LLMUnavailableError):
            send_with_retries("anthropic", "generation", 5, classify_anthropic_failure, send)

        assert len(calls) == 5
        assert sleeps == [1.0, 2.0, 4.0, 8.0]
        assert len(caplog.records) == 4

    def test_send_with_retries_over_cap_retry_after_wins_over_exhaustion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        error = make_status_error(openai.RateLimitError, 429, {"retry-after": "15"})
        calls: list[int] = []

        def send() -> object:
            calls.append(1)
            raise error

        monkeypatch.setattr("time.sleep", lambda _pause: None)

        with pytest.raises(LLMUnavailableError) as excinfo:
            send_with_retries("openai", "generation", 1, classify_openai_failure, send)

        assert "retry cap" in str(excinfo.value)
        assert "after 1 attempts" not in str(excinfo.value)

    def test_send_with_retries_zero_retry_after_is_ignored_not_fatal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = object()
        outcomes: list[object] = [make_status_error(anthropic.RateLimitError, 429, {"retry-after": "0"}), response]
        sleeps: list[float] = []

        def send() -> object:
            outcome = outcomes.pop(0)

            if isinstance(outcome, Exception):
                raise outcome

            return outcome

        monkeypatch.setattr("time.sleep", sleeps.append)
        monkeypatch.setattr("random.uniform", lambda _a, _b: 0.0)

        result = send_with_retries("anthropic", "generation", 2, classify_anthropic_failure, send)

        assert result is response
        assert sleeps == [1.0]

    def test_logging_carries_no_request_payloads(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        request_kwargs = {"api_key": "secret-token", "messages": [{"role": "user", "content": "secret-token"}]}
        outcomes: list[object] = [anthropic.APIConnectionError(request=SimpleNamespace()), "ok"]

        def send() -> str:
            _ = request_kwargs  # the closure carries the payload; the retry record must never see it
            outcome = outcomes.pop(0)

            if isinstance(outcome, Exception):
                raise outcome

            return str(outcome)

        monkeypatch.setattr("time.sleep", lambda _pause: None)
        monkeypatch.setattr("random.uniform", lambda _a, _b: 0.0)
        caplog.set_level(logging.WARNING, logger="prettyplay")

        assert send_with_retries("anthropic", "generation", 2, classify_anthropic_failure, send) == "ok"

        assert len(caplog.records) == 1
        assert all("secret-token" not in record.getMessage() for record in caplog.records)
        expected_fields = {"provider", "operation", "attempt", "category", "delay"}
        assert all(expected_fields <= set(record.__dict__) for record in caplog.records)


class TestFacadeExports:
    """Contract tests: the cell facade exposes the transport machinery; the root facade does not."""

    def test_facade_exports_the_transport_machinery(self) -> None:
        import prettyplay  # noqa: PLC0415 — cell facade check
        from prettyplay import llm  # noqa: PLC0415 — cell facade check

        names = [
            "TransportFailureClassification",
            "classify_openai_failure",
            "classify_anthropic_failure",
            "compute_transport_pause",
            "send_with_retries",
        ]

        assert all(name in llm.__all__ and getattr(llm, name) is not None for name in names)
        assert not (set(names) & set(prettyplay.__all__))
