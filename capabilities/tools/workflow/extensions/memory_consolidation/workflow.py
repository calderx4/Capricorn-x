"""
Memory Consolidation Workflow

被动触发，由 core/consolidation.py 调用。

职责：接收待整合消息，调用 LLM 提取关键信息写入 MEMORY.md 和 HISTORY.md。

触发和切割逻辑由 consolidation.py 负责，本模块只做 LLM 总结。
"""

import json
from datetime import datetime
from typing import Any, Dict, List

from loguru import logger

from core.base_workflow import BaseWorkflow
from memory.long_term import LongTermMemory
from memory.history import HistoryLog
from capabilities.tools.workflow.extensions.memory_consolidation.prompts import SAVE_MEMORY_TOOL, build_consolidation_prompt


class MemoryConsolidationWorkflow(BaseWorkflow):
    """记忆整合 Workflow — 只负责 LLM 总结"""

    auto_discover = False  # 依赖复杂，不走自动发现

    @property
    def name(self) -> str:
        return "memory_consolidation"

    @property
    def description(self) -> str:
        return "Consolidate session messages into long-term memory and history log."

    @property
    def required_tools(self) -> List[str]:
        return []

    def __init__(self, long_term_memory: LongTermMemory, history_log: HistoryLog,
                 llm_client, config: Dict = None):
        self.long_term_memory = long_term_memory
        self.history_log = history_log
        self.llm = llm_client
        self._consecutive_failures = 0
        self._max_failures = 3
        self.max_memory_tokens = (config or {}).get("max_memory_tokens", 0)

    async def execute(self, tools: Any = None, **kwargs) -> Any:
        """执行 LLM 总结。期望 session_data 中包含 messages_to_consolidate。"""
        session_data = kwargs.get("session_data", {})
        messages_to_consolidate = session_data.get("messages_to_consolidate", [])

        if not messages_to_consolidate:
            return True

        current_memory = self.long_term_memory.read()
        prompt = build_consolidation_prompt(
            current_memory,
            self._format_messages(messages_to_consolidate),
            max_memory_tokens=self.max_memory_tokens,
        )

        max_retries = 2
        for attempt in range(max_retries):
            try:
                llm_with_tools = self.llm.bind_tools(SAVE_MEMORY_TOOL)

                from langchain_core.messages import HumanMessage
                response = await llm_with_tools.ainvoke([
                    HumanMessage(content=prompt)
                ])

                if not hasattr(response, "tool_calls") or not response.tool_calls:
                    logger.debug(f"Consolidation: no tool_calls (attempt {attempt + 1}), response: {getattr(response, 'content', '')[:200]}")
                    if attempt < max_retries - 1:
                        continue
                    logger.warning("Consolidation: all retries exhausted — LLM never returned tool_calls")
                    return self._fail_or_raw_archive(messages_to_consolidate)

                tool_call = response.tool_calls[0]

                if tool_call.get("name") != "save_memory":
                    logger.debug(f"Consolidation: wrong tool name '{tool_call.get('name')}' (attempt {attempt + 1})")
                    if attempt < max_retries - 1:
                        continue
                    logger.warning(f"Consolidation: all retries exhausted — LLM returned tool '{tool_call.get('name')}' instead of 'save_memory'")
                    return self._fail_or_raw_archive(messages_to_consolidate)

                args = tool_call.get("args", {})
                if isinstance(args, str):
                    args = json.loads(args)

                history_entry = args.get("history_entry", "")
                memory_update = args.get("memory_update", "")

                if not history_entry or not memory_update:
                    logger.debug(f"Consolidation: missing args (attempt {attempt + 1}), keys={list(args.keys())}")
                    if attempt < max_retries - 1:
                        continue
                    logger.warning("Consolidation: all retries exhausted — save_memory args missing history_entry or memory_update")
                    return self._fail_or_raw_archive(messages_to_consolidate)

                self.history_log.append(history_entry)
                if memory_update != current_memory:
                    self.long_term_memory.write(memory_update)

                self._consecutive_failures = 0
                return True

            except Exception as e:
                logger.warning(f"Consolidation LLM error (attempt {attempt + 1}): {type(e).__name__}: {e}")
                if attempt < max_retries - 1:
                    continue
                return self._fail_or_raw_archive(messages_to_consolidate)

        return self._fail_or_raw_archive(messages_to_consolidate)

    def _format_messages(self, messages: List[Dict]) -> str:
        lines = []
        for msg in messages:
            if not msg.get("content"):
                continue
            role = msg.get("role", "unknown").upper()
            content = msg["content"]
            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            timestamp = msg.get("timestamp", "?")[:16]
            tools = f" [tools: {', '.join(msg['tools_used'])}]" if msg.get("tools_used") else ""
            lines.append(f"[{timestamp}] {role}{tools}: {content}")
        return "\n".join(lines)

    def _fail_or_raw_archive(self, messages: List[Dict]) -> bool:
        self._consecutive_failures += 1

        if self._consecutive_failures < self._max_failures:
            return False

        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.history_log.append(
            f"[{ts}] [RAW] {len(messages)} messages\n{self._format_messages(messages)}"
        )
        self._consecutive_failures = 0
        return True
