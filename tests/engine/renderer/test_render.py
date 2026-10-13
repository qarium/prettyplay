"""Tests for the PreparedStep model and render_step function of the prettyplay.engine.renderer cell."""

import inspect
from unittest import mock

import jinja2.filters
import prettyplay.engine.renderer.render as render_module
import pydantic
import pytest
from prettyplay.engine.renderer import PreparedStep, StepMemory, render_step
from prettyplay.failures import PrettyplayError


class TestPreparedStepContract:
    """Contract tests: facade import, kw_only shape, empty defaults, frozen."""

    def test_is_importable_from_facade(self) -> None:
        assert isinstance(PreparedStep, type)

    def test_is_listed_in_the_facade_all(self) -> None:
        import prettyplay.engine.renderer  # noqa: PLC0415 — cell facade check

        assert "PreparedStep" in prettyplay.engine.renderer.__all__

    def test_is_a_pydantic_base_model(self) -> None:
        assert issubclass(PreparedStep, pydantic.BaseModel)

    def test_declares_exactly_four_fields(self) -> None:
        assert set(PreparedStep.model_fields) == {"instruction", "addressing_text", "inputs", "declarations"}

    def test_fields_have_empty_defaults(self) -> None:
        prepared = PreparedStep()

        assert prepared.instruction == ""
        assert prepared.addressing_text == ""
        assert prepared.inputs == {}
        assert prepared.declarations == []

    def test_exposes_the_addressing_text_attribute(self) -> None:
        prepared = PreparedStep(instruction="click Save", addressing_text="click Save")

        assert prepared.addressing_text == "click Save"

    def test_construction_is_keyword_only(self) -> None:
        for parameter in inspect.signature(PreparedStep).parameters.values():
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY

    def test_model_is_frozen(self) -> None:
        prepared = PreparedStep(instruction="click Save")

        with pytest.raises(pydantic.ValidationError):
            prepared.instruction = "click Cancel"  # type: ignore[misc]

    def test_has_declarations_is_a_plain_property(self) -> None:
        assert isinstance(inspect.getattr_static(PreparedStep, "has_declarations"), property)

        assert PreparedStep().has_declarations is False
        assert PreparedStep(declarations=["name"]).has_declarations is True


class TestRenderStepContract:
    """Contract tests: facade import, signature shape, return type."""

    def test_is_importable_from_facade(self) -> None:
        assert inspect.isfunction(render_step)

    def test_is_listed_in_the_facade_all(self) -> None:
        import prettyplay.engine.renderer  # noqa: PLC0415 — cell facade check

        assert "render_step" in prettyplay.engine.renderer.__all__

    def test_signature_matches_the_contract(self) -> None:
        parameters = inspect.signature(render_step).parameters

        assert list(parameters) == ["text", "step_type", "memory", "vars"]

    def test_signature_types_match_the_contract(self) -> None:
        annotations = render_step.__annotations__

        assert annotations["text"] is str
        assert annotations["step_type"] is str
        assert annotations["memory"] is StepMemory
        assert annotations["vars"] == dict[str, str] | None
        assert annotations["return"] is PreparedStep

    def test_returns_a_prepared_step_for_a_plain_sentence(self) -> None:
        prepared = render_step("click Save", "action", StepMemory(), None)

        assert isinstance(prepared, PreparedStep)


class TestRenderStepLogic:
    """Logic tests: substitution, namespaces, capture declarations, authoring errors."""

    def test_render_substitutes_memory_value_into_instruction(self) -> None:
        memory = StepMemory()
        memory.publish({"name": "Book"})

        prepared = render_step("Open the item named {{ name }}", "action", memory, None)

        assert prepared.instruction == "Open the item named Book"
        assert prepared.inputs == {}
        assert prepared.declarations == []
        assert prepared.has_declarations is False

    def test_render_reads_vars_namespace_separately_from_memory(self) -> None:
        memory = StepMemory()
        memory.publish({"name": "Book"})

        prepared = render_step(
            "The page contains {{ name }} and {{ vars.expected }}", "assertion", memory, {"expected": "Details"}
        )

        assert prepared.instruction == "The page contains Book and Details"
        assert prepared.inputs == {"expected": "Details"}

    def test_render_capture_tag_declares_result_and_renders_empty(self) -> None:
        prepared = render_step("Read the first item name into {% var name %}", "action", StepMemory(), None)

        assert prepared.declarations == ["name"]
        assert prepared.has_declarations is True
        assert prepared.instruction == "Read the first item name into "

    def test_render_unicode_capture_name_preserves_its_tag_in_address(self) -> None:
        sentence = "Read the drink into {% var café %}"

        prepared = render_step(sentence, "action", StepMemory(), None)

        assert prepared.declarations == ["café"]
        assert prepared.instruction == "Read the drink into "
        assert prepared.addressing_text == sentence

    def test_render_inactive_branch_declares_nothing(self) -> None:
        prepared = render_step("{% if false %}{% var x %}{% endif %}click Save", "action", StepMemory(), None)

        assert prepared.declarations == []
        assert prepared.instruction == "click Save"

    def test_render_duplicate_capture_name_raises_authoring_error(self) -> None:
        with pytest.raises(PrettyplayError, match="x") as excinfo:
            render_step("{% var x %}{% var x %} go", "action", StepMemory(), None)

        assert "twice" in str(excinfo.value)

    def test_render_capture_in_loop_body_reached_twice_raises(self) -> None:
        with pytest.raises(PrettyplayError, match="x"):
            render_step("{% for i in [1, 2] %}{% var x %}{% endfor %}", "action", StepMemory(), None)

    def test_render_malformed_standard_jinja_is_an_authoring_error(self) -> None:
        with pytest.raises(PrettyplayError) as excinfo:
            render_step("{% if x %}", "action", StepMemory(), None)

        assert "if" in str(excinfo.value)
        assert "line 1" in str(excinfo.value)

    def test_render_expression_failure_is_an_authoring_error(self) -> None:
        with pytest.raises(PrettyplayError, match="failed to evaluate") as excinfo:
            render_step("Open {{ 1 / 0 }}", "action", StepMemory(), None)

        assert "{{ 1 / 0 }}" in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, ZeroDivisionError)

    @pytest.mark.parametrize("text", ["{% var vars %}", "{% var 1x %}"])
    def test_render_reserved_and_invalid_capture_names_raise(self, text: str) -> None:
        with pytest.raises(PrettyplayError, match="var"):
            render_step(text, "action", StepMemory(), None)

    def test_render_unavailable_name_raises_naming_the_name(self) -> None:
        with pytest.raises(PrettyplayError, match="missing"):
            render_step("Open {{ missing }}", "action", StepMemory(), None)

    def test_render_missing_vars_input_names_the_qualified_name(self) -> None:
        with pytest.raises(PrettyplayError, match=r"vars\.x"):
            render_step("Show {{ vars.x }}", "action", StepMemory(), None)

    def test_render_capture_in_expectation_raises(self) -> None:
        with pytest.raises(PrettyplayError):
            render_step("The page shows {% var x %}", "assertion", StepMemory(), None)

        prepared = render_step("The page shows {% var x %}", "action", StepMemory(), None)

        assert prepared.declarations == ["x"]

    def test_render_same_step_cannot_read_its_own_capture(self) -> None:
        with pytest.raises(PrettyplayError, match="name"):
            render_step("Read {{ name }} and {% var name %}", "action", StepMemory(), None)

    def test_render_captured_value_containing_jinja_stays_literal(self) -> None:
        memory = StepMemory()
        memory.publish({"payload": "{{ boom }}"})

        prepared = render_step("Type {{ payload }}", "action", memory, None)

        assert prepared.instruction == "Type {{ boom }}"

    def test_render_author_written_default_and_is_defined_keep_behavior(self) -> None:
        default = render_step("{{ missing | default('n/a') }}", "action", StepMemory(), None)
        defined = render_step("{% if missing is defined %}x{% else %}y{% endif %}", "action", StepMemory(), None)

        assert default.instruction == "n/a"
        assert defined.instruction == "y"

    def test_render_raw_block_stays_literal(self) -> None:
        prepared = render_step("a {% raw %}{{ x }}{% endraw %} b", "action", StepMemory(), None)

        assert prepared.instruction == "a {{ x }} b"

    def test_render_memory_name_equal_to_input_name_keeps_both_accessible(self) -> None:
        memory = StepMemory()
        memory.publish({"name": "mem"})

        prepared = render_step("{{ name }} and {{ vars.name }}", "action", memory, {"name": "in"})

        assert prepared.instruction == "mem and in"

    def test_render_does_not_mutate_memory(self) -> None:
        memory = StepMemory()
        memory.publish({"name": "Book"})

        render_step("Read {{ name }} into {% var title %}", "action", memory, None)

        assert memory.snapshot() == {"name": "Book"}

    def test_render_reads_the_pre_step_snapshot(self) -> None:
        memory = StepMemory()
        memory.publish({"kind": "novel"})

        prepared = render_step("Read the {{ kind }} into {% var name %}", "action", memory, None)

        assert prepared.instruction == "Read the novel into "
        assert memory.snapshot() == {"kind": "novel"}

    def test_render_uses_a_fresh_environment_per_call(self) -> None:
        first = render_step("{% var a %}", "action", StepMemory(), None)
        second = render_step("{% var a %}", "action", StepMemory(), None)

        assert first.declarations == ["a"]
        assert second.declarations == ["a"]


class TestAddressingRender:
    """Logic tests: both texts of one render — the addressing-text scenarios of the design."""

    @pytest.mark.parametrize(
        ("source", "instruction"),
        [
            ("{# Ignore {% var hidden %} #}Read {% var actual %}", "Read "),
            (
                "{{ 'quoted \\' {% var hidden %} }}' }} {% var actual %}",
                "quoted ' {% var hidden %} }} ",
            ),
            (
                "{% set label = 'quoted \\' {% var hidden %} %}' %}{{ label }} {% var actual %}",
                "quoted ' {% var hidden %} %} ",
            ),
            ('{{ "backslash \\\\" }} {% var actual %}', "backslash \\ "),
        ],
        ids=["comment", "escaped-expression-quote", "escaped-block-quote", "escaped-backslash"],
    )
    def test_render_ignores_capture_syntax_in_comments_and_quoted_data(self, source: str, instruction: str) -> None:
        prepared = render_step(source, "action", StepMemory(), None)

        assert prepared.instruction == instruction
        assert prepared.addressing_text == instruction + "{% var actual %}"
        assert prepared.declarations == ["actual"]

    @pytest.mark.parametrize(
        "source",
        [
            '{{ "unterminated',
            "{{ vars.name",
            '{% set label = "unterminated',
            "{# unfinished comment {% var hidden %}",
            "{% raw %}unclosed {% var hidden %}",
            "{% raw %}unclosed {% endraw wrong %}",
            "{% 42 %}",
        ],
    )
    def test_render_malformed_scanner_boundaries_raise_authoring_error(self, source: str) -> None:
        memory = StepMemory()
        memory.publish({"existing": "preserved"})

        with pytest.raises(PrettyplayError, match="the step template is malformed"):
            render_step(source, "action", memory, None)

        assert memory.snapshot() == {"existing": "preserved"}

    def test_render_produces_both_texts_of_one_render(self) -> None:
        memory = StepMemory()
        memory.publish({"name": "Book"})

        prepared = render_step(
            "For the item named {{ name }}, read its tags into {% var tags %}", "action", memory, None
        )

        assert prepared.instruction == "For the item named Book, read its tags into "
        assert prepared.addressing_text == "For the item named Book, read its tags into {% var tags %}"
        assert prepared.declarations == ["tags"]

    def test_render_both_texts_observe_one_snapshot_and_branches(self) -> None:
        memory = StepMemory()
        memory.publish({"name": "Book", "kind": "short"})

        prepared = render_step(
            "{% if kind == 'short' %}The {{ name }} briefly{% else %}The {{ name }} at length{% endif %}"
            " — note {% var n %}",
            "action",
            memory,
            None,
        )

        assert prepared.instruction == "The Book briefly — note "
        assert prepared.addressing_text == "The Book briefly — note {% var n %}"
        assert "at length" not in prepared.addressing_text

    def test_render_nondeterministic_filter_is_evaluated_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def counted_choice(sequence: list[str]) -> str:
            calls.append("call")

            return "A" if len(calls) == 1 else "B"

        monkeypatch.setattr(jinja2.filters.random, "choice", counted_choice)

        prepared = render_step("Open {{ ['A', 'B']|random }} {% var found %}", "action", StepMemory(), None)

        assert len(calls) == 1
        assert prepared.instruction == "Open A "
        assert prepared.addressing_text == "Open A {% var found %}"
        assert prepared.declarations == ["found"]

    def test_render_preserves_reached_capture_tag_source(self) -> None:
        prepared = render_step(
            "A{%var x%}{% if false %}{% var hidden %}{% endif %}B{% var  y %}", "action", StepMemory(), None
        )

        assert prepared.instruction == "AB"
        assert prepared.addressing_text == "A{%var x%}B{% var  y %}"
        assert prepared.declarations == ["x", "y"]

    def test_render_data_never_reparsed_in_addressing_text(self) -> None:
        memory = StepMemory()
        memory.publish({"captured": "read {% var x %} then {{ y }}"})

        prepared = render_step("Echo {{ captured }}", "action", memory, None)

        assert prepared.instruction == "Echo read {% var x %} then {{ y }}"
        assert prepared.addressing_text == prepared.instruction
        assert prepared.declarations == []

    def test_plain_sentence_and_identical_render_share_one_address(self) -> None:
        from prettyplay.cache import StepIdentity, normalize_step_text  # noqa: PLC0415 — the addressing consumer

        memory = StepMemory()
        memory.publish({"name": "Book"})

        plain = render_step("Open the item named Book", "action", memory, None)
        template = render_step("Open the item named {{ name }}", "action", memory, None)

        assert plain.addressing_text == "Open the item named Book"
        assert template.addressing_text == "Open the item named Book"

        first = StepIdentity(
            cache_key="k", step_type="action", normalized_text=normalize_step_text(plain.addressing_text)
        )
        second = StepIdentity(
            cache_key="k", step_type="action", normalized_text=normalize_step_text(template.addressing_text)
        )

        assert first.filename == second.filename

    def test_render_marker_collision_with_data_fails_loudly(self) -> None:
        memory = StepMemory()
        memory.publish({"name": "\ue000capture 0 0000000000000000\ue001"})

        with (
            mock.patch.object(render_module.secrets, "token_hex", return_value="0000000000000000"),
            pytest.raises(PrettyplayError, match="marker"),
        ):
            render_step("Say {{ name }} and {% var x %}", "action", memory, None)
