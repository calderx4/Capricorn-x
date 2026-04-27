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
from datetime import datetime
from loguru import logger

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import WorkspaceConfig
from core.utils import strip_thinking_tags


@dataclass
class Session:
    """会话数据类"""

    thread_id: str
    messages: List[Dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """
        添加消息

        Args:
            role: 角色（user/assistant）
            content: 消息内容
            **kwargs: 其他字段
        """
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 0) -> List[Dict[str, Any]]:
        """
        获取消息历史

        Args:
            max_messages: 最大消息数，0 表示加载所有消息

        Returns:
            消息列表（所有消息都是未整合的短期记忆）
        """
        if max_messages > 0:
            return self.messages[-max_messages:]

        return self.messages


class SessionManager:
    """会话管理器"""

    def __init__(self, workspace: WorkspaceConfig, **kwargs):
        """
        初始化会话管理器

        Args:
            workspace: 工作空间配置
        """
        self.workspace = workspace
        self.session_dir = Path(workspace.root) / workspace.session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)

        # 内存中的会话缓存
        self._sessions: Dict[str, Session] = {}

        logger.debug(f"Session directory: {self.session_dir}")

    def get_session(self, thread_id: str) -> Session:
        """
        获取或创建会话

        Args:
            thread_id: 会话 ID

        Returns:
            会话对象
        """
        if thread_id not in self._sessions:
            session = self.load_session(thread_id)
            if session:
                self._sessions[thread_id] = session
            else:
                self._sessions[thread_id] = Session(thread_id=thread_id)
                logger.debug(f"Created new session: {thread_id}")

        return self._sessions[thread_id]

    def get_session_path(self, thread_id: str) -> Path:
        """
        获取会话文件路径

        Args:
            thread_id: 会话 ID

        Returns:
            会话文件路径
        """
        return self.workspace.get_session_path(thread_id)

    def save_session(self, session: Session) -> None:
        """
        保存会话到文件（纯写入，不触发整合）

        Args:
            session: 会话对象
        """
        try:
            session_path = self.get_session_path(session.thread_id)
            session_path.parent.mkdir(parents=True, exist_ok=True)

            # 写入文件（覆盖模式）
            with open(session_path, "w", encoding="utf-8") as f:
                for msg in session.messages:
                    content = msg.get("content", "")
                    if content:
                        content = strip_thinking_tags(content)
                        msg = {**msg, "content": content}
                    if msg.get("content"):
                        f.write(json.dumps(msg, ensure_ascii=False) + "\n")

            session.updated_at = datetime.now()
            logger.debug(f"Saved session: {session.thread_id} ({len(session.messages)} messages)")

        except Exception as e:
            logger.error(f"Failed to save session {session.thread_id}: {e}")
            raise

    def load_session(self, thread_id: str) -> Optional[Session]:
        """
        从文件加载会话

        Args:
            thread_id: 会话 ID

        Returns:
            会话对象，不存在则返回 None
        """
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
                        if data.get("content"):
                            messages.append(data)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Skipping invalid JSON at line {line_num}: {e}")
                        continue

            session = Session(
                thread_id=thread_id,
                messages=messages,
                created_at=datetime.now()
            )

            logger.debug(f"Loaded session: {thread_id} ({len(session.messages)} messages)")

            return session

        except Exception as e:
            logger.error(f"Failed to load session {thread_id}: {e}")
            return None

    def rewrite_session(self, thread_id: str, messages: List[Dict[str, Any]]) -> None:
        """
        用指定消息列表重写 session 文件，并清除内存缓存。

        用于记忆整合后裁剪 session。
        """
        session_path = self.get_session_path(thread_id)
        session_path.parent.mkdir(parents=True, exist_ok=True)

        with open(session_path, "w", encoding="utf-8") as f:
            for msg in messages:
                content = msg.get("content", "")
                if content:
                    content = strip_thinking_tags(content)
                    msg = {**msg, "content": content}
                if msg.get("content"):
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        self._sessions.pop(thread_id, None)

    def clear_session(self, thread_id: str) -> None:
        """
        清除会话

        Args:
            thread_id: 会话 ID
        """
        if thread_id in self._sessions:
            del self._sessions[thread_id]

        session_path = self.get_session_path(thread_id)
        if session_path.exists():
            session_path.unlink()

        logger.debug(f"Cleared session: {thread_id}")
