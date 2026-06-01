"""
Tests for core/paths.py — verify path constants resolve correctly
"""

from core.paths import (
    CORE_DIR,
    PROJECT_ROOT,
    CONFIG_DIR,
    CAPABILITIES_DIR,
    GATEWAY_DIR,
    WORKSPACE_DIR,
    PROMPTS_DIR,
    ROLES_DIR,
    BUILTIN_EXTENSIONS,
    WORKFLOW_EXTENSIONS,
)


class TestPathConstants:
    def test_core_dir_is_package_dir(self):
        assert CORE_DIR.name == "core"

    def test_project_root_is_parent_of_core(self):
        assert CORE_DIR.parent == PROJECT_ROOT

    def test_config_dir_under_project_root(self):
        assert CONFIG_DIR.parent == PROJECT_ROOT
        assert CONFIG_DIR.name == "config"

    def test_capabilities_dir_under_project_root(self):
        assert CAPABILITIES_DIR.parent == PROJECT_ROOT
        assert CAPABILITIES_DIR.name == "capabilities"

    def test_prompts_dir_under_config(self):
        assert PROMPTS_DIR.parent == CONFIG_DIR

    def test_roles_dir_under_config(self):
        assert ROLES_DIR.parent == CONFIG_DIR

    def test_builtin_extensions_path(self):
        assert "builtin" in str(BUILTIN_EXTENSIONS)
        assert "extensions" in str(BUILTIN_EXTENSIONS)

    def test_workflow_extensions_path(self):
        assert "workflow" in str(WORKFLOW_EXTENSIONS)
        assert "extensions" in str(WORKFLOW_EXTENSIONS)

    def test_all_paths_are_absolute(self):
        paths = [
            CORE_DIR, PROJECT_ROOT, CONFIG_DIR, CAPABILITIES_DIR,
            GATEWAY_DIR, WORKSPACE_DIR, PROMPTS_DIR, ROLES_DIR,
            BUILTIN_EXTENSIONS, WORKFLOW_EXTENSIONS,
        ]
        for p in paths:
            assert p.is_absolute(), f"{p} is not absolute"
