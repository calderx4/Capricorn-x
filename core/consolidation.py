"""
Memory consolidation 共享逻辑

被 executor.py（主 Agent）和 scheduler.py（cron）共同使用。

触发机制（二选一）：
1. 消息条数 > message_threshold
2. 总 token > token_threshold

切割策略：
- 条数触发 → 保留最后 messages_to_keep 条
- Token 触发 → 保留最近 messages 的 (1 - consolidation_ratio) token 量
- 安全下限：至少保留 5 条（防止过度裁剪）
"""

from pathlib import Path

from loguru import logger

from core import trace
from core.paths import MEMORY_CONSOLIDATION_DIR
from core.utils import load_class_from_file


# 安全下限：无论哪种触发，至少保留这么多条消息
MIN_MESSAGES_TO_KEEP = 5


def _check_trigger(messages: list, mem_config) -> str | None:
    """检查是否触发 consolidation，返回触发原因或 None。"""
    total = len(messages)

    if total > mem_config.message_threshold:
        return f"messages({total} > {mem_config.message_threshold})"

    if mem_config.token_threshold > 0:
        from core.token_counter import TokenCounter
        est_tokens = TokenCounter.count_messages_tokens(messages)
        if est_tokens > mem_config.token_threshold:
            return f"tokens({est_tokens} > {mem_config.token_threshold})"

    return None


def _compute_cut_point(messages: list, mem_config) -> int:
    """根据触发类型计算切割点（返回要保留的消息起始索引）。

    Returns:
        切割点索引。messages[:cut_point] 被整合，messages[cut_point:] 被保留。
        返回 0 表示不切割。
    """
    n = len(messages)

    if n <= MIN_MESSAGES_TO_KEEP:
        return 0

    # 优先级 1：条数触发 → 保留最后 messages_to_keep 条
    if n >= mem_config.message_threshold:
        cut = n - mem_config.messages_to_keep
        return max(0, min(cut, n - MIN_MESSAGES_TO_KEEP))

    # 优先级 2：Token 触发 → 按 ratio 保留
    from core.token_counter import TokenCounter
    token_count = TokenCounter.count_messages_tokens(messages)
    target_tokens = int(token_count * (1 - mem_config.consolidation_ratio))

    # 从尾部累加，找到满足 target_tokens 的最早位置
    accumulated = 0
    keep_from = n
    for i in range(n - 1, -1, -1):
        accumulated += TokenCounter.count_messages_tokens([messages[i]])
        if accumulated >= target_tokens:
            keep_from = i
            break

    # 硬安全下限
    return min(keep_from, n - MIN_MESSAGES_TO_KEEP)


def _adjust_for_tool_calls(messages: list, cut_point: int) -> int:
    """微调切割点，确保：
    1. 不切在 assistant(tool_calls) 和它的 tool 结果之间
    2. 剩余消息以 user 消息开头（避免 WebUI 显示 assistant 打头）
    """
    adjusted = cut_point

    # 如果切在了 tool 结果上，退回对应的 assistant 消息
    while 0 < adjusted < len(messages) and messages[adjusted].get("role") == "tool":
        adjusted -= 1
    adjusted += 1
    # 包含该 assistant 的所有 tool 结果
    while adjusted < len(messages) and messages[adjusted].get("role") == "tool":
        adjusted += 1

    # 确保剩余消息以 user 开头：跳过开头的 assistant 消息
    # 记住调整前位置，若找不到 user 消息则回退（避免清空整个 session）
    before_user_skip = adjusted
    while adjusted < len(messages) and messages[adjusted].get("role") != "user":
        adjusted += 1
    if adjusted >= len(messages):
        # 没有找到 user 消息，回退到跳过前的位置
        adjusted = before_user_skip

    return adjusted


async def consolidate_if_needed(
    session_manager,
    session_id: str,
    messages: list,
    active_dir: Path,
    long_term_memory,
    history_log,
    llm_client,
    mem_config,
    context_label: str = "",
    on_event=None,
) -> bool:
    """检查是否需要整合记忆并执行。

    Args:
        session_manager: 会话管理器
        session_id: 会话 ID
        messages: 当前会话消息列表
        active_dir: 当前垂类目录
        long_term_memory: 长期记忆
        history_log: 历史日志
        llm_client: LLM 客户端
        mem_config: MemoryConfig 对象
        context_label: 日志标签（如 cron 任务名）
        on_event: 事件回调（用于 SSE 通知客户端）

    Returns:
        True = 无需整合或整合成功，False = 整合失败
    """
    if not messages:
        return True

    # 1. 检查触发
    triggered_by = _check_trigger(messages, mem_config)
    if not triggered_by:
        return True

    prefix = f"[{context_label}] " if context_label else ""
    logger.info(f"{prefix}Consolidation triggered by {triggered_by}")

    # 发出 consolidation_start 事件
    if on_event:
        from agent.events import safe_emit
        msg_count = len(messages)
        token_count = sum(len(str(m.get("content", ""))) // 4 for m in messages)
        await safe_emit(on_event, "consolidation_start", {
            "thread_id": session_id,
            "triggered_by": triggered_by,
            "message_count": msg_count,
            "token_count": token_count,
        })

    # 2. 计算切割点
    cut_point = _compute_cut_point(messages, mem_config)
    if cut_point == 0:
        return True
    to_consolidate = messages[:cut_point]

    # 3. 创建 workflow（只做 LLM 总结，不传阈值常量）
    mc_path = MEMORY_CONSOLIDATION_DIR / "__init__.py"
    if not mc_path.exists():
        logger.warning(f"Memory consolidation workflow not found: {mc_path}")
        if on_event:
            await safe_emit(on_event, "consolidation_end", {
                "thread_id": session_id, "success": False,
            })
        return False

    MCWorkflow = load_class_from_file(mc_path, "MemoryConsolidationWorkflow")

    workflow = MCWorkflow(
        long_term_memory=long_term_memory,
        history_log=history_log,
        llm_client=llm_client,
        config={"max_memory_tokens": mem_config.max_memory_tokens},
    )

    # 4. 执行 LLM 总结
    session_data = {"messages_to_consolidate": to_consolidate}
    success = await workflow.execute(session_data=session_data)

    # 5. 成功则裁剪 session
    if success:
        adjusted_cut = _adjust_for_tool_calls(messages, cut_point)
        remaining = messages[adjusted_cut:]
        session_manager.rewrite_session(session_id, remaining)
        trace.consolidation(triggered_by, len(messages), len(remaining), True)
        logger.info(f"{prefix}Consolidated {len(messages)} → {len(remaining)} messages")
    else:
        trace.consolidation(triggered_by, len(messages), len(messages), False)
        logger.warning(f"{prefix}Consolidation failed")

    if on_event:
        await safe_emit(on_event, "consolidation_end", {
            "thread_id": session_id, "success": success,
        })

    return success
