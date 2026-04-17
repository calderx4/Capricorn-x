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

    def __init__(self, skills_dir: str):
        """
        初始化技能管理器

        Args:
            skills_dir: 技能目录路径
        """
        self.skills_dir = Path(skills_dir)
        self._skills: Dict[str, Dict[str, Any]] = {}
        self._load_all_skills()

    def _load_all_skills(self) -> None:
        """加载所有技能"""
        if not self.skills_dir.exists():
            logger.warning(f"Skills directory not found: {self.skills_dir}")
            return

        # 遍历技能目录
        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue

            # 查找 SKILL.md 文件
            skill_file = SkillLoader.find_skill_file(skill_dir)
            if not skill_file:
                logger.debug(f"No SKILL.md found in {skill_dir}")
                continue

            try:
                # 加载技能
                skill_data = SkillLoader.load(skill_file)
                skill_name = skill_data.get("name")

                if skill_name:
                    self._skills[skill_name] = skill_data
                    logger.debug(f"Loaded skill: {skill_name}")
                else:
                    logger.warning(f"Skill missing 'name' field: {skill_file}")

            except Exception as e:
                logger.error(f"Failed to load skill from {skill_file}: {e}")

    def list_skills(self) -> List[str]:
        """
        列出所有技能名称

        Returns:
            技能名称列表
        """
        return list(self._skills.keys())

    def get_skill(self, name: str) -> Optional[Dict[str, Any]]:
        """
        获取技能详情

        Args:
            name: 技能名称

        Returns:
            技能数据字典，不存在返回 None
        """
        return self._skills.get(name)

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

    def get_skill_summary(self, include_always: bool = True) -> str:
        """
        获取技能摘要（XML 格式）

        Args:
            include_always: 是否只包含 always=true 的技能

        Returns:
            XML 格式的技能摘要
        """
        summaries = []

        for skill_name, skill_data in self._skills.items():
            if include_always and not skill_data.get("always", False):
                continue

            summary = SkillLoader.get_summary(skill_data)
            summaries.append(summary)

        if not summaries:
            return "<skills>\n  (no skills loaded)\n</skills>"

        return "<skills>\n" + "\n".join(summaries) + "\n</skills>"

    def get_always_skills(self) -> List[str]:
        """
        获取所有 always=true 的技能名称

        Returns:
            技能名称列表
        """
        return [
            name for name, data in self._skills.items()
            if data.get("always", False)
        ]

    def has(self, name: str) -> bool:
        """检查技能是否存在"""
        return name in self._skills

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills
