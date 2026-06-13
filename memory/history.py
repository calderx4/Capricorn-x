"""
History Log - 历史日志管理

职责：
- 管理 HISTORY.md 文件
- 追加时间线记录
- 提供搜索接口
"""

import re
from typing import List
from loguru import logger

from config.settings import WorkspaceConfig


class HistoryLog:
    """历史日志管理"""

    def __init__(self, workspace: WorkspaceConfig, max_entries: int = 100):
        self.file_path = workspace.get_memory_path("HISTORY.md")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._max_entries = max_entries
        logger.debug(f"History log path: {self.file_path}")

    def append(self, entry: str) -> None:
        try:
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
            self._prune_if_needed()
            logger.debug(f"Appended to history log: {entry[:50]}...")
        except Exception as e:
            logger.error(f"Failed to append to history log: {e}")
            raise

    def _prune_if_needed(self) -> None:
        if self._max_entries <= 0 or not self.file_path.exists():
            return
        try:
            lines = self.file_path.read_text(encoding="utf-8").split("\n")
            entry_indices = [i for i, l in enumerate(lines) if re.match(r"^\[\d{4}-", l.strip())]
            if len(entry_indices) <= self._max_entries:
                return
            cut = entry_indices[-self._max_entries]
            from core.utils import atomic_write
            atomic_write(self.file_path, "\n".join(lines[cut:]).lstrip("\n"))
            logger.info(
                f"History pruned: removed {len(entry_indices) - self._max_entries} oldest entries"
            )
        except Exception as e:
            logger.error(f"History prune failed: {e}")

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
