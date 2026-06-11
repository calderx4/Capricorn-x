"""
BaseTool - 工具抽象基类

定义工具的统一接口，包括：
- JSON Schema 参数定义
- 参数类型转换与验证
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List
from loguru import logger


class BaseTool(ABC):
    """工具抽象基类"""

    auto_discover = True

    @classmethod
    def from_config(cls, config: dict) -> "BaseTool":
        """从配置创建实例（workspace_root + sandbox）；需要额外依赖的子类覆写此方法。"""
        return cls(
            workspace_root=config.get("workspace_root", "./workspace"),
            sandbox=config.get("sandbox", True),
        )

    # JSON Schema 类型到 Python 类型的映射
    _TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        pass

    def to_langchain_tool(self):
        """转换为 LangChain StructuredTool 格式"""
        from langchain_core.tools import StructuredTool
        from pydantic import create_model

        field_definitions = {}
        properties = self.parameters.get("properties", {})
        required = self.parameters.get("required", [])

        for field_name, field_schema in properties.items():
            field_type = self._json_schema_to_python_type(field_schema)
            default = ... if field_name in required else None
            field_definitions[field_name] = (field_type, default)

        args_schema = create_model(f"{self.name}Args", **field_definitions)

        return StructuredTool(
            name=self.name,
            description=self.description,
            args_schema=args_schema,
            coroutine=self.execute,
        )

    def _json_schema_to_python_type(self, schema: Dict[str, Any]) -> type:
        json_type = schema.get("type", "string")

        if json_type == "array":
            items = schema.get("items", {})
            item_type = self._json_schema_to_python_type(items)
            return List[item_type]

        if json_type == "object":
            return Dict[str, Any]

        return self._TYPE_MAP.get(json_type, str)

    def cast_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if not params:
            return params

        properties = self.parameters.get("properties", {})
        casted = {}

        for key, value in params.items():
            if key not in properties:
                casted[key] = value
                continue

            schema = properties[key]
            json_type = schema.get("type", "string")

            try:
                casted[key] = self._cast_value(value, json_type, schema)
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to cast parameter '{key}': {e}, using original value")
                casted[key] = value

        return casted

    def _cast_value(self, value: Any, json_type: str, schema: Dict[str, Any]) -> Any:
        if value is None:
            return None

        if json_type == "string":
            return str(value)

        if json_type == "integer":
            return int(value)

        if json_type == "number":
            if isinstance(value, int):
                return value
            return float(value)

        if json_type == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            return bool(value)

        if json_type == "array":
            if isinstance(value, list):
                items_schema = schema.get("items", {})
                items_type = items_schema.get("type", "string")
                return [
                    self._cast_value(item, items_type, items_schema)
                    for item in value
                ]
            return [value]

        if json_type == "object":
            if isinstance(value, dict):
                return value
            if isinstance(value, str):
                import json
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    pass
            return value

        return value

    def validate_params(self, params: Dict[str, Any]) -> List[str]:
        errors = []
        properties = self.parameters.get("properties", {})
        required = self.parameters.get("required", [])

        for param_name in required:
            if param_name not in params:
                errors.append(f"Missing required parameter: {param_name}")

        for param_name, param_value in params.items():
            if param_name not in properties:
                continue

            schema = properties[param_name]
            json_type = schema.get("type", "string")

            if not self._validate_type(param_value, json_type, schema):
                errors.append(
                    f"Parameter '{param_name}' has wrong type: expected {json_type}, "
                    f"got {type(param_value).__name__}"
                )

        return errors

    def _validate_type(self, value: Any, json_type: str, schema: Dict[str, Any]) -> bool:
        if value is None:
            return True

        if json_type == "string":
            return isinstance(value, str)

        if json_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)

        if json_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)

        if json_type == "boolean":
            return isinstance(value, bool)

        if json_type == "array":
            if not isinstance(value, list):
                return False
            items_schema = schema.get("items", {})
            items_type = items_schema.get("type", "string")
            return all(
                self._validate_type(item, items_type, items_schema)
                for item in value
            )

        if json_type == "object":
            if not isinstance(value, dict):
                return False
            return True

        return True

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}')>"
