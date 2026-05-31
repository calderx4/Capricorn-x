"""
Workflow Tools module - 工作流工具层

将工作流包装为 LangChain Tool，实现四层能力体系：
- tools:    原子操作（确定性单步执行）
- workflow:  代码编排（代码约束的多步执行）
- skills:   自然语言驱动（SKILL.md 指导的复杂执行）
- mcp:      外部服务（通过 MCP 协议调用）
"""

from .workflow_wrapper import WorkflowToolWrapper

__all__ = ["WorkflowToolWrapper"]
