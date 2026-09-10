"""Tests for the load_config routine of the prettyplay.config cell."""

import inspect

import pytest
from prettyplay.config import Config, ConfigurationError, PrettyConfig, load_config
from prettyplay.failures import PrettyplayError
from pydantic import ValidationError

#: Every PRETTYPLAY_* override the loader reads; tests neutralize ambient values.
_ALL_ENV_FIELDS = (
    "PROVIDER",
    "BROWSER_NAME",
    "BROWSER_HEADLESS",
    "MODEL",
    "GENERATION_MODEL",
    "CLASSIFICATION_MODEL",
    "BASE_URL",
    "CACHE_ROOT",
    "GENERATION_ATTEMPTS",
    "HEALING_ATTEMPTS",
    "SEND_SCREENSHOTS",
    "GENERATION_PROMPT",
    "BROWSER_ENDPOINT",
    "BROWSER",
)


@pytest.fixture(autouse=True)
def no_ambient_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize ambient PRETTYPLAY_* variables: loader tests stay deterministic."""
    for field in _ALL_ENV_FIELDS:
        monkeypatch.delenv(f"PRETTYPLAY_{field}", raising=False)


PYPROJECT_WITH_SECTION = """\
[tool.prettyplay]
provider = "openai"
browser = "chromium"
model = "gpt-5"
"""

PYPROJECT_WITHOUT_SECTION = """\
[project]
name = "sandbox"
"""


class TestLoadConfigContract:
    """Contract tests: facade, signature shape, return type."""

    def test_load_config_is_importable_from_facade(self) -> None:
        assert callable(load_config)

    def test_configuration_error_is_importable_from_facade(self) -> None:
        """The facade exposes the configuration failure beside the loader."""
        assert issubclass(ConfigurationError, PrettyplayError)

    def test_configuration_error_signature_is_single_message(self) -> None:
        parameters = inspect.signature(ConfigurationError.__init__).parameters
        assert list(parameters) == ["self", "message"]

    def test_signature_accepts_none_and_str_path(self, tmp_path, monkeypatch) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_WITH_SECTION, encoding="utf-8")
        monkeypatch.chdir(tmp_path)  # авто-поиск детерминирован: cwd содержит pyproject.toml

        assert load_config(pyproject_path=None).provider == "openai"
        assert load_config(pyproject_path=str(pyproject)).browser == "chromium"

    def test_signature_parameters_are_path_and_overrides(self) -> None:
        """Both parameters are optional; single-argument calls keep working."""
        parameters = inspect.signature(load_config).parameters

        assert list(parameters) == ["pyproject_path", "overrides"]
        assert parameters["pyproject_path"].default is None
        assert parameters["overrides"].default is None


class TestLoadConfigLogic:
    """Logic tests: section reading, env overrides, loud failures, defaults."""

    def test_load_config_reads_section_and_env_overrides(self, tmp_path, monkeypatch) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_WITH_SECTION, encoding="utf-8")

        monkeypatch.setenv("PRETTYPLAY_BROWSER_NAME", "firefox")
        monkeypatch.setenv("PRETTYPLAY_GENERATION_ATTEMPTS", "5")

        config = load_config(pyproject_path=str(pyproject))

        assert config.model == "gpt-5"
        assert config.browser == "firefox"  # env overrides TOML
        assert config.generation_attempts == 5  # str→int coercion
        assert config.cache_root == str(tmp_path / ".prettyplay" / "cache")

    def test_load_env_browser_name_and_headless(self, tmp_path, monkeypatch) -> None:
        """The two special browser env names override the settings; bool strings coerce."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_WITH_SECTION, encoding="utf-8")

        monkeypatch.setenv("PRETTYPLAY_BROWSER_NAME", "firefox")
        monkeypatch.setenv("PRETTYPLAY_BROWSER_HEADLESS", "false")

        config = load_config(pyproject_path=str(pyproject))

        assert config.browser == "firefox"
        assert config.headless is False  # pydantic coerces the "false" string

    def test_configuration_error_wraps_validation_with_lines(self, tmp_path) -> None:
        """A raw ValidationError never leaves the loader; one line names each invalid setting."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.prettyplay]\nbrowser = "netscape"\ngeneration_attempts = 0\n',
            encoding="utf-8",
        )

        with pytest.raises(ConfigurationError) as excinfo:
            load_config(pyproject_path=str(pyproject))

        assert isinstance(excinfo.value, PrettyplayError)
        message = str(excinfo.value)
        assert "browser" in message
        assert "netscape" in message
        assert "chromium, firefox, webkit, chrome, msedge" in message
        assert "generation_attempts" in message
        assert message.count("\n") == 1  # exactly two lines, one per setting
        assert isinstance(excinfo.value.__cause__, ValidationError)

    @pytest.mark.parametrize(
        ("env_name", "env_value", "setting", "allowed"),
        [
            ("PRETTYPLAY_BROWSER_HEADLESS", "maybe", "headless", "a boolean"),
            ("PRETTYPLAY_SEND_SCREENSHOTS", "perhaps", "send_screenshots", "a boolean"),
            ("PRETTYPLAY_PROVIDER", "yandex", "provider", "openai, anthropic"),
        ],
        ids=["headless", "send_screenshots", "provider"],
    )
    def test_invalid_setting_renders_allowed_values(  # noqa: PLR0913, PLR0917 — параметры параметризации
        self, tmp_path, monkeypatch, env_name: str, env_value: str, setting: str, allowed: str
    ) -> None:
        """Every overridable setting fails with its own allowed-values line — no pydantic internals."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_WITH_SECTION, encoding="utf-8")
        monkeypatch.setenv(env_name, env_value)

        with pytest.raises(ConfigurationError) as excinfo:
            load_config(pyproject_path=str(pyproject))

        line = next(line for line in str(excinfo.value).splitlines() if line.startswith(f"{setting}:"))
        assert f"received {env_value!r}" in line
        assert line.endswith(f"allowed: {allowed}")

    def test_legacy_browser_env_raises_configuration_error(self, tmp_path, monkeypatch) -> None:
        """The removed env name fails loudly and names its replacement."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_WITH_SECTION, encoding="utf-8")

        monkeypatch.setenv("PRETTYPLAY_BROWSER", "firefox")

        with pytest.raises(ConfigurationError) as excinfo:
            load_config(pyproject_path=str(pyproject))

        assert "PRETTYPLAY_BROWSER_NAME" in str(excinfo.value)

    def test_load_config_no_pyproject_fails_loudly(self, tmp_path, monkeypatch) -> None:
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        monkeypatch.chdir(sandbox)
        monkeypatch.delenv("PRETTYPLAY_CACHE_ROOT", raising=False)

        # /tmp и выше не содержат pyproject.toml (проверено окружением),
        # поэтому авто-поиск вверх от cwd детерминированно ничего не находит.
        with pytest.raises(FileNotFoundError) as excinfo:
            load_config(pyproject_path=None)

        assert "pyproject.toml not found" in str(excinfo.value)

    def test_load_config_missing_section_yields_defaults(self, tmp_path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_WITHOUT_SECTION, encoding="utf-8")

        config = load_config(pyproject_path=str(pyproject))

        assert config.provider == "openai"
        assert config.generation_attempts == 3
        assert isinstance(config, Config)


class TestLoadConfigEdge:
    """Edge tests: env set to empty overrides TOML; auto-search finds cwd file."""

    def test_env_set_to_empty_overrides_toml_value(self, tmp_path, monkeypatch) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_WITH_SECTION, encoding="utf-8")
        monkeypatch.setenv("PRETTYPLAY_MODEL", "")

        config = load_config(pyproject_path=str(pyproject))

        # переменная задана (пусть и пустая) — оверрайд применяется
        assert config.model == ""
        assert config.effective_generation_model == ""

    def test_auto_search_finds_pyproject_in_cwd(self, tmp_path, monkeypatch) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_WITH_SECTION, encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        config = load_config(pyproject_path=None)

        assert config.model == "gpt-5"
        assert config.cache_root == str(tmp_path / ".prettyplay" / "cache")

    def test_empty_cache_root_from_env_overrides_default(self, tmp_path, monkeypatch) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_WITH_SECTION, encoding="utf-8")
        monkeypatch.setenv("PRETTYPLAY_CACHE_ROOT", "/custom/cache")

        config = load_config(pyproject_path=str(pyproject))

        assert config.cache_root == "/custom/cache"


class TestLoadConfigOverlay:
    """Logic tests: the programmatic layer over pyproject → env (explicit values win)."""

    def test_load_config_overrides_explicit_values_win(self, write_pyproject) -> None:
        path = write_pyproject(browser="chromium", model="gpt-5", base_url="https://file.example/v1")

        config = load_config(
            path,
            Config(browser="firefox", browser_endpoint="ws://ci-grid:3000/playwright/firefox"),
        )

        assert config.browser == "firefox"
        assert config.browser_endpoint == "ws://ci-grid:3000/playwright/firefox"
        assert config.model == "gpt-5"  # untouched file values survive
        assert config.base_url == "https://file.example/v1"

    def test_load_config_without_overrides_returns_file_layer(self, write_pyproject) -> None:
        path = write_pyproject(provider="anthropic", generation_attempts=5)

        assert load_config(path, None).provider == "anthropic"
        assert load_config(path, None).generation_attempts == 5

        # пустой PrettyConfig участвует ни в одном поле — ведёт себя как None
        empty = load_config(path, PrettyConfig())

        assert empty.provider == "anthropic"
        assert empty.generation_attempts == 5
        assert empty.generation_prompt == ""
        assert empty.browser_endpoint == ""

    def test_load_config_renders_actionable_line_for_endpoint(self, write_pyproject) -> None:
        path = write_pyproject(browser_endpoint="http://bad")

        with pytest.raises(ConfigurationError) as excinfo:
            load_config(path)

        assert "browser_endpoint" in str(excinfo.value)
        assert "ws/wss" in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, ValidationError)

    def test_load_config_empty_string_override_does_not_win(self, write_pyproject) -> None:
        path = write_pyproject(cache_root="/custom/cache", model="gpt-5")

        config = load_config(path, Config(model="", cache_root=""))

        assert config.model == "gpt-5"
        assert config.cache_root == "/custom/cache"

    def test_load_config_explicit_false_overrides_file_true(self, write_pyproject) -> None:
        path = write_pyproject(headless=True)

        config = load_config(path, Config(headless=False))

        assert config.headless is False

    def test_load_config_env_value_loses_to_explicit_override(self, write_pyproject, monkeypatch) -> None:
        path = write_pyproject(browser="chromium")
        monkeypatch.setenv("PRETTYPLAY_BROWSER_NAME", "webkit")

        config = load_config(path, Config(browser="firefox"))

        # pyproject → env → PrettyConfig наблюдаемо сквозь всю цепочку
        assert config.browser == "firefox"


class TestLoadConfigNewEnvNames:
    """The two new settings carry env overrides like every other setting."""

    @pytest.mark.parametrize(
        ("env_name", "env_value", "setting"),
        [
            ("PRETTYPLAY_GENERATION_PROMPT", "prefer data-test-id", "generation_prompt"),
            ("PRETTYPLAY_BROWSER_ENDPOINT", "ws://ci-grid:3000/playwright", "browser_endpoint"),
        ],
        ids=["generation_prompt", "browser_endpoint"],
    )
    def test_env_override_exists_for_every_new_setting(
        self, write_pyproject, monkeypatch, env_name: str, env_value: str, setting: str
    ) -> None:
        path = write_pyproject(model="gpt-5")
        monkeypatch.setenv(env_name, env_value)

        config = load_config(path)

        assert getattr(config, setting) == env_value

    def test_invalid_endpoint_env_renders_allowed_values(self, write_pyproject, monkeypatch) -> None:
        path = write_pyproject(model="gpt-5")
        monkeypatch.setenv("PRETTYPLAY_BROWSER_ENDPOINT", "http://ci-grid:3000")

        with pytest.raises(ConfigurationError) as excinfo:
            load_config(path)

        line = next(line for line in str(excinfo.value).splitlines() if line.startswith("browser_endpoint:"))
        assert line.endswith("allowed: a valid ws/wss URL")
