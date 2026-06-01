import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from agent.scheduler import CronScheduler, _infer_type


def _make_config(tmp_path):
    config = MagicMock()
    config.workspace = MagicMock()
    config.workspace.root = str(tmp_path / "workspace")
    config.cron = MagicMock()
    config.cron.tick_interval = 60
    config.cron.fresh_session = False
    config.memory = MagicMock()
    config.memory.enabled = False
    config.agent = {}
    return config


def _make_scheduler(tmp_path):
    config = _make_config(tmp_path)
    s = CronScheduler(config)
    # Override GATEWAY_DIR-based paths to use tmp_path for isolation
    gw = tmp_path / "gateway"
    s.jobs_path = gw / "jobs.json"
    s.lock_path = gw / ".tick.lock"
    s.output_dir = gw / "output"
    s.workspaces_dir = gw / "workspaces"
    # Set attributes that initialize() would normally set
    s._notification_bus = None
    s._capability_registry = None
    return s


def _write_jobs(scheduler, jobs):
    scheduler._save_jobs(jobs)


class TestCreateJob:

    @pytest.mark.asyncio
    async def test_create_returns_valid_job_dict(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 1h", name="test")
        assert len(job["id"]) == 8
        assert job["type"] == "recurring"
        assert job["schedule"] == "every 1h"
        assert job["prompt"] == "Do X"
        assert job["status"] == "active"
        assert job["name"] == "test"
        assert "next_run_at" in job
        assert "created_at" in job

    @pytest.mark.asyncio
    async def test_create_persists_to_jobs_json(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 1h", name="test")
        assert s.jobs_path.exists()
        jobs = json.loads(s.jobs_path.read_text())
        assert len(jobs) == 1
        assert jobs[0]["id"] == job["id"]

    @pytest.mark.asyncio
    async def test_create_workspace_dir(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 1h", name="test")
        assert Path(job["workdir"]).exists()

    @pytest.mark.asyncio
    async def test_create_infers_type_once(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="30m", name="test")
        assert job["type"] == "once"

    @pytest.mark.asyncio
    async def test_create_infers_type_recurring(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 30m", name="test")
        assert job["type"] == "recurring"

    @pytest.mark.asyncio
    async def test_create_explicit_type_overrides(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 30m", name="test", type="once")
        assert job["type"] == "once"

    @pytest.mark.asyncio
    async def test_create_sanitizes_workdir_name(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 1h", name="test job! special#chars")
        assert "test_job__special_chars" in job["workdir"]


class TestListAndGetJobs:

    @pytest.mark.asyncio
    async def test_list_empty(self, tmp_path):
        s = _make_scheduler(tmp_path)
        assert s.list_jobs() == []

    @pytest.mark.asyncio
    async def test_list_after_create(self, tmp_path):
        s = _make_scheduler(tmp_path)
        await s.create_job(prompt="A", schedule="every 1h", name="a")
        await s.create_job(prompt="B", schedule="every 2h", name="b")
        assert len(s.list_jobs()) == 2

    @pytest.mark.asyncio
    async def test_get_existing(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 1h", name="test")
        found = s.get_job(job["id"])
        assert found is not None
        assert found["id"] == job["id"]

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, tmp_path):
        s = _make_scheduler(tmp_path)
        assert s.get_job("nonexistent") is None


class TestUpdateJob:

    @pytest.mark.asyncio
    async def test_update_partial(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 1h", name="test")
        updated = await s.update_job(job["id"], name="renamed")
        assert updated["name"] == "renamed"
        assert updated["schedule"] == "every 1h"

    @pytest.mark.asyncio
    async def test_update_recalc_next_run(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 1h", name="test")
        old_next = job["next_run_at"]
        updated = await s.update_job(job["id"], schedule="every 2h")
        # next_run_at should change (both future, but different)
        assert updated["next_run_at"] != old_next

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, tmp_path):
        s = _make_scheduler(tmp_path)
        result = await s.update_job("nonexistent", name="x")
        assert result is None


class TestPauseResumeJob:

    @pytest.mark.asyncio
    async def test_pause_sets_status(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 1h", name="test")
        paused = await s.pause_job(job["id"])
        assert paused["status"] == "paused"

    @pytest.mark.asyncio
    async def test_resume_sets_active(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 1h", name="test")
        await s.pause_job(job["id"])
        resumed = await s.resume_job(job["id"])
        assert resumed["status"] == "active"

    @pytest.mark.asyncio
    async def test_resume_recalc_next_run(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 1h", name="test")
        await s.pause_job(job["id"])
        resumed = await s.resume_job(job["id"])
        # next_run_at should be in the future
        next_run = datetime.fromisoformat(resumed["next_run_at"])
        assert next_run > datetime.now() - timedelta(seconds=5)

    @pytest.mark.asyncio
    async def test_pause_nonexistent(self, tmp_path):
        s = _make_scheduler(tmp_path)
        assert await s.pause_job("nonexistent") is None

    @pytest.mark.asyncio
    async def test_resume_nonexistent(self, tmp_path):
        s = _make_scheduler(tmp_path)
        assert await s.resume_job("nonexistent") is None


class TestRemoveJob:

    @pytest.mark.asyncio
    async def test_remove_existing(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 1h", name="test")
        assert await s.remove_job(job["id"]) is True
        assert s.get_job(job["id"]) is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent(self, tmp_path):
        s = _make_scheduler(tmp_path)
        assert await s.remove_job("nonexistent") is False


class TestRunJobNow:

    @pytest.mark.asyncio
    async def test_run_now_sets_next_run_to_now(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 1h", name="test")
        triggered = await s.run_job_now(job["id"])
        next_run = datetime.fromisoformat(triggered["next_run_at"])
        assert abs((datetime.now() - next_run).total_seconds()) < 5

    @pytest.mark.asyncio
    async def test_run_now_unpauses(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 1h", name="test")
        await s.pause_job(job["id"])
        triggered = await s.run_job_now(job["id"])
        assert triggered["status"] == "active"

    @pytest.mark.asyncio
    async def test_run_now_nonexistent(self, tmp_path):
        s = _make_scheduler(tmp_path)
        assert await s.run_job_now("nonexistent") is None


class TestTick:

    @pytest.mark.asyncio
    async def test_tick_marks_expired_jobs_as_queued(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 1h", name="test")
        # Set next_run_at to past
        jobs = s._load_jobs()
        jobs[0]["next_run_at"] = (datetime.now() - timedelta(minutes=5)).isoformat()
        s._save_jobs(jobs)

        with patch.object(s, "_execute_job", new_callable=AsyncMock, return_value="ok"):
            await s.tick()

        # After tick, job should have been executed and updated
        updated = s.get_job(job["id"])
        assert updated["last_run_status"] == "success"

    @pytest.mark.asyncio
    async def test_tick_skips_active_future_jobs(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 1h", name="test")
        # next_run_at is already in the future
        with patch.object(s, "_execute_job", new_callable=AsyncMock) as mock_exec:
            await s.tick()
            mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_skips_paused_jobs(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 1h", name="test")
        await s.pause_job(job["id"])
        # Force next_run_at to past
        jobs = s._load_jobs()
        jobs[0]["next_run_at"] = (datetime.now() - timedelta(minutes=5)).isoformat()
        s._save_jobs(jobs)

        with patch.object(s, "_execute_job", new_callable=AsyncMock) as mock_exec:
            await s.tick()
            mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_marks_once_as_completed(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="30m", name="test")
        jobs = s._load_jobs()
        jobs[0]["next_run_at"] = (datetime.now() - timedelta(minutes=1)).isoformat()
        s._save_jobs(jobs)

        with patch.object(s, "_execute_job", new_callable=AsyncMock, return_value="ok"):
            await s.tick()

        updated = s.get_job(job["id"])
        assert updated["status"] == "completed"

    @pytest.mark.asyncio
    async def test_tick_recurring_resets_next_run(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 30m", name="test")
        jobs = s._load_jobs()
        jobs[0]["next_run_at"] = (datetime.now() - timedelta(minutes=1)).isoformat()
        s._save_jobs(jobs)

        with patch.object(s, "_execute_job", new_callable=AsyncMock, return_value="ok"):
            await s.tick()

        updated = s.get_job(job["id"])
        assert updated["status"] == "active"
        next_run = datetime.fromisoformat(updated["next_run_at"])
        assert next_run > datetime.now()


class TestUpdateNextRunInline:

    def test_once_completes(self, tmp_path):
        s = _make_scheduler(tmp_path)
        jobs = [{"id": "j1", "type": "once", "schedule": "30m", "status": "running"}]
        s._update_next_run_inline(jobs, "j1", "success")
        assert jobs[0]["status"] == "completed"

    def test_recurring_resets_to_active(self, tmp_path):
        s = _make_scheduler(tmp_path)
        jobs = [{"id": "j1", "type": "recurring", "schedule": "every 30m", "status": "running"}]
        s._update_next_run_inline(jobs, "j1", "success")
        assert jobs[0]["status"] == "active"
        next_run = datetime.fromisoformat(jobs[0]["next_run_at"])
        assert next_run > datetime.now()

    def test_end_at_expires(self, tmp_path):
        s = _make_scheduler(tmp_path)
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        jobs = [{"id": "j1", "type": "recurring", "schedule": "every 30m",
                 "status": "running", "end_at": past}]
        s._update_next_run_inline(jobs, "j1", "success")
        assert jobs[0]["status"] == "completed"

    def test_repeat_decrements(self, tmp_path):
        s = _make_scheduler(tmp_path)
        jobs = [{"id": "j1", "type": "recurring", "schedule": "every 30m",
                 "status": "running", "repeat": 2}]
        s._update_next_run_inline(jobs, "j1", "success")
        assert jobs[0]["repeat"] == 1
        assert jobs[0]["status"] == "active"

    def test_repeat_reaches_zero(self, tmp_path):
        s = _make_scheduler(tmp_path)
        jobs = [{"id": "j1", "type": "recurring", "schedule": "every 30m",
                 "status": "running", "repeat": 1}]
        s._update_next_run_inline(jobs, "j1", "success")
        assert jobs[0]["repeat"] == 0
        assert jobs[0]["status"] == "completed"


class TestRecoverJobs:

    def test_recover_resets_queued_to_active(self, tmp_path):
        s = _make_scheduler(tmp_path)
        jobs = [{"id": "j1", "status": "queued", "schedule": "every 1h"}]
        _write_jobs(s, jobs)
        s._recover_jobs()
        recovered = s._load_jobs()
        assert recovered[0]["status"] == "active"

    def test_recover_resets_running_to_active(self, tmp_path):
        s = _make_scheduler(tmp_path)
        jobs = [{"id": "j1", "status": "running", "schedule": "every 1h"}]
        _write_jobs(s, jobs)
        s._recover_jobs()
        recovered = s._load_jobs()
        assert recovered[0]["status"] == "active"

    def test_recover_ignores_other_statuses(self, tmp_path):
        s = _make_scheduler(tmp_path)
        jobs = [
            {"id": "j1", "status": "active", "schedule": "every 1h"},
            {"id": "j2", "status": "paused", "schedule": "every 1h"},
            {"id": "j3", "status": "completed", "schedule": "30m"},
        ]
        _write_jobs(s, jobs)
        s._recover_jobs()
        recovered = s._load_jobs()
        assert recovered[0]["status"] == "active"
        assert recovered[1]["status"] == "paused"
        assert recovered[2]["status"] == "completed"


class TestComputeExcludeTools:

    def test_default_excludes_cron_and_spawn(self, tmp_path):
        s = _make_scheduler(tmp_path)
        excluded = s._compute_exclude_tools(None)
        assert "cron" in excluded
        assert "spawn" in excluded

    def test_role_with_all_tools(self, tmp_path):
        s = _make_scheduler(tmp_path)
        s._roles = {"executor": {"tools": "all"}}
        excluded = s._compute_exclude_tools("executor")
        assert set(excluded) == {"cron", "spawn"}

    def test_role_with_whitelist(self, tmp_path):
        s = _make_scheduler(tmp_path)
        mock_tools = [MagicMock(name="read_file"), MagicMock(name="write_file"), MagicMock(name="exec")]
        mock_tools[0].name = "read_file"
        mock_tools[1].name = "write_file"
        mock_tools[2].name = "exec"
        s._capability_registry = MagicMock()
        s._capability_registry.get_langchain_tools.return_value = mock_tools
        s._roles = {"verifier": {"tools": ["read_file"]}}
        excluded = s._compute_exclude_tools("verifier")
        assert "read_file" not in excluded
        assert "write_file" in excluded
        assert "exec" in excluded
        assert "cron" in excluded
        assert "spawn" in excluded


class TestFilePersistence:

    def test_load_jobs_missing_file(self, tmp_path):
        s = _make_scheduler(tmp_path)
        assert s._load_jobs() == []

    def test_load_jobs_corrupt_json(self, tmp_path):
        s = _make_scheduler(tmp_path)
        s.jobs_path.parent.mkdir(parents=True, exist_ok=True)
        s.jobs_path.write_text("not json{{{")
        result = s._load_jobs()
        assert result == []
        # Backup should exist
        assert s.jobs_path.with_suffix(".json.bak").exists()

    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self, tmp_path):
        s = _make_scheduler(tmp_path)
        job = await s.create_job(prompt="Do X", schedule="every 1h", name="test")
        loaded = s._load_jobs()
        assert len(loaded) == 1
        assert loaded[0]["id"] == job["id"]
        assert loaded[0]["prompt"] == "Do X"
        assert loaded[0]["name"] == "test"
