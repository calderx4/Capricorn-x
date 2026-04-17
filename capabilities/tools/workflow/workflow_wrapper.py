"""
Workflow Tool Wrapper - 将 BaseWorkflow 包装为 BaseTool

使工作流可以像普通工具一样被 LLM 通过 function calling 调用。
"""

from typing import Any, Dict
from loguru import logger

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_tool import BaseTool
from core.base_workflow import BaseWorkflow


class WorkflowToolWrapper(BaseTool):
    """将 BaseWorkflow 包装为 BaseTool"""

    def __init__(self, workflow: BaseWorkflow, tool_registry):
        self._workflow = workflow
        self._tool_registry = tool_registry
        self._name = f"workflow_{workflow.name}"
        self._description = workflow.description
        self._parameters = self._build_parameters(workflow)

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> Dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs) -> Any:
        """执行工作流"""
        logger.info(f"Executing workflow tool: {self._name}")
        return await self._workflow.execute(tools=self._tool_registry, **kwargs)

    def _build_parameters(self, workflow: BaseWorkflow) -> Dict[str, Any]:
        """构建参数 schema"""
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": f"Task description for the {workflow.name} workflow"
                }
            },
            "required": ["task"]
        }
