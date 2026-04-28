"""
Executor - Agent 执行器

职责：
- 初始化所有组件
- 协调执行
- 资源管理
"""

import asyncio
from typing import Optional
from loguru import logger

from agent.agent import CapricornGraph
from config.settings import Config
from capabilities.capability_registry import CapabilityRegistry
from capabilities.skills.manager import SkillManager
from memory.session import SessionManager
from memory.long_term import LongTermMemory
from memory.history import HistoryLog
from capabilities.tools.workflow.extensions.memory_consolidation import MemoryConsolidationWorkflow
from core import trace
from core.token_counter import TokenCounter


class CapricornAgent:
    """Capricorn Agent 执行器"""

    def __init__(self, config: Config, config_path: str = None):
        """
        初始化执行器

        Args:
            config: 配置对象
            config_path: 配置文件路径（用于 SessionManager 初始化 LLM）
        """
        self.config = config
        self.config_path = config_path
        self.graph: Optional[CapricornGraph] = None
        self.llm_client = None
        self.capability_registry: Optional[CapabilityRegistry] = None
        self.skill_manager: Optional[SkillManager] = None
        self.session_manager: Optional[SessionManager] = None
        self.long_term_memory: Optional[LongTermMemory] = None
        self.history_log: Optional[HistoryLog] = None

    @classmethod
    async def create(cls, config: Config, config_path: str = None) -> "CapricornAgent":
        """
        工厂方法：创建并初始化 Agent

        Args:
            config: 配置对象
            config_path: 配置文件路径（用于 SessionManager 初始化 LLM）

        Returns:
            初始化后的 Agent
        """
        agent = cls(config, config_path)
        await agent.initialize()
        return agent

    async def initialize(self):
        """初始化所有组件"""
        logger.info("Initializing Capricorn Agent...")

        # 1. 初始化 LLM 客户端
        self._init_llm_client()

        # 2. 初始化技能管理器
        skills_dir = self.config.skills.get("skills_dir", "capabilities/skills/skills")
        self.skill_manager = SkillManager(skills_dir)

        # 3. 初始化能力注册中心（传入 skill_manager 以注册 skill_view 工具）
        self.capability_registry = await CapabilityRegistry.create(
            self.config.mcp_servers,
            workspace_root=self.config.workspace.root,
            sandbox=self.config.workspace.sandbox,
            skill_manager=self.skill_manager,
            blocked_commands=self.config.blocked_commands,
        )

        # 4. 初始化会话管理器
        self.session_manager = SessionManager(
            self.config.workspace
        )

        # 5. 初始化长期记忆
        self.long_term_memory = LongTermMemory(self.config.workspace)

        # 6. 初始化历史日志
        self.history_log = HistoryLog(self.config.workspace)

        # 7. 构建图
        self.graph = CapricornGraph(
            self.capability_registry,
            self.skill_manager,
            self.session_manager,
            self.long_term_memory,
            self.history_log,
            self.llm_client,
            sandbox=self.config.workspace.sandbox,
            max_iterations=self.config.agent.get("max_iterations", 50),
        )

        logger.info("✓ Capricorn Agent initialized")

    def _init_llm_client(self):
        """初始化 LLM 客户端"""
        llm_config = self.config.llm

        if llm_config.provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            self.llm_client = ChatAnthropic(
                model=llm_config.model,
                temperature=llm_config.temperature,
                max_tokens=llm_config.max_tokens,
                api_key=llm_config.api_key
            )
        elif llm_config.provider == "openai":
            from langchain_openai import ChatOpenAI

            # 构建 ChatOpenAI 参数
            openai_params = {
                "model": llm_config.model,
                "temperature": llm_config.temperature,
                "max_tokens": llm_config.max_tokens,
                "api_key": llm_config.api_key
            }

            # 如果有自定义 api_base，添加到参数中
            if llm_config.api_base:
                openai_params["base_url"] = llm_config.api_base

            self.llm_client = ChatOpenAI(**openai_params)
        else:
            raise ValueError(f"Unsupported LLM provider: {llm_config.provider}")

        logger.debug(f"Initialized LLM client: {llm_config.provider}/{llm_config.model}")
        if llm_config.api_base:
            logger.debug(f"Using custom API base: {llm_config.api_base}")

    async def chat(self, user_input: str, thread_id: str = "default") -> str:
        """
        执行对话

        Args:
            user_input: 用户输入
            thread_id: 会话 ID

        Returns:
            响应结果
        """
        if not self.graph:
            raise RuntimeError("Agent not initialized")

        # 对话开始前：检查并同步整合记忆（阻塞式）
        await self._check_and_consolidate_memory(thread_id)

        # 执行对话
        response = await self.graph.run(user_input, thread_id)

        return response

    async def _check_and_consolidate_memory(self, thread_id: str):
        """对话前检查：是否需要整合记忆。两种触发：条数或 token 数超阈值。"""
        try:
            mem_cfg = self.config.memory
            if not mem_cfg.enabled:
                return

            # 直接用内存中的 session，不重读文件
            session = self.session_manager.get_session(thread_id)
            messages = session.get_history(max_messages=0)

            if not messages:
                return

            # 触发条件 1：消息条数超阈值
            total = len(messages)
            triggered_by = None
            if total > mem_cfg.message_threshold:
                triggered_by = f"messages({total} > {mem_cfg.message_threshold})"

            # 触发条件 2：总 token 数超阈值（仅条数未触发时才算）
            if not triggered_by:
                est_tokens = TokenCounter.count_messages_tokens(messages)
                if est_tokens > mem_cfg.token_threshold:
                    triggered_by = f"tokens({est_tokens} > {mem_cfg.token_threshold})"

            if not triggered_by:
                return

            logger.info(f"Memory consolidation triggered by {triggered_by}")

            workflow = MemoryConsolidationWorkflow(
                long_term_memory=self.long_term_memory,
                history_log=self.history_log,
                llm_client=self.llm_client,
                config={
                    "max_messages": mem_cfg.message_threshold,
                    "messages_to_keep": mem_cfg.messages_to_keep,
                    "max_tokens": mem_cfg.token_threshold,
                    "context_budget": mem_cfg.context_budget,
                }
            )

            session_data = {"messages": messages}
            logger.info(f"Consolidating {len(messages)} messages, keep={mem_cfg.messages_to_keep}")
            success = await workflow.execute(session_data=session_data)
            logger.info(f"Consolidation result: {success}, consecutive_failures={workflow._consecutive_failures}")

            if success:
                to_consolidate = workflow.get_messages_to_consolidate(session_data)
                num_remove = len(to_consolidate)
                remaining = messages[num_remove:]
                trace.consolidation(triggered_by, len(messages), len(remaining), True)

                self.session_manager.rewrite_session(thread_id, remaining)

                logger.info(f"Consolidated {num_remove} messages, kept {len(remaining)}")
            else:
                logger.warning("Memory consolidation failed")
                trace.consolidation(triggered_by, len(messages), len(messages), False)

        except Exception as e:
            logger.exception(f"Memory consolidation error: {e}")

    async def cleanup(self):
        """清理资源"""
        logger.info("Cleaning up resources...")

        if self.capability_registry:
            await self.capability_registry.cleanup()

        logger.info("✓ Cleanup completed")
