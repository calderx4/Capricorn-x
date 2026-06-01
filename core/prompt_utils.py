"""
Prompt 工具函数 — build_prompt + section 构建器

供 agent.py 和 scheduler.py 共用，避免重复逻辑。
"""

import re
from pathlib import Path
from loguru import logger

from capabilities.skills.loader import SkillLoader


def build_prompt(template_path: str, **sections: str) -> str:
    """加载模板并替换 {{placeholder}} 段落。"""
    p = Path(template_path)
    if not p.exists():
        raise FileNotFoundError(f"Prompt template not found: {template_path}")
    template = p.read_text("utf-8")
    # 先转义用户内容中的 {{ }}，防止被当作模板变量
    placeholders = set(sections.keys())
    safe_sections = {}
    for name, content in sections.items():
        if name in ("workspace_section", "memory_section", "agent_md_section",
                     "tools_section", "skills_section", "task_prompt"):
            content = content.replace("{{", "<<").replace("}}", ">>")
        safe_sections[name] = content
    for name, content in safe_sections.items():
        template = template.replace("{{" + name + "}}", content)
    while "\n\n\n" in template:
        template = template.replace("\n\n\n", "\n\n")
    result = template.strip()
    # 检查 unreplaced（此时用户内容还是 << >> 形式，不会误报）
    unreplaced = re.findall(r'\{\{(\w+)\}\}', result)
    if unreplaced:
        logger.warning(f"build_prompt: unreplaced placeholders: {unreplaced}")
    # 还原转义
    result = result.replace("<<", "{{").replace(">>", "}}")
    return result


LAYER_DESC_MAP = {
    "tools": "## Tools（原子操作）\n确定性原子操作 — 文件读写、命令执行、任务管理等基础能力。",
    "workflow": "## Workflows（代码编排）\n代码约束的多步编排任务，按固定流程调用多个工具协作完成。",
    "mcp": "## MCP（外部服务）\n通过 MCP 协议接入的外部服务（搜索、图像理解等），按需调用。\n注意：图像类工具请传入绝对路径或 base64 data URI，不要传入相对路径。",
}


def build_tools_section(capability_registry) -> str:
    if not capability_registry:
        return ""
    tool_registry = capability_registry.tools
    if not hasattr(tool_registry, "list_by_layer"):
        return ""
    layers = tool_registry.list_by_layer()
    if not any(layers.values()):
        return ""
    sections = []
    for layer_name, tools in layers.items():
        if not tools:
            continue
        desc = LAYER_DESC_MAP.get(layer_name, f"## {layer_name}")
        details = []
        for name in tools:
            tool = tool_registry.get(name)
            details.append(f"- **{name}**: {tool.description if tool else ''}")
        sections.append(f"{desc}\n\n" + "\n".join(details))
    return "# Available Tools\n\n" + "\n\n".join(sections)


def build_skills_section(skill_manager) -> str:
    if not skill_manager or not hasattr(skill_manager, "list_skills"):
        return ""
    skills = skill_manager.list_skills()
    if not skills:
        return ""

    parts = []

    autoload_skills = skill_manager.get_autoload_skills()
    if autoload_skills:
        for skill_name, skill_data in autoload_skills.items():
            content = skill_data.get("content", "").strip()
            if content:
                parts.append(f"# Skill: {skill_name}\n\n{content}")

    available = skill_manager.get_available_skills()
    on_demand = {
        k: v for k, v in available.items()
        if not v.get("autoload", False) and "." not in k
    }
    if on_demand:
        summaries = [SkillLoader.get_summary(v) for v in on_demand.values()]
        summary = "<skills>\n" + "\n".join(summaries) + "\n</skills>"

        if summary:
            parts.append(
                "# Available Skills\n\n"
                "你可以使用以下技能。当用户的请求匹配某个技能时，"
                "**必须**先调用 `skill_view(name)` 加载完整指令后再执行。\n\n"
                f"{summary}"
            )

    return "\n\n".join(parts)


def build_memory_section(long_term_memory) -> str:
    if not long_term_memory:
        return ""
    content = long_term_memory.read()
    if not content:
        return ""
    return (
        "# Long-term Memory\n\n"
        "以下包含需要始终记住的重要事实、偏好和上下文。\n\n"
        f"{content}"
    )


def build_bia_section(bia_path: str) -> str:
    if not bia_path:
        return ""
    p = Path(bia_path)
    if not p.exists():
        return ""
    content = p.read_text(encoding="utf-8").strip()
    if not content:
        return ""
    return (
        "# Behavioral Corrections\n\n"
        "以下行为纠偏规则在执行任务时持续生效。"
        "你可以通过 bia_update 工具更新这些规则。\n\n"
        f"{content}"
    )
