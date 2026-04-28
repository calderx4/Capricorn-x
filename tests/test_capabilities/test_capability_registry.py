import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path

from capabilities.capability_registry import CapabilityRegistry


class TestCapabilityRegistryCreate:
    @pytest.mark.asyncio
    async def test_create_with_no_mcp(self, tmp_path):
        """Registry 能在无 MCP 配置时初始化"""
        registry = await CapabilityRegistry.create(
            mcp_servers=None,
            workspace_root=str(tmp_path),
            sandbox=True,
        )
        assert len(registry.tools) > 0  # 至少有 builtin tools
        assert "read_file" in registry.tools

    @pytest.mark.asyncio
    async def test_create_registers_builtin_tools(self, tmp_path):
        registry = await CapabilityRegistry.create(
            mcp_servers=None,
            workspace_root=str(tmp_path),
            sandbox=True,
        )
        builtin_tools = registry.tools.list_by_layer()["builtin"]
        assert "read_file" in builtin_tools
        assert "write_file" in builtin_tools
        assert "list_files" in builtin_tools

    @pytest.mark.asyncio
    async def test_get_langchain_tools(self, tmp_path):
        registry = await CapabilityRegistry.create(
            mcp_servers=None,
            workspace_root=str(tmp_path),
            sandbox=True,
        )
        lc_tools = registry.get_langchain_tools()
        assert len(lc_tools) > 0
        names = [t.name for t in lc_tools]
        assert "read_file" in names


class TestCapabilityRegistryExecute:
    @pytest.mark.asyncio
    async def test_execute_tool_delegates_to_registry(self, tmp_path):
        registry = await CapabilityRegistry.create(
            mcp_servers=None,
            workspace_root=str(tmp_path),
            sandbox=True,
        )
        # 写一个文件再读
        await registry.execute_tool("write_file", {"path": "test.txt", "content": "hello"})
        result = await registry.execute_tool("read_file", {"path": "test.txt"})
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, tmp_path):
        registry = await CapabilityRegistry.create(
            mcp_servers=None,
            workspace_root=str(tmp_path),
            sandbox=True,
        )
        result = await registry.execute_tool("nonexistent_tool", {})
        assert "not found" in result.lower() or "Error" in result


class TestCapabilityRegistryCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_without_mcp(self, tmp_path):
        registry = await CapabilityRegistry.create(
            mcp_servers=None,
            workspace_root=str(tmp_path),
            sandbox=True,
        )
        # 无 MCP 时 cleanup 不报错
        await registry.cleanup()
