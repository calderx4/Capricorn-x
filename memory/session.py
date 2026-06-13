"""
Session Manager - 会话管理

职责：
- 管理会话状态
- JSONL 格式存储（一行一条消息）
- 记忆整合由 hooks/auto_memory_consolidation.py 异步处理
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from loguru import logger

from config.settings import WorkspaceConfig
from core.utils import strip_thinking_tags, atomic_write


def _serialize_message(msg: Dict[str, Any]) -> str:
    """序列化单条消息。保留含 tool_calls 等结构字段的消息（即使 content 为空）。"""
    content = msg.get("content", "")
    if content:
        content = strip_thinking_tags(content)
        msg = {**msg, "content": content}
    has_structural = msg.get("tool_calls") or msg.get("tool_call_id") or msg.get("tools_used")
    if not msg.get("content") and not has_structural:
        return ""
    return json.dumps(msg, ensure_ascii=False) + "\n"


@dataclass
class Session:
    """会话数据"""
    thread_id: str
    messages: List[Dict[str, Any]] = field(default_factory=list)

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        self.messages.append({"role": role, "content": content, **kwargs})

    def get_history(self) -> List[Dict[str, Any]]:
        return list(self.messages)


class SessionManager:
    """会话管理器"""

    def __init__(self, workspace: WorkspaceConfig, **kwargs):
        self.workspace = workspace
        self.session_dir = Path(workspace.root) / workspace.session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[str, Session] = {}
        logger.debug(f"Session directory: {self.session_dir}")

    def get_session(self, thread_id: str) -> Session:
        if thread_id not in self._sessions:
            session = self.load_session(thread_id)
            if session:
                self._sessions[thread_id] = session
            else:
                self._sessions[thread_id] = Session(thread_id=thread_id)
                logger.debug(f"Created new session: {thread_id}")
        return self._sessions[thread_id]

    def get_session_path(self, thread_id: str) -> Path:
        return self.workspace.get_session_path(thread_id)

    def save_session(self, session: Session) -> None:
        try:
            session_path = self.get_session_path(session.thread_id)
            lines = []
            for msg in session.messages:
                line = _serialize_message(msg)
                if line:
                    lines.append(line)
            atomic_write(session_path, "".join(lines))
            logger.debug(f"Saved session: {session.thread_id} ({len(session.messages)} messages)")
        except Exception as e:
            logger.error(f"Failed to save session {session.thread_id}: {e}")
            raise

    def load_session(self, thread_id: str) -> Optional[Session]:
        session_path = self.get_session_path(thread_id)
        if not session_path.exists():
            return None

        try:
            messages = []
            with open(session_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        has_content = data.get("content")
                        has_structural = data.get("tool_calls") or data.get("tool_call_id") or data.get("tools_used")
                        if has_content or has_structural:
                            messages.append(data)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Skipping invalid JSON at line {line_num}: {e}")
                        continue

            session = Session(thread_id=thread_id, messages=messages)
            logger.debug(f"Loaded session: {thread_id} ({len(session.messages)} messages)")
            return session
        except Exception as e:
            logger.error(f"Failed to load session {thread_id}: {e}")
            return None

    def rewrite_session(self, thread_id: str, messages: List[Dict[str, Any]]) -> None:
        """用指定消息列表重写 session 文件，并清除内存缓存。"""
        session_path = self.get_session_path(thread_id)
        lines = []
        for msg in messages:
            line = _serialize_message(msg)
            if line:
                lines.append(line)
        atomic_write(session_path, "".join(lines))
        self._sessions.pop(thread_id, None)

    def clear_session(self, thread_id: str) -> None:
        if thread_id in self._sessions:
            del self._sessions[thread_id]
        session_path = self.get_session_path(thread_id)
        if session_path.exists():
            session_path.unlink()
        logger.debug(f"Cleared session: {thread_id}")
