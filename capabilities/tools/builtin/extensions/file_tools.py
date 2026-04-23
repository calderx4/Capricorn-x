"""
File Tools - 文件操作工具

提供基本的文件读写功能。
sandbox=True 时限制路径在 workspace 内，sandbox=False 时允许访问任意路径。
"""

from pathlib import Path
from typing import Any, Dict
from loguru import logger

import sys
from pathlib import Path as PathLib
sys.path.insert(0, str(PathLib(__file__).parent.parent.parent.parent))

from core.base_tool import BaseTool


def _resolve_path(path: str, workspace_root: str, sandbox: bool) -> Path:
    """解析路径，sandbox 模式下验证在 workspace 内"""
    p = Path(path)
    if not p.is_absolute():
        p = Path(workspace_root) / p
    p = p.resolve()

    if sandbox:
        root = Path(workspace_root).resolve()
        if not str(p).startswith(str(root)):
            raise ValueError(f"Path '{path}' is outside workspace (sandbox mode enabled)")

    return p


class ReadFileTool(BaseTool):
    """读取文件工具"""

    def __init__(self, workspace_root: str = "./workspace", sandbox: bool = True):
        self._workspace_root = workspace_root
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read the contents of a file from the local filesystem. "
            "Use this when you need to inspect file contents, check configurations, "
            "or read user-provided data. Returns the full text content of the file."
        )

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
        try:
            file_path = _resolve_path(path, self._workspace_root, self._sandbox)

            if not file_path.exists():
                return f"Error: File not found: {path}"

            if not file_path.is_file():
                return f"Error: Not a file: {path}"

            content = file_path.read_text(encoding="utf-8")
            logger.debug(f"Read file: {path} ({len(content)} chars)")
            return content

        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.error(f"Failed to read file '{path}': {e}")
            return f"Error: Failed to read file: {str(e)}"


class WriteFileTool(BaseTool):
    """写入文件工具"""

    def __init__(self, workspace_root: str = "./workspace", sandbox: bool = True):
        self._workspace_root = workspace_root
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a file on the local filesystem. "
            "Creates parent directories automatically if they don't exist. "
            "Overwrites existing files. Use this to save results, create documents, "
            "or write generated content."
        )

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
        try:
            file_path = _resolve_path(path, self._workspace_root, self._sandbox)

            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            logger.debug(f"Wrote file: {path} ({len(content)} chars)")

            return f"Successfully wrote to {path}"

        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.error(f"Failed to write file '{path}': {e}")
            return f"Error: Failed to write file: {str(e)}"


class ListFilesTool(BaseTool):
    """列出文件工具"""

    def __init__(self, workspace_root: str = "./workspace", sandbox: bool = True):
        self._workspace_root = workspace_root
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "list_files"

    @property
    def description(self) -> str:
        return (
            "List files and subdirectories in a directory. "
            "Use this to explore the workspace structure, find files, "
            "or check what resources are available before reading."
        )

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
        try:
            dir_path = _resolve_path(path, self._workspace_root, self._sandbox)

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

        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.error(f"Failed to list directory '{path}': {e}")
            return f"Error: Failed to list directory: {str(e)}"
