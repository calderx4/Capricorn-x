"""
Capability Registry - 能力注册中心

职责：
- 统一管理 Tool（builtin / mcp / workflow）
- 提供 create 工厂方法
- 协调执行
"""

from typing import Dict, Any, Optional
from loguru import logger

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from capabilities.tools.registry import ToolRegistry


class CapabilityRegistry:
    """能力注册中心 - 统一管理所有 Tool（builtin / mcp / workflow）"""

    def __init__(self):
        self.tools = ToolRegistry()
        self._mcp_manager = None

    @classmethod
    async def create(cls, mcp_servers: Dict[str, Any] = None, workspace_root: str = "./workspace", sandbox: bool = True) -> "CapabilityRegistry":
        registry = cls()
        registry._workspace_root = workspace_root
        registry._sandbox = sandbox

        # 注册内置工具（第 1 层：原子执行）
        await registry._register_builtin_tools()

        # 注册 MCP 工具（第 2 层：联网中级执行）
        if mcp_servers:
            await registry._register_mcp_tools(mcp_servers)

        # 注册工作流工具（第 3 层：复杂执行）
        await registry._register_workflow_tools()

        logger.info(f"CapabilityRegistry initialized with {len(registry.tools)} tools")
        return registry

    async def _register_builtin_tools(self):
        from capabilities.tools.builtin.extensions.file_tools import (
            ReadFileTool, WriteFileTool, ListFilesTool
        )
        from capabilities.tools.builtin.extensions.exec_tools import ExecTool

        for tool in [ReadFileTool(self._workspace_root, self._sandbox), WriteFileTool(self._workspace_root, self._sandbox), ListFilesTool(self._workspace_root, self._sandbox), ExecTool()]:
            self.tools.register(tool, layer="builtin")

    async def _register_mcp_tools(self, mcp_servers: Dict[str, Any]):
        from capabilities.tools.mcp.mcp_client import MCPClientManager

        self._mcp_manager = MCPClientManager(mcp_servers)
        await self._mcp_manager.connect(self.tools, layer="mcp")

    async def _register_workflow_tools(self):
        from capabilities.tools.workflow.workflow_wrapper import WorkflowToolWrapper
        from capabilities.tools.workflow.extensions.document_workflow import DocumentCreationWorkflow
        from capabilities.tools.workflow.extensions.test_workflow import TestWorkflow

        for workflow_cls in [DocumentCreationWorkflow, TestWorkflow]:
            workflow = workflow_cls()
            wrapper = WorkflowToolWrapper(workflow, self.tools)
            self.tools.register(wrapper, layer="workflow")

    async def execute_tool(self, name: str, params: Dict[str, Any]) -> Any:
        return await self.tools.execute(name, params)

    def get_langchain_tools(self) -> list:
        return self.tools.get_langchain_tools()

    async def cleanup(self):
        if self._mcp_manager:
            await self._mcp_manager.disconnect()
        logger.debug("CapabilityRegistry cleanup completed")
