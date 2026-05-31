import importlib.util
import json
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

_spec = importlib.util.spec_from_file_location(
    "team_tools",
    "capabilities/tools/builtin/extensions/team_tools.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
SpawnTool = _mod.SpawnTool


def _make_mock_tool(name):
    t = MagicMock()
    t.name = name
    return t


def _make_spawn_tool(tmp_path, roles=None):
    mock_registry = MagicMock()
    mock_registry.get_langchain_tools.return_value = [
        _make_mock_tool("read_file"),
        _make_mock_tool("write_file"),
        _make_mock_tool("exec"),
        _make_mock_tool("list_files"),
    ]
    if roles is None:
        executor_template = tmp_path / "executor.md"
        executor_template.write_text("# Executor\n{{task_prompt}}\n{{workspace_section}}")
        verifier_template = tmp_path / "verifier.md"
        verifier_template.write_text("# Verifier\n{{task_prompt}}\n{{workspace_section}}")
        roles = {
            "executor": {
                "prompt_path": str(executor_template),
                "tools": "all",
            },
            "verifier": {
                "prompt_path": str(verifier_template),
                "tools": ["read_file", "list_files"],
            },
        }
    return SpawnTool(
        llm_client=MagicMock(),
        capability_registry=mock_registry,
        skill_manager=MagicMock(),
        long_term_memory=MagicMock(),
        roles=roles,
        bia_path="",
        workspace_root=str(tmp_path),
        max_questions=3,
    )


class TestSpawnToolBasic:

    @pytest.mark.asyncio
    async def test_successful_spawn_returns_task_id(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        with patch.object(SpawnTool, "_run_agent", new_callable=AsyncMock):
            result = json.loads(await tool.execute(role="executor", prompt="Do something"))
        assert "task_id" in result
        assert result["status"] == _mod.STATUS_PRODUCING
        task_dir = tmp_path / "team" / "tasks" / result["task_id"]
        assert task_dir.exists()

    @pytest.mark.asyncio
    async def test_spawn_creates_brief_md(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        with patch.object(SpawnTool, "_run_agent", new_callable=AsyncMock):
            result = json.loads(await tool.execute(role="executor", prompt="Analyze data"))
        brief = tmp_path / "team" / "tasks" / result["task_id"] / "brief.md"
        assert brief.exists()
        assert "Analyze data" in brief.read_text()

    @pytest.mark.asyncio
    async def test_spawn_creates_task_json(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        with patch.object(SpawnTool, "_run_agent", new_callable=AsyncMock):
            result = json.loads(await tool.execute(role="executor", prompt="Do something"))
        task_json = tmp_path / "team" / "tasks" / f"{result['task_id']}.json"
        assert task_json.exists()
        task = json.loads(task_json.read_text())
        assert task["status"] == _mod.STATUS_PRODUCING
        assert task["assigned_role"] == "executor"
        assert task["attempts"] == 0

    @pytest.mark.asyncio
    async def test_spawn_creates_questions_dir(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        with patch.object(SpawnTool, "_run_agent", new_callable=AsyncMock):
            result = json.loads(await tool.execute(role="executor", prompt="Do something"))
        q_dir = tmp_path / "team" / "tasks" / result["task_id"] / "questions"
        assert q_dir.exists()
        assert q_dir.is_dir()


class TestSpawnToolValidation:

    @pytest.mark.asyncio
    async def test_invalid_role_returns_error(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        result = await tool.execute(role="nonexistent", prompt="Do something")
        assert "Error" in result
        assert "未知角色" in result

    @pytest.mark.asyncio
    async def test_missing_prompt_path_returns_error(self, tmp_path):
        roles = {
            "executor": {"prompt_path": "/nonexistent/path.md", "tools": "all"},
        }
        tool = _make_spawn_tool(tmp_path, roles=roles)
        result = await tool.execute(role="executor", prompt="Do something")
        assert "Error" in result
        assert "不存在" in result


class TestBuildTaskPrompt:

    def test_includes_task_id(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        result = tool._build_task_prompt("Do X", "task_abc12345")
        assert "task_abc12345" in result

    def test_includes_questions_path(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        result = tool._build_task_prompt("Do X", "task_abc12345")
        assert "team/tasks/task_abc12345/questions/" in result

    def test_includes_max_questions(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        result = tool._build_task_prompt("Do X", "task_abc12345")
        assert "3" in result  # max_questions=3

    def test_includes_original_prompt(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        result = tool._build_task_prompt("Analyze sales data", "task_abc12345")
        assert "Analyze sales data" in result


class TestComputeExcludedTools:

    def test_default_exclusions(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        role = tool._roles["executor"]
        excluded = tool._compute_excluded_tools(role)
        for name in _mod.MUST_EXCLUDE_TOOLS:
            assert name in excluded

    def test_verifier_whitelist(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        role = tool._roles["verifier"]
        excluded = tool._compute_excluded_tools(role)
        assert "read_file" not in excluded
        assert "list_files" not in excluded
        assert "write_file" in excluded
        assert "exec" in excluded
        for name in _mod.MUST_EXCLUDE_TOOLS:
            assert name in excluded

    def test_no_tool_list_means_all(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        role = {"tools": None}
        excluded = tool._compute_excluded_tools(role)
        assert set(excluded) == set(_mod.MUST_EXCLUDE_TOOLS)


class TestRunAgentSuccess:

    @pytest.mark.asyncio
    async def test_success_writes_result_md(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        with patch.object(SpawnTool, "_run_agent", new_callable=AsyncMock):
            spawn_result = json.loads(await tool.execute(role="executor", prompt="Do something"))
        task_id = spawn_result["task_id"]

        # Simulate _run_agent completing: write result and update status
        result_path = tmp_path / "team" / "tasks" / task_id / "result.md"
        result_path.write_text("Task completed successfully")
        task_json_path = tmp_path / "team" / "tasks" / f"{task_id}.json"
        task = json.loads(task_json_path.read_text())
        task["status"] = _mod.STATUS_DONE
        task["question_count"] = 0
        task_json_path.write_text(json.dumps(task))

        assert result_path.exists()
        assert "Task completed successfully" in result_path.read_text()

    @pytest.mark.asyncio
    async def test_success_updates_to_done(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        with patch.object(SpawnTool, "_run_agent", new_callable=AsyncMock):
            spawn_result = json.loads(await tool.execute(role="executor", prompt="Do something"))
        task_id = spawn_result["task_id"]

        # Simulate agent success
        result_path = tmp_path / "team" / "tasks" / task_id / "result.md"
        result_path.write_text("Done")
        task_json_path = tmp_path / "team" / "tasks" / f"{task_id}.json"
        task = json.loads(task_json_path.read_text())
        task["status"] = _mod.STATUS_DONE
        task_json_path.write_text(json.dumps(task))

        task = json.loads(task_json_path.read_text())
        assert task["status"] == _mod.STATUS_DONE

    @pytest.mark.asyncio
    async def test_with_questions_updates_to_need_decision(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        with patch.object(SpawnTool, "_run_agent", new_callable=AsyncMock):
            spawn_result = json.loads(await tool.execute(role="executor", prompt="Do something"))
        task_id = spawn_result["task_id"]

        # Write a question file
        q_dir = tmp_path / "team" / "tasks" / task_id / "questions"
        q_dir.mkdir(parents=True, exist_ok=True)
        (q_dir / "1.json").write_text(json.dumps({"message": "Need info", "can_continue": False}))

        # Simulate status update
        task_json_path = tmp_path / "team" / "tasks" / f"{task_id}.json"
        task = json.loads(task_json_path.read_text())
        task["status"] = _mod.STATUS_NEED_DECISION
        task["question_count"] = 1
        task_json_path.write_text(json.dumps(task))

        task = json.loads(task_json_path.read_text())
        assert task["status"] == _mod.STATUS_NEED_DECISION
        assert task["question_count"] == 1

    @pytest.mark.asyncio
    async def test_question_count(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        with patch.object(SpawnTool, "_run_agent", new_callable=AsyncMock):
            spawn_result = json.loads(await tool.execute(role="executor", prompt="Do something"))
        task_id = spawn_result["task_id"]

        q_dir = tmp_path / "team" / "tasks" / task_id / "questions"
        q_dir.mkdir(parents=True, exist_ok=True)
        (q_dir / "1.json").write_text(json.dumps({"message": "Q1", "can_continue": False}))
        (q_dir / "2.json").write_text(json.dumps({"message": "Q2", "can_continue": False}))

        count = len(list(q_dir.glob("*.json")))
        assert count == 2


class TestRunAgentError:

    @pytest.mark.asyncio
    async def test_error_updates_task_to_error_status(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        with patch.object(SpawnTool, "_run_agent", new_callable=AsyncMock):
            spawn_result = json.loads(await tool.execute(role="executor", prompt="Do something"))
        task_id = spawn_result["task_id"]

        # Simulate error
        task_json_path = tmp_path / "team" / "tasks" / f"{task_id}.json"
        task = json.loads(task_json_path.read_text())
        task["status"] = _mod.STATUS_ERROR
        task["error"] = "Something went wrong"
        task_json_path.write_text(json.dumps(task))

        task = json.loads(task_json_path.read_text())
        assert task["status"] == _mod.STATUS_ERROR
        assert "Something went wrong" in task["error"]

    @pytest.mark.asyncio
    async def test_error_message_truncated(self, tmp_path):
        tool = _make_spawn_tool(tmp_path)
        with patch.object(SpawnTool, "_run_agent", new_callable=AsyncMock):
            spawn_result = json.loads(await tool.execute(role="executor", prompt="Do something"))
        task_id = spawn_result["task_id"]

        long_error = "x" * 1000
        task_json_path = tmp_path / "team" / "tasks" / f"{task_id}.json"
        task = json.loads(task_json_path.read_text())
        task["status"] = _mod.STATUS_ERROR
        task["error"] = long_error[:500]
        task_json_path.write_text(json.dumps(task))

        task = json.loads(task_json_path.read_text())
        assert len(task["error"]) <= 500
