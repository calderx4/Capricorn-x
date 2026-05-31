"""
Long Term Memory - 长期记忆管理

职责：
- 管理 MEMORY.md 文件
- 提供读写接口
"""

from loguru import logger

from config.settings import WorkspaceConfig
from core.utils import atomic_write


class LongTermMemory:
    """长期记忆管理"""

    def __init__(self, workspace: WorkspaceConfig):
        self.file_path = workspace.get_memory_path("MEMORY.md")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Long term memory path: {self.file_path}")

    def read(self) -> str:
        if not self.file_path.exists():
            return ""

        try:
            content = self.file_path.read_text(encoding="utf-8")
            logger.debug(f"Read long term memory: {len(content)} chars")
            return content
        except Exception as e:
            logger.error(f"Failed to read long term memory: {e}")
            return ""

    def write(self, content: str) -> None:
        try:
            atomic_write(self.file_path, content)
            logger.debug(f"Wrote long term memory: {len(content)} chars")
        except Exception as e:
            logger.error(f"Failed to write long term memory: {e}")
            raise
