"""
Tests for agent/notification.py — NotificationBus
"""

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from agent.notification import NotificationBus


@pytest.fixture
def bus(tmp_path):
    """NotificationBus with path redirected to tmp_path."""
    b = NotificationBus()
    b._path = tmp_path / "notifications.jsonl"
    b._path.parent.mkdir(parents=True, exist_ok=True)
    return b


def _write_notifications(path, notifications):
    """Helper: write a list of notification dicts to JSONL file."""
    with open(path, "w", encoding="utf-8") as f:
        for n in notifications:
            f.write(json.dumps(n, ensure_ascii=False) + "\n")


class TestPublish:
    async def test_publish_appends_to_file(self, bus):
        await bus.publish("test_event", {"key": "value"})
        content = bus._path.read_text(encoding="utf-8")
        assert "test_event" in content
        assert "key" in content

    async def test_publish_has_required_fields(self, bus):
        await bus.publish("test_event", {"key": "value"})
        lines = bus._path.read_text(encoding="utf-8").strip().split("\n")
        n = json.loads(lines[0])
        assert "id" in n
        assert n["type"] == "test_event"
        assert n["data"] == {"key": "value"}
        assert "timestamp" in n
        assert n["read"] is False

    async def test_publish_id_is_8_chars(self, bus):
        await bus.publish("test_event", {})
        lines = bus._path.read_text(encoding="utf-8").strip().split("\n")
        n = json.loads(lines[0])
        assert len(n["id"]) == 8

    async def test_publish_pushes_to_subscribers(self, bus):
        q = bus.subscribe()
        await bus.publish("test_event", {"x": 1})
        notification = q.get_nowait()
        assert notification["type"] == "test_event"

    async def test_publish_to_multiple_subscribers(self, bus):
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        await bus.publish("test_event", {})
        assert q1.get_nowait()["type"] == "test_event"
        assert q2.get_nowait()["type"] == "test_event"


class TestSubscribeUnsubscribe:
    def test_subscribe_returns_queue(self, bus):
        q = bus.subscribe()
        assert isinstance(q, asyncio.Queue)

    def test_unsubscribe_removes_queue(self, bus):
        q = bus.subscribe()
        assert q in bus._subscribers
        bus.unsubscribe(q)
        assert q not in bus._subscribers

    def test_unsubscribe_nonexistent_safe(self, bus):
        q = asyncio.Queue()
        bus.unsubscribe(q)  # should not raise

    async def test_subscriber_receives_events(self, bus):
        q = bus.subscribe()
        await bus.publish("alert", {"msg": "hello"})
        n = q.get_nowait()
        assert n["data"]["msg"] == "hello"


class TestGetUnread:
    def test_empty_file_returns_empty(self, bus):
        assert bus.get_unread() == []

    def test_returns_only_unread(self, bus):
        _write_notifications(bus._path, [
            {"id": "a", "type": "t", "data": {}, "timestamp": datetime.now().isoformat(), "read": True},
            {"id": "b", "type": "t", "data": {}, "timestamp": datetime.now().isoformat(), "read": False},
        ])
        unread = bus.get_unread()
        assert len(unread) == 1
        assert unread[0]["id"] == "b"

    def test_all_read_returns_empty(self, bus):
        _write_notifications(bus._path, [
            {"id": "a", "type": "t", "data": {}, "timestamp": datetime.now().isoformat(), "read": True},
        ])
        assert bus.get_unread() == []


class TestMarkRead:
    async def test_mark_read_updates_status(self, bus):
        await bus.publish("test", {})
        nid = bus._load_all()[0]["id"]
        await bus.mark_read([nid])
        assert bus._load_all()[0]["read"] is True

    async def test_mark_read_empty_ids_noop(self, bus):
        await bus.publish("test", {})
        await bus.mark_read([])
        assert bus._load_all()[0]["read"] is False

    async def test_mark_read_idempotent(self, bus):
        await bus.publish("test", {})
        nid = bus._load_all()[0]["id"]
        await bus.mark_read([nid])
        await bus.mark_read([nid])  # second call should not error
        assert bus._load_all()[0]["read"] is True

    async def test_mark_read_partial_match(self, bus):
        await bus.publish("test", {})
        await bus.publish("test", {})
        ids = [n["id"] for n in bus._load_all()]
        await bus.mark_read([ids[0]])  # only first
        all_n = bus._load_all()
        assert all_n[0]["read"] is True
        assert all_n[1]["read"] is False


class TestGetRecent:
    def test_returns_recent_n(self, bus):
        notifications = [
            {"id": str(i), "type": "t", "data": {}, "timestamp": datetime.now().isoformat(), "read": False}
            for i in range(30)
        ]
        _write_notifications(bus._path, notifications)
        recent = bus.get_recent(limit=10)
        assert len(recent) == 10

    def test_unread_only_filter(self, bus):
        notifications = [
            {"id": str(i), "type": "t", "data": {}, "timestamp": datetime.now().isoformat(), "read": i < 5}
            for i in range(10)
        ]
        _write_notifications(bus._path, notifications)
        recent = bus.get_recent(limit=20, unread_only=True)
        assert all(not n.get("read") for n in recent)
        assert len(recent) == 5

    def test_empty_file_returns_empty(self, bus):
        assert bus.get_recent() == []


class TestCleanup:
    def test_removes_old_read_notifications(self, bus):
        old_ts = (datetime.now() - timedelta(days=10)).isoformat()
        _write_notifications(bus._path, [
            {"id": "old", "type": "t", "data": {}, "timestamp": old_ts, "read": True},
            {"id": "new", "type": "t", "data": {}, "timestamp": datetime.now().isoformat(), "read": False},
        ])
        bus.cleanup(max_age_days=7)
        remaining = bus._load_all()
        assert len(remaining) == 1
        assert remaining[0]["id"] == "new"

    def test_keeps_unread_regardless_of_age(self, bus):
        old_ts = (datetime.now() - timedelta(days=30)).isoformat()
        _write_notifications(bus._path, [
            {"id": "old_unread", "type": "t", "data": {}, "timestamp": old_ts, "read": False},
        ])
        bus.cleanup(max_age_days=7)
        remaining = bus._load_all()
        assert len(remaining) == 1

    def test_noop_when_no_file(self, bus):
        # _path may not exist
        if bus._path.exists():
            bus._path.unlink()
        bus.cleanup()  # should not raise

    def test_keeps_recently_read(self, bus):
        _write_notifications(bus._path, [
            {"id": "recent_read", "type": "t", "data": {}, "timestamp": datetime.now().isoformat(), "read": True},
        ])
        bus.cleanup(max_age_days=7)
        remaining = bus._load_all()
        assert len(remaining) == 1


class TestLoadTail:
    def test_handles_corrupt_json_lines(self, bus):
        with open(bus._path, "w", encoding="utf-8") as f:
            f.write('{"id":"a","type":"t","data":{},"timestamp":"2026-01-01","read":false}\n')
            f.write("not valid json\n")
            f.write('{"id":"b","type":"t","data":{},"timestamp":"2026-01-01","read":false}\n')
        recent = bus.get_recent(limit=10)
        assert len(recent) == 2
