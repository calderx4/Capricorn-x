"""
File Tools - 文件操作工具

提供基本的文件读写功能。
sandbox=True 时限制路径在 workspace 内，sandbox=False 时允许访问任意路径。
"""

from typing import Any, Dict
from loguru import logger

from core.base_tool import BaseTool
from core.sandbox import resolve_path as _resolve_path, MAX_FILE_SIZE
from core.utils import atomic_write


class ReadFileTool(BaseTool):
    """读取文件工具"""

    DEFAULT_LIMIT = 2000

    def __init__(self, workspace_root: str = "./workspace", sandbox: bool = True):
        self._workspace_root = workspace_root
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "读取文件内容（纯文本），带行号输出（cat -n 格式）。\n"
            "参数：path（必填）、offset（0-based 起始行，默认 0）、limit（最大行数，默认 2000）。\n"
            "适用场景：查看配置、代码检查、数据分析。\n"
            "限制：最大 10MB，超过报错。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to read"
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (0-based). Default: 0",
                    "minimum": 0
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read. Default: 2000",
                    "minimum": 0
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str, offset: int = 0, limit: int = 0) -> str:
        try:
            file_path = _resolve_path(path, self._workspace_root, self._sandbox)

            if not file_path.exists():
                return f"Error: File not found: {path}"

            if not file_path.is_file():
                return f"Error: Not a file: {path}"

            size = file_path.stat().st_size
            if size > MAX_FILE_SIZE:
                return f"Error: File too large ({size // 1024 // 1024}MB), max 10MB"

            # 防护：offset/limit 不允许负数
            offset = max(0, offset)
            if limit < 0:
                limit = 0
            effective_limit = limit if limit > 0 else self.DEFAULT_LIMIT

            # 逐行读取，跳过 offset 前的行，最多读 effective_limit 行
            collected = []
            end_line = offset + effective_limit
            with open(file_path, "r", encoding="utf-8") as f:
                for line_idx, line in enumerate(f):
                    line_num = line_idx + 1  # 1-based
                    if line_num <= offset:
                        continue
                    if line_num > end_line:
                        break
                    collected.append((line_num, line.rstrip("\n")))

            if not collected:
                return ""

            # cat -n 格式：右对齐行号 + tab + 内容，位数按实际最大行号
            width = len(str(collected[-1][0]))
            result = "\n".join(
                f"{num:>{width}}\t{text}" for num, text in collected
            )
            logger.debug(f"Read file: {path} (lines {collected[0][0]}-{collected[-1][0]}, {size} bytes)")
            return result

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
            "新建或覆盖文件，自动创建父目录。适用场景：保存结果、生成代码、写文档。\n"
            "注意：直接覆盖原内容，无备份；如只需小改用 edit_file。"
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
            atomic_write(file_path, content)
            logger.debug(f"Wrote file: {path} ({len(content)} chars)")

            return f"Successfully wrote to {path}"

        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.error(f"Failed to write file '{path}': {e}")
            return f"Error: Failed to write file: {str(e)}"


class EditFileTool(BaseTool):
    """精准编辑文件工具 — 字符串替换"""

    def __init__(self, workspace_root: str = "./workspace", sandbox: bool = True):
        self._workspace_root = workspace_root
        self._sandbox = sandbox


    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "对文件做精确字符串替换。找到 old_string 替换为 new_string。\n"
            "限制：old_string 必须唯一（出现多次需 replace_all=true 或加更多上下文）。\n"
            "适用：修改配置、增删代码行、修复文字 — 小改动首选。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to edit",
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact text to find in the file",
                },
                "new_string": {
                    "type": "string",
                    "description": "The text to replace old_string with",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "If true, replace all occurrences of old_string. Default: false",
                },
            },
            "required": ["path", "old_string", "new_string"],
        }

    async def execute(
        self, path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> str:
        try:
            file_path = _resolve_path(path, self._workspace_root, self._sandbox)

            if not file_path.exists():
                return f"Error: File not found: {path}"
            if not file_path.is_file():
                return f"Error: Not a file: {path}"

            content = file_path.read_text(encoding="utf-8")

            count = content.count(old_string)
            if count == 0:
                return f"Error: old_string not found in {path}"
            if count > 1 and not replace_all:
                return f"Error: old_string appears {count} times in {path}. Use replace_all=true to replace all occurrences, or provide more surrounding context to make it unique."

            new_content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)
            atomic_write(file_path, new_content)
            logger.debug(f"Edited file: {path} ({count} replacement(s))")
            return f"Successfully edited {path} ({count} replacement(s))"

        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.error(f"Failed to edit file '{path}': {e}")
            return f"Error: Failed to edit file: {str(e)}"


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
            "列出目录下的文件（[FILE]）和子目录（[DIR]/）。适用场景：探索目录结构、找文件、查看可用资源。"
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
