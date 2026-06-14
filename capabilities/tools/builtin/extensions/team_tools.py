"""
Team Tools - SubAgent 任务管理工具

职责：
- TaskManageTool：管理任务状态机（create / list / update / get）
- SpawnTool：异步召唤 SubAgent，立即返回 task_id
- CheckStatusTool：检查任务状态
- GetResultTool：获取任务结果
"""

import asyncio
import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger

from core.base_tool import BaseTool
from core.utils import atomic_write, short_id, compute_excluded_tools

_TASK_ID_RE = re.compile(r'^task_[a-f0-9]{8}$')
_task_lock = threading.Lock()

# Task status constants
#
# 设计说明：spawn 路径的状态机是 producing → running → done | need_decision | error。
# 历史上曾设计了 verifying/failed 两态 + max_attempts 自动 force-done 的「自动验收-重试
# 闭环」，但该闭环从未在代码层实现——verifier 的验收结论写在 result.md 自由文本里，系统
# 不解析，因此无法自动判定 pass/rejected、无法自动 re-spawn。「验收不通过 → 带 feedback 重跑」
# 完全由 LLM 手动驱动（主 Agent 读 get_result 文本后自行决定是否再 spawn + 填 retry_feedback）。
# 故移除 verifying/failed 及依赖它们的 force-done 逻辑，避免代码声称一个并不存在的保证。
# attempts / max_attempts / retry_feedback 字段保留在 task schema 中供 LLM 手动驱动参考，
# 但系统不再据此强制任何自动行为。
STATUS_PRODUCING = "producing"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_NEED_DECISION = "need_decision"
STATUS_ERROR = "error"

VALID_TRANSITIONS = {
    STATUS_PRODUCING: [STATUS_RUNNING],
    STATUS_RUNNING: [STATUS_DONE, STATUS_NEED_DECISION, STATUS_ERROR],
    STATUS_NEED_DECISION: [STATUS_RUNNING, STATUS_PRODUCING],
    STATUS_DONE: [],
    STATUS_ERROR: [STATUS_PRODUCING, STATUS_RUNNING],
}

MUST_EXCLUDE_TOOLS = ("cron", "spawn", "check_status", "get_result")
MAX_RESULT_CHARS = 5000


def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _transition_task(workspace_root: Path, task_id: str, new_status: str, extra: dict = None) -> dict | None:
    """线程安全的任务状态转换。返回更新后的 task dict，失败返回 None。"""
    path = workspace_root / "team" / "tasks" / f"{task_id}.json"
    if not path.exists():
        logger.warning(f"Task {task_id} not found for transition")
        return None

    with _task_lock:
        try:
            task = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        old_status = task["status"]
        if new_status not in VALID_TRANSITIONS.get(old_status, []):
            logger.warning(f"Invalid transition for {task_id}: {old_status} → {new_status}")
            return None

        task["status"] = new_status
        task["updated_at"] = _now_ts()

        if new_status == STATUS_RUNNING:
            task["attempts"] += 1

        if extra:
            task.update(extra)

        atomic_write(path, json.dumps(task, ensure_ascii=False, indent=2))
        logger.info(f"Task {task_id}: {old_status} → {task['status']}")
        return task


# ── TaskManageTool ──────────────────────────────────────────────


class TaskManageTool(BaseTool):
    """管理任务状态机"""

    name = "task"
    description = (
        "管理团队任务状态机：创建、查询、更新任务状态。"
        f"状态值：{STATUS_PRODUCING} → {STATUS_RUNNING} → {STATUS_DONE} / {STATUS_NEED_DECISION} / {STATUS_ERROR}"
    )
    auto_discover = False

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "update", "get"],
                    "description": "操作类型",
                },
                "task_id": {
                    "type": "string",
                    "description": "任务 ID（update / get 时必填）",
                },
                "title": {
                    "type": "string",
                    "description": "任务标题（create 时必填）",
                },
                "description": {
                    "type": "string",
                    "description": "任务描述（create 时可选）",
                },
                "status": {
                    "type": "string",
                    "enum": [STATUS_PRODUCING, STATUS_RUNNING, STATUS_DONE, STATUS_NEED_DECISION, STATUS_ERROR],
                    "description": "目标状态（update 时必填）",
                },
                "assigned_role": {
                    "type": "string",
                    "enum": ["executor", "verifier"],
                    "description": "分配角色（create 时可选，默认 executor）",
                },
                "max_attempts": {
                    "type": "integer",
                    "description": "最大重试次数（create 时可选，默认 3）",
                },
                "filter_status": {
                    "type": "string",
                    "description": "按状态筛选（list 时可选）",
                },
            },
            "required": ["action"],
        }

    def __init__(self, workspace_root: str, team_config: dict = None):
        self._workspace_root = Path(workspace_root)
        self._tasks_dir = self._workspace_root / "team" / "tasks"
        self._team_config = team_config or {}

    def _ensure_dirs(self):
        self._tasks_dir.mkdir(parents=True, exist_ok=True)

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action")
        if action == "create":
            return self._create(kwargs)
        elif action == "list":
            return self._list(kwargs)
        elif action == "update":
            return self._update(kwargs)
        elif action == "get":
            return self._get(kwargs)
        else:
            return f"未知操作: {action}"

    def _create(self, params: dict) -> str:
        self._ensure_dirs()

        title = params.get("title", "未命名任务")
        task_id = f"task_{short_id()}"

        executor_cfg = self._team_config.get("executor", {})
        task = {
            "id": task_id,
            "title": title,
            "status": STATUS_PRODUCING,
            "assigned_role": params.get("assigned_role", "executor"),
            "attempts": 0,
            "max_attempts": params.get("max_attempts", executor_cfg.get("max_attempts", 3)),
            "question_count": 0,
            "max_questions": executor_cfg.get("max_questions", 3),
            "input": {
                "description": params.get("description", ""),
            },
            "output_path": f"team/tasks/{task_id}/result.md",
            "created_at": _now_ts(),
            "updated_at": _now_ts(),
        }

        path = self._tasks_dir / f"{task_id}.json"
        atomic_write(path, json.dumps(task, ensure_ascii=False, indent=2))
        logger.info(f"Created task: {task_id} ({title})")
        return json.dumps(task, ensure_ascii=False, indent=2)

    def _list(self, params: dict) -> str:
        self._ensure_dirs()

        filter_status = params.get("filter_status")
        tasks = []

        for path in sorted(self._tasks_dir.glob("task_*.json")):
            try:
                task = json.loads(path.read_text(encoding="utf-8"))
                if not filter_status or task.get("status") == filter_status:
                    tasks.append(task)
            except (json.JSONDecodeError, OSError):
                continue

        if not tasks:
            return "没有找到匹配的任务"

        lines = []
        for t in tasks:
            lines.append(
                f"- [{t['status']}] {t['id']}: {t.get('title', '')} "
                f"(role={t.get('assigned_role', '?')})"
            )
        return "\n".join(lines)

    def _update(self, params: dict) -> str:
        task_id = params.get("task_id")
        if not task_id:
            return "Error: update 需要 task_id"
        if not _TASK_ID_RE.fullmatch(task_id):
            return "Error: 无效的 task_id 格式"

        new_status = params.get("status")
        if not new_status:
            return "Error: update 需要 status"

        task = _transition_task(self._workspace_root, task_id, new_status)
        if task is None:
            return f"Error: 无法将任务 {task_id} 转换到 '{new_status}'"

        return json.dumps(task, ensure_ascii=False, indent=2)

    def _get(self, params: dict) -> str:
        task_id = params.get("task_id")
        if not task_id:
            return "Error: get 需要 task_id"
        if not _TASK_ID_RE.fullmatch(task_id):
            return "Error: 无效的 task_id 格式"

        path = self._tasks_dir / f"{task_id}.json"
        if not path.exists():
            return f"Error: 任务 {task_id} 不存在"

        try:
            task = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return f"Error: 任务 {task_id} 数据损坏"

        # 附带问题文件摘要
        questions_dir = self._tasks_dir / task_id / "questions"
        if questions_dir.exists():
            questions = []
            for qf in sorted(questions_dir.glob("*.json")):
                try:
                    questions.append(json.loads(qf.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, OSError):
                    continue
            if questions:
                task["questions"] = questions

        return json.dumps(task, ensure_ascii=False, indent=2)


# ── SpawnTool ────────────────────────────────────────────────────


@dataclass
class SpawnConfig:
    """SpawnTool 配置（将 12 个参数收敛为一个结构体）"""
    roles: dict
    bia_path: str
    workspace_root: str
    sandbox: bool = True
    max_iterations: int = 50
    max_questions: int = 3
    max_attempts: int = 3
    max_concurrent: int = 5


class SpawnTool(BaseTool):
    """异步召唤 SubAgent 执行任务，立即返回 task_id"""

    name = "spawn"
    description = (
        "召唤 SubAgent 执行子任务。立即返回 task_id，不等待完成。"
        "role=executor 执行任务，role=verifier 验收质量。"
        "用 check_status 查询状态，get_result 获取结果。"
        "注意：系统不自动验收也不自动重试——verifier 结论在 result 文本里，"
        "若需重跑，由你读结论后再次 spawn，并在 retry_feedback 填上次反馈。"
    )
    auto_discover = False

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "enum": ["executor", "verifier"],
                    "description": "SubAgent 角色",
                },
                "prompt": {
                    "type": "string",
                    "description": "给 SubAgent 的指令（自包含）",
                },
                "retry_feedback": {
                    "type": "string",
                    "description": "上次验收反馈（重试时传入，让 SubAgent 知道上次哪里没过）",
                },
            },
            "required": ["role", "prompt"],
        }

    def __init__(
        self,
        llm_client,
        capability_registry,
        skill_manager,
        long_term_memory,
        config: SpawnConfig,
    ):
        self._llm_client = llm_client
        self._capability_registry = capability_registry
        self._skill_manager = skill_manager
        self._long_term_memory = long_term_memory
        self._config = config
        self._background_tasks: dict[str, asyncio.Task] = {}

    async def execute(self, **kwargs) -> str:
        cfg = self._config
        if len(self._background_tasks) >= cfg.max_concurrent:
            return json.dumps({"error": f"已达到最大并发任务数（{cfg.max_concurrent}）"}, ensure_ascii=False)

        role_name = kwargs.get("role", "executor")
        prompt = kwargs.get("prompt", "")
        retry_feedback = kwargs.get("retry_feedback", "")

        if role_name not in cfg.roles:
            return f"Error: 未知角色 '{role_name}'，可用: {list(cfg.roles.keys())}"

        role = cfg.roles[role_name]
        prompt_path = role.get("prompt_path")
        if not prompt_path or not Path(prompt_path).exists():
            return f"Error: 角色 '{role_name}' 的 prompt 模板不存在"

        # 1. 创建任务目录和文件
        task_id = f"task_{short_id()}"
        workspace = Path(cfg.workspace_root)
        task_dir = workspace / "team" / "tasks" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "questions").mkdir(exist_ok=True)

        atomic_write(task_dir / "brief.md", prompt)

        # 2. 创建任务 JSON
        task_data = {
            "id": task_id,
            "title": f"[spawned] {role_name}",
            "status": STATUS_PRODUCING,
            "assigned_role": role_name,
            "attempts": 0,
            "max_attempts": cfg.max_attempts,
            "question_count": 0,
            "max_questions": cfg.max_questions,
            "output_path": f"team/tasks/{task_id}/result.md",
            "created_at": _now_ts(),
            "updated_at": _now_ts(),
        }
        tasks_dir = workspace / "team" / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        atomic_write(
            tasks_dir / f"{task_id}.json",
            json.dumps(task_data, ensure_ascii=False, indent=2),
        )

        # 3. 构建 system prompt
        system_prompt = self._build_system_prompt(prompt_path)

        # 4. 构建增强的 task prompt（包含元信息和重试反馈）
        enhanced_prompt = self._build_task_prompt(prompt, task_id, retry_feedback)

        # 5. 启动后台任务
        exclude_tools = self._compute_excluded_tools(role)
        bg_task = asyncio.create_task(
            self._run_agent(system_prompt, enhanced_prompt, task_id, exclude_tools)
        )
        self._background_tasks[task_id] = bg_task
        bg_task.add_done_callback(lambda t: self._background_tasks.pop(task_id, None))

        logger.info(f"Spawned {role_name} task {task_id}")
        return json.dumps({"task_id": task_id, "status": STATUS_PRODUCING}, ensure_ascii=False)

    def _build_task_prompt(self, original_prompt: str, task_id: str, retry_feedback: str = "") -> str:
        parts = [original_prompt]

        if retry_feedback:
            parts.append(f"\n## 上次验收反馈\n\n{retry_feedback}")

        parts.append(
            f"\n---\n\n"
            f"## 任务元信息\n\n"
            f"- task_id: `{task_id}`\n"
            f"- 遇到问题需要 Capricorn 决策时，用 `write_file` 写入 "
            f"`team/tasks/{task_id}/questions/` 目录\n"
            f"  文件名递增：`1.json`、`2.json`、`3.json`\n"
            f"  格式：{{\"message\": \"具体问题描述\", \"can_continue\": false}}\n"
            f"- 最多问 **{self._config.max_questions}** 个问题，超过后任务会被标记为需要重新创建\n"
        )
        return "".join(parts)

    def _build_system_prompt(self, prompt_path: str) -> str:
        from core.prompt_utils import (
            build_prompt,
            build_tools_section,
            build_skills_section,
            build_memory_section,
            build_bia_section,
            build_simple_workspace_section,
        )

        return build_prompt(
            prompt_path,
            workspace_section=build_simple_workspace_section(self._config.workspace_root, sandbox=True),
            bia_section=build_bia_section(self._config.bia_path),
            memory_section=build_memory_section(self._long_term_memory),
            tools_section=build_tools_section(self._capability_registry),
            skills_section=build_skills_section(self._skill_manager),
            task_prompt="",
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    async def _run_agent(
        self,
        system_prompt: str,
        enhanced_prompt: str,
        task_id: str,
        exclude_tools: list,
    ):
        # producing → running（经状态机校验，attempts 自增）
        cfg = self._config
        workspace_root = Path(cfg.workspace_root)
        _transition_task(workspace_root, task_id, STATUS_RUNNING)

        try:
            from agent.agent import CapricornGraph
            from memory.session import SessionManager
            from config.settings import WorkspaceConfig

            ws = WorkspaceConfig(root=str(workspace_root), sandbox=cfg.sandbox)
            session_manager = SessionManager(ws)

            graph = CapricornGraph(
                capability_registry=self._capability_registry,
                skill_manager=self._skill_manager,
                session_manager=session_manager,
                long_term_memory=self._long_term_memory,
                llm_client=self._llm_client,
                sandbox=cfg.sandbox,
                max_iterations=cfg.max_iterations,
                exclude_tools=exclude_tools,
                system_prompt_override=system_prompt,
            )

            result = await graph.run(enhanced_prompt, thread_id=f"spawn_{task_id}")

            # 写入结果
            result_path = workspace_root / "team" / "tasks" / task_id / "result.md"
            atomic_write(result_path, result)

            # 检查问题文件
            questions_dir = workspace_root / "team" / "tasks" / task_id / "questions"
            question_count = len(list(questions_dir.glob("*.json"))) if questions_dir.exists() else 0

            # running → done / need_decision
            final_status = STATUS_NEED_DECISION if question_count > 0 else STATUS_DONE
            updated = _transition_task(workspace_root, task_id, final_status, {
                "question_count": question_count,
            })
            if not updated:
                logger.error(f"Failed to transition {task_id} to {final_status}")

        except Exception as e:
            logger.exception(f"Task {task_id} failed: {e}")
            updated = _transition_task(workspace_root, task_id, STATUS_ERROR, {
                "error": str(e)[:500],
            })
            if not updated:
                logger.error(f"Failed to transition {task_id} to error state")

    def _compute_excluded_tools(self, role: dict) -> list:
        all_tools = self._capability_registry.tools.list_tools()
        return compute_excluded_tools(all_tools, role.get("tools"), MUST_EXCLUDE_TOOLS)


# ── CheckStatusTool ──────────────────────────────────────────────


class CheckStatusTool(BaseTool):
    """检查 Agent 任务状态"""

    name = "check_status"
    description = f"检查 Agent 任务状态。返回 {STATUS_RUNNING}/{STATUS_DONE}/{STATUS_NEED_DECISION}/{STATUS_ERROR} 等状态。"
    auto_discover = False

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "任务 ID",
                },
            },
            "required": ["task_id"],
        }

    def __init__(self, workspace_root: str):
        self._workspace_root = Path(workspace_root)

    async def execute(self, task_id: str = "", **kwargs) -> str:
        if not _TASK_ID_RE.fullmatch(task_id):
            return json.dumps({"error": f"无效的 task_id: {task_id}"}, ensure_ascii=False)
        task_json_path = self._workspace_root / "team" / "tasks" / f"{task_id}.json"
        if not task_json_path.exists():
            return json.dumps({"error": f"任务 {task_id} 不存在"}, ensure_ascii=False)

        try:
            task = json.loads(task_json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return json.dumps({"error": f"任务 {task_id} 数据损坏"}, ensure_ascii=False)
        return json.dumps({
            "task_id": task["id"],
            "status": task["status"],
            "role": task.get("assigned_role", ""),
            "question_count": task.get("question_count", 0),
            "updated_at": task.get("updated_at", ""),
        }, ensure_ascii=False, indent=2)


# ── GetResultTool ────────────────────────────────────────────────


class GetResultTool(BaseTool):
    """获取 Agent 任务结果"""

    name = "get_result"
    description = f"获取 Agent 任务的结果和问题。仅在状态为 {STATUS_DONE} 或 {STATUS_NEED_DECISION} 时可用。"
    auto_discover = False

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "任务 ID",
                },
            },
            "required": ["task_id"],
        }

    def __init__(self, workspace_root: str):
        self._workspace_root = Path(workspace_root)

    async def execute(self, task_id: str = "", **kwargs) -> str:
        if not _TASK_ID_RE.fullmatch(task_id):
            return json.dumps({"error": f"无效的 task_id: {task_id}"}, ensure_ascii=False)
        task_json_path = self._workspace_root / "team" / "tasks" / f"{task_id}.json"
        if not task_json_path.exists():
            return json.dumps({"error": f"任务 {task_id} 不存在"}, ensure_ascii=False)

        task = json.loads(task_json_path.read_text(encoding="utf-8"))

        if task["status"] not in (STATUS_DONE, STATUS_NEED_DECISION):
            return json.dumps(
                {"error": f"任务状态为 {task['status']}，结果尚未就绪"},
                ensure_ascii=False,
            )

        # 读取结果文件
        result_path = self._workspace_root / "team" / "tasks" / task_id / "result.md"
        result = result_path.read_text(encoding="utf-8") if result_path.exists() else ""

        # 读取问题文件
        questions = []
        questions_dir = self._workspace_root / "team" / "tasks" / task_id / "questions"
        if questions_dir.exists():
            for qf in sorted(questions_dir.glob("*.json")):
                try:
                    questions.append(json.loads(qf.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, OSError):
                    continue

        return json.dumps({
            "task_id": task_id,
            "status": task["status"],
            "result": result[:MAX_RESULT_CHARS],
            "result_truncated": len(result) > MAX_RESULT_CHARS,
            "questions": questions,
        }, ensure_ascii=False, indent=2)
