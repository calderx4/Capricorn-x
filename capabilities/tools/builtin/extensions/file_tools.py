"""
File Tools - 文件操作工具

提供基本的文件读写功能。
"""

from pathlib import Path
from typing import Any, Dict
from loguru import logger

import sys
from pathlib import Path as PathLib
sys.path.insert(0, str(PathLib(__file__).parent.parent.parent.parent))

from core.base_tool import BaseTool


class ReadFileTool(BaseTool):
    """读取文件工具"""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file from the local filesystem."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to read"
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str) -> str:
        """
        读取文件内容

        Args:
            path: 文件路径

        Returns:
            文件内容
        """
        try:
            file_path = Path(path)

            if not file_path.exists():
                return f"Error: File not found: {path}"

            if not file_path.is_file():
                return f"Error: Not a file: {path}"

            content = file_path.read_text(encoding="utf-8")
            logger.debug(f"Read file: {path} ({len(content)} chars)")
            return content

        except Exception as e:
            logger.error(f"Failed to read file '{path}': {e}")
            return f"Error: Failed to read file: {str(e)}"


class WriteFileTool(BaseTool):
    """写入文件工具"""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file on the local filesystem."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to write"
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file"
                }
            },
            "required": ["path", "content"]
        }

    async def execute(self, path: str, content: str) -> str:
        """
        写入文件内容

        Args:
            path: 文件路径
            content: 文件内容

        Returns:
            成功或错误消息
        """
        try:
            file_path = Path(path)

            # 创建父目录
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # 写入文件
            file_path.write_text(content, encoding="utf-8")
            logger.debug(f"Wrote file: {path} ({len(content)} chars)")

            return f"Successfully wrote to {path}"

        except Exception as e:
            logger.error(f"Failed to write file '{path}': {e}")
            return f"Error: Failed to write file: {str(e)}"


class ListFilesTool(BaseTool):
    """列出文件工具"""

    @property
    def name(self) -> str:
        return "list_files"

    @property
    def description(self) -> str:
        return "List files in a directory."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The directory path to list files from"
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str) -> str:
        """
        列出目录中的文件

        Args:
            path: 目录路径

        Returns:
            文件列表
        """
        try:
            dir_path = Path(path)

            if not dir_path.exists():
                return f"Error: Directory not found: {path}"

            if not dir_path.is_dir():
                return f"Error: Not a directory: {path}"

            files = []
            for item in sorted(dir_path.iterdir()):
                if item.is_file():
                    files.append(f"[FILE] {item.name}")
                elif item.is_dir():
                    files.append(f"[DIR]  {item.name}/")

            if not files:
                return f"Directory '{path}' is empty"

            result = "\n".join(files)
            logger.debug(f"Listed {len(files)} items in {path}")
            return result

        except Exception as e:
            logger.error(f"Failed to list directory '{path}': {e}")
            return f"Error: Failed to list directory: {str(e)}"
