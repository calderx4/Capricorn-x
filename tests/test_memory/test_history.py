import pytest
from config.settings import WorkspaceConfig
from memory.history import HistoryLog


class TestHistoryLog:
    def _make_history(self, tmp_path):
        ws = WorkspaceConfig(root=str(tmp_path), memory_dir="memory")
        return HistoryLog(ws)

    def test_search(self, tmp_path):
        history = self._make_history(tmp_path)
        history.append("deployed version 1.0")
        history.append("fixed bug in auth")
        history.append("deployed version 1.1")

        results = history.search("deployed")
        assert len(results) == 2

    def test_search_case_insensitive(self, tmp_path):
        history = self._make_history(tmp_path)
        history.append("Deployed Version 1.0")
        results = history.search("deployed")
        assert len(results) == 1

    def test_search_case_sensitive(self, tmp_path):
        history = self._make_history(tmp_path)
        history.append("Deployed Version 1.0")
        results = history.search("deployed", case_sensitive=True)
        assert len(results) == 0
