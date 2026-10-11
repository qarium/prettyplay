"""Tests for the cache models of the prettyplay.cache cell."""

import pydantic
import pytest
from prettyplay.cache import CachedStep, StepIdentity


class TestStepIdentityContract:
    """Contract tests: facade import, kw_only shape, triple surface."""

    def test_identity_is_importable_from_facade(self) -> None:
        assert isinstance(StepIdentity, type)

    def test_identity_is_pydantic_base_model(self) -> None:
        assert issubclass(StepIdentity, pydantic.BaseModel)

    def test_identity_is_kw_only(self) -> None:
        assert StepIdentity.model_config.get("kw_only") is True

    def test_identity_positional_construction_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            StepIdentity("k", "action", "нажать войти")  # type: ignore[misc]

    def test_identity_declares_exactly_the_triple(self) -> None:
        assert set(StepIdentity.model_fields) == {"cache_key", "step_type", "normalized_text"}

    def test_identity_exposes_all_four_properties(self) -> None:
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="нажать войти")

        assert identity.cache_key == "k"
        assert identity.step_type == "action"
        assert identity.normalized_text == "нажать войти"
        assert isinstance(identity.filename, str)


class TestCachedStepContract:
    """Contract tests: facade import, kw_only shape, the four unit fields."""

    def test_cached_step_is_importable_from_facade(self) -> None:
        assert isinstance(CachedStep, type)

    def test_cached_step_is_pydantic_base_model(self) -> None:
        assert issubclass(CachedStep, pydantic.BaseModel)

    def test_cached_step_is_kw_only(self) -> None:
        assert CachedStep.model_config.get("kw_only") is True

    def test_cached_step_positional_construction_is_rejected(self) -> None:
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="нажать войти")

        with pytest.raises(TypeError):
            CachedStep(identity, "нажать войти", "def step(page) -> None:\n    pass\n", "2026-09-07")  # type: ignore[misc]

    def test_cached_step_declares_exactly_the_four_fields(self) -> None:
        assert set(CachedStep.model_fields) == {"identity", "addressing_text", "code", "created_at"}

    def test_cached_step_holds_identity_addressing_code_and_created_at(self) -> None:
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="нажать войти")
        code = "def step(page) -> None:\n    page.goto('https://example.com')\n"

        step = CachedStep(identity=identity, addressing_text="нажать войти", code=code, created_at="2026-09-07")

        assert step.identity == identity
        assert step.addressing_text == "нажать войти"
        assert step.code == code
        assert step.created_at == "2026-09-07"


class TestStepIdentityLogic:
    """Logic tests: deterministic and discriminating filename."""

    def test_identity_filename_deterministic_and_discriminating(self) -> None:
        f1 = StepIdentity(cache_key="k", step_type="action", normalized_text="нажать войти").filename
        f2 = StepIdentity(cache_key="k", step_type="action", normalized_text="нажать войти").filename
        f3 = StepIdentity(cache_key="k", step_type="assertion", normalized_text="нажать войти").filename
        f4 = StepIdentity(cache_key="k2", step_type="action", normalized_text="нажать войти").filename

        assert f1 == f2
        assert f1 != f3
        assert f1 != f4

        digest_part = f1[: -len(".py")]
        assert f1.endswith(".py")
        assert len(digest_part) == 64

    def test_identity_normalized_text_discriminates_too(self) -> None:
        f1 = StepIdentity(cache_key="k", step_type="action", normalized_text="нажать войти").filename
        f2 = StepIdentity(cache_key="k", step_type="action", normalized_text="нажать выйти").filename

        assert f1 != f2

    def test_identity_triple_is_required(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            StepIdentity(cache_key="k", step_type="action")


class TestCachedStepLogic:
    """Logic tests: the addressing invariant, value equality, required fields."""

    def test_cached_step_rejects_addressing_invariant_violation(self) -> None:
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="open the login page")

        with pytest.raises(pydantic.ValidationError) as excinfo:
            CachedStep(identity=identity, addressing_text="Open the LOGIN page", code="...", created_at="2026-10-11")

        assert isinstance(excinfo.value, ValueError)  # the model validator raises a ValueError

    def test_cached_step_restores_legacy_normalized_addressing(self) -> None:
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="open the login page")

        step = CachedStep(
            identity=identity,
            addressing_text="open the login page",
            code="def step(page) -> None:\n    pass\n",
            created_at="2026-09-07",
        )

        assert step.addressing_text == "open the login page"  # a legacy file's STEP_TEXT is the normalized sentence

    def test_cached_step_accepts_verbatim_addressing_with_surrounding_whitespace(self) -> None:
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="Open the login page")

        step = CachedStep(
            identity=identity,
            addressing_text=" Open the login page ",
            code="def step(page) -> None:\n    pass\n",
            created_at="2026-09-07",
        )

        assert step.addressing_text == " Open the login page "  # verbatim — NFC + trim only at the identity

    def test_cached_step_equal_by_value(self) -> None:
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="нажать войти")

        first = CachedStep(
            identity=identity,
            addressing_text="нажать войти",
            code="def step(page) -> None:\n    pass\n",
            created_at="2026-09-07",
        )
        second = CachedStep(
            identity=identity,
            addressing_text="нажать войти",
            code="def step(page) -> None:\n    pass\n",
            created_at="2026-09-07",
        )

        assert first == second

    def test_cached_step_fields_are_required(self) -> None:
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="нажать войти")

        with pytest.raises(pydantic.ValidationError):
            CachedStep(identity=identity, addressing_text="нажать войти", code="def step(page) -> None:\n    pass\n")

    def test_cached_step_carries_identity_filename(self) -> None:
        identity = StepIdentity(cache_key="login-flow", step_type="action", normalized_text="открыть страницу")

        step = CachedStep(
            identity=identity,
            addressing_text="открыть страницу",
            code="def step(page) -> None:\n    pass\n",
            created_at="2026-09-07",
        )

        assert step.identity.filename == identity.filename
