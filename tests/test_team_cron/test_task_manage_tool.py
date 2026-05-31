import importlib.util
import json
import re
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "team_tools",
    "capabilities/tools/builtin/extensions/team_tools.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
TaskManageTool = _mod.TaskManageTool

_TASK_ID_RE = re.compile(r'^task_[a-f0-9]{8}$')


def _make_tool(workspace_root: str) -> TaskManageTool:
    return TaskManageTool(workspace_root)


def _create_task(tool, title="Test Task", **overrides):
    return json.loads(tool._create({"title": title, **overrides}))


def _transition(tool, task_id, status):
    return json.loads(tool._update({"task_id": task_id, "status": status}))


def _reach_status(tool, target):
    """Create a task and drive it through transitions to target status."""
    task = _create_task(tool)
    if target == "producing":
        return task
    task = _transition(tool, task["id"], "running")
    if target == "running":
        return task
    if target == "done":
        return _transition(tool, task["id"], "done")
    if target == "need_decision":
        return _transition(tool, task["id"], "need_decision")
    if target == "error":
        return _transition(tool, task["id"], "error")
    if target == "verifying":
        return _transition(tool, task["id"], "verifying")
    if target == "failed":
        task = _transition(tool, task["id"], "verifying")
        return _transition(tool, task["id"], "failed")
    raise ValueError(f"Cannot reach status: {target}")


class TestTaskCreate:

    def setup_method(self):
        self.tool = _make_tool(str(pytest.tmp_path)) if hasattr(pytest, 'tmp_path') else None

    def test_create_returns_valid_json_structure(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        result = _create_task(tool)
        assert _TASK_ID_RE.fullmatch(result["id"])
        assert result["status"] == "producing"
        assert result["question_count"] == 0
        assert result["max_questions"] == 3
        assert result["attempts"] == 0
        assert result["max_attempts"] == 3
        assert result["assigned_role"] == "executor"
        assert "input" in result
        assert "output_path" in result
        assert "created_at" in result
        assert "updated_at" in result

    def test_create_file_exists_on_disk(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        result = _create_task(tool)
        json_path = tmp_path / "team" / "tasks" / f"{result['id']}.json"
        assert json_path.exists()
        loaded = json.loads(json_path.read_text())
        assert loaded["id"] == result["id"]

    def test_create_task_id_format(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        result = _create_task(tool)
        assert _TASK_ID_RE.fullmatch(result["id"])

    def test_create_with_custom_params(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        result = _create_task(tool, description="desc", assigned_role="verifier", max_attempts=5)
        assert result["input"]["description"] == "desc"
        assert result["assigned_role"] == "verifier"
        assert result["max_attempts"] == 5

    def test_create_default_title(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        result = json.loads(tool._create({}))
        assert result["title"] == "未命名任务"

    def test_create_default_role(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        result = _create_task(tool)
        assert result["assigned_role"] == "executor"


class TestTaskList:

    def test_list_empty(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        result = tool._list({})
        assert result == "没有找到匹配的任务"

    def test_list_multiple(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        t1 = _create_task(tool, title="A")
        t2 = _create_task(tool, title="B")
        t3 = _create_task(tool, title="C")
        result = tool._list({})
        assert t1["id"] in result
        assert t2["id"] in result
        assert t3["id"] in result

    def test_list_filter_by_status(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        t1 = _create_task(tool)
        _transition(tool, t1["id"], "running")
        _create_task(tool)
        result = tool._list({"filter_status": "running"})
        assert t1["id"] in result
        assert "producing" not in result

    def test_list_filter_no_match(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        _create_task(tool)
        result = tool._list({"filter_status": "done"})
        assert result == "没有找到匹配的任务"


class TestTaskGet:

    def test_get_existing_task(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        created = _create_task(tool)
        result = json.loads(tool._get({"task_id": created["id"]}))
        assert result["id"] == created["id"]
        assert result["status"] == "producing"

    def test_get_nonexisting_task(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        result = tool._get({"task_id": "task_00000000"})
        assert "不存在" in result

    def test_get_invalid_id(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        result = tool._get({"task_id": "bad_id"})
        assert "无效" in result

    def test_get_with_questions(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        created = _create_task(tool)
        q_dir = tmp_path / "team" / "tasks" / created["id"] / "questions"
        q_dir.mkdir(parents=True, exist_ok=True)
        (q_dir / "1.json").write_text(json.dumps({"message": "需要确认", "can_continue": False}))
        result = json.loads(tool._get({"task_id": created["id"]}))
        assert "questions" in result
        assert len(result["questions"]) == 1
        assert result["questions"][0]["message"] == "需要确认"

    def test_get_missing_task_id(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        result = tool._get({})
        assert "Error" in result


class TestTaskUpdateValidTransitions:

    def test_producing_to_running(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _create_task(tool)
        result = _transition(tool, task["id"], "running")
        assert result["status"] == "running"

    def test_running_to_done(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "running")
        result = _transition(tool, task["id"], "done")
        assert result["status"] == "done"

    def test_running_to_need_decision(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "running")
        result = _transition(tool, task["id"], "need_decision")
        assert result["status"] == "need_decision"

    def test_running_to_error(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "running")
        result = _transition(tool, task["id"], "error")
        assert result["status"] == "error"

    def test_running_to_verifying(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "running")
        result = _transition(tool, task["id"], "verifying")
        assert result["status"] == "verifying"

    def test_verifying_to_done(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "verifying")
        result = _transition(tool, task["id"], "done")
        assert result["status"] == "done"

    def test_verifying_to_failed(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "verifying")
        result = _transition(tool, task["id"], "failed")
        assert result["status"] == "failed"

    def test_verifying_to_need_decision(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "verifying")
        result = _transition(tool, task["id"], "need_decision")
        assert result["status"] == "need_decision"

    def test_failed_to_producing(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "failed")
        result = _transition(tool, task["id"], "producing")
        assert result["status"] == "producing"

    def test_failed_to_running(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "failed")
        result = _transition(tool, task["id"], "running")
        assert result["status"] == "running"

    def test_need_decision_to_running(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "need_decision")
        result = _transition(tool, task["id"], "running")
        assert result["status"] == "running"

    def test_need_decision_to_producing(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "need_decision")
        result = _transition(tool, task["id"], "producing")
        assert result["status"] == "producing"

    def test_error_to_producing(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "error")
        result = _transition(tool, task["id"], "producing")
        assert result["status"] == "producing"

    def test_error_to_running(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "error")
        result = _transition(tool, task["id"], "running")
        assert result["status"] == "running"


class TestTaskUpdateInvalidTransitions:

    def test_done_to_running_rejected(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "done")
        result = tool._update({"task_id": task["id"], "status": "running"})
        assert "不允许" in result

    def test_done_to_error_rejected(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "done")
        result = tool._update({"task_id": task["id"], "status": "error"})
        assert "不允许" in result

    def test_producing_to_done_rejected(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _create_task(tool)
        result = tool._update({"task_id": task["id"], "status": "done"})
        assert "不允许" in result

    def test_producing_to_error_rejected(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _create_task(tool)
        result = tool._update({"task_id": task["id"], "status": "error"})
        assert "不允许" in result

    def test_running_to_producing_rejected(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "running")
        result = tool._update({"task_id": task["id"], "status": "producing"})
        assert "不允许" in result

    def test_invalid_task_id_format(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        result = tool._update({"task_id": "bad_id", "status": "running"})
        assert "无效" in result

    def test_nonexistent_task_id(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        result = tool._update({"task_id": "task_00000000", "status": "running"})
        assert "不存在" in result

    def test_update_without_status(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _create_task(tool)
        result = tool._update({"task_id": task["id"]})
        assert "Error" in result


class TestTaskUpdateAttemptsTracking:

    def test_attempts_incremented_on_running(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _create_task(tool)
        assert task["attempts"] == 0
        result = _transition(tool, task["id"], "running")
        assert result["attempts"] == 1

    def test_attempts_incremented_on_verifying(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "running")
        result = _transition(tool, task["id"], "verifying")
        assert result["attempts"] == 2

    def test_attempts_not_incremented_on_done(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _reach_status(tool, "running")
        assert task["attempts"] == 1
        result = _transition(tool, task["id"], "done")
        assert result["attempts"] == 1


class TestTaskMaxAttempts:

    def test_max_attempts_triggers_force_done(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _create_task(tool, max_attempts=2)
        tid = task["id"]
        _transition(tool, tid, "running")
        task = _transition(tool, tid, "verifying")
        assert task["attempts"] == 2
        result = _transition(tool, tid, "failed")
        assert result["status"] == "done"
        assert result.get("quality_warning") is True

    def test_max_attempts_not_triggered_below_threshold(self, tmp_path):
        tool = _make_tool(str(tmp_path))
        task = _create_task(tool, max_attempts=3)
        tid = task["id"]
        _transition(tool, tid, "running")
        _transition(tool, tid, "verifying")
        result = _transition(tool, tid, "failed")
        assert result["status"] == "failed"
        assert "quality_warning" not in result
