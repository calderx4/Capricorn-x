"""
Executor - Agent 执行器

职责：
- 初始化所有组件
- 协调执行
- 资源管理
"""

from typing import Optional
from pathlib import Path
from contextvars import ContextVar
from loguru import logger
from langchain_core.messages import AIMessage

from agent.agent import CapricornGraph
from config.settings import Config
from capabilities.capability_registry import CapabilityRegistry
from capabilities.skills.manager import SkillManager
from memory.session import SessionManager
from memory.long_term import LongTermMemory
from memory.history import HistoryLog
from core.paths import (
    PROMPTS_DIR, ROLES_DIR, BUILTIN_EXTENSIONS,
    WORKFLOW_EXTENSIONS, CONFIG_DIR,
)
from core.consolidation import consolidate_if_needed

# 防止 LangChain OpenAI patch 被重复应用
_lc_openai_patched = False


def _ensure_lc_openai_extras_patch():
    """一次性 patch：让 LangChain OpenAI 保留非标准字段（如 reasoning_content）。

    DeepSeek 等模型在响应中返回 reasoning_content 等非标准字段，
    LangChain 默认会丢弃。这个 patch 确保这些字段通过 additional_kwargs 保留。
    """
    global _lc_openai_patched
    if _lc_openai_patched:
        return
    _lc_openai_patched = True

    from langchain_openai.chat_models import base as _lc_base

    _LC_KNOWN_KEYS = {
        "role", "content", "name", "id", "function_call", "tool_calls",
        "audio", "refusal", "parsed",
    }

    _orig_to_msg = _lc_base._convert_dict_to_message
    def _to_msg_with_extras(_dict):
        msg = _orig_to_msg(_dict)
        if isinstance(msg, AIMessage):
            for k, v in _dict.items():
                if k not in _LC_KNOWN_KEYS and k not in msg.additional_kwargs:
                    msg.additional_kwargs[k] = v
        return msg
    _lc_base._convert_dict_to_message = _to_msg_with_extras

    _orig_to_dict = _lc_base._convert_message_to_dict
    def _to_dict_with_extras(message, api="chat/completions"):
        d = _orig_to_dict(message, api=api)
        if isinstance(message, AIMessage) and message.additional_kwargs:
            for k, v in message.additional_kwargs.items():
                if k not in d:
                    d[k] = v
        return d
    _lc_base._convert_message_to_dict = _to_dict_with_extras


# 当前对话来源（contextvars 保障并发安全，CronTool 创建任务时读取）
_current_source: ContextVar[dict | None] = ContextVar("_current_source", default=None)


class CapricornAgent:
    """Capricorn Agent 执行器"""

    def __init__(self, config: Config, config_path: str = None):
        self.config = config
        self.config_path = config_path
        self.graph: Optional[CapricornGraph] = None
        self.llm_client = None
        self.capability_registry: Optional[CapabilityRegistry] = None
        self.skill_manager: Optional[SkillManager] = None
        self.session_manager: Optional[SessionManager] = None
        self.long_term_memory: Optional[LongTermMemory] = None
        self.history_log: Optional[HistoryLog] = None
        self._cron_scheduler = None
        self._notification_bus = None
        self._system_prompt_path: Optional[str] = None
        self._bia_path: Optional[str] = None
        self._roles: dict = {}
        self._team_config: dict = {}
        self._active_dir: Optional[Path] = None
        self._cron_prompt_path: Optional[str] = None

    @classmethod
    async def create(cls, config: Config, config_path: str = None, notification_bus=None) -> "CapricornAgent":
        agent = cls(config, config_path)
        agent._notification_bus = notification_bus
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

        # 3. 初始化能力注册中心（auto-discovery: builtin + mcp + workflow + skill）
        self.capability_registry = await CapabilityRegistry.create(
            self.config.mcp_servers,
            workspace_root=self.config.workspace.root,
            sandbox=self.config.workspace.sandbox,
            skill_manager=self.skill_manager,
            blocked_commands=self.config.blocked_commands,
        )

        # 4. 加载角色系统
        self._load_roles()
        self._bia_path = str(Path(self.config.workspace.root) / "memory" / "bia.md")
        self._active_dir = WORKFLOW_EXTENSIONS
        self._cron_prompt_path = str(PROMPTS_DIR / "cron.md")
        self._team_config = self.config.team.model_dump()

        # 5. 注册 BIA 工具（手动，需要 bia_path）
        from core.utils import load_class_from_file
        bia_tool_path = BUILTIN_EXTENSIONS / "bia_tools.py"
        if bia_tool_path.exists():
            BiaUpdateTool = load_class_from_file(bia_tool_path, "BiaUpdateTool")
            bia_tool = BiaUpdateTool(bia_path=self._bia_path, llm_client=self.llm_client)
            self.capability_registry.tools.register(bia_tool, layer="builtin")
            logger.info("BIA tool registered")

        # 5b. 注册 Quality 工具（手动，需要 llm_client）
        quality_tool_path = BUILTIN_EXTENSIONS / "quality_tools.py"
        if quality_tool_path.exists():
            QualityCheckTool = load_class_from_file(quality_tool_path, "QualityCheckTool")
            quality_tool = QualityCheckTool(llm_client=self.llm_client)
            self.capability_registry.tools.register(quality_tool, layer="builtin")
            logger.info("Quality check tool registered (LLM-based)")

        # 6. 注册 Team 工具（如果定义了 roles）
        if self._roles:
            team_tool_path = BUILTIN_EXTENSIONS / "team_tools.py"
            if team_tool_path.exists():
                from core.utils import load_module_from_file
                _team_mod = load_module_from_file(team_tool_path)

                task_tool = _team_mod.TaskManageTool(
                    workspace_root=self.config.workspace.root,
                    team_config=self._team_config,
                )
                self.capability_registry.tools.register(task_tool, layer="builtin")

                spawn_config = _team_mod.SpawnConfig(
                    roles=self._roles,
                    bia_path=self._bia_path,
                    workspace_root=self.config.workspace.root,
                    sandbox=self.config.workspace.sandbox,
                    max_iterations=self.config.agent.get("max_iterations", 50),
                    max_questions=self.config.team.max_questions,
                    max_attempts=self.config.team.max_attempts,
                    max_concurrent=self.config.team.max_concurrent,
                )
                spawn_tool = _team_mod.SpawnTool(
                    llm_client=self.llm_client,
                    capability_registry=self.capability_registry,
                    skill_manager=self.skill_manager,
                    long_term_memory=self.long_term_memory,
                    config=spawn_config,
                )
                self.capability_registry.tools.register(spawn_tool, layer="builtin")

                check_status_tool = _team_mod.CheckStatusTool(
                    workspace_root=self.config.workspace.root,
                )
                self.capability_registry.tools.register(check_status_tool, layer="builtin")

                get_result_tool = _team_mod.GetResultTool(
                    workspace_root=self.config.workspace.root,
                )
                self.capability_registry.tools.register(get_result_tool, layer="builtin")

                logger.info(f"Team tools registered (roles: {list(self._roles.keys())})")

                # 校验角色白名单工具是否都已注册
                registered = {t.name for t in self.capability_registry.get_langchain_tools()}
                for role_name, role_def in self._roles.items():
                    role_tools = role_def.get("tools")
                    if role_tools and role_tools != "all":
                        missing = set(role_tools) - registered
                        if missing:
                            logger.warning(
                                f"Role '{role_name}' whitelist has unregistered tools: {missing}"
                            )

        # 7. 初始化会话管理器
        self.session_manager = SessionManager(self.config.workspace)

        # 8. 初始化长期记忆
        self.long_term_memory = LongTermMemory(self.config.workspace)

        # 9. 初始化历史日志
        self.history_log = HistoryLog(self.config.workspace, max_entries=self.config.memory.max_history_entries)

        # 10. 初始化 Cron 调度器
        if self.config.cron.enabled:
            from agent.scheduler import CronScheduler
            from capabilities.tools.builtin.extensions.cron_tools import CronTool

            self._cron_scheduler = CronScheduler(self.config)
            self._cron_scheduler.initialize(
                llm_client=self.llm_client,
                capability_registry=self.capability_registry,
                skill_manager=self.skill_manager,
                long_term_memory=self.long_term_memory,
                notification_bus=self._notification_bus,
                cron_prompt_path=self._cron_prompt_path,
                bia_path=self._bia_path,
                roles=self._roles,
                active_dir=str(self._active_dir),
                agent=self,
            )

            cron_tool = CronTool(self._cron_scheduler)
            self.capability_registry.tools.register(cron_tool, layer="builtin")

        # 11. 构建图
        system_prompt_path = str(PROMPTS_DIR / "system.md")
        self._system_prompt_path = system_prompt_path

        self.graph = CapricornGraph(
            self.capability_registry,
            self.skill_manager,
            self.session_manager,
            self.long_term_memory,
            self.llm_client,
            sandbox=self.config.workspace.sandbox,
            max_iterations=self.config.agent.get("max_iterations", 50),
            system_prompt_path=system_prompt_path,
            bia_path=self._bia_path,
        )

        logger.info("✓ Capricorn Agent initialized")

    def _load_roles(self):
        """扫描 config/roles/ 目录，加载角色定义"""
        import yaml
        roles_dir = ROLES_DIR
        if not roles_dir.exists():
            return

        for yaml_file in sorted(roles_dir.glob("*.yaml")):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    role_def = yaml.safe_load(f)

                role_name = role_def.get("name", yaml_file.stem)
                prompt_rel = role_def.get("prompt")
                prompt_path = str((roles_dir / prompt_rel).resolve()) if prompt_rel else None

                self._roles[role_name] = {
                    "name": role_name,
                    "description": role_def.get("description", ""),
                    "prompt_path": prompt_path,
                    "tools": role_def.get("tools", "all"),
                }
            except Exception as e:
                logger.error(f"Failed to load role {yaml_file}: {e}")

        if self._roles:
            logger.info(f"Roles loaded: {list(self._roles.keys())}")

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

            openai_params = {
                "model": llm_config.model,
                "temperature": llm_config.temperature,
                "max_tokens": llm_config.max_tokens,
                "api_key": llm_config.api_key
            }

            if llm_config.api_base:
                openai_params["base_url"] = llm_config.api_base

            self.llm_client = ChatOpenAI(**openai_params)
            _ensure_lc_openai_extras_patch()
        else:
            raise ValueError(f"Unsupported LLM provider: {llm_config.provider}")

        logger.debug(f"Initialized LLM client: {llm_config.provider}/{llm_config.model}")
        if llm_config.api_base:
            logger.debug(f"Using custom API base: {llm_config.api_base}")

    async def chat(self, user_input: str, thread_id: str = "default",
                   images: list = None, attachments: list = None,
                   on_event=None, source: dict = None,
                   extra_system_prompt: str = "") -> str:
        if not self.graph:
            raise RuntimeError("Agent not initialized")

        # 设置 source（CronTool 创建任务时读取，ContextVar 保障并发安全）
        if source is None:
            source = {"type": "cli"} if thread_id == "default" else {"type": "gateway"}
        token = _current_source.set(source)
        try:
            return await self._chat_inner(user_input, thread_id, images, attachments, on_event,
                                          extra_system_prompt=extra_system_prompt)
        finally:
            _current_source.reset(token)

    async def _chat_inner(self, user_input: str, thread_id: str,
                           images: list, attachments: list,
                           on_event, extra_system_prompt: str = "") -> str:
        """chat() 的内部实现（_current_source 已设置）。"""
        await self._check_and_consolidate_memory(thread_id, on_event=on_event)

        notifications = ""
        unread_ids = []
        if self._notification_bus:
            unread = self._notification_bus.get_unread()
            if unread:
                lines = []
                for n in unread:
                    d = n["data"]
                    ts = n["timestamp"][:16]
                    name = d.get("job_name", "未命名任务")
                    msg = d.get("message", "")[:300]
                    status = d.get("status", "")
                    icon = "✅" if status == "success" else "❌"
                    lines.append(f"{icon} [{ts}] {name}: {msg}")
                notifications = (
                    "# 未读通知\n\n"
                    "以下是你之前设定的定时任务执行结果，请在回复中视情况自然提及：\n\n"
                    + "\n".join(lines)
                )
                unread_ids = [n["id"] for n in unread]

        response = await self.graph.run(
            user_input, thread_id, notifications=notifications,
            images=images, attachments=attachments,
            on_event=on_event,
            extra_system_prompt=extra_system_prompt,
        )

        if unread_ids:
            await self._notification_bus.mark_read(unread_ids)

        return response

    async def _check_and_consolidate_memory(self, thread_id: str, on_event=None):
        """对话前检查：是否需要整合记忆"""
        try:
            mem_cfg = self.config.memory
            if not mem_cfg.enabled:
                return

            session = self.session_manager.get_session(thread_id)
            messages = session.get_history()

            await consolidate_if_needed(
                session_manager=self.session_manager,
                session_id=thread_id,
                messages=messages,
                active_dir=self._active_dir,
                long_term_memory=self.long_term_memory,
                history_log=self.history_log,
                llm_client=self.llm_client,
                mem_config=mem_cfg,
                on_event=on_event,
            )

        except Exception as e:
            logger.exception(f"Memory consolidation error: {e}")

    async def cleanup(self):
        logger.info("Cleaning up resources...")

        if self._cron_scheduler:
            self._cron_scheduler.stop()

        if self.capability_registry:
            await self.capability_registry.cleanup()

        logger.info("✓ Cleanup completed")
