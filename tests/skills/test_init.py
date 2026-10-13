"""Tests for the packaged skill loader."""

from pathlib import Path

import pytest
from prettyplay.skills import load_skill

SKILL_FILE = Path(__file__).resolve().parents[2] / "prettyplay" / "skills" / "playwright" / "SKILL.md"


class TestLoadSkill:
    """Load packaged references and reject missing skill names."""

    def test_the_loader_reads_the_packaged_file(self) -> None:
        assert load_skill("playwright") == SKILL_FILE.read_text(encoding="utf-8")
        assert "strict mode" in load_skill("playwright")

    def test_a_missing_skill_name_raises_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_skill("no-such-skill")
