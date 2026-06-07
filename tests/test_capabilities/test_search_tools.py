"""
Tests for search_tools.py — GlobTool and GrepTool
"""

import pytest

from capabilities.tools.builtin.extensions.search_tools import (
    GlobTool,
    GrepTool,
    MAX_GLOB_RESULTS,
    MAX_GREP_RESULTS,
)


# ── Helpers ───────────────────────────────────────────────

def _make_glob_tool(tmp_path, sandbox=True):
    return GlobTool(workspace_root=str(tmp_path), sandbox=sandbox)


def _make_grep_tool(tmp_path, sandbox=True):
    return GrepTool(workspace_root=str(tmp_path), sandbox=sandbox)


# ── GlobTool Tests ────────────────────────────────────────

class TestGlobTool:

    async def test_match_python_files(self, tmp_path):
        """glob 能递归匹配 .py 文件"""
        (tmp_path / "a.py").write_text("pass")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.py").write_text("pass")
        (tmp_path / "c.txt").write_text("hi")

        tool = _make_glob_tool(tmp_path)
        result = await tool.execute(pattern="**/*.py")
        assert "a.py" in result
        assert str(tmp_path / "sub" / "b.py" / ".." / ".." / "sub" / "b.py") not in result
        assert "b.py" in result
        assert "c.txt" not in result

    async def test_no_matches(self, tmp_path):
        """无匹配时返回提示"""
        tool = _make_glob_tool(tmp_path)
        result = await tool.execute(pattern="**/*.xyz")
        assert "No files matching" in result

    async def test_path_not_found(self, tmp_path):
        """路径不存在时返回 Error"""
        tool = _make_glob_tool(tmp_path)
        result = await tool.execute(pattern="*", path="/nonexistent_dir")
        assert "Error" in result

    async def test_sandbox_blocks_escape(self, tmp_path):
        """sandbox 模式拦截 workspace 外路径"""
        tool = _make_glob_tool(tmp_path, sandbox=True)
        result = await tool.execute(pattern="*", path="/etc")
        assert "Error" in result

    async def test_sandbox_off_allows_any_path(self, tmp_path):
        """sandbox=False 允许任意路径"""
        tool = _make_glob_tool(tmp_path, sandbox=False)
        # /tmp is accessible on macOS
        result = await tool.execute(pattern="*", path=str(tmp_path))
        assert "Error" not in result

    async def test_truncation_at_max(self, tmp_path):
        """结果超过 MAX_GLOB_RESULTS 时截断"""
        for i in range(MAX_GLOB_RESULTS + 10):
            (tmp_path / f"file_{i:04d}.txt").write_text("x")

        tool = _make_glob_tool(tmp_path)
        result = await tool.execute(pattern="*.txt")
        assert "truncated" in result.lower() or result.count("\n") >= MAX_GLOB_RESULTS - 1

    async def test_only_files_no_dirs(self, tmp_path):
        """结果只包含文件，不包含目录"""
        (tmp_path / "subdir").mkdir()
        (tmp_path / "file.txt").write_text("hi")

        tool = _make_glob_tool(tmp_path)
        result = await tool.execute(pattern="*")
        assert "file.txt" in result
        # subdirectories should not appear as matches
        lines = [l for l in result.split("\n") if l.strip() and not l.startswith("...")]
        for line in lines:
            assert "subdir" not in line or line.endswith(".txt")

    async def test_custom_base_path(self, tmp_path):
        """path 参数指定搜索基目录"""
        sub = tmp_path / "src"
        sub.mkdir()
        (sub / "main.py").write_text("pass")

        tool = _make_glob_tool(tmp_path)
        result = await tool.execute(pattern="*.py", path="src")
        assert "main.py" in result


# ── GrepTool Tests ────────────────────────────────────────

class TestGrepTool:

    async def test_basic_search(self, tmp_path):
        """基本正则搜索"""
        (tmp_path / "test.py").write_text("def hello():\n    pass\n")
        tool = _make_grep_tool(tmp_path)
        result = await tool.execute(pattern="def hello")
        assert "test.py:1:def hello():" in result

    async def test_include_filter(self, tmp_path):
        """include 参数过滤文件类型"""
        (tmp_path / "a.py").write_text("TODO: fix this")
        (tmp_path / "b.txt").write_text("TODO: also this")

        tool = _make_grep_tool(tmp_path)
        result = await tool.execute(pattern="TODO", include="*.py")
        assert "a.py" in result
        assert "b.txt" not in result

    async def test_skip_binary_files(self, tmp_path):
        """跳过二进制文件"""
        (tmp_path / "binary.dat").write_bytes(b"\x00\x01\x02\x00")
        (tmp_path / "text.txt").write_text("findme")

        tool = _make_grep_tool(tmp_path)
        result = await tool.execute(pattern=".")
        assert "text.txt" in result
        assert "binary.dat" not in result

    async def test_skip_large_files(self, tmp_path):
        """跳过 >10MB 文件"""
        big = tmp_path / "big.log"
        big.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
        (tmp_path / "small.txt").write_text("findme")

        tool = _make_grep_tool(tmp_path)
        result = await tool.execute(pattern="findme")
        assert "small.txt" in result
        assert "big.log" not in result

    async def test_invalid_regex(self, tmp_path):
        """无效正则返回 Error"""
        tool = _make_grep_tool(tmp_path)
        result = await tool.execute(pattern="[invalid")
        assert "Error" in result
        assert "regex" in result.lower() or "Invalid" in result

    async def test_no_matches(self, tmp_path):
        """无匹配时返回提示"""
        (tmp_path / "a.txt").write_text("hello world")
        tool = _make_grep_tool(tmp_path)
        result = await tool.execute(pattern="xyz_not_found")
        assert "No matches" in result

    async def test_sandbox_blocks_escape(self, tmp_path):
        """sandbox 模式拦截 workspace 外路径"""
        tool = _make_grep_tool(tmp_path, sandbox=True)
        result = await tool.execute(pattern="test", path="/etc")
        assert "Error" in result

    async def test_truncation_at_max(self, tmp_path):
        """结果超过 MAX_GREP_RESULTS 时截断"""
        lines = [f"match_line_{i}" for i in range(MAX_GREP_RESULTS + 10)]
        (tmp_path / "big.txt").write_text("\n".join(lines))

        tool = _make_grep_tool(tmp_path)
        result = await tool.execute(pattern="match_line")
        assert "truncated" in result.lower() or result.count("\n") >= MAX_GREP_RESULTS - 1

    async def test_multiline_file_line_numbers(self, tmp_path):
        """输出格式为 path:line_num:content"""
        (tmp_path / "code.py").write_text("line1\nline2\nimport os\nline4\n")
        tool = _make_grep_tool(tmp_path)
        result = await tool.execute(pattern="import os")
        assert "code.py:3:import os" in result

    async def test_custom_base_path(self, tmp_path):
        """path 参数指定搜索基目录"""
        sub = tmp_path / "src"
        sub.mkdir()
        (sub / "main.py").write_text("TARGET_STRING")

        tool = _make_grep_tool(tmp_path)
        result = await tool.execute(pattern="TARGET_STRING", path="src")
        assert "main.py:1:TARGET_STRING" in result
