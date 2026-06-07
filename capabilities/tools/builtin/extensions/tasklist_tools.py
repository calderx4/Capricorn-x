"""
Tasklist Tools - 整体替换式任务列表

参考 Claude Code TodoWrite 设计：每次调用传入完整列表，整体替换。
LLM 可以在执行过程中随时调整（增加/删除/重排/拆分），不浪费 FC 调用。
"""

import json
from pathlib import Path
from typing import Any, Dict, List
from loguru import logger

from core.base_tool import BaseTool
from core.utils import atomic_write

_STATUS_ICONS = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}


class TasklistTool(BaseTool):
    """整体替换式任务列表"""

    def __init__(self, workspace_root: str = "./workspace", sandbox: bool = True):
        self._tasklist_path = Path(workspace_root) / ".tasklist.json"

    @property
    def name(self) -> str:
        return "tasklist"

    @property
    def description(self) -> str:
        return (
            "任务列表工具（整体替换模式）。每次调用传入完整任务列表，直接覆盖。\n"
            "适用于 3 步以上的复杂任务规划和跟踪。\n\n"
            "用法：\n"
            "  首次规划：传入所有步骤，全部设 pending\n"
            "  推进任务：更新当前步骤为 in_progress，完成的改为 completed\n"
            "  动态调整：随时增删步骤、拆分过大的步骤、调整顺序\n\n"
            "规则：始终只保持 1 项 in_progress，完成后推进下一项。\n"
            "每项可填 activeForm（进行中显示的短标签）。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "完整任务列表（整体替换）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "任务描述",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "任务状态",
                            },
                            "activeForm": {
                                "type": "string",
                                "description": "进行中显示的短标签（可选，如 '分析依赖关系'）",
                            },
                        },
                        "required": ["content", "status"],
                    },
                },
            },
            "required": ["items"],
        }

    async def execute(self, items: List[Dict[str, Any]] = None) -> str:
        if items is None:
            items = []

        try:
            # 标准化：确保每项都有 content 和 status
            cleaned = []
            for item in items:
                content = item.get("content", "").strip()
                if not content:
                    continue
                status = item.get("status", "pending")
                if status not in _STATUS_ICONS:
                    status = "pending"
                cleaned.append({
                    "content": content,
                    "status": status,
                    "activeForm": item.get("activeForm", ""),
                })

            self._save(cleaned)

            # 发射 SSE 事件（通过 context variable 获取 on_event）
            if cleaned:
                from agent.events import current_on_event, safe_emit
                on_event = current_on_event.get()
                if on_event:
                    await safe_emit(on_event, "tasklist_update", {"items": cleaned})

            return self._format(cleaned)

        except Exception as e:
            logger.error(f"tasklist tool failed: {e}")
            return f"Error: {e}"

    def _format(self, items: list) -> str:
        if not items:
            return "任务列表已清空"
        lines = []
        for item in items:
            icon = _STATUS_ICONS.get(item["status"], "[ ]")
            lines.append(f"  {icon} {item['content']}")
        return "任务列表：\n" + "\n".join(lines)

    def _load(self) -> list:
        if not self._tasklist_path.exists():
            return []
        try:
            return json.loads(self._tasklist_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save(self, items: list):
        self._tasklist_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(
            self._tasklist_path,
            json.dumps(items, ensure_ascii=False, indent=2),
        )
