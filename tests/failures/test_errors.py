"""Tests for the failure taxonomy of the prettyplay.failures cell."""

import inspect

import pytest
from prettyplay.failures import (
    ComplianceVerdictError,
    ErrorParts,
    FailureVerdict,
    IncurableStepError,
    LLMUnavailableError,
    PrettyplayError,
    ProductDefectError,
    __all__,
    decompose_error_text,
    render_terminal_message,
)

#: The representative failed-expectation text reused across the decomposition tests.
EXPECT_FAILURE_TEXT = "\n".join(
    [
        "Locator expected to be visible",
        "Actual value: display:none",
        "Call log:",
        '  - waiting for get_by_role("button", name="Sign in")',
    ]
)


class TestFailuresContract:
    """Contract tests: facade import, subclassing, constructor signatures, fields."""

    def test_all_nine_names_importable_from_facade(self) -> None:
        for name in (
            PrettyplayError,
            ProductDefectError,
            IncurableStepError,
            LLMUnavailableError,
            ComplianceVerdictError,
            FailureVerdict,
            ErrorParts,
        ):
            assert isinstance(name, type)

        assert callable(render_terminal_message)
        assert callable(decompose_error_text)

    def test_every_mutation_is_subclass_of_prettyplay_error(self) -> None:
        assert issubclass(ProductDefectError, PrettyplayError)
        assert issubclass(IncurableStepError, PrettyplayError)
        assert issubclass(LLMUnavailableError, PrettyplayError)
        assert issubclass(ComplianceVerdictError, PrettyplayError)

    def test_base_is_an_exception(self) -> None:
        assert issubclass(PrettyplayError, Exception)

    def test_base_signature_is_single_message(self) -> None:
        parameters = list(inspect.signature(PrettyplayError.__init__).parameters.values())[1:]  # drop self

        assert [parameter.name for parameter in parameters] == ["message"]

    def test_verdict_signature_is_three_fields(self) -> None:
        parameters = list(inspect.signature(FailureVerdict.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["category", "explanation", "recommendation"]

    def test_verdict_render_is_callable_method(self) -> None:
        assert callable(FailureVerdict.render)

    def test_render_terminal_message_signature_is_five_parameters(self) -> None:
        parameters = list(inspect.signature(render_terminal_message).parameters.values())

        assert [parameter.name for parameter in parameters] == [
            "error_class",
            "reason",
            "step_text",
            "error",
            "verdict",
        ]

    def test_decompose_error_text_signature_is_single_error(self) -> None:
        assert list(inspect.signature(decompose_error_text).parameters) == ["error"]

    def test_error_parts_signature_is_five_keyword_only_string_fields(self) -> None:
        parameters = list(inspect.signature(ErrorParts).parameters.values())

        assert [parameter.name for parameter in parameters] == ["class_name", "reason", "received", "cause", "call_log"]
        assert all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in parameters)
        assert all(parameter.default == "" for parameter in parameters)

    def test_product_defect_signature_is_step_text_message_error_verdict(self) -> None:
        parameters = list(inspect.signature(ProductDefectError.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["step_text", "message", "error", "verdict"]
        assert parameters[2].default == ""
        assert parameters[3].default is None

    def test_product_defect_accepts_the_four_argument_form(self) -> None:
        verdict = FailureVerdict("product_defect", "e", "r")
        error = ProductDefectError("step", "msg", "err", verdict)

        assert (error.step_text, error.message, error.error, error.verdict) == ("step", "msg", "err", verdict)

    def test_incurable_signature_is_step_text_reason_error_code_verdict(self) -> None:
        parameters = list(inspect.signature(IncurableStepError.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["step_text", "reason", "error", "code", "verdict"]
        assert parameters[2].default == ""
        assert parameters[3].default == ""
        assert parameters[4].default is None

    def test_incurable_accepts_the_five_argument_form_with_code(self) -> None:
        verdict = FailureVerdict("incurable", "e", "r")
        error = IncurableStepError("step", "why", "err", "code", verdict)

        assert (error.step_text, error.reason, error.error, error.code, error.verdict) == (
            "step",
            "why",
            "err",
            "code",
            verdict,
        )

        keyword = IncurableStepError("step", "why", "err", code="code", verdict=None)

        assert keyword.code == "code"

    def test_incurable_legacy_construction_still_works_with_empty_code(self) -> None:
        error = IncurableStepError("step", "why", "err")
        with_verdict = IncurableStepError("step", "why", "err", verdict=FailureVerdict("incurable", "e", "r"))

        assert error.code == ""
        assert with_verdict.code == ""

    def test_incurable_code_property_returns_the_stored_value(self) -> None:
        assert IncurableStepError("s", "r", "e", "c", None).code == "c"
        assert IncurableStepError("s", "r", "e").code == ""

    def test_llm_unavailable_signature_is_single_message(self) -> None:
        parameters = list(inspect.signature(LLMUnavailableError.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["message"]

    def test_compliance_verdict_error_importable_from_facade(self) -> None:
        # the module-level import above proves the facade import; the contract pins the export list
        assert "ComplianceVerdictError" in __all__

    def test_compliance_verdict_signature_is_single_message(self) -> None:
        parameters = list(inspect.signature(ComplianceVerdictError.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["message"]

    def test_compliance_verdict_api_shape_exposes_the_message_property(self) -> None:
        assert ComplianceVerdictError("m").message == "m"

    def test_product_defect_is_assertion_and_library_error(self) -> None:
        assert issubclass(ProductDefectError, AssertionError)
        assert issubclass(ProductDefectError, PrettyplayError)

    def test_product_defect_properties(self) -> None:
        error = ProductDefectError("click Sign in", "expected the banner, observed none")

        assert error.step_text == "click Sign in"
        assert error.message == "expected the banner, observed none"
        assert error.verdict is None

    def test_incurable_properties(self) -> None:
        error = IncurableStepError("click Sign in", "budget exhausted")

        assert error.step_text == "click Sign in"
        assert error.reason == "budget exhausted"
        assert error.verdict is None

    def test_llm_unavailable_property(self) -> None:
        error = LLMUnavailableError("llm unavailable: openai: OPENAI_API_KEY is not set")

        assert error.message == "llm unavailable: openai: OPENAI_API_KEY is not set"

    def test_facade_all_lists_nine_names(self) -> None:
        assert __all__ == [
            "ComplianceVerdictError",
            "ErrorParts",
            "FailureVerdict",
            "IncurableStepError",
            "LLMUnavailableError",
            "PrettyplayError",
            "ProductDefectError",
            "decompose_error_text",
            "render_terminal_message",
        ]


class TestFailureVerdictLogic:
    """Logic tests: the frozen value object and its stable render."""

    def test_render_lists_aligned_fields_without_category(self) -> None:
        verdict = FailureVerdict("rot", "the button was renamed", "refresh the cache")

        assert verdict.render().splitlines() == [
            "explanation: the button was renamed",
            "recommendation: refresh the cache",
        ]

    def test_render_skips_empty_fields(self) -> None:
        verdict = FailureVerdict("rot", "", "refresh the cache")

        assert verdict.render() == "recommendation: refresh the cache"

    def test_verdict_render_labels_at_column_zero_with_two_space_continuations(self) -> None:
        assert FailureVerdict("rot", "two\nlines", "do X").render() == "explanation: two\n  lines\nrecommendation: do X"

    def test_verdict_render_empty_fields_yield_empty_block(self) -> None:
        assert FailureVerdict("rot", "", "").render() == ""

        rendered = render_terminal_message(
            "IncurableStepError", "budget exhausted", "step", "err", FailureVerdict("rot", "", "")
        )

        assert "recommendation:" not in rendered
        assert not rendered.endswith("---")  # an empty verdict block leaves no section at all

    def test_verdict_is_frozen(self) -> None:
        verdict = FailureVerdict("rot", "the button was renamed", "refresh the cache")

        with pytest.raises(Exception):  # noqa: B017, PT011 — frozen dataclass raises FrozenInstanceError
            verdict.category = "incurable"


class TestRenderTerminalMessageLogic:
    """Logic tests: the single structured render and its block-omission rules."""

    def test_render_composes_the_full_template(self) -> None:
        verdict = FailureVerdict("fixable", "the button is behind the modal", "dismiss the modal first")
        rendered = render_terminal_message(
            "IncurableStepError", "the generation budget is exhausted", "click Checkout", EXPECT_FAILURE_TEXT, verdict
        )

        assert rendered == "\n".join(
            [
                "IncurableStepError: the generation budget is exhausted",
                "---",
                "step: click Checkout",
                "error: Locator expected to be visible",
                "---",
                "received: display:none",
                "Call log:",
                '  - waiting for get_by_role("button", name="Sign in")',
                "---",
                "explanation: the button is behind the modal",
                "recommendation: dismiss the modal first",
            ]
        )  # labels at column zero, no padding anywhere

    def test_render_terminal_message_full_template(self) -> None:
        rendered = render_terminal_message(
            "ProductDefectError",
            "кнопка осталась невидимой",
            "Проверить кнопку",
            "Locator expected to be visible",
            FailureVerdict("product_defect", "на странице нет элемента", "проверить селектор"),
        )

        assert rendered == (
            "ProductDefectError: кнопка осталась невидимой\n"
            "---\n"
            "step: Проверить кнопку\n"
            "error: Locator expected to be visible\n"
            "---\n"
            "explanation: на странице нет элемента\n"
            "recommendation: проверить селектор"
        )
        # the labels sit at column zero — no padding anywhere in the render
        assert "explanation: на странице нет элемента" in rendered
        # the first line is the class name plus the reason
        assert rendered.partition("\n")[0] == "ProductDefectError: кнопка осталась невидимой"

    def test_verdict_render_alignment_and_multiline(self) -> None:
        rendered = FailureVerdict("rot", "line one\nline two", "fix it").render()

        assert rendered == "explanation: line one\n  line two\nrecommendation: fix it"
        assert "category" not in rendered  # the category line is gone — structured fields only
        assert FailureVerdict("rot", "", "").render() == ""
        assert FailureVerdict("rot", "only", "").render() == "explanation: only"  # column zero — no padding

    def test_render_terminal_message_block_omission(self) -> None:
        assert render_terminal_message("IncurableStepError", "reason", "", "", None) == "IncurableStepError: reason"
        assert render_terminal_message("IncurableStepError", "reason", "step", "", None) == (
            "IncurableStepError: reason\n---\nstep: step"
        )
        assert render_terminal_message("IncurableStepError", "reason", "", "err", None) == (
            "IncurableStepError: reason\n---\nerror: err"
        )

        recommendation_only = render_terminal_message(
            "IncurableStepError", "reason", "", "", FailureVerdict("rot", "", "rec")
        )

        assert recommendation_only == "IncurableStepError: reason\n---\nrecommendation: rec"
        assert not recommendation_only.endswith("---")  # no trailing separator, ever

    def test_render_omits_the_details_section_without_parts(self) -> None:
        rendered = render_terminal_message(
            "IncurableStepError", "budget exhausted", "click Pay", "TimeoutError: Timeout 30000ms exceeded", None
        )

        assert rendered == (
            "IncurableStepError: budget exhausted\n"
            "---\n"
            "step: click Pay\n"
            "error: TimeoutError: Timeout 30000ms exceeded"
        )
        assert rendered.count("---") == 1  # no second separator — the section is gone entirely
        assert "received:" not in rendered
        assert "cause:" not in rendered
        assert "Call log:" not in rendered

    def test_render_error_line_reconstructs_typed_headline(self) -> None:
        rendered = render_terminal_message(
            "IncurableStepError", "budget exhausted", "reload the page", "Page.reload: Timeout 30000ms exceeded", None
        )

        assert "error: Page.reload: Timeout 30000ms exceeded" in rendered.splitlines()
        # the dotted head lives inside the headline — distinct from the first line's terminal class
        assert rendered.partition("\n")[0] == "IncurableStepError: budget exhausted"

    def test_render_empty_error_omits_step_error_entirely_when_step_also_empty(self) -> None:
        rendered = render_terminal_message("IncurableStepError", "budget exhausted", "", "", None)

        assert rendered == "IncurableStepError: budget exhausted"
        assert "---" not in rendered  # no bare separator when the whole step section is empty

    def test_terminal_errors_carry_render_error_field_and_types(self) -> None:
        verdict = FailureVerdict("product_defect", "на странице нет элемента", "проверить селектор")
        pde = ProductDefectError(
            "Проверить кнопку", "the button stayed invisible", "Locator expected to be visible", verdict
        )

        assert str(pde) == render_terminal_message(
            "ProductDefectError",
            "the button stayed invisible",
            "Проверить кнопку",
            "Locator expected to be visible",
            verdict,
        )
        assert pde.error == "Locator expected to be visible"
        assert pde.verdict is verdict
        assert pde.message == "the button stayed invisible"  # the message attribute stays the primary reason
        assert isinstance(pde, AssertionError)
        assert isinstance(pde, PrettyplayError)

        ise = IncurableStepError("step", "strict mode forbids generation — the step is missing from the cache")

        assert ise.reason == "strict mode forbids generation — the step is missing from the cache"
        assert ise.message == ise.reason  # the base-class message attribute stays the primary reason
        assert ise.error == ""
        assert ise.verdict is None
        assert "recommendation: reword the step or refresh the cache" in str(ise)
        assert ise.recommendation == "reword the step or refresh the cache"
        assert not isinstance(ise, AssertionError)

        llm_error = LLMUnavailableError("llm unavailable: openai")

        assert str(llm_error) == "llm unavailable: openai"
        assert issubclass(LLMUnavailableError, PrettyplayError)


class TestFailuresLogic:
    """Logic tests: rendered messages, single-except boundary, actionable fields."""

    def test_product_defect_is_assertion_and_library_error_with_and_without_verdict(self) -> None:
        verdict = FailureVerdict("product_defect", "the total was wrong", "file a bug")

        with_verdict = ProductDefectError("step", "expected x, observed y", "", verdict)
        without_verdict = ProductDefectError("step", "expected x, observed y", "", None)

        assert isinstance(with_verdict, PrettyplayError)
        assert isinstance(with_verdict, AssertionError)
        assert isinstance(without_verdict, PrettyplayError)
        assert isinstance(without_verdict, AssertionError)

    def test_product_defect_str_without_verdict_carries_step_block(self) -> None:
        assert str(ProductDefectError("step", "expected x, observed y")) == (
            "ProductDefectError: expected x, observed y\n---\nstep: step"
        )

    def test_product_defect_str_appends_verdict_block(self) -> None:
        verdict = FailureVerdict("product_defect", "the banner is gone", "rec")
        rendered = str(ProductDefectError("step", "expected x, observed y", "", verdict))

        assert rendered.startswith("ProductDefectError: expected x, observed y")
        assert "recommendation: rec" in rendered
        assert rendered.index("expected x, observed y") < rendered.index("recommendation:")

    def test_incurable_recommendation_comes_from_verdict(self) -> None:
        error = IncurableStepError(
            "s", "budget exhausted", "", verdict=FailureVerdict("incurable", "e", "reword the step")
        )

        assert error.recommendation == "reword the step"

    def test_incurable_fallback_recommendation_without_verdict(self) -> None:
        error = IncurableStepError("s", "budget exhausted")

        assert error.recommendation == "reword the step or refresh the cache"
        assert str(error).startswith("IncurableStepError: budget exhausted")
        assert "recommendation: reword the step or refresh the cache" in str(error)
        assert not isinstance(error, AssertionError)

    def test_incurable_str_appends_verdict_block(self) -> None:
        verdict = FailureVerdict("incurable", "the text is gone", "reword the step")
        rendered = str(IncurableStepError("s", "budget exhausted", "", verdict=verdict))

        assert rendered.startswith("IncurableStepError: budget exhausted")
        assert "recommendation: reword the step" in rendered
        assert rendered.index("budget exhausted") < rendered.index("recommendation:")

    def test_incurable_is_catchable_by_base(self) -> None:
        error = IncurableStepError(
            "click Sign in", "budget exhausted", "", verdict=FailureVerdict("incurable", "e", "reword")
        )

        assert isinstance(error, PrettyplayError)  # one except clause at the suite boundary

    def test_single_except_clause_catches_every_mutation(self) -> None:
        mutations = [
            ProductDefectError("click Sign in", "expected the banner, observed none"),
            IncurableStepError("click Sign in", "budget exhausted"),
            LLMUnavailableError("llm unavailable: openai: OPENAI_API_KEY is not set"),
        ]

        for error in mutations:
            with pytest.raises(PrettyplayError) as excinfo:
                raise error

            assert excinfo.value is error

    def test_llm_unavailable_message_names_provider(self) -> None:
        message = "llm unavailable: openai: OPENAI_API_KEY is not set"

        assert LLMUnavailableError(message).message == message
        assert "openai" in str(LLMUnavailableError(message))

    def test_compliance_verdict_error_is_a_library_failure(self) -> None:
        message = "compliance verdict unparsable — expected a JSON list of findings; received fragment: []"
        error = ComplianceVerdictError(message)

        assert isinstance(error, PrettyplayError)
        assert not isinstance(error, AssertionError)  # a gate failure is an error, never a failed check
        assert error.message == message
        assert str(error) == message
        assert not hasattr(error, "verdict")  # a verdict parse failure is not a step failure classification

    def test_base_message_stored_as_attribute(self) -> None:
        error = PrettyplayError("something broke")

        assert error.message == "something broke"
        assert str(error) == "something broke"

    def test_product_defect_args_carry_the_single_render(self) -> None:
        error = ProductDefectError("step", "expected x, observed y", "", FailureVerdict("product_defect", "e", "rec"))

        assert error.args == (str(error),)  # one render — composed at construction, never re-composed

    def test_code_bearing_error_keeps_code_out_of_every_render(self) -> None:
        step_code = "def step(page): boom()"
        error = IncurableStepError("click Pay", "budget exhausted", "Timeout 10000ms exceeded", step_code, None)

        assert error.code == step_code
        assert step_code not in str(error)
        assert step_code not in render_terminal_message(
            "IncurableStepError", error.reason, error.step_text, error.error, error.verdict
        )
        assert error.message == "budget exhausted"  # the code never leaks into the message attribute

    def test_no_code_error_renders_the_pre_change_form(self) -> None:
        error = IncurableStepError("s", "budget exhausted", "err")

        assert error.code == ""
        assert str(error) == (
            "IncurableStepError: budget exhausted\n"
            "---\n"
            "step: s\n"
            "error: err\n"
            "---\n"
            "recommendation: reword the step or refresh the cache"
        )

    def test_verdict_bearing_error_with_code_renders_verdict_block_without_code(self) -> None:
        verdict = FailureVerdict("rot", "the button was renamed", "refresh the cache")
        step_code = "page.click('#pay')"
        error = IncurableStepError("s", "budget exhausted", "err", step_code, verdict)

        assert error.verdict is verdict
        assert "explanation: the button was renamed" in str(error)
        assert "recommendation: refresh the cache" in str(error)
        assert step_code not in str(error)  # the code field stays programmatic-only

    def test_product_defect_first_line_carries_its_own_class_name(self) -> None:
        exc = ProductDefectError("s", "the button stayed invisible", "", None)

        assert str(exc).splitlines()[0] == "ProductDefectError: the button stayed invisible"
        assert exc.message == "the button stayed invisible"  # the attribute keeps the primary reason

        incurable = IncurableStepError("s", "budget exhausted", "", None)

        assert str(incurable).splitlines()[0] == "IncurableStepError: budget exhausted"
        # the render-only fallback verdict still renders when the verdict is None
        assert "recommendation: reword the step or refresh the cache" in str(incurable)

    def test_incurable_property_set_matches_the_contract(self) -> None:
        error = IncurableStepError("s", "r", "e", "c", None)

        assert (error.step_text, error.reason, error.error, error.code) == ("s", "r", "e", "c")
        assert error.recommendation == "reword the step or refresh the cache"  # fallback — no verdict
        assert error.verdict is None


class TestDecomposeErrorText:
    """Logic tests: the pure recognition of the playwright failure-message anatomy."""

    def test_decompose_extracts_all_parts_of_an_expect_failure(self) -> None:
        parts = decompose_error_text(EXPECT_FAILURE_TEXT)

        assert parts.class_name == ""
        assert parts.reason == "Locator expected to be visible"
        assert parts.received == "display:none"
        assert parts.cause == ""
        assert parts.call_log == '  - waiting for get_by_role("button", name="Sign in")'

    def test_decompose_extracts_typed_error_head(self) -> None:
        parts = decompose_error_text("TimeoutError: Timeout 30000ms exceeded\n=========================== logs ====…")

        assert parts.class_name == "TimeoutError"
        assert parts.reason == "Timeout 30000ms exceeded"
        assert parts.received == ""
        assert parts.cause == ""
        assert parts.call_log == ""  # the logs appendix is not a Call log block

    def test_decompose_extracts_cause_line(self) -> None:
        text = "TimeoutError: Page.goto failed\nCaused by: net::ERR_CONNECTION_REFUSED at https://x.test"
        parts = decompose_error_text(text)

        assert parts.class_name == "TimeoutError"
        assert parts.reason == "Page.goto failed"
        assert parts.received == ""
        assert parts.cause == "net::ERR_CONNECTION_REFUSED at https://x.test"
        assert parts.call_log == ""

        rendered = render_terminal_message("IncurableStepError", "r", "s", text, None)

        # the render half: the cause line sits inside the details section, between the --- separators
        assert rendered == (
            "IncurableStepError: r\n"
            "---\n"
            "step: s\n"
            "error: TimeoutError: Page.goto failed\n"
            "---\n"
            "cause: net::ERR_CONNECTION_REFUSED at https://x.test"
        )

    def test_decompose_unrecognized_shapes_leave_parts_empty(self) -> None:
        parts = decompose_error_text("weird failure text\nno shapes here")

        assert parts.class_name == ""
        assert parts.reason == "weird failure text"
        assert parts.received == parts.cause == parts.call_log == ""

    def test_decompose_empty_error_yields_all_empty_parts(self) -> None:
        parts = decompose_error_text("")

        assert parts == ErrorParts()

    def test_decompose_multiline_actual_value_is_preserved(self) -> None:
        text = "\n".join(
            [
                "Locator expected to have text",
                "Actual value: welcome",
                "extra context line",
                "more context",
                "Call log:",
                "  - waiting for locator",
            ]
        )
        parts = decompose_error_text(text)

        assert parts.received == "welcome\nextra context line\nmore context"
        assert parts.call_log == "  - waiting for locator"

    def test_decompose_net_error_head_is_not_a_class(self) -> None:
        parts = decompose_error_text("net::ERR_CONNECTION_REFUSED at https://x.test")

        assert parts.class_name == ""
        assert parts.reason == "net::ERR_CONNECTION_REFUSED at https://x.test"

    def test_error_parts_is_pydantic_kw_only_with_empty_defaults(self) -> None:
        assert ErrorParts(class_name="X").model_dump() == {
            "class_name": "X",
            "reason": "",
            "received": "",
            "cause": "",
            "call_log": "",
        }
        assert ErrorParts(reason="r", class_name="c").reason == "r"

        with pytest.raises(TypeError):  # kw_only — positional construction is rejected
            ErrorParts("X")
