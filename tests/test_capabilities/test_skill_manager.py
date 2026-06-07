"""
Tests for capabilities/skills/manager.py — SkillManager
"""

from pathlib import Path

import pytest

from capabilities.skills.manager import SkillManager


def _create_skill(tmp_path, dir_name, content="Skill content.", **frontmatter):
    """Helper: create a skill directory with SKILL.md."""
    skill_dir = tmp_path / dir_name
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    if frontmatter:
        fm_lines = ["---"]
        for k, v in frontmatter.items():
            fm_lines.append(f"{k}: {v}")
        fm_lines.append("---")
        fm_lines.append("")
        fm_lines.append(content)
        skill_file.write_text("\n".join(fm_lines), encoding="utf-8")
    else:
        skill_file.write_text(content, encoding="utf-8")
    return skill_dir


class TestLoadDir:
    def test_loads_skills_from_directory(self, tmp_path):
        _create_skill(tmp_path, "coding", name="coding", available=True)
        _create_skill(tmp_path, "deploy", name="deploy", available=True)
        mgr = SkillManager(skills_dir=str(tmp_path))
        assert sorted(mgr.list_skills()) == ["coding", "deploy"]

    def test_skips_non_dirs(self, tmp_path):
        (tmp_path / "readme.txt").write_text("not a dir", encoding="utf-8")
        _create_skill(tmp_path, "valid", name="valid")
        mgr = SkillManager(skills_dir=str(tmp_path))
        assert mgr.list_skills() == ["valid"]

    def test_skips_dir_without_skill_md(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        _create_skill(tmp_path, "valid", name="valid")
        mgr = SkillManager(skills_dir=str(tmp_path))
        assert mgr.list_skills() == ["valid"]

    def test_nonexistent_dir_noop(self, tmp_path):
        mgr = SkillManager(skills_dir=str(tmp_path / "nonexistent"))
        assert mgr.list_skills() == []

    def test_skill_without_name_skipped(self, tmp_path):
        """Skill without 'name' in frontmatter uses directory name as fallback."""
        skill_dir = tmp_path / "no_name"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Just content, no frontmatter.", encoding="utf-8")
        # No frontmatter → name falls back to directory name
        mgr = SkillManager(skills_dir=str(tmp_path))
        assert "no_name" in mgr.list_skills()


class TestListSkills:
    def test_empty_returns_empty_list(self):
        mgr = SkillManager()
        assert mgr.list_skills() == []

    def test_returns_all_names(self, tmp_path):
        _create_skill(tmp_path, "a", name="alpha")
        _create_skill(tmp_path, "b", name="beta")
        mgr = SkillManager(skills_dir=str(tmp_path))
        assert sorted(mgr.list_skills()) == ["alpha", "beta"]


class TestLoadSkill:
    def test_existing_returns_content(self, tmp_path):
        _create_skill(tmp_path, "test", name="test")
        mgr = SkillManager(skills_dir=str(tmp_path))
        content = mgr.load_skill("test")
        assert "Skill content" in content

    def test_nonexistent_returns_error(self):
        mgr = SkillManager()
        result = mgr.load_skill("nope")
        assert "Error" in result


class TestGetAvailableSkills:
    def test_filters_to_available_true(self, tmp_path):
        _create_skill(tmp_path, "a", name="alpha", available=True)
        _create_skill(tmp_path, "b", name="beta", available=False)
        _create_skill(tmp_path, "c", name="gamma", available=True)
        mgr = SkillManager(skills_dir=str(tmp_path))
        available = mgr.get_available_skills()
        assert sorted(available.keys()) == ["alpha", "gamma"]

    def test_empty_when_none_available(self, tmp_path):
        _create_skill(tmp_path, "a", name="alpha", available=False)
        mgr = SkillManager(skills_dir=str(tmp_path))
        assert mgr.get_available_skills() == {}


class TestGetAutoloadSkills:
    def test_filters_to_autoload_true(self, tmp_path):
        _create_skill(tmp_path, "a", name="alpha", autoload=True)
        _create_skill(tmp_path, "b", name="beta", autoload=False)
        mgr = SkillManager(skills_dir=str(tmp_path))
        autoload = mgr.get_autoload_skills()
        assert list(autoload.keys()) == ["alpha"]

    def test_empty_when_none_autoload(self, tmp_path):
        _create_skill(tmp_path, "a", name="alpha")
        mgr = SkillManager(skills_dir=str(tmp_path))
        assert mgr.get_autoload_skills() == {}
