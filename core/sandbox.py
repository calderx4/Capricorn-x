"""
Sandbox - 沙盒路径校验

sandbox=true 时，所有文件操作和 exec 的路径必须限定在 workspace root 内。
"""

from pathlib import Path


# ── 文件操作共享常量 ──────────────────────────────────────
MAX_FILE_SIZE = 10 * 1024 * 1024   # 10MB — read_file / grep 共用
BINARY_CHECK_BYTES = 8192          # 前 8KB 用于检测二进制文件


def resolve_path(path: str, workspace_root: str, sandbox: bool) -> Path:
    """解析路径，sandbox 模式下验证在 workspace 内。

    被 file_tools / search_tools 等所有文件工具共用。
    """
    p = Path(path)
    if not p.is_absolute():
        p = Path(workspace_root) / p
    p = p.resolve()

    allowed, reason = check_path(str(p), workspace_root, sandbox)
    if not allowed:
        raise ValueError(reason)

    return p


def is_binary(file_path: Path) -> bool:
    """检测文件是否为二进制（前 8KB 含 \\x00 则判定为二进制）"""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(BINARY_CHECK_BYTES)
        return b"\x00" in chunk
    except OSError:
        return True


def check_path(path: str, root: str, sandbox: bool) -> tuple[bool, str]:
    """
    检查路径是否在沙盒范围内。

    Returns:
        (allowed, reason) — allowed=True 表示放行，reason 为空。
        allowed=False 表示拒绝，reason 是原因说明。
    """
    if not sandbox:
        return True, ""

    resolved = Path(path).resolve()
    root_resolved = Path(root).resolve()

    try:
        resolved.relative_to(root_resolved)
        return True, ""
    except ValueError:
        return False, f"Path '{path}' is outside workspace '{root}'"


def check_command(command: str, blocked_commands: list[str]) -> tuple[bool, str]:
    """
    检查命令是否在黑名单中。

    匹配规则：
    1. 首词精确匹配（单词条目如 "rm"、"mkfs"）
    2. 多词条目在整个命令中子串匹配（如 "rm -rf /"、"dd if="）

    Returns:
        (allowed, reason)
    """
    import shlex
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    base = parts[0].lower() if parts else ""
    command_lower = command.lower()

    for blocked in blocked_commands:
        blocked_lower = blocked.lower().strip()
        if not blocked_lower:
            continue
        # 首词精确匹配（单词条目，如 "rm" 匹配 "rm file.txt"）
        if base == blocked_lower:
            return False, f"Blocked command: '{blocked}'"
        # 多词条目：在整个命令中子串匹配（如 "rm -rf /" 匹配 "rm -rf / --no-preserve-root"）
        if " " in blocked_lower and blocked_lower in command_lower:
            return False, f"Blocked command pattern: '{blocked}'"
    return True, ""
