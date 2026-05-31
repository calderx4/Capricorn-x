import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "team_tools",
    "capabilities/tools/builtin/extensions/team_tools.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
GetResultTool = _mod.GetResultTool


def _make_tool(workspace_root: str) -> GetResultTool:
    return GetResultTool(workspace_root)


def _write_task_with_result(tmp_path, task_id, status="done", result_content="Test result"):
    tasks_dir = tmp_path / "team" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    task = {
        "id": task_id,
        "status": status,
        "assigned_role": "executor",
        "question_count": 0,
        "updated_at": "2026-01-01 00:00:00",
    }
    (tasks_dir / f"{task_id}.json").write_text(json.dumps(task))
    task_dir = tasks_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "result.md").write_text(result_content)


class TestGetResult:

    @pytest.mark.asyncio
    async def test_done_task_returns_result(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        _write_task_with_result(tmp_path, "task_a1b2c3d4", status="done", result_content="Hello world")
        result = json.loads(await tool.execute(task_id="task_a1b2c3d4"))
        assert result["status"] == "done"
        assert "Hello world" in result["result"]

    @pytest.mark.asyncio
    async def test_running_task_returns_error(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        _write_task_with_result(tmp_path, "task_a1b2c3d4", status="running")
        result = json.loads(await tool.execute(task_id="task_a1b2c3d4"))
        assert "error" in result
        assert "尚未就绪" in result["error"]

    @pytest.mark.asyncio
    async def test_nonexisting_task_returns_error(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        result = json.loads(await tool.execute(task_id="task_00000000"))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_task_with_questions(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        _write_task_with_result(tmp_path, "task_a1b2c3d4", status="need_decision")
        q_dir = tmp_path / "team" / "tasks" / "task_a1b2c3d4" / "questions"
        q_dir.mkdir(parents=True, exist_ok=True)
        (q_dir / "1.json").write_text(json.dumps({"message": "需要确认", "can_continue": False}))
        result = json.loads(await tool.execute(task_id="task_a1b2c3d4"))
        assert len(result["questions"]) == 1
        assert result["questions"][0]["message"] == "需要确认"

    @pytest.mark.asyncio
    async def test_result_truncated_at_5000(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        long_content = "x" * 10000
        _write_task_with_result(tmp_path, "task_a1b2c3d4", status="done", result_content=long_content)
        result = json.loads(await tool.execute(task_id="task_a1b2c3d4"))
        assert len(result["result"]) <= 5000

    @pytest.mark.asyncio
    async def test_no_result_file(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        tasks_dir = tmp_path / "team" / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        task = {"id": "task_a1b2c3d4", "status": "done", "assigned_role": "executor",
                "question_count": 0, "updated_at": "2026-01-01 00:00:00"}
        (tasks_dir / "task_a1b2c3d4.json").write_text(json.dumps(task))
        result = json.loads(await tool.execute(task_id="task_a1b2c3d4"))
        assert result["result"] == ""
