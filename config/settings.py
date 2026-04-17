"""
Settings - 配置管理

职责：
- 加载配置文件
- 解析环境变量
- 配置验证
"""

import json
import os
from pathlib import Path
from typing import Dict, Any
from pydantic import BaseModel, Field


class WorkspaceConfig(BaseModel):
    """工作空间配置"""

    root: str = "./workspace"
    memory_dir: str = "memory"
    session_dir: str = "sessions"

    def get_memory_path(self, filename: str) -> Path:
        """
        获取记忆文件路径

        Args:
            filename: 文件名（如 MEMORY.md, HISTORY.md）

        Returns:
            完整路径
        """
        return Path(self.root) / self.memory_dir / filename

    def get_session_path(self, thread_id: str) -> Path:
        """
        获取会话文件路径

        Args:
            thread_id: 会话 ID

        Returns:
            完整路径
        """
        return Path(self.root) / self.session_dir / f"{thread_id}.jsonl"


class LLMConfig(BaseModel):
    """LLM 配置"""

    provider: str
    model: str
    api_key: str
    api_base: str = None  # Optional: for custom API endpoints
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, gt=0)


class MCPServerConfig(BaseModel):
    """MCP 服务器配置"""

    type: str  # stdio, sse, streamable_http
    command: str = None
    args: list = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    url: str = None
    headers: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    enabled_tools: list = Field(default_factory=lambda: ["*"])
    tool_timeout: int = Field(default=30, gt=0)


class HooksConfig(BaseModel):
    """Hook 配置"""

    memory_consolidation: Dict[str, Any] = Field(
        default_factory=lambda: {
            "enabled": True,
            "message_threshold": 20,
            "messages_to_keep": 10,
            "token_threshold": 8000,
        }
    )


class Config(BaseModel):
    """主配置类"""

    workspace: WorkspaceConfig
    llm: LLMConfig
    mcp_servers: Dict[str, MCPServerConfig] = Field(default_factory=dict)
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    skills: Dict[str, Any] = Field(default_factory=dict)
    agent: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def load(cls, config_path: str) -> "Config":
        """
        加载配置文件

        Args:
            config_path: 配置文件路径

        Returns:
            Config 实例

        Raises:
            FileNotFoundError: 配置文件不存在
            ValidationError: 配置验证失败
        """
        path = Path(config_path)

        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 解析环境变量
        data = cls._resolve_env_vars(data)

        return cls(**data)

    @staticmethod
    def _resolve_env_vars(data: Any) -> Any:
        """
        递归解析环境变量

        支持格式：
        - ${ENV_VAR_NAME} - 完整替换
        - "prefix ${ENV_VAR} suffix" - 字符串中嵌入

        Args:
            data: 待处理的数据

        Returns:
            解析后的数据
        """
        if isinstance(data, str):
            # 完整匹配 ${VAR}
            if data.startswith("${") and data.endswith("}"):
                var_name = data[2:-1]
                resolved = os.getenv(var_name, data)
                if resolved != data:
                    import loguru
                    loguru.logger.debug(f"Resolved env var ${{{var_name}}} -> {resolved[:20]}...")
                return resolved

            # 字符串中包含 ${VAR}
            if "${" in data and "}" in data:
                import re
                pattern = r'\$\{([^}]+)\}'

                def replace_env_var(match):
                    var_name = match.group(1)
                    value = os.getenv(var_name, match.group(0))
                    if value != match.group(0):
                        import loguru
                        loguru.logger.debug(f"Resolved env var ${{{var_name}}} in string")
                    return value

                return re.sub(pattern, replace_env_var, data)

            return data

        if isinstance(data, dict):
            return {k: Config._resolve_env_vars(v) for k, v in data.items()}

        if isinstance(data, list):
            return [Config._resolve_env_vars(item) for item in data]

        return data

    def __repr__(self) -> str:
        return f"<Config(workspace={self.workspace.root}, llm={self.llm.provider})>"
