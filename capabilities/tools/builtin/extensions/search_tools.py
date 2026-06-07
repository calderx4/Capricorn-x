"""
Search Tools - 文件搜索工具

提供 glob 模式匹配和 grep 内容搜索功能。
sandbox=True 时限制搜索路径在 workspace 内。
"""

import re
from pathlib import Path
from typing import Any, Dict

from loguru import logger

from core.base_tool import BaseTool
from core.sandbox import check_path

# ── 共享常量 ──────────────────────────────────────────────
MAX_GLOB_RESULTS = 500
MAX_GREP_RESULTS = 200
BINARY_CHECK_BYTES = 8192      # 前 8KB 用于检测二进制文件
MAX_GREP_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _resolve_path(path: str, workspace_root: str, sandbox: bool) -> Path:
    """解析路径，sandbox 模式下验证在 workspace 内"""
    p = Path(path)
    if not p.is_absolute():
        p = Path(workspace_root) / p
    p = p.resolve()

    allowed, reason = check_path(str(p), workspace_root, sandbox)
    if not allowed:
        raise ValueError(reason)

    return p


def _is_binary(file_path: Path) -> bool:
    """检测文件是否为二进制（前 8KB 含 \\x00 则判定为二进制）"""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(BINARY_CHECK_BYTES)
        return b"\x00" in chunk
    except OSError:
        return True


# ── Glob 工具 ─────────────────────────────────────────────
class GlobTool(BaseTool):
    """文件模式匹配工具"""

    def __init__(self, workspace_root: str = "./workspace", sandbox: bool = True):
        self._workspace_root = workspace_root
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return (
            "用 glob 模式递归匹配文件路径。适用场景：查找文件、项目结构扫描。\n"
            "参数：pattern（必填，如 '**/*.py'）、path（可选，默认 workspace 根目录）。\n"
            f"结果上限 {MAX_GLOB_RESULTS} 条。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match files (e.g. '**/*.py', 'src/**/*.ts')"
                },
                "path": {
                    "type": "string",
                    "description": "Base directory to search from. Default: workspace root"
                }
            },
            "required": ["pattern"]
        }

    async def execute(self, pattern: str, path: str = None) -> str:
        try:
            base = _resolve_path(
                path or self._workspace_root, self._workspace_root, self._sandbox
            )

            if not base.exists():
                return f"Error: Directory not found: {path or self._workspace_root}"
            if not base.is_dir():
                return f"Error: Not a directory: {path or self._workspace_root}"

            matches = sorted(base.rglob(pattern))

            # 只保留文件，排除目录和符号链接
            matches = [m for m in matches if m.is_file() and not m.is_symlink()]

            if not matches:
                return f"No files matching '{pattern}' in {path or '.'}"

            total = len(matches)
            truncated = total > MAX_GLOB_RESULTS
            matches = matches[:MAX_GLOB_RESULTS]

            # 返回相对于 base 的路径
            try:
                lines = [str(m.relative_to(base)) for m in matches]
            except ValueError:
                lines = [str(m) for m in matches]

            result = "\n".join(lines)
            if truncated:
                result += f"\n... (truncated, showing first {MAX_GLOB_RESULTS} of {total} results)"

            logger.debug(f"Glob '{pattern}': {min(total, MAX_GLOB_RESULTS)}/{total} matches")
            return result

        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.error(f"Glob failed: {e}")
            return f"Error: Glob search failed: {str(e)}"


# ── Grep 工具 ─────────────────────────────────────────────
class GrepTool(BaseTool):
    """文件内容搜索工具"""

    def __init__(self, workspace_root: str = "./workspace", sandbox: bool = True):
        self._workspace_root = workspace_root
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return (
            "正则表达式搜索文件内容。适用场景：代码搜索、日志分析、文本提取。\n"
            "参数：pattern（必填，正则表达式）、include（可选，glob 过滤如 '*.py'）、"
            "path（可选，默认 workspace 根目录）。\n"
            f"跳过二进制文件（前 8KB 检测）和 >10MB 文件。结果上限 {MAX_GREP_RESULTS} 条。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regular expression pattern to search for"
                },
                "include": {
                    "type": "string",
                    "description": "Glob filter to limit which files are searched (e.g. '*.py'). Default: '*'"
                },
                "path": {
                    "type": "string",
                    "description": "Base directory to search from. Default: workspace root"
                }
            },
            "required": ["pattern"]
        }

    async def execute(self, pattern: str, include: str = "*", path: str = None) -> str:
        try:
            # 验证正则表达式
            try:
                regex = re.compile(pattern)
            except re.error as e:
                return f"Error: Invalid regex pattern: {e}"

            base = _resolve_path(
                path or self._workspace_root, self._workspace_root, self._sandbox
            )

            if not base.exists():
                return f"Error: Directory not found: {path or self._workspace_root}"
            if not base.is_dir():
                return f"Error: Not a directory: {path or self._workspace_root}"

            # 用 include glob 筛选文件（排除符号链接）
            candidate_files = sorted(
                f for f in base.rglob(include)
                if f.is_file() and not f.is_symlink()
            )

            results = []
            total_matches = 0
            truncated = False

            for file_path in candidate_files:
                if truncated:
                    break

                # 跳过大文件
                try:
                    if file_path.stat().st_size > MAX_GREP_FILE_SIZE:
                        continue
                except OSError:
                    continue

                # 跳过二进制文件
                if _is_binary(file_path):
                    continue

                try:
                    text = file_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                try:
                    rel = str(file_path.relative_to(base))
                except ValueError:
                    rel = str(file_path)

                for line_num, line in enumerate(text.splitlines(), start=1):
                    if regex.search(line):
                        results.append(f"{rel}:{line_num}:{line}")
                        total_matches += 1
                        if total_matches >= MAX_GREP_RESULTS:
                            truncated = True
                            break

            if not results:
                return f"No matches found for pattern '{pattern}'"

            result = "\n".join(results)
            if truncated:
                result += f"\n... (truncated at {MAX_GREP_RESULTS} results)"

            logger.debug(f"Grep '{pattern}': {total_matches} matches")
            return result

        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.error(f"Grep failed: {e}")
            return f"Error: Grep search failed: {str(e)}"
