"""
Interfaces - 统一接口定义

使用 Protocol 定义接口类型，提供类型注解和静态检查支持。
"""

from typing import Protocol, Any, Dict, List, runtime_checkable


@runtime_checkable
class IToolRegistry(Protocol):
    """工具注册中心接口"""

    def register(self, tool: Any) -> None:
        """
        注册工具

        Args:
            tool: 工具实例
        """
        ...

    def unregister(self, name: str) -> None:
        """
        注销工具

        Args:
            name: 工具名称
        """
        ...

    def get(self, name: str) -> Any:
        """
        获取工具

        Args:
            name: 工具名称

        Returns:
            工具实例
        """
        ...

    def has(self, name: str) -> bool:
        """
        检查工具是否存在

        Args:
            name: 工具名称

        Returns:
            是否存在
        """
        ...

    def list_tools(self) -> List[str]:
        """
        列出所有工具

        Returns:
            工具名称列表
        """
        ...

    async def execute(self, name: str, params: Dict[str, Any]) -> Any:
        """
        执行工具

        Args:
            name: 工具名称
            params: 工具参数

        Returns:
            执行结果
        """
        ...


@runtime_checkable
class IWorkflowRegistry(Protocol):
    """工作流注册中心接口"""

    def register(self, workflow: Any) -> None:
        """
        注册工作流

        Args:
            workflow: 工作流实例
        """
        ...

    def unregister(self, name: str) -> None:
        """
        注销工作流

        Args:
            name: 工作流名称
        """
        ...

    def get(self, name: str) -> Any:
        """
        获取工作流

        Args:
            name: 工作流名称

        Returns:
            工作流实例
        """
        ...

    def has(self, name: str) -> bool:
        """
        检查工作流是否存在

        Args:
            name: 工作流名称

        Returns:
            是否存在
        """
        ...

    def list_workflows(self) -> List[str]:
        """
        列出所有工作流

        Returns:
            工作流名称列表
        """
        ...

    async def execute(self, name: str, tools: Any, **kwargs) -> Any:
        """
        执行工作流

        Args:
            name: 工作流名称
            tools: 工具注册中心实例
            **kwargs: 工作流参数

        Returns:
            执行结果
        """
        ...


@runtime_checkable
class ISkillManager(Protocol):
    """技能管理器接口"""

    def list_skills(self) -> List[str]:
        """
        列出所有技能

        Returns:
            技能名称列表
        """
        ...

    def load_skill(self, name: str) -> str:
        """
        加载技能内容

        Args:
            name: 技能名称

        Returns:
            技能内容（SKILL.md 文件内容）
        """
        ...

    def get_skill_summary(self) -> str:
        """
        获取技能摘要（XML 格式）

        Returns:
            XML 格式的技能摘要
        """
        ...


@runtime_checkable
class IMemoryStore(Protocol):
    """记忆存储接口"""

    def read_long_term(self) -> str:
        """
        读取长期记忆

        Returns:
            长期记忆内容
        """
        ...

    def write_long_term(self, content: str) -> None:
        """
        写入长期记忆

        Args:
            content: 长期记忆内容
        """
        ...

    def append_history(self, entry: str) -> None:
        """
        追加历史记录

        Args:
            entry: 历史记录条目
        """
        ...

    def search_history(self, query: str) -> List[str]:
        """
        搜索历史记录

        Args:
            query: 搜索关键词

        Returns:
            匹配的历史记录列表
        """
        ...
