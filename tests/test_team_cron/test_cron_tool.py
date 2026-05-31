import importlib.util
import json
from unittest.mock import MagicMock, AsyncMock

import pytest

_spec = importlib.util.spec_from_file_location(
    "cron_tools",
    "capabilities/tools/builtin/extensions/cron_tools.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
CronTool = _mod.CronTool


def _make_cron_tool():
    scheduler = MagicMock()
    scheduler.create_job = AsyncMock(return_value={
        "id": "abc12345", "name": "test", "type": "recurring",
        "schedule": "every 1h", "status": "active",
    })
    scheduler.list_jobs.return_value = []
    scheduler.update_job = AsyncMock(return_value={
        "id": "abc12345", "name": "updated", "status": "active",
    })
    scheduler.pause_job = AsyncMock(return_value={
        "id": "abc12345", "name": "test", "status": "paused",
    })
    scheduler.resume_job = AsyncMock(return_value={
        "id": "abc12345", "name": "test", "status": "active",
    })
    scheduler.run_job_now = AsyncMock(return_value={
        "id": "abc12345", "name": "test", "status": "active",
    })
    scheduler.remove_job = AsyncMock(return_value=True)
    tool = CronTool(scheduler)
    return tool, scheduler


class TestCronToolCreate:

    @pytest.mark.asyncio
    async def test_create_success(self):
        tool, _ = _make_cron_tool()
        result = await tool.execute(action="create", prompt="Do X", schedule="every 1h")
        assert "定时任务已创建" in result

    @pytest.mark.asyncio
    async def test_create_missing_prompt(self):
        tool, _ = _make_cron_tool()
        result = await tool.execute(action="create", schedule="every 1h")
        assert "Error" in result
        assert "prompt" in result

    @pytest.mark.asyncio
    async def test_create_missing_schedule(self):
        tool, _ = _make_cron_tool()
        result = await tool.execute(action="create", prompt="Do X")
        assert "Error" in result
        assert "schedule" in result


class TestCronToolList:

    @pytest.mark.asyncio
    async def test_list_with_jobs(self):
        tool, scheduler = _make_cron_tool()
        scheduler.list_jobs.return_value = [
            {"id": "a", "name": "job1", "status": "active"},
            {"id": "b", "name": "job2", "status": "active"},
        ]
        result = await tool.execute(action="list")
        assert "共 2 个定时任务" in result

    @pytest.mark.asyncio
    async def test_list_empty(self):
        tool, _ = _make_cron_tool()
        result = await tool.execute(action="list")
        assert "当前没有定时任务" in result


class TestCronToolUpdate:

    @pytest.mark.asyncio
    async def test_update_success(self):
        tool, _ = _make_cron_tool()
        result = await tool.execute(action="update", job_id="abc12345", schedule="every 2h")
        assert "定时任务已更新" in result

    @pytest.mark.asyncio
    async def test_update_missing_job_id(self):
        tool, _ = _make_cron_tool()
        result = await tool.execute(action="update", schedule="every 2h")
        assert "Error" in result
        assert "job_id" in result

    @pytest.mark.asyncio
    async def test_update_not_found(self):
        tool, scheduler = _make_cron_tool()
        scheduler.update_job = AsyncMock(return_value=None)
        result = await tool.execute(action="update", job_id="nonexistent", schedule="every 2h")
        assert "not found" in result


class TestCronToolPause:

    @pytest.mark.asyncio
    async def test_pause_success(self):
        tool, _ = _make_cron_tool()
        result = await tool.execute(action="pause", job_id="abc12345")
        assert "已暂停" in result

    @pytest.mark.asyncio
    async def test_pause_missing_job_id(self):
        tool, _ = _make_cron_tool()
        result = await tool.execute(action="pause")
        assert "Error" in result
        assert "job_id" in result

    @pytest.mark.asyncio
    async def test_pause_not_found(self):
        tool, scheduler = _make_cron_tool()
        scheduler.pause_job = AsyncMock(return_value=None)
        result = await tool.execute(action="pause", job_id="nonexistent")
        assert "not found" in result


class TestCronToolResume:

    @pytest.mark.asyncio
    async def test_resume_success(self):
        tool, _ = _make_cron_tool()
        result = await tool.execute(action="resume", job_id="abc12345")
        assert "已恢复" in result

    @pytest.mark.asyncio
    async def test_resume_missing_job_id(self):
        tool, _ = _make_cron_tool()
        result = await tool.execute(action="resume")
        assert "Error" in result
        assert "job_id" in result


class TestCronToolRun:

    @pytest.mark.asyncio
    async def test_run_success(self):
        tool, _ = _make_cron_tool()
        result = await tool.execute(action="run", job_id="abc12345")
        assert "已触发" in result

    @pytest.mark.asyncio
    async def test_run_missing_job_id(self):
        tool, _ = _make_cron_tool()
        result = await tool.execute(action="run")
        assert "Error" in result
        assert "job_id" in result


class TestCronToolRemove:

    @pytest.mark.asyncio
    async def test_remove_success(self):
        tool, _ = _make_cron_tool()
        result = await tool.execute(action="remove", job_id="abc12345")
        assert "已删除" in result

    @pytest.mark.asyncio
    async def test_remove_not_found(self):
        tool, scheduler = _make_cron_tool()
        scheduler.remove_job = AsyncMock(return_value=False)
        result = await tool.execute(action="remove", job_id="nonexistent")
        assert "not found" in result


class TestCronToolUnknownAction:

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self):
        tool, _ = _make_cron_tool()
        result = await tool.execute(action="bogus")
        assert "Unknown action" in result
