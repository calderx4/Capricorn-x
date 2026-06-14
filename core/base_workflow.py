"""
BaseWorkflow - 工作流抽象基类

定义工作流的统一接口，包括：
- 声明依赖的工具
- 提供状态和记忆管理接口
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseWorkflow(ABC):
    """工作流抽象基类"""

    auto_discover = True

    @classmethod
    def from_config(cls, config: dict) -> "BaseWorkflow":
        """从配置创建实例，需要外部依赖的子类覆写此方法"""
        return cls()

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": f"Task description for the {self.name} workflow",
                }
            },
            "required": ["task"],
        }

    @abstractmethod
    async def execute(self, tools: Any, **kwargs: Any) -> Any:
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}')>"
