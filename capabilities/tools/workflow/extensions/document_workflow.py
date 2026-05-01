"""
Document Creation Workflow - 文档创建工作流

示例工作流，展示如何组合多个工具完成复杂任务。
"""

from typing import Any, Dict, List
from datetime import datetime

from core.base_workflow import BaseWorkflow


class DocumentCreationWorkflow(BaseWorkflow):
    """文档创建工作流"""

    @property
    def name(self) -> str:
        return "create_document"

    @property
    def description(self) -> str:
        return "创建结构化文档，支持 Markdown 格式和元数据（标题/作者/标签/时间戳）。\n参数：title（必填）、content（必填）、path（保存路径，默认 ./documents/{title}.md）、author、tags。"

    @property
    def required_tools(self) -> List[str]:
        return ["write_file"]

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "文档标题（必填）"},
                "content": {"type": "string", "description": "文档内容（必填）"},
                "path": {"type": "string", "description": "保存路径，可选，默认 ./documents/{title}.md"},
                "author": {"type": "string", "description": "作者，可选，默认 Capricorn Agent"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表，可选"},
            },
            "required": ["title", "content"],
        }

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
