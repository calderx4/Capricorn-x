"""
Tests for file_tools.py — ReadFileTool (with offset/limit + cat-n format)
"""

import pytest

from capabilities.tools.builtin.extensions.file_tools import ReadFileTool


# ── Helpers ───────────────────────────────────────────────

def _make_read_tool(tmp_path, sandbox=True):
    return ReadFileTool(workspace_root=str(tmp_path), sandbox=sandbox)


# ── ReadFileTool Tests ────────────────────────────────────

class TestReadFileTool:

    async def test_read_full_file_with_line_numbers(self, tmp_path):
        """全量读取输出 cat-n 格式行号"""
        (tmp_path / "test.txt").write_text("alpha\nbeta\ngamma\n")
        tool = _make_read_tool(tmp_path)
        result = await tool.execute(path="test.txt")

        lines = result.split("\n")
        assert len(lines) == 3
        assert lines[0].endswith("\talpha")
        assert lines[1].endswith("\tbeta")
        assert lines[2].endswith("\tgamma")
        # 行号是 1-based 右对齐
        assert "1" in lines[0]
        assert "2" in lines[1]
        assert "3" in lines[2]

    async def test_read_with_offset(self, tmp_path):
        """offset 跳过前 N 行（0-based）"""
        (tmp_path / "test.txt").write_text("line1\nline2\nline3\nline4\nline5\n")
        tool = _make_read_tool(tmp_path)
        result = await tool.execute(path="test.txt", offset=2)

        lines = result.split("\n")
        assert len(lines) == 3  # lines 3,4,5
        assert "line3" in lines[0]
        assert "line4" in lines[1]
        assert "line5" in lines[2]
        # 显示行号从 3 开始（1-based）
        assert "3" in lines[0].split("\t")[0]

    async def test_read_with_limit(self, tmp_path):
        """limit 限制返回行数"""
        (tmp_path / "test.txt").write_text("line1\nline2\nline3\nline4\nline5\n")
        tool = _make_read_tool(tmp_path)
        result = await tool.execute(path="test.txt", limit=2)

        lines = result.split("\n")
        assert len(lines) == 2
        assert "line1" in lines[0]
        assert "line2" in lines[1]

    async def test_read_with_offset_and_limit(self, tmp_path):
        """offset + limit 组合"""
        (tmp_path / "test.txt").write_text("a\nb\nc\nd\ne\n")
        tool = _make_read_tool(tmp_path)
        result = await tool.execute(path="test.txt", offset=1, limit=2)

        lines = result.split("\n")
        assert len(lines) == 2
        assert "b" in lines[0]
        assert "c" in lines[1]
        # 行号从 2 开始（1-based, offset=1 → 第 2 行）
        assert "2" in lines[0].split("\t")[0]
        assert "3" in lines[1].split("\t")[0]

    async def test_default_limit_2000(self, tmp_path):
        """不传 limit 时默认 2000 行"""
        lines_content = "\n".join(f"line_{i}" for i in range(2500))
        (tmp_path / "big.txt").write_text(lines_content)
        tool = _make_read_tool(tmp_path)
        result = await tool.execute(path="big.txt")

        result_lines = result.split("\n")
        assert len(result_lines) == 2000

    async def test_file_not_found(self, tmp_path):
        """文件不存在返回 Error"""
        tool = _make_read_tool(tmp_path)
        result = await tool.execute(path="nonexistent.txt")
        assert "Error" in result
        assert "not found" in result.lower()

    async def test_not_a_file(self, tmp_path):
        """路径是目录返回 Error"""
        (tmp_path / "subdir").mkdir()
        tool = _make_read_tool(tmp_path)
        result = await tool.execute(path="subdir")
        assert "Error" in result
        assert "Not a file" in result

    async def test_file_too_large(self, tmp_path):
        """超过 10MB 返回 Error"""
        big = tmp_path / "big.dat"
        big.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
        tool = _make_read_tool(tmp_path)
        result = await tool.execute(path="big.dat")
        assert "Error" in result
        assert "too large" in result.lower()

    async def test_sandbox_blocks_escape(self, tmp_path):
        """sandbox 模式拦截 workspace 外路径"""
        tool = _make_read_tool(tmp_path, sandbox=True)
        result = await tool.execute(path="/etc/passwd")
        assert "Error" in result

    async def test_sandbox_off_allows(self, tmp_path):
        """sandbox=False 允许任意路径"""
        tool = _make_read_tool(tmp_path, sandbox=False)
        # 读自身的测试文件（确保存在）
        (tmp_path / "readme.txt").write_text("ok")
        result = await tool.execute(path=str(tmp_path / "readme.txt"))
        assert "ok" in result

    async def test_empty_file(self, tmp_path):
        """空文件返回空字符串"""
        (tmp_path / "empty.txt").write_text("")
        tool = _make_read_tool(tmp_path)
        result = await tool.execute(path="empty.txt")
        assert result == ""

    async def test_offset_beyond_file(self, tmp_path):
        """offset 超出文件行数返回空"""
        (tmp_path / "short.txt").write_text("only one line")
        tool = _make_read_tool(tmp_path)
        result = await tool.execute(path="short.txt", offset=100)
        assert result == ""

    async def test_line_number_alignment(self, tmp_path):
        """行号右对齐，位数随最大行号调整"""
        content = "\n".join(f"line {i}" for i in range(1, 12))  # 11 lines
        (tmp_path / "align.txt").write_text(content)
        tool = _make_read_tool(tmp_path)
        result = await tool.execute(path="align.txt")

        lines = result.split("\n")
        # 行号 1-9 前面有空格对齐到 2 位数
        first_line = lines[0]
        parts = first_line.split("\t")
        assert len(parts[0]) == 2  # " 1" (right-aligned to width 2)
