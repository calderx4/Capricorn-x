"""
Tests for capabilities/skills/loader.py — SkillLoader
"""

from pathlib import Path

import pytest

from capabilities.skills.loader import SkillLoader


class TestSkillLoaderLoad:
    def test_loads_valid_skill_md(self, tmp_path):
        skill_dir = tmp_path / "coding"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: coding\n"
            "description: Coding assistant\n"
            "available: true\n"
            "autoload: true\n"
            "---\n\n"
            "You are an expert coder.\n",
            encoding="utf-8",
        )
        data = SkillLoader.load(skill_file)
        assert data["name"] == "coding"
        assert data["description"] == "Coding assistant"
        assert data["available"] is True
        assert data["autoload"] is True
        assert "expert coder" in data["content"]

    def test_loads_skill_without_frontmatter(self, tmp_path):
        skill_dir = tmp_path / "simple"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("Just plain content.\n", encoding="utf-8")
        data = SkillLoader.load(skill_file)
        # name falls back to parent dir name
        assert data["name"] == "simple"
        assert data["content"].strip() == "Just plain content."
        assert data["available"] is False

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            SkillLoader.load(tmp_path / "nonexistent.md")

    def test_invalid_yaml_falls_back(self, tmp_path):
        skill_dir = tmp_path / "broken"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\n: invalid yaml [([\n---\nFallback content.\n",
            encoding="utf-8",
        )
        data = SkillLoader.load(skill_file)
        # Should fall back to plain content mode
        assert data["name"] == "broken"

    def test_available_default_false(self, tmp_path):
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\nname: test\n---\nContent.\n",
            encoding="utf-8",
        )
        data = SkillLoader.load(skill_file)
        assert data["available"] is False

    def test_autoload_default_false(self, tmp_path):
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\nname: test\n---\nContent.\n",
            encoding="utf-8",
        )
        data = SkillLoader.load(skill_file)
        assert data["autoload"] is False

    def test_path_stored(self, tmp_path):
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("---\nname: test\n---\nContent.\n", encoding="utf-8")
        data = SkillLoader.load(skill_file)
        assert data["path"] == str(skill_file)


class TestSkillLoaderGetSummary:
    def test_generates_xml_summary(self):
        skill_data = {
            "name": "pdf-gen",
            "description": "Generate PDFs",
        }
        summary = SkillLoader.get_summary(skill_data)
        assert '<skill name="pdf-gen">' in summary
        assert "<description>Generate PDFs</description>" in summary
        assert "</skill>" in summary

    def test_missing_name_uses_unknown(self):
        skill_data = {"description": "No name skill"}
        summary = SkillLoader.get_summary(skill_data)
        assert '<skill name="unknown">' in summary


class TestSkillLoaderFindSkillFile:
    def test_finds_uppercase_skill_md(self, tmp_path):
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("content", encoding="utf-8")
        result = SkillLoader.find_skill_file(skill_dir)
        assert result is not None
        assert result.name == "SKILL.md"

    def test_finds_lowercase_skill_md(self, tmp_path):
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        (skill_dir / "skill.md").write_text("content", encoding="utf-8")
        result = SkillLoader.find_skill_file(skill_dir)
        assert result is not None
        assert result.name.lower() == "skill.md"

    def test_returns_none_when_no_file(self, tmp_path):
        skill_dir = tmp_path / "empty"
        skill_dir.mkdir()
        result = SkillLoader.find_skill_file(skill_dir)
        assert result is None

    def test_uppercase_takes_priority(self, tmp_path):
        skill_dir = tmp_path / "priority"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("upper", encoding="utf-8")
        (skill_dir / "skill.md").write_text("lower", encoding="utf-8")
        result = SkillLoader.find_skill_file(skill_dir)
        assert result.name == "SKILL.md"
