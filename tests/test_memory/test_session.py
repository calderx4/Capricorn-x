import json
import pytest
from pathlib import Path

from config.settings import WorkspaceConfig
from memory.session import Session, SessionManager


class TestSession:
    def test_add_message(self):
        session = Session(thread_id="test")
        session.add_message("user", "hello")
        assert len(session.messages) == 1
        assert session.messages[0]["role"] == "user"
        assert session.messages[0]["content"] == "hello"

    def test_add_message_with_kwargs(self):
        session = Session(thread_id="test")
        session.add_message("assistant", "done", tools_used=["echo"])
        assert session.messages[0]["tools_used"] == ["echo"]

    def test_get_history_all(self):
        session = Session(thread_id="test")
        for i in range(5):
            session.add_message("user", f"msg {i}")
        history = session.get_history()
        assert len(history) == 5

    def test_get_history_limited(self):
        session = Session(thread_id="test")
        for i in range(10):
            session.add_message("user", f"msg {i}")
        history = session.get_history(max_messages=3)
        assert len(history) == 3
        assert history[0]["content"] == "msg 7"


class TestSessionManager:
    def _make_workspace(self, tmp_path):
        return WorkspaceConfig(root=str(tmp_path), session_dir="sessions")

    def test_creates_session_dir(self, tmp_path):
        ws = self._make_workspace(tmp_path)
        SessionManager(ws)
        assert (tmp_path / "sessions").is_dir()

    def test_get_new_session(self, tmp_path):
        mgr = SessionManager(self._make_workspace(tmp_path))
        session = mgr.get_session("new-thread")
        assert session.thread_id == "new-thread"
        assert len(session.messages) == 0

    def test_save_and_load(self, tmp_path):
        mgr = SessionManager(self._make_workspace(tmp_path))
        session = mgr.get_session("test")
        session.add_message("user", "hello")
        session.add_message("assistant", "world")

        mgr.save_session(session)

        loaded = mgr.load_session("test")
        assert loaded is not None
        assert len(loaded.messages) == 2
        assert loaded.messages[0]["content"] == "hello"
        assert loaded.messages[1]["content"] == "world"

    def test_load_nonexistent(self, tmp_path):
        mgr = SessionManager(self._make_workspace(tmp_path))
        assert mgr.load_session("ghost") is None

    def test_clear_session(self, tmp_path):
        mgr = SessionManager(self._make_workspace(tmp_path))
        session = mgr.get_session("to-clear")
        session.add_message("user", "bye")
        mgr.save_session(session)

        mgr.clear_session("to-clear")
        assert mgr.load_session("to-clear") is None

    def test_session_persists_jsonl_format(self, tmp_path):
        mgr = SessionManager(self._make_workspace(tmp_path))
        session = mgr.get_session("jsonl-test")
        session.add_message("user", "test content")
        mgr.save_session(session)

        session_file = tmp_path / "sessions" / "jsonl-test.jsonl"
        assert session_file.exists()
        lines = session_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["role"] == "user"
        assert data["content"] == "test content"
