"""
Exec Tools - 终端执行工具

提供 shell 命令执行功能。
"""

import asyncio
import subprocess
from typing import Any, Dict
from loguru import logger

import sys
from pathlib import Path as PathLib
sys.path.insert(0, str(PathLib(__file__).parent.parent.parent.parent))

from core.base_tool import BaseTool


class ExecTool(BaseTool):
    """Shell 命令执行工具"""

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command on the system. "
            "Returns stdout, stderr, and exit code. "
            "Supports an optional working directory (cwd) and timeout in seconds. "
            "Use this for running scripts, installing packages, git operations, "
            "or any system-level tasks that require shell access."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory (optional)"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 30)",
                    "default": 30
                }
            },
            "required": ["command"]
        }

    async def execute(self, command: str, cwd: str = None, timeout: int = 30) -> str:
        """
        执行 shell 命令

        Args:
            command: 要执行的命令
            cwd: 工作目录（可选）
            timeout: 超时时间（秒）

        Returns:
            命令输出结果
        """
        try:
            logger.debug(f"Executing command: {command}")

            # 创建子进程
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )

            # 等待命令完成（带超时）
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                # 超时，杀死进程
                proc.kill()
                await proc.wait()
                return f"Error: Command timed out after {timeout} seconds"

            # 解码输出
            result = []

            if stdout:
                stdout_text = stdout.decode('utf-8', errors='replace')
                if stdout_text.strip():
                    result.append(stdout_text.strip())

            if stderr:
                stderr_text = stderr.decode('utf-8', errors='replace')
                if stderr_text.strip():
                    result.append(f"[stderr] {stderr_text.strip()}")

            # 组合输出
            output = "\n".join(result)

            # 添加退出码信息（如果不是 0）
            if proc.returncode != 0:
                output = f"{output}\n[exit code: {proc.returncode}]"

            logger.debug(f"Command completed with exit code {proc.returncode}")

            return output if output else "(no output)"

        except Exception as e:
            logger.error(f"Failed to execute command '{command}': {e}")
            return f"Error: {str(e)}"
