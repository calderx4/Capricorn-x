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

from pathlib import Path

from core.utils import strip_thinking_tags
from core import trace


class CapricornGraph:
    """Capricorn Agent — 原生 Function Calling 循环"""

    def __init__(
        self,
        capability_registry,
        skill_manager,
        session_manager,
        long_term_memory,
        history_log,
        llm_client=None,
        sandbox: bool = True,
        max_iterations: int = 50,
    ):
        self.capability_registry = capability_registry
        self.skill_manager = skill_manager
        self.session_manager = session_manager
        self.long_term_memory = long_term_memory
        self.history_log = history_log
        self.llm_client = llm_client
        self.sandbox = sandbox
        self.max_iterations = max_iterations

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

        # 记录本轮输入的 messages 结构
        logger.debug(f"[Trace] 输入 messages 结构: {self._summarize_messages(messages)}")
        logger.debug(f"[Trace] 用户输入: {user_input}")

        if not self._llm_with_tools:
            return "LLM 客户端未初始化"

        tools_used = []

        try:
            for i in range(self.max_iterations):
                round_start_ts = asyncio.get_event_loop().time()
                logger.info(f"Thinking... (iteration {i + 1})")
                trace.round_start(i + 1, len(messages))

                response = await self._llm_with_tools.ainvoke(messages)
                messages.append(response)

                response_content = self._extract_content(response)
                logger.debug(f"[Trace] LLM 响应 (iter {i + 1}): {response_content[:500]}")

                if not (hasattr(response, "tool_calls") and response.tool_calls):
                    round_latency = int((asyncio.get_event_loop().time() - round_start_ts) * 1000)
                    trace.round_end(i + 1, 0, round_latency)
                    logger.debug(f"[Trace] 无工具调用，FC 循环结束 (iter {i + 1})")
                    break

                tool_names = [tc["name"] for tc in response.tool_calls]
                tool_args = [{"name": tc["name"], "args": tc["args"]} for tc in response.tool_calls]
                logger.info(f"Tool calls: {tool_names}")
                logger.debug(f"[Trace] 工具调用详情: {tool_args}")

                # 并发执行工具（带 trace）
                tool_messages = await self._execute_tools(response.tool_calls, round=i + 1)
                messages.extend(tool_messages)
                tools_used.extend(tool_names)

                round_latency = int((asyncio.get_event_loop().time() - round_start_ts) * 1000)
                trace.round_end(i + 1, len(tool_names), round_latency)

                for tm in tool_messages:
                    logger.debug(f"[Trace] 工具返回 (id={tm.tool_call_id}): {tm.content}")

            final_response = self._extract_content(messages[-1])
            logger.debug(f"[Trace] 最终回复: {final_response[:500]}")
            logger.debug(f"[Trace] 总迭代: {i + 1}, 使用工具: {tools_used}")
            session.add_message("assistant", final_response, tools_used=tools_used)
            self.session_manager.save_session(session)
            return final_response

        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            return f"执行失败: {str(e)}"

    async def _execute_tools(self, tool_calls, round: int = 0) -> list:
        async def _run_one(call):
            name, args = call["name"], call["args"]
            start = asyncio.get_event_loop().time()
            try:
                result = await self._tool_map[name].ainvoke(args)
                content = str(result)
                latency = int((asyncio.get_event_loop().time() - start) * 1000)
                logger.info(f"  {name} -> {content[:100]}")
                trace.tool_call(round, name, args, latency, "ok")
            except Exception as e:
                content = f"Error: {e}"
                latency = int((asyncio.get_event_loop().time() - start) * 1000)
                logger.error(f"Tool {name} failed: {e}")
                trace.tool_call(round, name, args, latency, "error")
            return ToolMessage(content=content, tool_call_id=call["id"])

        return await asyncio.gather(*[_run_one(tc) for tc in tool_calls])

    def _summarize_messages(self, messages: list) -> str:
        """生成 messages 列表的结构摘要"""
        summary = []
        for idx, msg in enumerate(messages):
            role = type(msg).__name__
            content = getattr(msg, "content", "")
            preview = content[:80].replace("\n", " ") if content else "(empty)"
            summary.append(f"  [{idx}] {role}: {preview}...")
        return f"共 {len(messages)} 条:\n" + "\n".join(summary)

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
        template_path = Path(__file__).parent.parent / "config" / "prompts" / "system.md"
        template = template_path.read_text(encoding="utf-8")

        workspace_root = getattr(
            getattr(self.session_manager, "workspace", None), "root", "./workspace"
        )

        # 工作区（sandbox 开关只控制是否限制在 workspace 内，不影响默认 cwd）
        sandbox_note = "（沙盒模式：路径限制在工作区内）" if self.sandbox else "（可访问工作区外的路径）"
        workspace_section = (
            f"# Workspace\n\n"
            f"工作区根目录：`{workspace_root}` {sandbox_note}\n"
            f"所有工具（read_file、write_file、list_files、exec）都以工作区根目录为基准。\n"
            f"路径直接写相对路径，例如 `main/my-task/index.html`。"
            f" 不要加 `{workspace_root}/` 前缀。\n\n"
            f"规则：\n"
            f"- 任务文件放在 `main/<任务名>/` 下，每个任务一个独立文件夹。\n"
            f"- `exec` 执行命令时默认在工作区根目录下运行。"
            f" 所以 `python main/my-task/app.py` 能直接找到文件。\n"
            f"- 操作前先用 `list_files` 查看工作区结构。"
        )

        # 长期记忆
        memory_content = self.long_term_memory.read()
        if memory_content:
            memory_section = (
                "# Long-term Memory\n\n"
                "以下包含需要始终记住的重要事实、偏好和上下文。\n\n"
                f"{memory_content}"
            )
        else:
            memory_section = ""

        # 历史摘要
        history_lines = self.history_log.read(limit=10)
        if history_lines:
            history_section = (
                "# Recent History\n\n近期对话摘要：\n\n"
                + "\n".join(f"- {line}" for line in history_lines)
            )
        else:
            history_section = ""

        # 工具信息
        tool_registry = self.capability_registry.tools
        tools_section = ""
        if hasattr(tool_registry, "list_by_layer"):
            layers = tool_registry.list_by_layer()
            if any(layers.values()):
                layer_sections = []
                layer_desc_map = {
                    "builtin": "## Built-in Tools\n本地快速操作，用于文件系统和命令执行。",
                    "mcp": "## MCP Tools\n外部 API 工具，用于地图、交通和实时数据。",
                    "workflow": "## Workflow Tools\n复杂多步工作流，用于编排多个工具的任务。",
                }
                for layer_name, tools in layers.items():
                    if not tools:
                        continue
                    layer_desc = layer_desc_map.get(layer_name, f"## {layer_name}")
                    tool_details = []
                    for tool_name in tools:
                        tool = tool_registry.get(tool_name)
                        desc = tool.description if tool else ""
                        tool_details.append(f"- **{tool_name}**: {desc}")
                    layer_sections.append(f"{layer_desc}\n\n" + "\n".join(tool_details))
                if layer_sections:
                    tools_section = "# Available Tools\n\n" + "\n\n".join(layer_sections)

        # 技能信息
        skills_section = ""
        if hasattr(self.skill_manager, "list_skills") and self.skill_manager.list_skills():
            skill_summary = self.skill_manager.get_skill_summary()
            if skill_summary:
                skills_section = (
                    "# Available Skills\n\n"
                    "你可以使用以下技能。当用户的请求匹配某个技能时，"
                    "**必须**先调用 `skill_view(name)` 加载完整指令后再执行。\n\n"
                    f"{skill_summary}"
                )

        # agent.md 项目概述
        agent_md_section = ""
        agent_md_path = Path("agent.md")
        if agent_md_path.exists():
            content = agent_md_path.read_text(encoding="utf-8").strip()
            if content:
                agent_md_section = f"# Project Context\n\n{content}"

        # 变量替换
        result = template.replace("{{workspace_section}}", workspace_section)
        result = result.replace("{{memory_section}}", memory_section)
        result = result.replace("{{history_section}}", history_section)
        result = result.replace("{{tools_section}}", tools_section)
        result = result.replace("{{skills_section}}", skills_section)
        result = result.replace("{{agent_md_section}}", agent_md_section)
        result = result.replace("{{current_time}}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        # 清理多余空行（空 section 留下的）
        while "\n\n\n---\n\n" in result:
            result = result.replace("\n\n\n---\n\n", "\n\n")
        while "\n\n---\n\n\n" in result:
            result = result.replace("\n\n---\n\n\n", "\n\n")
        # 清理空 section（只有 --- 分隔符没有内容的段落）
        lines = result.split("\n")
        cleaned = []
        skip_separator = False
        for line in lines:
            if line.strip() == "---":
                # 检查前一段是否为空（只有分隔符，没有实质内容）
                if cleaned and cleaned[-1].strip() == "":
                    continue
                skip_separator = False
                cleaned.append(line)
            else:
                cleaned.append(line)
        result = "\n".join(cleaned)

        return result.strip()
