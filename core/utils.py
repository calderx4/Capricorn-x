"""
Core utilities - 共享工具函数
"""

import re


def strip_thinking_tags(text: str) -> str:
    """移除 <thinking>...</thinking> 标签及其内容"""
    return re.sub(r"<thinking>.*?</thinking>\s*", "", text, flags=re.DOTALL).strip()
