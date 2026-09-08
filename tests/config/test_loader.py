"""Tests for the load_config routine of the prettyplay.config cell."""

import pytest
from prettyplay.config import Config, load_config

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

    def test_signature_accepts_none_and_str_path(self) -> None:
        assert load_config(pyproject_path=None).provider == "openai"
        assert load_config(pyproject_path=None).browser == "chromium"


class TestLoadConfigLogic:
    """Logic tests: section reading, env overrides, loud failures, defaults."""

    def test_load_config_reads_section_and_env_overrides(self, tmp_path, monkeypatch) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(PYPROJECT_WITH_SECTION, encoding="utf-8")

        monkeypatch.setenv("PRETTYPLAY_BROWSER", "firefox")
        monkeypatch.setenv("PRETTYPLAY_GENERATION_ATTEMPTS", "5")

        config = load_config(pyproject_path=str(pyproject))

        assert config.model == "gpt-5"
        assert config.browser == "firefox"  # env перекрывает TOML
        assert config.generation_attempts == 5  # str→int коэрсия
        assert config.cache_root == str(tmp_path / ".prettyplay" / "cache")

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
