"""
Tests for core/utils.py
"""

import os
import re
from pathlib import Path

import pytest

from core.utils import (
    strip_thinking_tags,
    atomic_write,
    short_id,
    compute_excluded_tools,
    load_class_from_file,
    load_module_from_file,
)


class TestStripThinkingTags:
    @pytest.mark.parametrize(
        "input_text, expected",
        [
            ("<thinking>inner</thinking>result", "result"),
            ("<thinking>a</thinking>x<thinking>b</thinking>y", "xy"),
            ("<thinking>\nline1\nline2\n</thinking>output", "output"),
            ("plain text", "plain text"),
            ("", ""),
            ("no tags here at all", "no tags here at all"),
            ("<thinking>only thinking</thinking>", ""),
            ("before<thinking>mid</thinking>after", "beforeafter"),
        ],
    )
    def test_strip(self, input_text, expected):
        assert strip_thinking_tags(input_text) == expected


class TestAtomicWrite:
    def test_writes_file_content(self, tmp_path):
        target = tmp_path / "test.txt"
        atomic_write(target, "hello world")
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "a" / "b" / "c" / "file.txt"
        atomic_write(target, "nested")
        assert target.read_text(encoding="utf-8") == "nested"

    def test_overwrites_existing(self, tmp_path):
        target = tmp_path / "test.txt"
        atomic_write(target, "first")
        atomic_write(target, "second")
        assert target.read_text(encoding="utf-8") == "second"

    def test_cleanup_on_error(self, tmp_path):
        target = tmp_path / "test.txt"
        target.write_text("original", encoding="utf-8")
        # Force write failure by making target a directory
        target.unlink()
        target.mkdir()
        with pytest.raises(OSError):
            atomic_write(target, "fail")
        # Temp files should be cleaned up — directory still exists (it's the target)
        tmp_files = list(target.parent.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_unicode_content(self, tmp_path):
        target = tmp_path / "unicode.txt"
        content = "你好世界 🌍 مرحبا"
        atomic_write(target, content)
        assert target.read_text(encoding="utf-8") == content


class TestShortId:
    def test_returns_8_chars(self):
        sid = short_id()
        assert len(sid) == 8

    def test_hex_chars_only(self):
        for _ in range(50):
            assert re.match(r"^[0-9a-f]{8}$", short_id())

    def test_unique(self):
        ids = {short_id() for _ in range(100)}
        assert len(ids) == 100


class TestComputeExcludedTools:
    @pytest.mark.parametrize(
        "all_tools, role_tools, must_exclude, expected",
        [
            # role_tools="all" → only must_exclude
            (["a", "b", "c"], "all", ("cron", "spawn"), ["cron", "spawn"]),
            # role_tools=None → only must_exclude
            (["a", "b", "c"], None, ("cron",), ["cron"]),
            # specific whitelist → complement + must_exclude
            (["a", "b", "c"], ["a", "b"], ("cron",), ["c", "cron"]),
            # must_exclude item already excluded — no duplicate
            (["a", "b", "c"], ["a"], ("b",), ["b", "c"]),
            # empty role_tools list → only must_exclude
            (["a", "b"], [], ("cron",), ["cron"]),
            # empty all_tools
            ([], "all", ("cron",), ["cron"]),
        ],
    )
    def test_compute(self, all_tools, role_tools, must_exclude, expected):
        result = compute_excluded_tools(all_tools, role_tools, must_exclude)
        assert sorted(result) == sorted(expected)


class TestLoadClassFromFile:
    def test_loads_class_successfully(self, tmp_path):
        py_file = tmp_path / "mymodule.py"
        py_file.write_text(
            "class MyClass:\n    value = 42\n",
            encoding="utf-8",
        )
        cls = load_class_from_file(str(py_file), "MyClass")
        assert cls.value == 42

    def test_attribute_error_on_missing_class(self, tmp_path):
        py_file = tmp_path / "mymodule.py"
        py_file.write_text("x = 1\n", encoding="utf-8")
        with pytest.raises(AttributeError):
            load_class_from_file(str(py_file), "NonExistent")

    def test_accepts_path_object(self, tmp_path):
        py_file = tmp_path / "mymodule.py"
        py_file.write_text("class Foo:\n    pass\n", encoding="utf-8")
        cls = load_class_from_file(py_file, "Foo")
        assert cls.__name__ == "Foo"


class TestLoadModuleFromFile:
    def test_loads_module(self, tmp_path):
        py_file = tmp_path / "helper.py"
        py_file.write_text(
            "def greet(name):\n    return f'hello {name}'\n",
            encoding="utf-8",
        )
        mod = load_module_from_file(str(py_file))
        assert mod.greet("world") == "hello world"

    def test_accepts_path_object(self, tmp_path):
        py_file = tmp_path / "helper.py"
        py_file.write_text("VALUE = 99\n", encoding="utf-8")
        mod = load_module_from_file(py_file)
        assert mod.VALUE == 99
