"""Tests for the failure taxonomy of the prettyplay.failures cell."""

import inspect

import pytest
from prettyplay.failures import (
    FailureVerdict,
    IncurableStepError,
    LLMUnavailableError,
    PrettyplayError,
    ProductDefectError,
    render_terminal_message,
    __all__,
)


class TestFailuresContract:
    """Contract tests: facade import, subclassing, constructor signatures, fields."""

    def test_all_six_names_importable_from_facade(self) -> None:
        for name in (PrettyplayError, ProductDefectError, IncurableStepError, LLMUnavailableError, FailureVerdict):
            assert isinstance(name, type)

        assert callable(render_terminal_message)

    def test_every_mutation_is_subclass_of_prettyplay_error(self) -> None:
        assert issubclass(ProductDefectError, PrettyplayError)
        assert issubclass(IncurableStepError, PrettyplayError)
        assert issubclass(LLMUnavailableError, PrettyplayError)

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

    def test_render_terminal_message_signature_is_four_parameters(self) -> None:
        parameters = list(inspect.signature(render_terminal_message).parameters.values())

        assert [parameter.name for parameter in parameters] == ["reason", "step_text", "error", "verdict"]

    def test_product_defect_signature_is_step_text_message_error_verdict(self) -> None:
        parameters = list(inspect.signature(ProductDefectError.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["step_text", "message", "error", "verdict"]
        assert parameters[2].default == ""
        assert parameters[3].default is None

    def test_product_defect_accepts_the_four_argument_form(self) -> None:
        verdict = FailureVerdict("product_defect", "e", "r")
        error = ProductDefectError("step", "msg", "err", verdict)

        assert (error.step_text, error.message, error.error, error.verdict) == ("step", "msg", "err", verdict)

    def test_incurable_signature_is_step_text_reason_error_verdict(self) -> None:
        parameters = list(inspect.signature(IncurableStepError.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["step_text", "reason", "error", "verdict"]
        assert parameters[2].default == ""
        assert parameters[3].default is None

    def test_incurable_accepts_the_four_argument_form(self) -> None:
        verdict = FailureVerdict("incurable", "e", "r")
        error = IncurableStepError("step", "why", "err", verdict)

        assert (error.step_text, error.reason, error.error, error.verdict) == ("step", "why", "err", verdict)

    def test_llm_unavailable_signature_is_single_message(self) -> None:
        parameters = list(inspect.signature(LLMUnavailableError.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["message"]

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

    def test_facade_all_lists_six_names(self) -> None:
        assert __all__ == [
            "FailureVerdict",
            "IncurableStepError",
            "LLMUnavailableError",
            "PrettyplayError",
            "ProductDefectError",
            "render_terminal_message",
        ]


class TestFailureVerdictLogic:
    """Logic tests: the frozen value object and its stable render."""

    def test_render_lists_aligned_fields_without_category(self) -> None:
        verdict = FailureVerdict("rot", "the button was renamed", "refresh the cache")

        assert verdict.render().splitlines() == [
            "explanation:    the button was renamed",
            "recommendation: refresh the cache",
        ]

    def test_render_skips_empty_fields(self) -> None:
        verdict = FailureVerdict("rot", "", "refresh the cache")

        assert verdict.render() == "recommendation: refresh the cache"

    def test_verdict_is_frozen(self) -> None:
        verdict = FailureVerdict("rot", "the button was renamed", "refresh the cache")

        with pytest.raises(Exception):  # noqa: B017, PT011 — frozen dataclass raises FrozenInstanceError
            verdict.category = "incurable"


class TestRenderTerminalMessageLogic:
    """Logic tests: the single structured render and its block-omission rules."""

    def test_render_terminal_message_full_template(self) -> None:
        rendered = render_terminal_message(
            "кнопка осталась невидимой",
            "Проверить кнопку",
            "Locator expected to be visible",
            FailureVerdict("product_defect", "на странице нет элемента", "проверить селектор"),
        )

        assert rendered == (
            "кнопка осталась невидимой\n"
            "---\n"
            "step: Проверить кнопку\n"
            "error: Locator expected to be visible\n"
            "---\n"
            "explanation:    на странице нет элемента\n"
            "recommendation: проверить селектор"
        )
        # the value column is len("recommendation:") + 1 — 4 spaces after "explanation:"
        assert "explanation:    на странице нет элемента" in rendered
        # the first line is the reason alone — no ":" of its own
        assert rendered.partition("\n")[0] == "кнопка осталась невидимой"

    def test_verdict_render_alignment_and_multiline(self) -> None:
        rendered = FailureVerdict("rot", "line one\nline two", "fix it").render()

        assert rendered == "explanation:    line one\n                line two\nrecommendation: fix it"
        assert "category" not in rendered  # the category line is gone — structured fields only
        assert FailureVerdict("rot", "", "").render() == ""
        assert FailureVerdict("rot", "only", "").render() == "explanation:    only"  # padded to the fixed column

    def test_render_terminal_message_block_omission(self) -> None:
        assert render_terminal_message("reason", "", "", None) == "reason"
        assert render_terminal_message("reason", "step", "", None) == "reason\n---\nstep: step"
        assert render_terminal_message("reason", "", "err", None) == "reason\n---\nerror: err"

        recommendation_only = render_terminal_message("reason", "", "", FailureVerdict("rot", "", "rec"))

        assert recommendation_only == "reason\n---\nrecommendation: rec"
        assert not recommendation_only.endswith("---")  # no trailing separator, ever

    def test_terminal_errors_carry_render_error_field_and_types(self) -> None:
        verdict = FailureVerdict("product_defect", "на странице нет элемента", "проверить селектор")
        pde = ProductDefectError("Проверить кнопку", "the button stayed invisible", "Locator expected to be visible", verdict)

        assert str(pde) == render_terminal_message(
            "the button stayed invisible", "Проверить кнопку", "Locator expected to be visible", verdict
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
            "expected x, observed y\n---\nstep: step"
        )

    def test_product_defect_str_appends_verdict_block(self) -> None:
        verdict = FailureVerdict("product_defect", "the banner is gone", "rec")
        rendered = str(ProductDefectError("step", "expected x, observed y", "", verdict))

        assert rendered.startswith("expected x, observed y")
        assert "recommendation: rec" in rendered
        assert rendered.index("expected x, observed y") < rendered.index("recommendation:")

    def test_incurable_recommendation_comes_from_verdict(self) -> None:
        error = IncurableStepError("s", "budget exhausted", "", FailureVerdict("incurable", "e", "reword the step"))

        assert error.recommendation == "reword the step"

    def test_incurable_fallback_recommendation_without_verdict(self) -> None:
        error = IncurableStepError("s", "budget exhausted")

        assert error.recommendation == "reword the step or refresh the cache"
        assert str(error).startswith("budget exhausted")
        assert "recommendation: reword the step or refresh the cache" in str(error)
        assert not isinstance(error, AssertionError)

    def test_incurable_str_appends_verdict_block(self) -> None:
        verdict = FailureVerdict("incurable", "the text is gone", "reword the step")
        rendered = str(IncurableStepError("s", "budget exhausted", "", verdict))

        assert rendered.startswith("budget exhausted")
        assert "recommendation: reword the step" in rendered
        assert rendered.index("budget exhausted") < rendered.index("recommendation:")

    def test_incurable_is_catchable_by_base(self) -> None:
        error = IncurableStepError("click Sign in", "budget exhausted", "", FailureVerdict("incurable", "e", "reword"))

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

    def test_base_message_stored_as_attribute(self) -> None:
        error = PrettyplayError("something broke")

        assert error.message == "something broke"
        assert str(error) == "something broke"

    def test_product_defect_args_carry_the_single_render(self) -> None:
        error = ProductDefectError("step", "expected x, observed y", "", FailureVerdict("product_defect", "e", "rec"))

        assert error.args == (str(error),)  # one render — composed at construction, never re-composed
