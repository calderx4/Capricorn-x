"""
Tests for core/prompt_utils.py
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.prompt_utils import (
    build_prompt,
    build_tools_section,
    build_skills_section,
    build_memory_section,
    build_bia_section,
    LAYER_DESC_MAP,
)


class TestBuildPrompt:
    def test_replaces_placeholders(self, prompt_template):
        result = build_prompt(
            prompt_template,
            workspace_section="WS",
            tools_section="TOOLS",
            skills_section="SK",
            memory_section="MEM",
            bia_section="BIA",
            agent_md_section="AGENT",
            task_prompt="TASK",
            current_time="2026-01-01",
        )
        assert "WS" in result
        assert "TOOLS" in result
        assert "SK" in result
        assert "MEM" in result
        assert "BIA" in result
        assert "AGENT" in result
        assert "TASK" in result
        assert "2026-01-01" in result

    def test_missing_template_raises(self):
        with pytest.raises(FileNotFoundError):
            build_prompt("/nonexistent/template.md")

    def test_escapes_user_braces(self, prompt_template):
        result = build_prompt(
            prompt_template,
            workspace_section="content with {{dangerous}} braces",
            tools_section="",
            skills_section="",
            memory_section="",
            bia_section="",
            agent_md_section="",
            task_prompt="",
            current_time="now",
        )
        # Escaped braces should be restored as literal {{ }}
        assert "{{dangerous}}" in result

    def test_collapses_triple_newlines(self, tmp_path):
        template = tmp_path / "system.md"
        template.write_text("A\n\n\n\nB", encoding="utf-8")
        result = build_prompt(str(template))
        assert "\n\n\n" not in result

    def test_warns_on_unreplaced_placeholders(self, tmp_path):
        template = tmp_path / "system.md"
        template.write_text("hello {{unknown_section}} world", encoding="utf-8")
        # Should not crash — just logs a warning
        result = build_prompt(str(template))
        assert "hello" in result
        assert "world" in result

    def test_empty_section_replaces_with_empty(self, prompt_template):
        result = build_prompt(
            prompt_template,
            workspace_section="",
            tools_section="",
            skills_section="",
            memory_section="",
            bia_section="",
            agent_md_section="",
            task_prompt="",
            current_time="",
        )
        assert "{{" not in result or "<<" in result  # no unreplaced placeholders

    def test_multiple_sections_all_replaced(self, prompt_template):
        result = build_prompt(
            prompt_template,
            workspace_section="ws",
            tools_section="ts",
            skills_section="ss",
            memory_section="ms",
            bia_section="bs",
            agent_md_section="as",
            task_prompt="tp",
            current_time="ct",
        )
        # No {{word}} patterns should remain
        import re
        unreplaced = re.findall(r"\{\{\w+\}\}", result.replace("<<", "").replace(">>", ""))
        assert unreplaced == []


class TestBuildToolsSection:
    def test_returns_empty_when_none_registry(self):
        assert build_tools_section(None) == ""

    def test_returns_empty_when_no_tools(self, mock_capability_registry):
        result = build_tools_section(mock_capability_registry)
        assert result == ""

    def test_formats_tools_by_layer(self):
        reg = MagicMock()
        tool = MagicMock()
        tool.description = "reads files"
        tool.name = "read_file"
        reg.tools.list_by_layer.return_value = {
            "builtin": ["read_file"],
            "mcp": [],
            "workflow": [],
        }
        reg.tools.get.return_value = tool
        result = build_tools_section(reg)
        assert "read_file" in result
        assert "reads files" in result
        assert "# Available Tools" in result

    def test_uses_layer_descriptions(self):
        reg = MagicMock()
        tool = MagicMock()
        tool.description = "test tool"
        reg.tools.list_by_layer.return_value = {
            "tools": ["test_tool"],
            "mcp": [],
        }
        reg.tools.get.return_value = tool
        result = build_tools_section(reg)
        assert "原子操作" in result  # from LAYER_DESC_MAP["tools"]

    def test_tool_not_found_still_listed(self):
        reg = MagicMock()
        reg.tools.list_by_layer.return_value = {
            "builtin": ["missing_tool"],
            "mcp": [],
            "workflow": [],
        }
        reg.tools.get.return_value = None
        result = build_tools_section(reg)
        assert "missing_tool" in result

    def test_no_list_by_layer_method(self):
        reg = MagicMock()
        del reg.tools.list_by_layer
        result = build_tools_section(reg)
        assert result == ""


class TestBuildSkillsSection:
    def test_returns_empty_when_none_manager(self):
        assert build_skills_section(None) == ""

    def test_returns_empty_when_no_skills(self, mock_skill_manager):
        result = build_skills_section(mock_skill_manager)
        assert result == ""

    def test_includes_autoload_skills_content(self):
        mgr = MagicMock()
        mgr.list_skills.return_value = ["coding"]
        mgr.get_autoload_skills.return_value = {
            "coding": {"content": "You are a coding expert.", "autoload": True},
        }
        mgr.get_available_skills.return_value = {}
        result = build_skills_section(mgr)
        assert "coding" in result
        assert "coding expert" in result

    def test_includes_on_demand_skills(self):
        mgr = MagicMock()
        mgr.list_skills.return_value = ["pdf"]
        mgr.get_autoload_skills.return_value = {}
        mgr.get_available_skills.return_value = {
            "minimax-pdf": {
                "name": "minimax-pdf",
                "description": "PDF generation",
                "available": True,
            },
        }
        result = build_skills_section(mgr)
        assert "<skills>" in result
        assert "minimax-pdf" in result

    def test_mixed_autoload_and_on_demand(self):
        mgr = MagicMock()
        mgr.list_skills.return_value = ["coding", "pdf"]
        mgr.get_autoload_skills.return_value = {
            "coding": {"content": "Expert coder.", "autoload": True},
        }
        mgr.get_available_skills.return_value = {
            "pdf-tool": {
                "name": "pdf-tool",
                "description": "PDF tool",
                "available": True,
            },
        }
        result = build_skills_section(mgr)
        assert "coding" in result
        assert "pdf-tool" in result

    def test_no_list_skills_method(self):
        mgr = MagicMock()
        del mgr.list_skills
        result = build_skills_section(mgr)
        assert result == ""


class TestBuildMemorySection:
    def test_returns_empty_when_none(self):
        assert build_memory_section(None) == ""

    def test_returns_empty_when_empty_read(self, mock_long_term_memory):
        result = build_memory_section(mock_long_term_memory)
        assert result == ""

    def test_returns_formatted_content(self):
        mem = MagicMock()
        mem.read.return_value = "User prefers Python over Java."
        result = build_memory_section(mem)
        assert "# Long-term Memory" in result
        assert "Python" in result


class TestBuildBiaSection:
    def test_returns_empty_when_empty_path(self):
        assert build_bia_section("") == ""

    def test_returns_empty_when_file_missing(self, tmp_path):
        assert build_bia_section(str(tmp_path / "nonexistent.md")) == ""

    def test_returns_empty_when_empty_content(self, tmp_path):
        bia_file = tmp_path / "bia.md"
        bia_file.write_text("   \n  \n", encoding="utf-8")
        assert build_bia_section(str(bia_file)) == ""

    def test_returns_formatted_content(self, tmp_path):
        bia_file = tmp_path / "bia.md"
        bia_file.write_text("Always use type hints.", encoding="utf-8")
        result = build_bia_section(str(bia_file))
        assert "# Behavioral Corrections" in result
        assert "type hints" in result
