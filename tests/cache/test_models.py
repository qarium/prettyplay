"""Tests for the cache models of the prettyplay.cache cell."""

import hashlib

import pydantic
import pytest
from prettyplay.cache import CachedStep, StepIdentity, validate_step_scope
from prettyplay.failures import PrettyplayError


class TestStepIdentityContract:
    """Contract tests: facade import, kw_only shape, address surface."""

    def test_identity_is_importable_from_facade(self) -> None:
        assert isinstance(StepIdentity, type)

    def test_identity_is_pydantic_base_model(self) -> None:
        assert issubclass(StepIdentity, pydantic.BaseModel)

    def test_identity_is_kw_only(self) -> None:
        assert StepIdentity.model_config.get("kw_only") is True

    def test_identity_positional_construction_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            StepIdentity("k", "action", "нажать войти")  # type: ignore[misc]

    def test_identity_declares_exactly_the_address_fields(self) -> None:
        assert set(StepIdentity.model_fields) == {"cache_key", "step_type", "normalized_text", "scope"}

    def test_identity_exposes_all_address_surfaces(self) -> None:
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="нажать войти")

        assert identity.cache_key == "k"
        assert identity.step_type == "action"
        assert identity.normalized_text == "нажать войти"
        assert identity.scope == ""
        assert identity.address_key == "k"
        assert isinstance(identity.filename, str)

    def test_identity_accepts_scope_kwarg_with_default_empty(self) -> None:
        scoped = StepIdentity(
            cache_key="k", step_type="action", normalized_text="open the dashboard", scope="pages/dashboard"
        )
        unscoped = StepIdentity(cache_key="k", step_type="action", normalized_text="open the dashboard")

        assert scoped.scope == "pages/dashboard"
        assert scoped.address_key == "pages/dashboard"
        assert unscoped.scope == ""  # the default keeps every existing construction unscoped
        assert unscoped.address_key == "k"


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

    def test_step_identity_scoped_address_key_and_filename(self) -> None:
        identity = StepIdentity(
            cache_key="login-flow", step_type="action", normalized_text="open the dashboard", scope="pages/dashboard"
        )

        identity_string = "\x1f".join(("pages/dashboard", "action", "open the dashboard"))
        expected = f"{hashlib.sha256(identity_string.encode()).hexdigest()}.py"

        assert identity.address_key == "pages/dashboard"
        assert identity.filename == expected
        assert identity.scope == "pages/dashboard"

    def test_step_identity_unscoped_digest_unchanged(self) -> None:
        identity = StepIdentity(cache_key="login-flow", step_type="action", normalized_text="open the dashboard")

        identity_string = "\x1f".join(("login-flow", "action", "open the dashboard"))
        expected = f"{hashlib.sha256(identity_string.encode()).hexdigest()}.py"
        explicit_empty = StepIdentity(
            cache_key="login-flow", step_type="action", normalized_text="open the dashboard", scope=""
        )

        assert identity.address_key == "login-flow"
        assert identity.filename == expected
        assert explicit_empty.filename == identity.filename

    def test_scoped_identity_and_equal_cache_key_share_one_address(self) -> None:
        a = StepIdentity(cache_key="pages/login", step_type="action", normalized_text="x", scope="")
        b = StepIdentity(cache_key="k", step_type="action", normalized_text="x", scope="pages/login")

        assert a.filename == b.filename  # scope == cache_key — one address space by construction


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


class TestValidateStepScopeContract:
    """Contract tests: facade import, valid scope returns None."""

    def test_validate_step_scope_is_importable_from_facade(self) -> None:
        assert callable(validate_step_scope)

    def test_validate_step_scope_returns_none_for_valid_scope(self) -> None:
        assert validate_step_scope("pages/login_page") is None


class TestValidateStepScopeLogic:
    """Logic tests: the one scope charset rule serving both validation rings."""

    @pytest.mark.parametrize("scope", ["pages/login_page", "a", "v1.2.config-x", "pages/nested/deep"])
    def test_validate_step_scope_accepts_valid_scopes(self, scope: str) -> None:
        assert validate_step_scope(scope) is None

    @pytest.mark.parametrize(
        "scope",
        [
            "",
            "/pages",
            "pages/",
            "pages//login",
            "..",
            "a/../b",
            "pages\\login",
            "C:/pages",
            "pages login",
            "страница",
            "pages:login",
        ],
    )
    def test_validate_step_scope_rejects_invalid_scopes(self, scope: str) -> None:
        with pytest.raises(PrettyplayError) as excinfo:
            validate_step_scope(scope)

        message = str(excinfo.value)
        assert "_scope" in message
        assert repr(scope) in message
        assert "segments of ASCII letters" in message

    @pytest.mark.parametrize("scope", [".", "pages/.", "..."])
    def test_validate_step_scope_accepts_dot_only_segments(self, scope: str) -> None:
        assert validate_step_scope(scope) is None  # the dot is a legal segment character, only ".." is banned
