"""
Memory consolidation 共享逻辑

被 executor.py（主 Agent）和 scheduler.py（cron）共同使用。
"""

from pathlib import Path

from loguru import logger

from core import trace
from core.utils import load_class_from_file


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
        mem_config: MemoryConfig 对象（含 message_threshold / token_threshold 等）
        context_label: 日志标签（如 cron 任务名）

    Returns:
        True = 无需整合或整合成功，False = 整合失败
    """
    if not messages:
        return True

    total = len(messages)
    triggered_by = None

    if total > mem_config.message_threshold:
        triggered_by = f"messages({total} > {mem_config.message_threshold})"

    if not triggered_by and mem_config.token_threshold > 0:
        from core.token_counter import TokenCounter
        est_tokens = TokenCounter.count_messages_tokens(messages)
        if est_tokens > mem_config.token_threshold:
            triggered_by = f"tokens({est_tokens} > {mem_config.token_threshold})"

    if not triggered_by:
        return True

    prefix = f"[{context_label}] " if context_label else ""
    logger.info(f"{prefix}Consolidation triggered by {triggered_by}")

    mc_path = active_dir / "workflows" / "memory_consolidation" / "__init__.py"
    if not mc_path.exists():
        logger.warning(f"Memory consolidation workflow not found: {mc_path}")
        return False

    MCWorkflow = load_class_from_file(mc_path, "MemoryConsolidationWorkflow")

    workflow = MCWorkflow(
        long_term_memory=long_term_memory,
        history_log=history_log,
        llm_client=llm_client,
        config={
            "max_messages": mem_config.message_threshold,
            "messages_to_keep": mem_config.messages_to_keep,
            "max_tokens": mem_config.token_threshold,
            "context_budget": mem_config.context_budget,
        }
    )

    session_data = {"messages": messages}
    success = await workflow.execute(session_data=session_data)

    if success:
        to_consolidate = workflow.get_messages_to_consolidate(session_data)
        cut_point = len(to_consolidate)

        # 向前微调切割点，确保不切在 assistant(tool_calls) 和它的 tool 结果之间
        while cut_point < len(messages) and messages[cut_point].get("role") == "tool":
            cut_point -= 1  # 退到对应的 assistant 消息
        cut_point += 1  # 从 assistant 之后开始
        while cut_point < len(messages) and messages[cut_point].get("role") == "tool":
            cut_point += 1  # 包含该 assistant 的所有 tool 结果

        remaining = messages[cut_point:]
        session_manager.rewrite_session(session_id, remaining)
        trace.consolidation(triggered_by, len(messages), len(remaining), True)
        logger.info(f"{prefix}Consolidated {cut_point} → {len(remaining)} messages")
        return True
    else:
        trace.consolidation(triggered_by, len(messages), len(messages), False)
        logger.warning(f"{prefix}Consolidation failed")
        return False
