"""
Workflow Registry - 工作流注册和执行

职责：
- 工作流注册与管理
- 工具依赖验证
- 执行工作流
"""

from typing import Dict, List, Any, Optional
from loguru import logger

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_workflow import BaseWorkflow


class WorkflowRegistry:
    """工作流注册表"""

    def __init__(self):
        self._workflows: Dict[str, BaseWorkflow] = {}

    def register(self, workflow: BaseWorkflow) -> None:
        """注册工作流"""
        self._workflows[workflow.name] = workflow
        logger.debug(f"✓ Registered workflow: {workflow.name}")

    def unregister(self, name: str) -> None:
        """注销工作流"""
        self._workflows.pop(name, None)

    def get(self, name: str) -> Optional[BaseWorkflow]:
        """获取工作流"""
        return self._workflows.get(name)

    def has(self, name: str) -> bool:
        """检查工作流是否存在"""
        return name in self._workflows

    def list_workflows(self) -> List[str]:
        """列出所有工作流"""
        return list(self._workflows.keys())

    def validate_dependencies(self, workflow: BaseWorkflow, tool_registry) -> List[str]:
        """
        验证工作流的工具依赖是否满足

        Args:
            workflow: 工作流实例
            tool_registry: 工具注册表

        Returns:
            缺失的工具名称列表（空列表表示全部满足）
        """
        missing = []
        for tool_name in workflow.required_tools:
            if not tool_registry.has(tool_name):
                missing.append(tool_name)

        if missing:
            logger.warning(f"Workflow '{workflow.name}' missing tools: {missing}")

        return missing

    async def execute(
        self,
        name: str,
        tools: Any,
        tool_registry=None,
        validate_deps: bool = True,
        **kwargs
    ) -> Any:
        """
        执行工作流

        Args:
            name: 工作流名称
            tools: 工具注册表实例（传递给工作流使用）
            tool_registry: 工具注册表实例（用于依赖验证）
            validate_deps: 是否验证工具依赖
            **kwargs: 工作流参数

        Returns:
            执行结果
        """
        workflow = self._workflows.get(name)
        if not workflow:
            logger.error(f"Workflow '{name}' not found")
            return f"Error: Workflow '{name}' not found. Available: {', '.join(self.list_workflows())}"

        try:
            logger.debug(f"Executing workflow: {name}")

            # 验证工具依赖
            if validate_deps and tool_registry:
                missing = self.validate_dependencies(workflow, tool_registry)
                if missing:
                    return f"Error: Missing required tools: {', '.join(missing)}"

            # 执行工作流
            result = await workflow.execute(tools, **kwargs)

            return result

        except Exception as e:
            logger.error(f"Workflow execution failed: {name} - {e}")
            return f"Error executing workflow {name}: {str(e)}"

    def __len__(self) -> int:
        return len(self._workflows)

    def __contains__(self, name: str) -> bool:
        return name in self._workflows
