"""
Agent - LangGraph ReAct Agent 实现

职责：
- 定义 Agent 状态
- 实现节点逻辑（think + act）
- 构建状态图
- 管理执行状态
"""

from typing import Dict, Any, Annotated, Sequence, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage
from loguru import logger

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))



class AgentState(TypedDict):
    """Agent 状态"""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    session: Any  # Session 对象
    tools_used: list[str]


# ============================================================================
# 图构建
# ============================================================================

class CapricornGraph:
    """Capricorn Agent 图 - ReAct 模式"""

    def __init__(
        self,
        capability_registry,
        skill_manager,
        session_manager,
        long_term_memory,
        history_log,
        llm_client=None
    ):
        """
        初始化图

        Args:
            capability_registry: 能力注册中心
            skill_manager: 技能管理器
            session_manager: 会话管理器
            long_term_memory: 长期记忆
            history_log: 历史日志
            llm_client: LLM 客户端
        """
        self.capability_registry = capability_registry
        self.skill_manager = skill_manager
        self.session_manager = session_manager
        self.long_term_memory = long_term_memory
        self.history_log = history_log
        self.llm_client = llm_client

        # 构建图
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """构建状态图 - ReAct 模式"""
        # 获取 LangChain 工具
        tools = self.capability_registry.get_langchain_tools()
        tool_map = {t.name: t for t in tools}

        # 绑定工具到 LLM
        if self.llm_client:
            llm_with_tools = self.llm_client.bind_tools(tools)
        else:
            logger.warning("LLM client not initialized")
            llm_with_tools = None

        # 节点：思考
        async def think(state: AgentState):
            """思考节点 - 调用 LLM 决定下一步"""
            logger.info("🤔 Thinking... calling LLM")

            if not llm_with_tools:
                return {
                    "messages": [AIMessage(content="LLM 客户端未初始化")],
                    "tools_used": state.get("tools_used", [])
                }

            # 调用 LLM
            try:
                response = await llm_with_tools.ainvoke(state["messages"])
                logger.info(f"✓ LLM response received, type: {type(response).__name__}")
            except Exception as e:
                logger.error(f"✗ LLM call failed: {e}")
                return {
                    "messages": [AIMessage(content=f"LLM 调用失败: {str(e)}")],
                    "tools_used": state.get("tools_used", [])
                }

            # 检查是否有工具调用
            if hasattr(response, "tool_calls") and response.tool_calls:
                logger.info(f"🔧 LLM decided to use tools: {[tc['name'] for tc in response.tool_calls]}")
            else:
                logger.info("💬 LLM returned text response")

            return {
                "messages": [response],
                "tools_used": state.get("tools_used", [])
            }

        # 节点：执行工具
        async def act(state: AgentState):
            """执行节点 - 执行工具调用"""
            last_message = state["messages"][-1]

            if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
                return state

            tool_messages = []
            tools_used = state.get("tools_used", [])

            # 执行所有工具调用
            for call in last_message.tool_calls:
                tool_name = call["name"]
                tool_args = call["args"]

                logger.debug(f"Executing tool: {tool_name} with args: {tool_args}")

                try:
                    # 执行工具
                    result = await tool_map[tool_name].ainvoke(tool_args)
                    content = str(result)
                    logger.info(f"  🔧 {tool_name} -> {content[:100]}")
                except Exception as e:
                    content = f"Error: {e}"
                    logger.error(f"Tool {tool_name} failed: {e}")

                tools_used.append(tool_name)
                tool_messages.append(ToolMessage(content=content, tool_call_id=call["id"]))

            return {"messages": tool_messages, "tools_used": tools_used}

        # 条件：是否继续
        def should_continue(state: AgentState):
            """判断是否继续执行工具"""
            last_message = state["messages"][-1]

            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                return "act"
            return "end"

        # 构建图
        graph = StateGraph(AgentState)

        # 添加节点
        graph.add_node("think", think)
        graph.add_node("act", act)

        # 设置入口
        graph.set_entry_point("think")

        # 添加边
        graph.add_conditional_edges(
            "think",
            should_continue,
            {"act": "act", "end": END}
        )
        graph.add_edge("act", "think")

        # 编译图
        return graph.compile()

    async def run(self, user_input: str, thread_id: str = "default") -> str:
        """
        运行 Agent

        Args:
            user_input: 用户输入
            thread_id: 会话 ID

        Returns:
            响应结果
        """
        logger.info(f"Running agent with thread_id: {thread_id}")

        # 加载或创建 session
        session = self.session_manager.get_session(thread_id)

        # 添加用户消息
        session.add_message("user", user_input)

        # 构建系统提示
        system_prompt = self._build_system_prompt()

        # 加载历史消息
        history_messages = session.get_history(max_messages=0)  # 加载所有未整合消息

        # 构建消息列表
        messages = [
            HumanMessage(content=system_prompt),
            *[self._dict_to_message(msg) for msg in history_messages],
            HumanMessage(content=user_input)
        ]

        try:
            # 执行图
            result_state = await self.graph.ainvoke({
                "messages": messages,
                "session": session,
                "tools_used": []
            })

            # 提取最终回复
            last_message = result_state["messages"][-1]
            response = self._extract_content(last_message)

            logger.debug(f"Reply length: {len(response)} chars")

            # 添加助手回复
            tools_used = result_state.get("tools_used", [])
            session.add_message("assistant", response, tools_used=tools_used)

            # 保存 session
            self.session_manager.save_session(session)

            return response

        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            return f"执行失败: {str(e)}"

    def _dict_to_message(self, msg: Dict) -> BaseMessage:
        """将字典转换为 LangChain 消息"""
        role = msg.get("role", "user")
        content = msg.get("content", "")
        return HumanMessage(content=content) if role == "user" else AIMessage(content=content)

    def _extract_content(self, message) -> str:
        """从消息中提取内容，过滤 thinking 标签"""
        content = getattr(message, "content", "")

        # 处理列表格式的内容
        if isinstance(content, list):
            text_parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            content = "\n".join(text_parts) if text_parts else str(content)

        # 过滤掉 <thinking>...</thinking> 标签
        import re
        content = re.sub(r'<thinking>.*?</thinking>\s*', '', content, flags=re.DOTALL)

        return content.strip()

    def _build_system_prompt(self) -> str:
        """构建系统提示"""
        parts = ["# Capricorn Agent\n\nYou are a helpful AI assistant."]

        # 添加工作区信息
        parts.append(f"""# Workspace

All files and resources are located in the workspace directory.
When working with files, always use paths relative to the workspace or absolute paths.""")

        # 添加长期记忆
        memory_content = self.long_term_memory.read()
        if memory_content:
            parts.append(f"""# Long-term Memory (MEMORY.md)

This contains important facts, preferences, and context that should always be remembered.

{memory_content}""")

        # 添加工具信息（按层级分组）
        tool_registry = self.capability_registry.tools
        if hasattr(tool_registry, 'list_by_layer'):
            layers = tool_registry.list_by_layer()
            if any(layers.values()):
                layer_sections = []
                for layer_name, tools in layers.items():
                    if tools:
                        layer_desc = {
                            "builtin": "**builtin** - Built-in atomic tools (fast, local operations)",
                            "mcp": "**mcp** - External MCP tools (network requests, third-party APIs)",
                            "workflow": "**workflow** - Complex multi-step workflows (slow, significant task completion)",
                        }.get(layer_name, layer_name)
                        layer_sections.append(f"{layer_desc}\nAvailable: {', '.join(tools)}")
                if layer_sections:
                    parts.append("# Tools (by complexity)\n\n" + "\n\n".join(layer_sections))

        # 添加技能信息（渐进式披露）
        if hasattr(self.skill_manager, 'list_skills') and self.skill_manager.list_skills():
            always_skills = self.skill_manager.get_always_skills()
            if always_skills:
                always_parts = []
                for skill_name in always_skills:
                    content = self.skill_manager.load_skill(skill_name)
                    if content:
                        always_parts.append(f"## {skill_name}\n\n{content}")
                if always_parts:
                    parts.append("# Active Skills (always on)\n\n" + "\n\n---\n\n".join(always_parts))

            on_demand_summary = self.skill_manager.get_skill_summary(include_always=False)
            if on_demand_summary and "no skills loaded" not in on_demand_summary:
                parts.append(f"# Available Skills (on-demand)\n\n{on_demand_summary}")

        return "\n\n---\n\n".join(parts)
