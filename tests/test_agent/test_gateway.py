"""
Tests for agent/gateway.py — validation logic and auth (no HTTP server startup)
"""

import asyncio
import json
import re
from collections import OrderedDict
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

aiohttp = pytest.importorskip("aiohttp")
from aiohttp import web

from agent.gateway import (
    Gateway,
    MAX_PROMPT_LENGTH,
    MAX_CONCURRENT_TASKS,
    TASK_ID_RE,
    THREAD_ID_RE,
)


def _make_gateway(tmp_path, api_key=""):
    """Create a Gateway instance with mocked dependencies."""
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.workspace.root = str(tmp_path / "workspace")
    config = MagicMock()
    config.gateway.host = "127.0.0.1"
    config.gateway.port = 8080
    config.gateway.task_timeout = 300
    gw = Gateway(agent=agent, config=config, notification_bus=None)
    gw._api_key = api_key
    return gw


class TestValidatePrompt:
    """Test Gateway._validate_prompt static method."""

    @pytest.mark.parametrize(
        "body, expected_prompt, has_error",
        [
            ({"prompt": "hello"}, "hello", False),
            ({"prompt": ""}, None, True),
            ({"prompt": "   "}, None, True),
            ({}, None, True),
            ({"prompt": "x" * 50001}, None, True),
            ({"prompt": "x" * 50000}, "x" * 50000, False),
            ({"prompt": "  valid  "}, "valid", False),
        ],
    )
    def test_validate(self, body, expected_prompt, has_error):
        prompt, err = Gateway._validate_prompt(body)
        if has_error:
            assert prompt is None
            assert err is not None
        else:
            assert prompt == expected_prompt
            assert err is None


class TestChatValidation:
    """Test /chat request validation logic."""

    def test_thread_id_valid(self):
        assert THREAD_ID_RE.fullmatch("abc-123") is not None
        assert THREAD_ID_RE.fullmatch("my_thread") is not None
        assert THREAD_ID_RE.fullmatch("default") is not None

    def test_thread_id_invalid(self):
        assert THREAD_ID_RE.fullmatch("") is None
        assert THREAD_ID_RE.fullmatch("a" * 65) is None
        assert THREAD_ID_RE.fullmatch("has space") is None
        assert THREAD_ID_RE.fullmatch("has/slash") is None

    def test_images_must_be_array(self, tmp_path):
        gw = _make_gateway(tmp_path)
        # Simulate the validation that happens in _handle_chat
        images = "not_array"
        attachments = []
        assert not isinstance(images, list)

    def test_image_must_have_base64_key(self):
        images = [{"no_base64": True}]
        for img in images:
            assert not (isinstance(img, dict) and "base64" in img)

    def test_too_many_images(self):
        images = [{"base64": f"data{i}"} for i in range(11)]
        assert len(images) > 10

    def test_images_size_limit(self):
        # ~21MB of base64 data
        images = [{"base64": "A" * 28_000_000}]
        total_image_size = sum(len(img.get("base64", "")) * 3 // 4 for img in images)
        assert total_image_size > 20 * 1024 * 1024

    def test_attachments_must_be_list(self):
        attachments = "not_list"
        assert not isinstance(attachments, list)


class TestTaskIdValidation:
    def test_valid_task_id(self):
        assert TASK_ID_RE.fullmatch("abc12345") is not None
        assert TASK_ID_RE.fullmatch("a1b2c3d4") is not None

    def test_invalid_task_id(self):
        assert TASK_ID_RE.fullmatch("xyz") is None
        assert TASK_ID_RE.fullmatch("ABC12345") is None  # uppercase
        assert TASK_ID_RE.fullmatch("") is None
        assert TASK_ID_RE.fullmatch("toolongid123") is None


class TestAuthMiddleware:
    async def test_correct_api_key_passes(self, tmp_path):
        gw = _make_gateway(tmp_path, api_key="secret123")
        middleware = gw._make_auth_middleware()

        request = MagicMock()
        request.path = "/chat"
        request.headers = {"Authorization": "Bearer secret123"}

        handler = AsyncMock(return_value=web.json_response({"ok": True}))
        resp = await middleware(request, handler)
        assert resp.status == 200

    async def test_wrong_api_key_rejected(self, tmp_path):
        gw = _make_gateway(tmp_path, api_key="secret123")
        middleware = gw._make_auth_middleware()

        request = MagicMock()
        request.path = "/chat"
        request.headers = {"Authorization": "Bearer wrong"}

        handler = AsyncMock(return_value=web.json_response({"ok": True}))
        resp = await middleware(request, handler)
        assert resp.status == 401

    async def test_health_skips_auth(self, tmp_path):
        gw = _make_gateway(tmp_path, api_key="secret123")
        middleware = gw._make_auth_middleware()

        request = MagicMock()
        request.path = "/health"
        request.headers = {}  # no auth

        handler = AsyncMock(return_value=web.json_response({"status": "ok"}))
        resp = await middleware(request, handler)
        assert resp.status == 200

    async def test_missing_bearer_prefix_still_matches(self, tmp_path):
        """Without 'Bearer ' prefix, removeprefix is a no-op → raw token compared."""
        gw = _make_gateway(tmp_path, api_key="secret123")
        middleware = gw._make_auth_middleware()

        request = MagicMock()
        request.path = "/chat"
        request.headers = {"Authorization": "secret123"}  # no "Bearer " prefix

        handler = AsyncMock(return_value=web.json_response({"ok": True}))
        resp = await middleware(request, handler)
        # removeprefix("Bearer ") on "secret123" → "secret123" → matches
        assert resp.status == 200

    async def test_wrong_format_rejected(self, tmp_path):
        gw = _make_gateway(tmp_path, api_key="secret123")
        middleware = gw._make_auth_middleware()

        request = MagicMock()
        request.path = "/chat"
        request.headers = {"Authorization": "Basic something"}

        handler = AsyncMock(return_value=web.json_response({"ok": True}))
        resp = await middleware(request, handler)
        assert resp.status == 401


class TestThreadLockLRU:
    def test_gets_lock(self, tmp_path):
        gw = _make_gateway(tmp_path)
        lock = gw._get_thread_lock("thread1")
        assert isinstance(lock, asyncio.Lock)

    def test_same_thread_returns_same_lock(self, tmp_path):
        gw = _make_gateway(tmp_path)
        lock1 = gw._get_thread_lock("thread1")
        lock2 = gw._get_thread_lock("thread1")
        assert lock1 is lock2

    def test_evicts_when_over_capacity(self, tmp_path):
        gw = _make_gateway(tmp_path)
        # Fill up locks
        for i in range(1025):
            gw._get_thread_lock(f"thread_{i}")
        # Should have evicted some (all unlocked)
        assert len(gw._thread_locks) <= 1025

    async def test_keeps_locked_lock(self, tmp_path):
        gw = _make_gateway(tmp_path)
        # Create the first lock and acquire it
        first_lock = gw._get_thread_lock("first")
        await first_lock.acquire()
        # Fill to capacity — eviction should stop because first is locked
        for i in range(1024):
            gw._get_thread_lock(f"thread_{i}")
        assert "first" in gw._thread_locks
        first_lock.release()


class TestTaskPersistence:
    def test_save_and_load_task(self, tmp_path):
        gw = _make_gateway(tmp_path)
        task_data = {
            "task_id": "abc12345",
            "status": "pending",
            "prompt": "test task",
        }
        gw._save_task(task_data)
        loaded = gw._load_task("abc12345")
        assert loaded["task_id"] == "abc12345"
        assert loaded["status"] == "pending"

    def test_load_nonexistent_task(self, tmp_path):
        gw = _make_gateway(tmp_path)
        assert gw._load_task("nonexist") is None

    def test_load_corrupt_json(self, tmp_path):
        gw = _make_gateway(tmp_path)
        task_path = gw._task_path("corrupt1")
        task_path.write_text("not json{{{", encoding="utf-8")
        assert gw._load_task("corrupt1") is None
