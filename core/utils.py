"""
Core utilities - 共享工具函数
"""

import importlib.util
import os
import re
import tempfile
import uuid
from pathlib import Path


def strip_thinking_tags(text: str) -> str:
    """移除 <thinking>...</thinking> 标签及其内容"""
    return re.sub(r"<thinking>.*?</thinking>\s*", "", text, flags=re.DOTALL).strip()


def atomic_write(path: Path, content: str) -> None:
    """原子写入：先写临时文件，再 rename 替换。防止崩溃时截断。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, str(path))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def short_id() -> str:
    """生成 8 字符短 ID"""
    return uuid.uuid4().hex[:8]


def compute_excluded_tools(all_tool_names: list, role_tools, must_exclude: tuple) -> list:
    """根据角色工具白名单计算要排除的工具列表。

    Args:
        all_tool_names: 所有可用工具名称列表
        role_tools: 角色配置的工具（"all"、列表、或 None）
        must_exclude: 必须排除的工具名称元组
    """
    if role_tools == "all" or not role_tools:
        return list(must_exclude)
    excluded = [t for t in all_tool_names if t not in role_tools]
    for t in must_exclude:
        if t not in excluded:
            excluded.append(t)
    return excluded


def load_class_from_file(path, class_name):
    """从指定 Python 文件加载一个类。

    Args:
        path: Python 文件路径（Path 或 str）
        class_name: 要加载的类名

    Returns:
        类对象

    Raises:
        AttributeError: 文件中不存在指定类名
    """
    path = Path(path)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, class_name)


def load_module_from_file(path):
    """从指定 Python 文件加载整个模块。

    Args:
        path: Python 文件路径（Path 或 str）

    Returns:
        模块对象
    """
    path = Path(path)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
