"""
SkillViewTool - 技能查看工具

职责：
- 允许 LLM 按需加载技能的完整内容
"""

from typing import Any, Dict
from loguru import logger

from core.base_tool import BaseTool


class SkillViewTool(BaseTool):
    """技能查看工具 - LLM 通过此工具获取技能的完整指令"""

    def __init__(self, skill_manager):
        self._skill_manager = skill_manager

    @property
    def name(self) -> str:
        return "skill_view"

    @property
    def description(self) -> str:
        available = self._skill_manager.get_available_skills()
        if not available:
            return "No skills available."

        names = ", ".join(available.keys())
        return (
            "Load the full content of a skill by name. "
            "Use this when a user's request matches a skill. "
            f"Available skills: {names}"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The name of the skill to load",
                },
            },
            "required": ["name"],
        }

    async def execute(self, **kwargs: Any) -> Any:
        skill_name = kwargs.get("name", "").strip()

        if not skill_name:
            return "Error: skill name is required"

        content = self._skill_manager.load_skill(skill_name)
        if content.startswith("Error:"):
            return content

        logger.info(f"Skill loaded: {skill_name}")

        return content
