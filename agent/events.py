"""
Events — FC Loop 执行事件系统

职责：
- 定义事件回调类型
- QueueEventSink: SSE 端点用，事件推入 asyncio.Queue
- PrintEventSink: CLI 模式用，事件 print 到 stdout
"""

import asyncio
import contextvars
from typing import Callable, Optional, Awaitable, Dict, Any

from loguru import logger

# 事件回调类型: (event_type: str, data: dict) -> Awaitable[None]
EventCallback = Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]]

# 当前请求的 on_event 回调（通过 context variable 传递给工具层）
current_on_event: contextvars.ContextVar[EventCallback] = contextvars.ContextVar(
    "current_on_event", default=None
)


async def safe_emit(on_event: EventCallback, event_type: str, data: dict):
    """安全发出事件，永不让事件发射打断调用方。
    所有 _emit 调用点统一使用此函数。"""
    if on_event:
        try:
            await on_event(event_type, data)
        except Exception as e:
            logger.debug(f"Event emission failed: {e}")


# ── 进度格式化（Gateway._append_progress 和 PrintEventSink 共用） ──────

_STATUS_ICONS = {"pending": "⬜", "in_progress": "🔄", "completed": "✅"}


def format_progress_line(event_type: str, data: dict) -> str | None:
    """将事件格式化为进度行。返回 None 表示该事件不产生进度行。"""
    if event_type == "thinking":
        return f"🧠 思考中... (第 {data.get('round', '?')} 轮)"

    if event_type == "tool_call_start":
        name = data.get("tool_name", "?")
        args = data.get("tool_args_preview", "")
        return f"🔧 {name}({args})" if args else f"🔧 {name}(...)"

    if event_type == "tool_call_end":
        name = data.get("tool_name", "?")
        latency = data.get("latency_ms", 0)
        status = data.get("status", "ok")
        icon = "✅" if status == "ok" else ("⏱️" if status == "timeout" else "❌")
        return f"{icon} {name} 完成 ({latency}ms)"

    if event_type == "round_end":
        round_n = data.get("round", "?")
        tc = data.get("tool_count", 0)
        return f"📊 第 {round_n} 轮完成 ({tc} 个工具)"

    if event_type == "consolidation_start":
        triggered_by = data.get("triggered_by", "")
        msg_count = data.get("message_count", 0)
        return f"🗜️ 记忆压缩中... ({triggered_by}, {msg_count} 条消息)"

    if event_type == "consolidation_end":
        success = data.get("success", True)
        icon = "✅" if success else "❌"
        return f"{icon} 记忆压缩{'完成' if success else '失败'}"

    if event_type == "tasklist_update":
        items = data.get("items", [])
        if items:
            tl = []
            for item in items:
                ic = _STATUS_ICONS.get(item.get("status"), "⬜")
                tl.append(f"{ic} {item.get('activeForm') or item.get('content', '')}")
            return "📋 " + " | ".join(tl)

    return None


class QueueEventSink:
    """将事件推入 asyncio.Queue，供 SSE 端点消费"""

    def __init__(self, maxsize: int = 200):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._done = asyncio.Event()

    async def emit(self, event_type: str, data: dict):
        """发出一个事件"""
        try:
            self.queue.put_nowait({"type": event_type, "data": data})
        except asyncio.QueueFull:
            logger.warning(f"QueueEventSink: dropped event '{event_type}' (queue full)")

    def mark_done(self):
        """标记执行完成，用于通知 SSE 流结束"""
        self._done.set()


class PrintEventSink:
    """CLI 模式用：将事件 print 到 stdout"""

    async def emit(self, event_type: str, data: dict):
        """发出一个事件，同步 print"""
        line = format_progress_line(event_type, data)

        if line is not None:
            print(f"  {line}")
            return

        # round_end 在 CLI 中额外显示延迟
        if event_type == "round_end":
            round_n = data.get("round", "?")
            tool_count = data.get("tool_count", 0)
            latency = data.get("latency_ms", 0)
            if tool_count > 0:
                print(f"  📊 第 {round_n} 轮完成: {tool_count} 个工具, {latency}ms")

        # tasklist_update 在 CLI 中用多行展示
        if event_type == "tasklist_update":
            items = data.get("items", [])
            if items:
                print("  📋 任务进度：")
                for item in items:
                    icon = _STATUS_ICONS.get(item.get("status"), "⬜")
                    label = item.get("activeForm") or item.get("content", "")
                    print(f"    {icon} {label}")

        # run_start, round_start, response, run_end 不在 CLI 中打印
        # response 内容由调用方在外层打印（保持 🤖 Assistant: 格式）
