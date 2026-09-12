"""Tests for the load_config routine of the prettyplay.config cell."""

import inspect
from pathlib import Path

import pytest
from prettyplay.config import BrowserConfig, Config, ConfigurationError, PrettyConfig, load_config
from prettyplay.config import loader as _loader
from prettyplay.failures import PrettyplayError
from pydantic import ValidationError

#: Every PRETTYPLAY_* override the loader reads; tests neutralize ambient values.
_ALL_ENV_FIELDS = (
    "PROVIDER",
    "BROWSER_NAME",
    "BROWSER_SCREEN",
    "BROWSER_HEADLESS",
    "BROWSER_ENDPOINT",
    "BROWSER_ACCEPT_DIALOGS",
    "MODEL",
    "GENERATION_MODEL",
    "CLASSIFICATION_MODEL",
    "BASE_URL",
    "CACHE_ROOT",
    "GENERATION_ATTEMPTS",
    "HEALING_ATTEMPTS",
    "SEND_SCREENSHOTS",
    "GENERATION_PROMPT",
    "CLASSIFICATION_PROMPT",
    "STRICT",
    "POLLING_TIMEOUT",
    "POLLING_DELAY",
    "INTERACTIVE",
    "BROWSER",
)


@pytest.fixture(autouse=True)
def no_ambient_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize ambient PRETTYPLAY_* variables: loader tests stay deterministic."""
    for field in _ALL_ENV_FIELDS:
        monkeypatch.delenv(f"PRETTYPLAY_{field}", raising=False)


def write_section(tmp_path, body: str):
    """Write a raw ``[tool.prettyplay]`` TOML body into a tmp pyproject.toml; return its path."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(body, encoding="utf-8")
    return str(pyproject)


PYPROJECT_WITH_SECTION = """\
[tool.prettyplay]
provider = "openai"
model = "gpt-5"

[tool.prettyplay.browser]
name = "chromium"
"""

PYPROJECT_WITHOUT_SECTION = """\
[project]
name = "sandbox"
"""

#: A browser group without the dialog switch — the env layer supplies it.
PYPROJECT_WITH_BROWSER_GROUP = """\
[tool.prettyplay]
model = "m"

[tool.prettyplay.browser]
name = "chromium"
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
        monkeypatch.chdir(tmp_path)  # auto-discovery is deterministic: cwd contains pyproject.toml

        assert load_config(pyproject_path=None).provider == "openai"
        assert load_config(pyproject_path=str(pyproject)).browser.name == "chromium"

    def test_signature_parameters_are_path_and_overrides(self) -> None:
        """Both parameters are optional; single-argument calls keep working."""
        parameters = inspect.signature(load_config).parameters

        assert list(parameters) == ["pyproject_path", "overrides"]
        assert parameters["pyproject_path"].default is None
        assert parameters["overrides"].default is None

    def test_every_setting_has_an_env_override(self) -> None:
        """Every scalar setting and every browser-group field maps to a PRETTYPLAY_* variable."""
        expected = {
            "PRETTYPLAY_PROVIDER",
            "PRETTYPLAY_MODEL",
            "PRETTYPLAY_GENERATION_MODEL",
            "PRETTYPLAY_CLASSIFICATION_MODEL",
            "PRETTYPLAY_BASE_URL",
            "PRETTYPLAY_CACHE_ROOT",
            "PRETTYPLAY_GENERATION_PROMPT",
            "PRETTYPLAY_CLASSIFICATION_PROMPT",
            "PRETTYPLAY_STRICT",
            "PRETTYPLAY_POLLING_TIMEOUT",
            "PRETTYPLAY_POLLING_DELAY",
            "PRETTYPLAY_INTERACTIVE",
            "PRETTYPLAY_GENERATION_ATTEMPTS",
            "PRETTYPLAY_HEALING_ATTEMPTS",
            "PRETTYPLAY_SEND_SCREENSHOTS",
            "PRETTYPLAY_BROWSER_NAME",
            "PRETTYPLAY_BROWSER_SCREEN",
            "PRETTYPLAY_BROWSER_HEADLESS",
            "PRETTYPLAY_BROWSER_ENDPOINT",
            "PRETTYPLAY_BROWSER_ACCEPT_DIALOGS",
        }

        values = set(_loader._ENV_NAMES.values())

        assert expected <= values  # every setting present — all five browser variables included
        # one entry per top-level scalar field (the group itself excluded) plus per group field
        wired = [name for name in Config.model_fields if name != "browser"]
        assert len(_loader._ENV_NAMES) == len(wired) + len(BrowserConfig.model_fields)

    def test_loader_accepts_polling_and_interactive_env(self, write_pyproject, monkeypatch) -> None:
        """Contract: the three settings carry env overrides the loader parses by field type."""
        monkeypatch.setenv("PRETTYPLAY_POLLING_TIMEOUT", "8")
        monkeypatch.setenv("PRETTYPLAY_POLLING_DELAY", "0.25")
        monkeypatch.setenv("PRETTYPLAY_INTERACTIVE", "true")

        config = load_config(pyproject_path=write_pyproject())

        assert config.polling_timeout == 8.0
        assert config.polling_delay == 0.25
        assert config.interactive is True

    def test_polling_and_interactive_load_from_the_file_layer(self, write_pyproject) -> None:
        """The three settings validate straight from the [tool.prettyplay] section — no env, no override."""
        path = write_pyproject(polling_timeout=6.0, polling_delay=0.25, interactive=True)

        config = load_config(pyproject_path=path)

        assert config.polling_timeout == 6.0
        assert config.polling_delay == 0.25
        assert config.interactive is True


class TestLoadConfigLogic:
    """Logic tests: section reading, env overrides, loud failures, defaults."""

    def test_load_config_reads_section_and_env_overrides(self, tmp_path, monkeypatch) -> None:
        path = write_section(tmp_path, PYPROJECT_WITH_SECTION)

        monkeypatch.chdir(tmp_path)  # the empty cache_root anchors at the run's working directory
        monkeypatch.setenv("PRETTYPLAY_BROWSER_NAME", "firefox")
        monkeypatch.setenv("PRETTYPLAY_GENERATION_ATTEMPTS", "5")

        config = load_config(pyproject_path=path)

        assert config.model == "gpt-5"
        assert config.browser.name == "firefox"  # env overrides the TOML group
        assert config.generation_attempts == 5  # the loader parses the decimal int
        assert config.cache_root == str(tmp_path / ".prettyplay" / "cache")

    def test_load_env_browser_name_and_headless(self, tmp_path, monkeypatch) -> None:
        """The flat group env names override the group; bool strings parse in the loader."""
        path = write_section(tmp_path, PYPROJECT_WITH_SECTION)

        monkeypatch.setenv("PRETTYPLAY_BROWSER_NAME", "firefox")
        monkeypatch.setenv("PRETTYPLAY_BROWSER_HEADLESS", "false")

        config = load_config(pyproject_path=path)

        assert config.browser.name == "firefox"
        assert config.browser.headless is False  # "false" parses before pydantic sees it

    def test_load_config_reads_browser_group_and_rejects_flat_keys(self, tmp_path) -> None:
        """Positive: the TOML group reaches the nested model field by field."""
        path = write_section(
            tmp_path,
            '[tool.prettyplay]\nprovider = "openai"\n'
            "\n[tool.prettyplay.browser]\n"
            'name = "firefox"\n'
            'screen = "fullscreen"\n'
            "headless = false\n"
            'endpoint = ""\n',
        )

        config = load_config(pyproject_path=path)

        assert config.browser.name == "firefox"
        assert config.browser.screen == "fullscreen"
        assert config.browser.headless is False
        assert config.provider == "openai"

    def test_load_config_env_overrides_reach_the_group_and_new_settings(self, tmp_path, monkeypatch) -> None:
        """Positive: group env overrides win per field; the new settings parse their bools."""
        path = write_section(
            tmp_path,
            '[tool.prettyplay]\nmodel = "gpt-5"\n\n[tool.prettyplay.browser]\nname = "chromium"\nscreen = ""\n',
        )

        monkeypatch.setenv("PRETTYPLAY_BROWSER_NAME", "webkit")
        monkeypatch.setenv("PRETTYPLAY_BROWSER_SCREEN", "1280x720")
        monkeypatch.setenv("PRETTYPLAY_STRICT", "true")
        monkeypatch.setenv("PRETTYPLAY_CLASSIFICATION_PROMPT", "be terse")
        monkeypatch.setenv("PRETTYPLAY_BROWSER_HEADLESS", "0")

        config = load_config(pyproject_path=path)

        assert config.browser.name == "webkit"
        assert config.browser.screen == "1280x720"
        assert config.browser.headless is False  # "0" parses to False
        assert config.strict is True  # "true" parses to True
        assert config.classification_prompt == "be terse"

    def test_load_config_rejects_each_old_flat_key(self, tmp_path) -> None:
        """Negative: one line per removed flat key; a browser TABLE is the group, not a flat key."""
        cases = {
            "browser": '[tool.prettyplay]\nbrowser = "chromium"\n',
            "headless": "[tool.prettyplay]\nheadless = true\n",
            "browser_endpoint": '[tool.prettyplay]\nbrowser_endpoint = "ws://x"\n',
        }
        for key, body in cases.items():
            with pytest.raises(ConfigurationError) as excinfo:
                load_config(pyproject_path=write_section(tmp_path, body))

            message = str(excinfo.value)
            assert key in message
            assert "[tool.prettyplay.browser]" in message

        # all three present — one line per key
        with pytest.raises(ConfigurationError) as excinfo:
            load_config(
                pyproject_path=write_section(
                    tmp_path, '[tool.prettyplay]\nbrowser = "c"\nheadless = true\nbrowser_endpoint = "ws://x"\n'
                )
            )

        assert str(excinfo.value).count("\n") == 2  # three lines, one per key

        # a browser key holding a TABLE is the nested group — not a flat key
        config = load_config(pyproject_path=write_section(tmp_path, '[tool.prettyplay.browser]\nname = "firefox"\n'))

        assert config.browser.name == "firefox"

    def test_load_config_rejects_empty_browser_name_from_file_and_env(self, tmp_path, monkeypatch) -> None:
        """Negative: an empty name is an invalid value in the file/env layer, not an unset."""
        with pytest.raises(ConfigurationError) as excinfo:
            load_config(pyproject_path=write_section(tmp_path, '[tool.prettyplay.browser]\nname = ""\n'))

        assert str(excinfo.value).splitlines() == [
            "browser.name: received '' — allowed: chromium, firefox, webkit, chrome, msedge"
        ]

        # an empty env override of a valid file name fails identically
        path = write_section(tmp_path, '[tool.prettyplay.browser]\nname = "firefox"\n')
        monkeypatch.setenv("PRETTYPLAY_BROWSER_NAME", "")

        with pytest.raises(ConfigurationError) as excinfo:
            load_config(pyproject_path=path)

        assert str(excinfo.value).startswith("browser.name: received '' — allowed: chromium")

    def test_load_config_rejects_unknown_keys(self, tmp_path) -> None:
        """Negative: a key outside the schema fails loudly — no silent drop, no pydantic internals."""
        with pytest.raises(ConfigurationError) as excinfo:
            load_config(pyproject_path=write_section(tmp_path, '[tool.prettyplay]\nmodle = "gpt-5"\n'))

        assert str(excinfo.value).splitlines() == ["modle: received 'gpt-5' — not a prettyplay setting"]

        with pytest.raises(ConfigurationError) as excinfo:
            load_config(pyproject_path=write_section(tmp_path, '[tool.prettyplay.browser]\nnmae = "firefox"\n'))

        assert str(excinfo.value).splitlines() == ["browser.nmae: received 'firefox' — not a prettyplay setting"]

    def test_pretty_config_rejects_removed_flat_fields_loudly(self) -> None:
        """Negative: the removed 0.0.x flat names fail at construction — never a silent no-op."""
        with pytest.raises(ValidationError):
            Config(headless=False)

        with pytest.raises(ValidationError):
            Config(browser_endpoint="ws://x")

        with pytest.raises(ValidationError):
            BrowserConfig(engine="chromium")

    def test_load_config_env_scalar_parse_failures(self, tmp_path, monkeypatch) -> None:
        """Negative: unparseable env values fail loudly naming setting, value and form."""
        cases = [
            ("PRETTYPLAY_STRICT", "maybe", "strict: received 'maybe' — allowed: a boolean (true/false/1/0)"),
            (
                "PRETTYPLAY_BROWSER_HEADLESS",
                "yes",
                "browser.headless: received 'yes' — allowed: a boolean (true/false/1/0)",
            ),
            (
                "PRETTYPLAY_GENERATION_ATTEMPTS",
                "three",
                "generation_attempts: received 'three' — allowed: a decimal integer",
            ),
        ]
        for env_name, env_value, expected_line in cases:
            monkeypatch.setenv(env_name, env_value)

            with pytest.raises(ConfigurationError) as excinfo:
                load_config(pyproject_path=write_section(tmp_path, PYPROJECT_WITH_SECTION))

            assert expected_line in str(excinfo.value).splitlines()
            assert isinstance(excinfo.value, PrettyplayError)

            monkeypatch.delenv(env_name)

    def test_configuration_error_wraps_validation_with_lines(self, tmp_path) -> None:
        """A raw ValidationError never leaves the loader; one line names each invalid setting."""
        path = write_section(
            tmp_path, '[tool.prettyplay]\ngeneration_attempts = 0\n\n[tool.prettyplay.browser]\nname = "netscape"\n'
        )

        with pytest.raises(ConfigurationError) as excinfo:
            load_config(pyproject_path=path)

        assert isinstance(excinfo.value, PrettyplayError)
        message = str(excinfo.value)
        assert "browser.name" in message
        assert "netscape" in message
        assert "chromium, firefox, webkit, chrome, msedge" in message
        assert "generation_attempts" in message
        assert message.count("\n") == 1  # exactly two lines, one per setting
        assert isinstance(excinfo.value.__cause__, ValidationError)

    @pytest.mark.parametrize(
        ("env_name", "env_value", "setting", "allowed"),
        [
            ("PRETTYPLAY_BROWSER_HEADLESS", "maybe", "browser.headless", "a boolean (true/false/1/0)"),
            ("PRETTYPLAY_SEND_SCREENSHOTS", "perhaps", "send_screenshots", "a boolean (true/false/1/0)"),
            ("PRETTYPLAY_PROVIDER", "yandex", "provider", "openai, anthropic"),
        ],
        ids=["browser.headless", "send_screenshots", "provider"],
    )
    def test_invalid_setting_renders_allowed_values(  # noqa: PLR0913, PLR0917 — parametrization parameters
        self, tmp_path, monkeypatch, env_name: str, env_value: str, setting: str, allowed: str
    ) -> None:
        """Every overridable setting fails with its own allowed-values line — no pydantic internals."""
        monkeypatch.setenv(env_name, env_value)

        with pytest.raises(ConfigurationError) as excinfo:
            load_config(pyproject_path=write_section(tmp_path, PYPROJECT_WITH_SECTION))

        line = next(line for line in str(excinfo.value).splitlines() if line.startswith(f"{setting}:"))
        assert f"received {env_value!r}" in line
        assert line.endswith(f"allowed: {allowed}")

    def test_legacy_browser_env_raises_configuration_error(self, tmp_path, monkeypatch) -> None:
        """The removed env name fails loudly and names its replacement."""
        monkeypatch.setenv("PRETTYPLAY_BROWSER", "firefox")

        with pytest.raises(ConfigurationError) as excinfo:
            load_config(pyproject_path=write_section(tmp_path, PYPROJECT_WITH_SECTION))

        assert "PRETTYPLAY_BROWSER_NAME" in str(excinfo.value)

    def test_load_config_no_pyproject_fails_loudly(self, monkeypatch) -> None:
        class EmptyTreeRoot:
            """Path stand-in whose directory tree contains no pyproject.toml."""

            parents: tuple[object, ...] = ()

            def __truediv__(self, name: str) -> "EmptyTreeRoot":
                return self

            def is_file(self) -> bool:
                return False

        # deterministic: the upward search sees an empty tree regardless of the
        # host layout around the pytest tmp directory — Path.cwd() constructs it
        monkeypatch.setattr(Path, "cwd", EmptyTreeRoot)

        with pytest.raises(FileNotFoundError) as excinfo:
            load_config(pyproject_path=None)

        assert "pyproject.toml not found" in str(excinfo.value)

    def test_load_config_missing_section_yields_defaults(self, tmp_path) -> None:
        config = load_config(pyproject_path=write_section(tmp_path, PYPROJECT_WITHOUT_SECTION))

        assert config.provider == "openai"
        assert config.generation_attempts == 3
        assert isinstance(config, Config)

    def test_browser_config_validation_failures(self, tmp_path) -> None:
        """Negative: nested locs render dotted; non-WxH screens pass through unresolved."""
        with pytest.raises(ValidationError) as excinfo:
            BrowserConfig(name="opera")
        assert ("name",) in [entry["loc"] for entry in excinfo.value.errors()]

        with pytest.raises(ValidationError) as excinfo:
            BrowserConfig(endpoint="http://x")
        assert ("endpoint",) in [entry["loc"] for entry in excinfo.value.errors()]

        with pytest.raises(ValidationError) as excinfo:
            Config(browser={"screen": "0x720"})
        assert ("browser", "screen") in [entry["loc"] for entry in excinfo.value.errors()]

        # through load_config the rendered line carries the dotted loc
        with pytest.raises(ConfigurationError) as excinfo:
            load_config(pyproject_path=write_section(tmp_path, '[tool.prettyplay.browser]\nname = "opera"\n'))

        assert str(excinfo.value).splitlines()[0].startswith(
            "browser.name: received 'opera' — allowed: chromium, firefox, webkit, chrome, msedge"
        )

        with pytest.raises(ConfigurationError) as excinfo:
            load_config(pyproject_path=write_section(tmp_path, '[tool.prettyplay.browser]\nscreen = "0x720"\n'))

        assert "browser.screen" in str(excinfo.value)
        assert "must be positive" in str(excinfo.value)

        # "fullscreen" and device names pass the format-level check verbatim
        config = load_config(
            pyproject_path=write_section(tmp_path, '[tool.prettyplay.browser]\nscreen = "fullscreen"\n')
        )
        assert config.browser.screen == "fullscreen"

        config = load_config(
            pyproject_path=write_section(tmp_path, '[tool.prettyplay.browser]\nscreen = "iPhone 13"\n')
        )
        assert config.browser.screen == "iPhone 13"


class TestLoadConfigEdge:
    """Edge tests: env set to empty overrides TOML; auto-search finds cwd file."""

    def test_env_set_to_empty_overrides_toml_value(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("PRETTYPLAY_MODEL", "")

        config = load_config(pyproject_path=write_section(tmp_path, PYPROJECT_WITH_SECTION))

        # the variable is set (even if empty) — the override applies
        assert config.model == ""
        assert config.effective_generation_model == ""

    def test_auto_search_finds_pyproject_in_cwd(self, tmp_path, monkeypatch) -> None:
        write_section(tmp_path, PYPROJECT_WITH_SECTION)
        monkeypatch.chdir(tmp_path)

        config = load_config(pyproject_path=None)

        assert config.model == "gpt-5"
        assert config.cache_root == str(tmp_path / ".prettyplay" / "cache")

    def test_empty_cache_root_from_env_overrides_default(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("PRETTYPLAY_CACHE_ROOT", "/custom/cache")

        config = load_config(pyproject_path=write_section(tmp_path, PYPROJECT_WITH_SECTION))

        assert config.cache_root == "/custom/cache"

    def test_default_cache_root_anchors_at_cwd_below_pyproject(self, tmp_path, monkeypatch) -> None:
        """The default anchors at the run's cwd even when the pyproject sits above it."""
        write_section(tmp_path, PYPROJECT_WITH_SECTION)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        monkeypatch.chdir(run_dir)  # auto-search walks up from here and finds tmp_path/

        config = load_config(pyproject_path=None)

        assert config.model == "gpt-5"  # the settings still come from the found pyproject
        assert config.cache_root == str(run_dir / ".prettyplay" / "cache")

    def test_default_cache_root_anchors_at_cwd_with_explicit_pyproject_path(self, tmp_path, monkeypatch) -> None:
        """The default anchors at the run's cwd even when the pyproject is passed explicitly."""
        path = write_section(tmp_path, PYPROJECT_WITH_SECTION)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        monkeypatch.chdir(run_dir)

        config = load_config(pyproject_path=path)

        assert config.model == "gpt-5"
        assert config.cache_root == str(run_dir / ".prettyplay" / "cache")


class TestLoadConfigOverlay:
    """Logic tests: the programmatic layer over pyproject → env (explicit values win)."""

    def test_load_config_overrides_explicit_values_win(self, tmp_path) -> None:
        path = write_section(
            tmp_path,
            '[tool.prettyplay]\nmodel = "gpt-5"\nbase_url = "https://file.example/v1"\n'
            "\n[tool.prettyplay.browser]\nname = \"chromium\"\n",
        )

        config = load_config(
            path,
            Config(browser=BrowserConfig(name="firefox", endpoint="ws://ci-grid:3000/playwright/firefox")),
        )

        assert config.browser.name == "firefox"
        assert config.browser.endpoint == "ws://ci-grid:3000/playwright/firefox"
        assert config.model == "gpt-5"  # untouched file values survive
        assert config.base_url == "https://file.example/v1"

    def test_load_config_without_overrides_returns_file_layer(self, tmp_path) -> None:
        path = write_section(tmp_path, '[tool.prettyplay]\nprovider = "anthropic"\ngeneration_attempts = 5\n')

        assert load_config(path, None).provider == "anthropic"
        assert load_config(path, None).generation_attempts == 5

        # an empty PrettyConfig sets no field — behaves like None
        empty = load_config(path, PrettyConfig())

        assert empty.provider == "anthropic"
        assert empty.generation_attempts == 5
        assert empty.generation_prompt == ""
        assert empty.browser.endpoint == ""

    def test_load_config_renders_actionable_line_for_endpoint(self, tmp_path) -> None:
        path = write_section(tmp_path, '[tool.prettyplay.browser]\nendpoint = "http://bad"\n')

        with pytest.raises(ConfigurationError) as excinfo:
            load_config(path)

        assert "browser.endpoint" in str(excinfo.value)
        assert "ws/wss" in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, ValidationError)

    def test_load_config_empty_string_override_does_not_win(self, tmp_path) -> None:
        path = write_section(tmp_path, '[tool.prettyplay]\ncache_root = "/custom/cache"\nmodel = "gpt-5"\n')

        config = load_config(path, Config(model="", cache_root=""))

        assert config.model == "gpt-5"
        assert config.cache_root == "/custom/cache"

    def test_load_config_explicit_false_overrides_file_true(self, tmp_path) -> None:
        path = write_section(tmp_path, "[tool.prettyplay.browser]\nheadless = true\n")

        config = load_config(path, Config(browser=BrowserConfig(headless=False)))

        assert config.browser.headless is False

    def test_programmatic_accept_dialogs_merges_into_group(self, tmp_path) -> None:
        """The dialog switch follows the group merge: unset skips, an explicit False wins too."""
        path = write_section(tmp_path, "[tool.prettyplay.browser]\naccept_dialogs = true\n")

        # unset override — the file True survives
        config = load_config(path, PrettyConfig(browser=BrowserConfig()))

        assert config.browser.accept_dialogs is True

        # an explicit False participates in the merge — bool is not str, it overrides
        config = load_config(path, PrettyConfig(browser=BrowserConfig(accept_dialogs=False)))

        assert config.browser.accept_dialogs is False

    def test_explicit_zero_and_false_override_the_file_layer(self, write_pyproject) -> None:
        """Explicit disable/off participates in the merge — bools and 0.0 have no empty form."""
        path = write_pyproject(polling_timeout=8.0, interactive=True)

        config = load_config(path, PrettyConfig(polling_timeout=0.0, interactive=False))

        assert config.polling_timeout == 0.0
        assert config.interactive is False

    def test_explicit_none_polling_timeout_is_indistinguishable_from_unset(self, write_pyproject) -> None:
        """A passed None skips the merge — indistinguishable from never passing the field."""
        path = write_pyproject(polling_timeout=8.0)

        config = load_config(path, PrettyConfig(polling_timeout=None))

        assert config.polling_timeout == 8.0

    def test_explicit_polling_delay_overrides_the_file_layer(self, write_pyproject) -> None:
        """A per-test polling_delay participates in the merge like every explicit scalar."""
        path = write_pyproject(polling_delay=0.25)

        config = load_config(path, PrettyConfig(polling_delay=1.5))

        assert config.polling_delay == 1.5

    def test_load_config_env_value_loses_to_explicit_override(self, tmp_path, monkeypatch) -> None:
        path = write_section(tmp_path, '[tool.prettyplay.browser]\nname = "chromium"\n')
        monkeypatch.setenv("PRETTYPLAY_BROWSER_NAME", "webkit")

        config = load_config(path, Config(browser=BrowserConfig(name="firefox")))

        # pyproject → env → PrettyConfig observable through the whole chain
        assert config.browser.name == "firefox"

    def test_load_config_nested_group_merge_matrix(self, tmp_path) -> None:
        """Edge: the overlay reaches inside the group; untouched defaults never overwrite."""
        group_path = write_section(
            tmp_path,
            '[tool.prettyplay]\nstrict = true\n\n[tool.prettyplay.browser]\nname = "firefox"\nheadless = false\n',
        )

        # (a) set group fields win; untouched file values survive
        config = load_config(group_path, PrettyConfig(browser=BrowserConfig(screen="fullscreen")))
        assert config.browser.name == "firefox"
        assert config.browser.screen == "fullscreen"
        assert config.browser.headless is False

        # (b) an untouched default group never overwrites the file group
        config = load_config(group_path, PrettyConfig(browser=BrowserConfig()))
        assert config.browser.name == "firefox"
        assert config.browser.headless is False
        assert config.browser.screen == ""

        # (c) an explicit False overrides the file value too
        config = load_config(group_path, PrettyConfig(strict=False))
        assert config.strict is False

        # (d) an empty string inside the group means unset as well
        config = load_config(group_path, PrettyConfig(browser=BrowserConfig(name="")))
        assert config.browser.name == "firefox"


class TestLoadConfigNewEnvNames:
    """The new settings carry env overrides like every other setting."""

    @pytest.mark.parametrize(
        ("env_name", "env_value"),
        [
            ("PRETTYPLAY_GENERATION_PROMPT", "prefer data-test-id"),
            ("PRETTYPLAY_BROWSER_ENDPOINT", "ws://ci-grid:3000/playwright"),
        ],
        ids=["generation_prompt", "browser.endpoint"],
    )
    def test_env_override_exists_for_every_new_setting(
        self, tmp_path, monkeypatch, env_name: str, env_value: str
    ) -> None:
        monkeypatch.setenv(env_name, env_value)

        config = load_config(pyproject_path=write_section(tmp_path, '[tool.prettyplay]\nmodel = "gpt-5"\n'))

        if env_name == "PRETTYPLAY_GENERATION_PROMPT":
            assert config.generation_prompt == env_value
        else:
            assert config.browser.endpoint == env_value

    def test_invalid_endpoint_env_renders_allowed_values(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("PRETTYPLAY_BROWSER_ENDPOINT", "http://ci-grid:3000")

        with pytest.raises(ConfigurationError) as excinfo:
            load_config(pyproject_path=write_section(tmp_path, '[tool.prettyplay]\nmodel = "gpt-5"\n'))

        line = next(line for line in str(excinfo.value).splitlines() if line.startswith("browser.endpoint:"))
        assert line.endswith("allowed: a valid ws/wss URL")

    @pytest.mark.parametrize(
        ("env_value", "expected"),
        [("true", True), ("1", True), ("false", False), ("0", False)],
        ids=["true", "one", "false", "zero"],
    )
    def test_env_override_parses_accept_dialogs_by_type(
        self, tmp_path, monkeypatch, env_value: str, expected: bool
    ) -> None:
        """The dialog switch parses as a boolean by its field type — like browser.headless."""
        path = write_section(tmp_path, PYPROJECT_WITH_BROWSER_GROUP)

        monkeypatch.setenv("PRETTYPLAY_BROWSER_ACCEPT_DIALOGS", env_value)

        config = load_config(pyproject_path=path)

        assert config.browser.accept_dialogs is expected

    def test_env_override_rejects_unparseable_accept_dialogs(self, tmp_path, monkeypatch) -> None:
        """Negative: a bool-like-but-unparseable value fails loudly — never a silent ignore."""
        path = write_section(tmp_path, PYPROJECT_WITH_BROWSER_GROUP)
        monkeypatch.setenv("PRETTYPLAY_BROWSER_ACCEPT_DIALOGS", "yes")

        with pytest.raises(ConfigurationError) as excinfo:
            load_config(pyproject_path=path)

        assert "browser.accept_dialogs: received 'yes' — allowed: a boolean (true/false/1/0)" in str(
            excinfo.value
        ).splitlines()
        assert isinstance(excinfo.value, PrettyplayError)

    def test_load_config_env_parses_polling_and_interactive(self, write_pyproject, monkeypatch) -> None:
        """Positive: the polling floats and the interactive bool parse from their env variables."""
        monkeypatch.setenv("PRETTYPLAY_POLLING_TIMEOUT", "8")
        monkeypatch.setenv("PRETTYPLAY_POLLING_DELAY", "0.25")
        monkeypatch.setenv("PRETTYPLAY_INTERACTIVE", "true")

        config = load_config(pyproject_path=write_pyproject())

        assert config.polling_timeout == 8.0
        assert config.polling_delay == 0.25
        assert config.interactive is True

        # boundary row: the explicit disable parses to the float zero, not None
        monkeypatch.setenv("PRETTYPLAY_POLLING_TIMEOUT", "0")

        config = load_config(pyproject_path=write_pyproject())

        assert config.polling_timeout == 0.0

    @pytest.mark.parametrize(
        ("raw", "expected_fragments"),
        [
            ("soon", ("polling_timeout", "received 'soon'", "a decimal float")),
            ("inf", ("polling_timeout", "inf", "non-negative")),
        ],
        ids=["unparseable", "non-finite"],
    )
    def test_load_config_env_rejects_unparseable_float(
        self, write_pyproject, monkeypatch, raw: str, expected_fragments: tuple[str, ...]
    ) -> None:
        """Negative: 'soon' dies in the float parser; 'inf' parses then dies in the validator."""
        monkeypatch.setenv("PRETTYPLAY_POLLING_TIMEOUT", raw)

        with pytest.raises(ConfigurationError) as excinfo:
            load_config(pyproject_path=write_pyproject())

        message = str(excinfo.value)
        for fragment in expected_fragments:
            assert fragment in message
        assert isinstance(excinfo.value, PrettyplayError)
