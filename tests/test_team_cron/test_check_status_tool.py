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
CheckStatusTool = _mod.CheckStatusTool


def _make_tool(workspace_root: str) -> CheckStatusTool:
    return CheckStatusTool(workspace_root)


def _write_task(tmp_path, task_id, **overrides):
    tasks_dir = tmp_path / "team" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    task = {
        "id": task_id,
        "status": "running",
        "assigned_role": "executor",
        "question_count": 0,
        "updated_at": "2026-01-01 00:00:00",
    }
    task.update(overrides)
    (tasks_dir / f"{task_id}.json").write_text(json.dumps(task))


class TestCheckStatus:

    @pytest.mark.asyncio
    async def test_existing_running_task(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        _write_task(tmp_path, "task_a1b2c3d4", status="running")
        result = json.loads(await tool.execute(task_id="task_a1b2c3d4"))
        assert result["task_id"] == "task_a1b2c3d4"
        assert result["status"] == "running"
        assert result["role"] == "executor"
        assert result["question_count"] == 0

    @pytest.mark.asyncio
    async def test_existing_done_task(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        _write_task(tmp_path, "task_a1b2c3d4", status="done")
        result = json.loads(await tool.execute(task_id="task_a1b2c3d4"))
        assert result["status"] == "done"

    @pytest.mark.asyncio
    async def test_nonexisting_task(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        result = json.loads(await tool.execute(task_id="task_00000000"))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_task_with_questions(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        _write_task(tmp_path, "task_a1b2c3d4", status="need_decision", question_count=2)
        result = json.loads(await tool.execute(task_id="task_a1b2c3d4"))
        assert result["question_count"] == 2
