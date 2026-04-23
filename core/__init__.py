"""
Core module - 核心抽象层

提供 Tool 和 Workflow 的抽象基类，以及统一接口定义。
"""

from .base_tool import BaseTool
from .base_workflow import BaseWorkflow
from .interfaces import (
    IToolRegistry,
    IWorkflowRegistry,
    ISkillManager,
    IMemoryStore,
)
from .token_counter import TokenCounter
from .utils import strip_thinking_tags

__all__ = [
    "BaseTool",
    "BaseWorkflow",
    "IToolRegistry",
    "IWorkflowRegistry",
    "ISkillManager",
    "IMemoryStore",
    "TokenCounter",
    "strip_thinking_tags",
]
