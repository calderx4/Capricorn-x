"""
ChannelManager - 多平台 Channel 管理器

职责：
- 根据 config 加载和启停所有 channel
- 统一生命周期管理
- 与 Gateway / Run 集成
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from agent.executor import CapricornAgent
    from config.settings import Config

from agent.channels import BaseChannel


class ChannelManager:
    """管理所有启用的 Channel 实例。"""

    def __init__(self, agent: "CapricornAgent", config: "Config"):
        self.agent = agent
        self.config = config
        self.channels: list[BaseChannel] = []
        self._tasks: list[asyncio.Task] = []

    def load_channels(self) -> None:
        """根据配置加载所有启用的 channel。"""
        channels_cfg = getattr(self.config, "channels", None)
        if not channels_cfg:
            return

        # 飞书
        feishu_cfg = getattr(channels_cfg, "feishu", None)
        if feishu_cfg and getattr(feishu_cfg, "enabled", False):
            try:
                from agent.channels.feishu import FeishuChannel
                self.channels.append(FeishuChannel(feishu_cfg, self.agent))
                logger.info("Channel loaded: Feishu")
            except ImportError:
                logger.warning("Feishu channel skipped: lark-oapi not installed. Run: pip install lark-oapi")
            except Exception as e:
                logger.error(f"Failed to load Feishu channel: {e}")

        # 后续在此添加更多 channel：
        # QQ, WeChat, DingTalk, Telegram, Discord ...

        if self.channels:
            logger.info(f"ChannelManager: {len(self.channels)} channel(s) loaded")

    async def send(self, channel_name: str, chat_id: str, message: str) -> bool:
        """通过指定 channel 发送消息（用于 cron 结果推送等场景）。

        Args:
            channel_name: channel 名称（如 "feishu"）
            chat_id: 平台侧的会话 ID
            message: 消息文本内容

        Returns:
            True 发送成功，False 失败（channel 未找到 / 未运行 / 发送异常）
        """
        for ch in self.channels:
            if ch.name == channel_name:
                try:
                    await ch.send(chat_id, message)
                    return True
                except Exception as e:
                    logger.error(f"[ChannelManager] send via '{channel_name}' to {chat_id} failed: {e}")
                    return False
        logger.warning(f"[ChannelManager] channel '{channel_name}' not found")
        return False

    async def start_all(self) -> None:
        """启动所有已加载的 channel。"""
        if not self.channels:
            return

        for ch in self.channels:
            task = asyncio.create_task(self._run_channel(ch))
            self._tasks.append(task)
            logger.info(f"Channel started: {ch.display_name} ({ch.name})")

    async def _run_channel(self, channel: BaseChannel) -> None:
        """运行单个 channel，带自动重连。"""
        retry_count = 0
        max_retries = 5
        base_delay = 5

        while retry_count < max_retries:
            try:
                channel._running = True
                await channel.start()
                # start() 正常退出（被 stop()）
                return
            except asyncio.CancelledError:
                return
            except Exception as e:
                retry_count += 1
                if retry_count >= max_retries:
                    logger.error(
                        f"[{channel.name}] Failed after {max_retries} retries: {e}"
                    )
                    return
                delay = min(base_delay * retry_count, 60)
                logger.warning(
                    f"[{channel.name}] Error (retry {retry_count}/{max_retries}): {e}. "
                    f"Reconnecting in {delay}s..."
                )
                await asyncio.sleep(delay)

    async def stop_all(self) -> None:
        """停止所有 channel。"""
        for ch in self.channels:
            try:
                ch._running = False
                await ch.stop()
                logger.info(f"Channel stopped: {ch.display_name}")
            except Exception as e:
                logger.warning(f"Error stopping channel {ch.name}: {e}")

        # 取消所有运行中的任务
        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._tasks.clear()
