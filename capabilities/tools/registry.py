"""
Tool Registry - 工具注册和执行
"""

import json
from typing import Dict, List, Any, Optional
from loguru import logger

from core.base_tool import BaseTool


class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._layers: Dict[str, str] = {}  # name -> layer

    def register(self, tool: BaseTool, layer: str = "builtin", public_name: str = None) -> None:
        try:
            schema = tool.parameters
            if not isinstance(schema, dict):
                logger.warning(f"Tool '{tool.name}' has invalid schema type: {type(schema)}")
            elif "type" not in schema:
                logger.warning(f"Tool '{tool.name}' schema missing 'type' field")

            name = public_name or tool.name
            if name in self._tools:
                existing_layer = self._layers.get(name, "?")
                raise ValueError(
                    f"Tool name conflict: '{name}' already registered [{existing_layer}]."
                )
            self._tools[name] = tool
            self._layers[name] = layer
            logger.debug(f"✓ Registered [{layer}] tool: {name}")

        except Exception as e:
            logger.error(f"Failed to register tool '{tool.name}': {e}")
            raise

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        return list(self._tools.keys())

    def list_by_layer(self) -> Dict[str, List[str]]:
        layers: Dict[str, List[str]] = {"builtin": [], "mcp": [], "workflow": []}
        for name, layer in self._layers.items():
            if layer in layers:
                layers[layer].append(name)
            else:
                layers[layer] = [name]
        return layers

    def get_langchain_tools(self) -> List:
        return [tool.to_langchain_tool() for tool in self._tools.values()]

    async def execute(self, name: str, params: Dict[str, Any]) -> Any:
        _HINT = "\n\n[Analyze the error above and try a different approach.]"

        tool = self._tools.get(name)
        if not tool:
            logger.error(f"Tool '{name}' not found")
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.list_tools())}"

        try:
            logger.debug(f"Executing tool: {name}")

            params = tool.cast_params(params)

            errors = tool.validate_params(params)
            if errors:
                logger.warning(f"Tool {name} validation failed: {'; '.join(errors)}")
                return f"Error: Invalid parameters: {'; '.join(errors)}{_HINT}"

            result = await tool.execute(**params)

            if isinstance(result, str) and result.startswith("Error:"):
                return result + _HINT

            if isinstance(result, (dict, list)):
                return json.dumps(result, ensure_ascii=False)

            return result

        except Exception as e:
            logger.error(f"Tool execution failed: {name} - {e}")
            return f"Error executing {name}: {str(e)}{_HINT}"

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name) -> bool:
        return name in self._tools
