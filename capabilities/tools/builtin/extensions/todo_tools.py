"""
Todo Tools - 任务规划与跟踪

让 agent 在处理复杂多步任务时能规划和跟踪进度。
"""

import json
from pathlib import Path
from typing import Any, Dict
from loguru import logger

from core.base_tool import BaseTool


class TodoTool(BaseTool):
    """任务规划与跟踪工具"""

    def __init__(self, workspace_root: str = "./workspace"):
        self._todo_path = Path(workspace_root) / ".todo.json"

    @classmethod
    def from_config(cls, config: dict) -> "TodoTool":
        return cls(config["workspace_root"])

    @property
    def name(self) -> str:
        return "todo"

    @property
    def description(self) -> str:
        return (
            "管理任务列表，用于复杂多步任务的规划和进度跟踪。"
            "action='add' 添加任务，action='update' 更新状态（pending/in_progress/completed），"
            "action='list' 查看所有任务，action='clear' 清空任务列表。"
            "复杂任务先用 add 规划步骤，再逐步执行。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "update", "list", "clear"],
                    "description": "操作类型",
                },
                "content": {
                    "type": "string",
                    "description": "任务描述（add 时必填）",
                },
                "task_id": {
                    "type": "integer",
                    "description": "任务 ID（update 时必填）",
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed"],
                    "description": "任务状态（update 时必填）",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, content: str = None, task_id: int = None, status: str = None) -> str:
        try:
            todos = self._load()

            if action == "add":
                if not content:
                    return "Error: 添加任务需要提供 content"
                new_id = max((t["id"] for t in todos), default=0) + 1
                todos.append({"id": new_id, "content": content, "status": "pending"})
                self._save(todos)
                return f"已添加任务 #{new_id}: {content}"

            elif action == "update":
                if task_id is None or not status:
                    return "Error: 更新任务需要提供 task_id 和 status"
                for t in todos:
                    if t["id"] == task_id:
                        t["status"] = status
                        self._save(todos)
                        return f"任务 #{task_id} 状态更新为 {status}"
                return f"Error: 未找到任务 #{task_id}"

            elif action == "list":
                if not todos:
                    return "任务列表为空"
                lines = []
                for t in todos:
                    icon = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}[t["status"]]
                    lines.append(f"  #{t['id']} {icon} {t['content']}")
                return "任务列表：\n" + "\n".join(lines)

            elif action == "clear":
                self._save([])
                return "已清空任务列表"

            return f"Error: 未知 action '{action}'"

        except Exception as e:
            logger.error(f"todo tool failed: {e}")
            return f"Error: {e}"

    def _load(self) -> list:
        if not self._todo_path.exists():
            return []
        try:
            return json.loads(self._todo_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            return []

    def _save(self, todos: list):
        self._todo_path.parent.mkdir(parents=True, exist_ok=True)
        self._todo_path.write_text(
            json.dumps(todos, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
