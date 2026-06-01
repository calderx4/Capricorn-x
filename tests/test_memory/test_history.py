import pytest
from config.settings import WorkspaceConfig
from memory.history import HistoryLog


class TestHistoryLog:
    def _make_history(self, tmp_path, max_entries=100):
        ws = WorkspaceConfig(root=str(tmp_path), memory_dir="memory")
        return HistoryLog(ws, max_entries=max_entries)

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


class TestHistoryAppend:
    def test_append_creates_file(self, tmp_path):
        history = self._make_history(tmp_path)
        history.append("[2026-01-01] first entry")
        assert history.file_path.exists()

    def test_append_adds_entry(self, tmp_path):
        history = self._make_history(tmp_path)
        history.append("[2026-01-01] first entry")
        content = history.file_path.read_text(encoding="utf-8")
        assert "first entry" in content

    def test_append_multiple_entries(self, tmp_path):
        history = self._make_history(tmp_path)
        history.append("[2026-01-01] entry 1")
        history.append("[2026-01-02] entry 2")
        history.append("[2026-01-03] entry 3")
        content = history.file_path.read_text(encoding="utf-8")
        assert "entry 1" in content
        assert "entry 2" in content
        assert "entry 3" in content

    def test_append_empty_entry(self, tmp_path):
        history = self._make_history(tmp_path)
        history.append("")
        # Should not crash, file should exist
        assert history.file_path.exists()

    def _make_history(self, tmp_path, max_entries=100):
        ws = WorkspaceConfig(root=str(tmp_path), memory_dir="memory")
        return HistoryLog(ws, max_entries=max_entries)


class TestHistoryPrune:
    def _make_history(self, tmp_path, max_entries=100):
        ws = WorkspaceConfig(root=str(tmp_path), memory_dir="memory")
        return HistoryLog(ws, max_entries=max_entries)

    def test_no_prune_under_limit(self, tmp_path):
        history = self._make_history(tmp_path, max_entries=10)
        for i in range(5):
            history.append(f"[2026-01-{i+1:02d}] entry {i}")
        content = history.file_path.read_text(encoding="utf-8")
        # All 5 entries should still be there
        assert content.count("[2026-") == 5

    def test_prune_removes_oldest(self, tmp_path):
        history = self._make_history(tmp_path, max_entries=5)
        for i in range(10):
            history.append(f"[2026-01-{i+1:02d}] entry {i}")
        content = history.file_path.read_text(encoding="utf-8")
        # After 10 appends with max=5, incremental pruning keeps the newest ~5
        assert "[2026-01-10]" in content  # newest always present
        assert "[2026-01-01]" not in content  # oldest pruned

    def test_prune_preserves_recent_entries(self, tmp_path):
        history = self._make_history(tmp_path, max_entries=3)
        for i in range(6):
            history.append(f"[2026-01-{i+1:02d}] entry {i}")
        content = history.file_path.read_text(encoding="utf-8")
        assert "entry 5" in content
        assert "entry 4" in content
        assert "entry 3" in content
        assert "entry 0" not in content

    def test_prune_disabled_when_max_zero(self, tmp_path):
        history = self._make_history(tmp_path, max_entries=0)
        for i in range(10):
            history.append(f"[2026-01-{i+1:02d}] entry {i}")
        content = history.file_path.read_text(encoding="utf-8")
        # All entries should be present (pruning disabled)
        assert content.count("[2026-") == 10

    def test_prune_only_counts_entry_lines(self, tmp_path):
        history = self._make_history(tmp_path, max_entries=2)
        # Non-entry lines (no [2 prefix) should not be counted
        history.file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(history.file_path, "w", encoding="utf-8") as f:
            f.write("header line\n")
            f.write("[2026-01-01] old entry\n")
            f.write("middle comment\n")
            f.write("[2026-01-02] mid entry\n")
            f.write("[2026-01-03] new entry\n")
        # Trigger prune by appending
        history.append("[2026-01-04] latest")
        content = history.file_path.read_text(encoding="utf-8")
        # Should keep newest 2 entry lines ([2026-01-03] and [2026-01-04])
        assert "[2026-01-04]" in content
        assert "[2026-01-03]" in content
        assert "[2026-01-01]" not in content


class TestHistorySearchEdgeCases:
    def _make_history(self, tmp_path, max_entries=100):
        ws = WorkspaceConfig(root=str(tmp_path), memory_dir="memory")
        return HistoryLog(ws, max_entries=max_entries)

    def test_search_empty_file(self, tmp_path):
        history = self._make_history(tmp_path)
        # Create empty file
        history.file_path.parent.mkdir(parents=True, exist_ok=True)
        history.file_path.write_text("", encoding="utf-8")
        results = history.search("anything")
        assert results == []

    def test_search_nonexistent_file(self, tmp_path):
        history = self._make_history(tmp_path)
        # Don't create file — search should return []
        assert not history.file_path.exists()
        results = history.search("anything")
        assert results == []

    def test_search_no_results(self, tmp_path):
        history = self._make_history(tmp_path)
        history.append("[2026-01-01] deployed v1")
        results = history.search("nonexistent_keyword")
        assert results == []
