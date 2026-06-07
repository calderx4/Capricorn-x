"""
Skill Manager - 技能管理器

职责：
- 管理所有技能
- 生成技能摘要（XML 格式）
- 按需加载技能详情
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from loguru import logger

from .loader import SkillLoader


class SkillManager:
    """技能管理器"""

    def __init__(self, skills_dir: str = None):
        self._skills: Dict[str, Dict[str, Any]] = {}
        if skills_dir:
            self._load_dir(skills_dir)

    def _load_dir(self, skills_dir: str) -> None:
        """加载 skill 目录"""
        dir_path = Path(skills_dir)
        if not dir_path.exists():
            return

        for skill_dir in dir_path.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_file = SkillLoader.find_skill_file(skill_dir)
            if not skill_file:
                continue

            try:
                skill_data = SkillLoader.load(skill_file)
                skill_name = skill_data.get("name")
                if not skill_name:
                    logger.warning(f"Skill missing 'name' field: {skill_file}")
                    continue

                self._skills[skill_name] = skill_data
                logger.debug(f"Loaded skill: {skill_name}")
            except Exception as e:
                logger.error(f"Failed to load skill from {skill_file}: {e}")

    def list_skills(self) -> List[str]:
        """
        列出所有技能名称

        Returns:
            技能名称列表
        """
        return list(self._skills.keys())

    def load_skill(self, name: str) -> str:
        """
        加载完整技能内容

        Args:
            name: 技能名称

        Returns:
            技能详细内容
        """
        skill_data = self._skills.get(name)
        if not skill_data:
            return f"Error: Skill '{name}' not found"

        return skill_data.get("content", "")

    def get_available_skills(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有 available=true 的技能（即告诉模型可用的技能）

        Returns:
            可用技能字典 {name: skill_data}
        """
        return {
            name: data for name, data in self._skills.items()
            if data.get("available", False)
        }

    def get_autoload_skills(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有 autoload=true 的技能，用于直接注入 system prompt。
        """
        return {
            name: data for name, data in self._skills.items()
            if data.get("autoload", False)
        }
