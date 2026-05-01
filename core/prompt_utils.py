"""
Prompt 工具函数 — tools / skills / memory section 构建

供 agent.py 和 scheduler.py 共用，避免重复逻辑。
"""

LAYER_DESC_MAP = {
    "builtin": "## Built-in Tools\n本地基础能力 — 文件操作、命令执行、任务规划、记忆管理。",
    "mcp": "## MCP Tools\n外部服务集成（地图、交通等），按需调用。",
    "workflow": "## Workflow Tools\n复杂多步编排任务，调用多个工具协作完成。",
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
    summary = skill_manager.get_skill_summary()
    if not summary:
        return ""
    return (
        "# Available Skills\n\n"
        "你可以使用以下技能。当用户的请求匹配某个技能时，"
        "**必须**先调用 `skill_view(name)` 加载完整指令后再执行。\n\n"
        f"{summary}"
    )


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


def clean_empty_sections(text: str) -> str:
    """清理模板替换后残留的连续空行"""
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()
