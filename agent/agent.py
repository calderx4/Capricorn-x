"""
Agent - 原生 Function Calling 循环

职责：
- 构建 System Prompt
- FC 循环：LLM 调用 → 工具执行 → 终止判断
- 并发工具执行
- 迭代上限和熔断保护
"""

import asyncio
from datetime import datetime
from typing import Dict

from langchain_core.messages import (
    HumanMessage, AIMessage, SystemMessage, ToolMessage, BaseMessage,
)
from loguru import logger

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.utils import strip_thinking_tags


class CapricornGraph:
    """Capricorn Agent — 原生 Function Calling 循环"""

    MAX_ITERATIONS = 50

    def __init__(
        self,
        capability_registry,
        skill_manager,
        session_manager,
        long_term_memory,
        history_log,
        llm_client=None,
        sandbox: bool = True,
    ):
        self.capability_registry = capability_registry
        self.skill_manager = skill_manager
        self.session_manager = session_manager
        self.long_term_memory = long_term_memory
        self.history_log = history_log
        self.llm_client = llm_client
        self.sandbox = sandbox

        # 预绑定工具
        if self.llm_client:
            tools = self.capability_registry.get_langchain_tools()
            self._tool_map = {t.name: t for t in tools}
            self._llm_with_tools = self.llm_client.bind_tools(tools)
        else:
            self._tool_map = {}
            self._llm_with_tools = None
            logger.warning("LLM client not initialized")

    async def run(self, user_input: str, thread_id: str = "default") -> str:
        """运行 FC 循环"""
        logger.info(f"Running agent with thread_id: {thread_id}")

        session = self.session_manager.get_session(thread_id)

        system_prompt = self._build_system_prompt()
        history_messages = session.get_history(max_messages=0)

        messages = [
            SystemMessage(content=system_prompt),
            *[self._dict_to_message(msg) for msg in history_messages],
            HumanMessage(content=user_input),
        ]

        session.add_message("user", user_input)

        if not self._llm_with_tools:
            return "LLM 客户端未初始化"

        tools_used = []

        try:
            for i in range(self.MAX_ITERATIONS):
                logger.info(f"Thinking... (iteration {i + 1})")
                response = await self._llm_with_tools.ainvoke(messages)
                messages.append(response)

                if not (hasattr(response, "tool_calls") and response.tool_calls):
                    break

                tool_names = [tc["name"] for tc in response.tool_calls]
                logger.info(f"Tool calls: {tool_names}")

                # 并发执行工具
                tool_messages = await self._execute_tools(response.tool_calls)
                messages.extend(tool_messages)
                tools_used.extend(tool_names)

            final_response = self._extract_content(messages[-1])
            session.add_message("assistant", final_response, tools_used=tools_used)
            self.session_manager.save_session(session)
            return final_response

        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            return f"执行失败: {str(e)}"

    async def _execute_tools(self, tool_calls) -> list:
        async def _run_one(call):
            name, args = call["name"], call["args"]
            try:
                result = await self._tool_map[name].ainvoke(args)
                content = str(result)
                logger.info(f"  {name} -> {content[:100]}")
            except Exception as e:
                content = f"Error: {e}"
                logger.error(f"Tool {name} failed: {e}")
            return ToolMessage(content=content, tool_call_id=call["id"])

        return await asyncio.gather(*[_run_one(tc) for tc in tool_calls])

    def _dict_to_message(self, msg: Dict) -> BaseMessage:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            return HumanMessage(content=content)
        elif role == "system":
            return SystemMessage(content=content)
        else:
            return AIMessage(content=content)

    def _extract_content(self, message) -> str:
        content = getattr(message, "content", "")

        if isinstance(content, list):
            text_parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            content = "\n".join(text_parts) if text_parts else str(content)

        content = strip_thinking_tags(content)
        return content

    def _build_system_prompt(self) -> str:
        parts = []

        # ── 身份与核心行为 ──
        parts.append("""# Capricorn Agent

You are Capricorn, an intelligent AI assistant. You are helpful, knowledgeable, and direct.

## Core Rules

1. **Tool-use enforcement**: You MUST use your tools to take action — do not describe
   what you would do without actually doing it. When you say you will perform an action,
   you MUST immediately make the corresponding tool call in the same response.
   Never end your turn with a promise of future action — execute it now.

2. **Direct answers**: Answer user questions directly. Do not prefix with unnecessary
   explanations about what you are going to do. Just do it.

3. **Error recovery**: If a tool call fails, analyze the error and try a different
   approach. Do not repeat the exact same failed call.

4. **Conciseness**: Be concise in your responses. Provide the information the user
   asked for without unnecessary elaboration.""")

        # ── 工作区信息 ──
        workspace_root = getattr(
            getattr(self.session_manager, "workspace", None), "root", "./workspace"
        )
        if self.sandbox:
            parts.append(f"""# Workspace (Sandbox Mode)

Your workspace is at `{workspace_root}`. Sandbox mode is enabled.

Rules:
- All file operations are restricted to the workspace directory.
- Paths outside the workspace will be rejected. Use relative paths or paths starting with `{workspace_root}`.
- Use `list_files` to explore the workspace structure before working with files.""")
        else:
            parts.append(f"""# Workspace

Your workspace is at `{workspace_root}`. This is your working directory for all file operations.

Rules:
- You have access to the full filesystem. Use this power responsibly.
- When writing code, creating documents, or saving any output, prefer writing to the workspace.
- Use `list_files` to explore directories before working with files.
- All paths passed to tools should be relative to the workspace root or absolute paths starting with `{workspace_root}`.""")

        # ── 长期记忆 ──
        memory_content = self.long_term_memory.read()
        if memory_content:
            parts.append(f"""# Long-term Memory

This contains important facts, preferences, and context that should always be remembered.

{memory_content}""")

        # ── 历史摘要 ──
        history_lines = self.history_log.read(limit=10)
        if history_lines:
            parts.append(
                "# Recent History\n\nSummaries of recent conversations:\n\n"
                + "\n".join(f"- {line}" for line in history_lines)
            )

        # ── 工具信息（含描述和使用指导）──
        tool_registry = self.capability_registry.tools
        if hasattr(tool_registry, "list_by_layer"):
            layers = tool_registry.list_by_layer()
            if any(layers.values()):
                layer_sections = []
                for layer_name, tools in layers.items():
                    if not tools:
                        continue
                    layer_desc = {
                        "builtin": "## Built-in Tools\nFast, local operations. Use these for file system access and command execution.",
                        "mcp": "## MCP Tools\nExternal API tools. Use these for maps, transportation, and real-time data.",
                        "workflow": "## Workflow Tools\nComplex multi-step workflows. Use these for tasks that require orchestrating multiple tools.",
                    }.get(layer_name, f"## {layer_name}")

                    tool_details = []
                    for tool_name in tools:
                        tool = tool_registry.get(tool_name)
                        desc = tool.description[:80] if tool else ""
                        tool_details.append(f"- **{tool_name}**: {desc}")

                    layer_sections.append(f"{layer_desc}\n\n" + "\n".join(tool_details))

                if layer_sections:
                    parts.append("# Available Tools\n\n" + "\n\n".join(layer_sections))

        # ── 技能信息 ──
        if hasattr(self.skill_manager, "list_skills") and self.skill_manager.list_skills():
            skill_summary = self.skill_manager.get_skill_summary()
            if skill_summary:
                parts.append(f"""# Available Skills

You have access to the following skills. When a user's request matches a skill, you MUST call `skill_view(name)` to load its full instructions before proceeding. Do not attempt to use a skill without loading it first.

{skill_summary}""")

        # ── 当前时间 ──
        parts.append(f"# Current Time\n\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        return "\n\n---\n\n".join(parts)
