"""
Document Creation Workflow - 文档创建工作流

示例工作流，展示如何组合多个工具完成复杂任务。
"""

from typing import Any, List
from datetime import datetime

from core.base_workflow import BaseWorkflow


class DocumentCreationWorkflow(BaseWorkflow):
    """文档创建工作流"""

    @property
    def name(self) -> str:
        return "create_document"

    @property
    def description(self) -> str:
        return "Create a structured document with metadata and formatting."

    @property
    def required_tools(self) -> List[str]:
        return ["write_file"]

    async def execute(self, tools: Any, **kwargs: Any) -> Any:
        """
        执行文档创建工作流

        Args:
            tools: 工具注册表实例
            **kwargs: 工作流参数
                - title: 文档标题
                - content: 文档内容
                - path: 保存路径（可选，默认为 ./documents/{title}.md）
                - author: 作者（可选）
                - tags: 标签列表（可选）

        Returns:
            执行结果
        """
        title = kwargs.get("title")
        content = kwargs.get("content")

        if not title or not content:
            return "Error: Missing required parameters: title and content"

        # 构建文档路径
        path = kwargs.get("path", f"./documents/{title}.md")

        # 构建文档内容
        author = kwargs.get("author", "Capricorn Agent")
        tags = kwargs.get("tags", [])

        # 添加元数据头部
        document_content = self._build_document(title, content, author, tags)

        # 调用 write_file 工具
        result = await tools.execute("write_file", {
            "path": path,
            "content": document_content
        })

        return result

    def _build_document(
        self,
        title: str,
        content: str,
        author: str,
        tags: List[str]
    ) -> str:
        """构建文档内容"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 构建元数据头部
        header = f"""---
title: {title}
author: {author}
created: {timestamp}
tags: {', '.join(tags) if tags else 'none'}
---

# {title}

"""

        # 添加内容
        full_content = header + content

        # 添加页脚
        footer = f"""

---

*Created by {author} at {timestamp}*
"""

        return full_content + footer
