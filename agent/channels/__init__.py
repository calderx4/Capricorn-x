"""
Channel - 多平台消息通道

职责：
- BaseChannel：所有 chat 平台适配器的抽象基类
- 提供统一的消息收发接口
- 与 CapricornAgent.chat() 无缝对接
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from agent.executor import CapricornAgent

# Channel prompt 文件所在目录（config/prompts/channels/）
_CHANNELS_PROMPT_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "prompts" / "channels"


class BaseChannel(ABC):
    """所有 chat 平台适配器的基类。

    每个 channel 实现：
    - start()：启动连接，开始监听消息
    - stop()：停止连接，清理资源
    - send()：发送消息到平台
    - login()：交互式登录（可选，如微信扫码）

    消息流转：
        平台消息 → _on_message() → _dispatch() → agent.chat() → _send_response()
    """

    name: str = "base"
    display_name: str = "Base"

    def __init__(self, config: Any, agent: "CapricornAgent"):
        self.config = config
        self.agent = agent
        self._running = False
        self._processed_ids: OrderedDict[str, None] = OrderedDict()
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── 生命周期 ──────────────────────────────────────

    @abstractmethod
    async def start(self) -> None:
        """启动 channel（连接平台、监听消息）。"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """停止 channel，清理资源。"""
        ...

    @abstractmethod
    async def send(self, chat_id: str, content: str, **kwargs) -> None:
        """发送消息到平台。

        Args:
            chat_id: 平台侧的会话 ID
            content: 消息文本内容
        """
        ...

    async def login(self, force: bool = False) -> bool:
        """交互式登录（如扫码）。默认无需登录。"""
        return True

    @property
    def is_running(self) -> bool:
        return self._running

    # ── 消息去重 ──────────────────────────────────────

    def _is_duplicate(self, msg_id: str) -> bool:
        """检查消息是否已处理（滑动窗口去重）。"""
        if msg_id in self._processed_ids:
            return True
        self._processed_ids[msg_id] = None
        while len(self._processed_ids) > 1000:
            self._processed_ids.popitem(last=False)
        return False

    # ── Channel Prompt ──────────────────────────────

    def _load_channel_prompt(self) -> str:
        """加载 channel 专属 prompt（config/prompts/channels/<name>.md）。

        如果文件存在则返回内容，否则返回空字符串。
        子类不需要重写此方法，只需确保 `name` 属性正确即可。
        """
        prompt_path = _CHANNELS_PROMPT_DIR / f"{self.name}.md"
        if not prompt_path.exists():
            return ""
        try:
            content = prompt_path.read_text(encoding="utf-8").strip()
            if content:
                logger.debug(f"[{self.name}] Loaded channel prompt ({len(content)} chars)")
            return content
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to load channel prompt: {e}")
            return ""

    # ── 核心调度 ──────────────────────────────────────

    async def _dispatch(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        images: list | None = None,
        metadata: dict | None = None,
    ) -> str | None:
        """统一入口：调用 agent.chat() 并收集最终响应。

        thread_id 编码为 "{channel_name}_{chat_id}"，
        确保不同平台、不同用户的会话互不干扰。

        权限模型（与 nanobot 一致）：
        - allow_from = [] → 拒绝所有
        - allow_from = ["*"] → 允许所有
        - allow_from = ["ou_xxx", "ou_yyy"] → 仅允许列表中的用户
        """
        thread_id = f"{self.name}_{chat_id}"
        # metadata 暂未使用，预留给审计日志 / 速率限制等扩展
        _ = metadata

        # 权限检查
        allow_from = getattr(self.config, "allow_from", [])
        if not allow_from:
            # 空列表 = 拒绝所有（与 nanobot 行为一致）
            logger.warning(f"[{self.name}] allow_from is empty — all access denied")
            return None
        if "*" not in allow_from and sender_id not in allow_from:
            logger.warning(f"[{self.name}] Access denied for sender: {sender_id}")
            return None

        try:
            # 加载 channel 专属 prompt（如飞书格式约束等）
            channel_prompt = self._load_channel_prompt()

            response = await self.agent.chat(
                user_input=content,
                thread_id=thread_id,
                images=images,
                source={"type": self.name, "chat_id": chat_id},
                extra_system_prompt=channel_prompt,
            )

            # 发送回复
            if response and response.strip():
                await self.send(chat_id, response.strip())
                return response

        except Exception as e:
            logger.error(f"[{self.name}] Error processing message: {e}")
            try:
                await self.send(chat_id, "❌ 处理消息时出错，请稍后重试")
            except Exception:
                pass

        return None
