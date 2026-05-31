"""
History Log - 历史日志管理

职责：
- 管理 HISTORY.md 文件
- 追加时间线记录
- 提供搜索接口
"""

from typing import List
from loguru import logger

from config.settings import WorkspaceConfig


class HistoryLog:
    """历史日志管理"""

    def __init__(self, workspace: WorkspaceConfig):
        self.file_path = workspace.get_memory_path("HISTORY.md")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug(f"History log path: {self.file_path}")

    def append(self, entry: str) -> None:
        try:
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
            logger.debug(f"Appended to history log: {entry[:50]}...")
        except Exception as e:
            logger.error(f"Failed to append to history log: {e}")
            raise

    def search(self, query: str, case_sensitive: bool = False) -> List[str]:
        if not self.file_path.exists():
            return []

        try:
            results = []
            search_query = query if case_sensitive else query.lower()

            with open(self.file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line_stripped = line.strip()
                    if not line_stripped:
                        continue

                    search_line = line_stripped if case_sensitive else line_stripped.lower()

                    if search_query in search_line:
                        results.append(line_stripped)

            logger.debug(f"History search for '{query}': found {len(results)} results")
            return results
        except Exception as e:
            logger.error(f"Failed to search history log: {e}")
            return []
