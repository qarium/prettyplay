"""Tests for the verbatim trace record of the prettyplay.engine.groups cell."""

import pydantic
import pytest
from prettyplay.cache import StepIdentity
from prettyplay.engine.groups import GroupStepOutcome


def _identity(normalized_text: str = "fill the email field") -> StepIdentity:
    return StepIdentity(cache_key="tests/test_login.py", step_type="action", normalized_text=normalized_text)


def _outcome(**overrides: object) -> GroupStepOutcome:
    fields: dict[str, object] = {
        "sentence": "fill the email field",
        "step_type": "action",
        "tries": None,
        "delay": None,
        "outcome": "passed",
        "url_before": "https://example.com/login",
        "url_after": "https://example.com/inbox",
        "identity": _identity(),
    }
    fields.update(overrides)
    return GroupStepOutcome(**fields)  # type: ignore[arg-type]


class TestGroupStepOutcomeContract:
    """Contract tests: facade import, kw_only frozen shape, the eight fields."""

    def test_is_importable_from_facade(self) -> None:
        assert isinstance(GroupStepOutcome, type)

    def test_is_listed_in_the_facade_all(self) -> None:
        import prettyplay.engine.groups  # noqa: PLC0415 — cell facade check

        assert "GroupStepOutcome" in prettyplay.engine.groups.__all__

    def test_is_pydantic_base_model(self) -> None:
        assert issubclass(GroupStepOutcome, pydantic.BaseModel)

    def test_is_kw_only(self) -> None:
        assert GroupStepOutcome.model_config.get("kw_only") is True

    def test_is_frozen(self) -> None:
        assert GroupStepOutcome.model_config.get("frozen") is True

    def test_positional_construction_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            GroupStepOutcome("fill the email field", "action")  # type: ignore[misc]

    def test_declares_exactly_the_eight_fields(self) -> None:
        assert set(GroupStepOutcome.model_fields) == {
            "sentence",
            "step_type",
            "tries",
            "delay",
            "outcome",
            "url_before",
            "url_after",
            "identity",
        }

    def test_kw_only_construction_carries_all_eight_fields(self) -> None:
        record = _outcome(tries=3, delay=1.5, outcome="failed")

        assert record.sentence == "fill the email field"
        assert record.step_type == "action"
        assert record.tries == 3
        assert record.delay == 1.5
        assert record.outcome == "failed"
        assert record.url_before == "https://example.com/login"
        assert record.url_after == "https://example.com/inbox"
        assert record.identity == _identity()

    def test_identity_is_typed_step_identity(self) -> None:
        record = _outcome()

        assert isinstance(record.identity, StepIdentity)

    def test_identity_is_required(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            GroupStepOutcome(sentence="fill the email field", outcome="passed")  # type: ignore[call-arg]

    def test_render_is_exposed_on_the_facade_type(self) -> None:
        assert callable(GroupStepOutcome.render)


class TestGroupStepOutcomeLogic:
    """Logic tests: the pinned three-line render, no truncation, immutability."""

    def test_render_passed_is_exactly_the_three_pinned_lines(self) -> None:
        record = _outcome(outcome="passed")

        assert record.render() == (
            "fill the email field\noutcome: passed\nurl: https://example.com/login -> https://example.com/inbox"
        )

    def test_render_failed_carries_the_failed_label(self) -> None:
        record = _outcome(outcome="failed")

        assert "outcome: failed" in record.render().splitlines()

    def test_render_never_contains_the_identity(self) -> None:
        record = _outcome(identity=_identity("a very distinctive normalized sentence"))

        rendered = record.render()

        assert "a very distinctive normalized sentence" not in rendered
        assert "tests/test_login.py" not in rendered
        assert record.identity.filename not in rendered

    def test_render_truncates_no_field(self) -> None:
        long_sentence = "open the very long inbox of the logged-in user " * 6
        long_url = "https://example.com/inbox?session=" + "a" * 400

        record = _outcome(sentence=long_sentence, url_before=long_url, url_after=long_url)

        assert record.render() == f"{long_sentence}\noutcome: passed\nurl: {long_url} -> {long_url}"

    def test_render_keeps_the_sentence_verbatim(self) -> None:
        sentence = "  click  the   SUBMIT  button "

        record = _outcome(sentence=sentence)

        assert record.render().splitlines()[0] == sentence

    def test_a_record_is_never_rewritten(self) -> None:
        record = _outcome()

        with pytest.raises(pydantic.ValidationError):
            record.outcome = "rewritten"  # type: ignore[misc]

    def test_neutral_fields_default_to_empty_and_none(self) -> None:
        record = GroupStepOutcome(identity=_identity())

        assert record.sentence == ""
        assert record.step_type == ""
        assert record.tries is None
        assert record.delay is None
        assert record.outcome == ""
        assert record.url_before == ""
        assert record.url_after == ""
