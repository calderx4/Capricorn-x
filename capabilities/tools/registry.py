"""
Tool Registry - 工具注册和执行

参考 nanobot 实现：
- 统一注册
- 并发执行
- 错误处理
"""

import asyncio
from typing import Dict, List, Any, Optional
from loguru import logger

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_tool import BaseTool


class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._layers: Dict[str, str] = {}  # tool_name -> layer (builtin/mcp/workflow)

    def register(self, tool: BaseTool, layer: str = "builtin") -> None:
        """注册工具"""
        try:
            schema = tool.parameters
            if not isinstance(schema, dict):
                logger.warning(f"Tool '{tool.name}' has invalid schema type: {type(schema)}")
            elif "type" not in schema:
                logger.warning(f"Tool '{tool.name}' schema missing 'type' field")

            self._tools[tool.name] = tool
            self._layers[tool.name] = layer
            logger.debug(f"✓ Registered [{layer}] tool: {tool.name}")

        except Exception as e:
            logger.error(f"Failed to register tool '{tool.name}': {e}")
            raise

    def unregister(self, name: str) -> None:
        """注销工具"""
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[BaseTool]:
        """获取工具"""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """检查工具是否存在"""
        return name in self._tools

    def list_tools(self) -> List[str]:
        """列出所有工具"""
        return list(self._tools.keys())

    def list_by_layer(self) -> Dict[str, List[str]]:
        """按层级列出工具"""
        layers = {"builtin": [], "mcp": [], "workflow": []}
        for name, layer in self._layers.items():
            if layer in layers:
                layers[layer].append(name)
        return layers

    def get_langchain_tools(self) -> List:
        """获取所有工具的 LangChain 格式"""
        return [tool.to_langchain_tool() for tool in self._tools.values()]

    async def execute(self, name: str, params: Dict[str, Any]) -> Any:
        """
        执行工具

        Args:
            name: 工具名称
            params: 工具参数

        Returns:
            执行结果
        """
        _HINT = "\n\n[Analyze the error above and try a different approach.]"

        tool = self._tools.get(name)
        if not tool:
            logger.error(f"Tool '{name}' not found")
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.list_tools())}"

        try:
            logger.debug(f"Executing tool: {name}")

            # 1. 参数类型转换
            params = tool.cast_params(params)

            # 2. 参数验证
            errors = tool.validate_params(params)
            if errors:
                logger.warning(f"Tool {name} validation failed: {'; '.join(errors)}")
                return f"Error: Invalid parameters: {'; '.join(errors)}{_HINT}"

            # 3. 执行
            result = await tool.execute(**params)

            # 4. 检查错误返回
            if isinstance(result, str) and result.startswith("Error"):
                return result + _HINT

            return result

        except Exception as e:
            logger.error(f"Tool execution failed: {name} - {e}")
            return f"Error executing {name}: {str(e)}{_HINT}"

    async def execute_batch(self, tool_calls: List[Dict[str, Any]]) -> List[Any]:
        """
        并发执行多个工具调用

        Args:
            tool_calls: 工具调用列表，格式: [{"name": "...", "arguments": {...}}]

        Returns:
            结果列表
        """
        tasks = [
            self.execute(call["name"], call["arguments"])
            for call in tool_calls
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常
        processed = []
        for result in results:
            if isinstance(result, Exception):
                processed.append(f"Error: {type(result).__name__}: {result}")
            else:
                processed.append(result)

        return processed

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
