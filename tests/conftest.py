"""
Capricorn-x 共享测试 fixtures
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from config.settings import WorkspaceConfig


@pytest.fixture
def workspace_config(tmp_path):
    """WorkspaceConfig pointing to tmp_path."""
    return WorkspaceConfig(root=str(tmp_path))


@pytest.fixture
def workspace_root(tmp_path):
    """Convenience: string path to tmp_path."""
    return str(tmp_path)


@pytest.fixture
def mock_llm():
    """Mock LLM client with bind_tools returning self."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock()
    llm.bind_tools = MagicMock(return_value=llm)
    return llm


@pytest.fixture
def mock_capability_registry():
    """Mock CapabilityRegistry with empty tools."""
    reg = MagicMock()
    reg.tools = MagicMock()
    reg.tools.execute = AsyncMock(return_value="ok")
    reg.tools.list_by_layer = MagicMock(
        return_value={"builtin": [], "mcp": [], "workflow": []}
    )
    reg.tools.get = MagicMock(return_value=None)
    reg.tools.get_langchain_tools = MagicMock(return_value=[])
    reg.get_langchain_tools = MagicMock(return_value=[])
    return reg


@pytest.fixture
def mock_session_manager():
    """Mock SessionManager with empty-history session."""
    mgr = MagicMock()
    session = MagicMock()
    session.get_history.return_value = []
    session.add_message = MagicMock()
    session.thread_id = "test"
    mgr.get_session.return_value = session
    mgr.workspace = MagicMock()
    mgr.workspace.root = "./workspace"
    mgr.save_session = MagicMock()
    return mgr


@pytest.fixture
def mock_long_term_memory():
    """Mock LongTermMemory returning empty string."""
    mem = MagicMock()
    mem.read.return_value = ""
    return mem


@pytest.fixture
def mock_skill_manager():
    """Mock SkillManager with no skills."""
    mgr = MagicMock()
    mgr.list_skills.return_value = []
    mgr.get_available_skills.return_value = {}
    mgr.get_autoload_skills.return_value = {}
    return mgr


@pytest.fixture
def prompt_template(tmp_path):
    """Create a system.md template and return its path string."""
    template = tmp_path / "system.md"
    template.write_text(
        "System Prompt\n\n"
        "{{workspace_section}}\n\n"
        "{{tools_section}}\n\n"
        "{{skills_section}}\n\n"
        "{{memory_section}}\n\n"
        "{{bia_section}}\n\n"
        "{{agent_md_section}}\n\n"
        "{{task_prompt}}\n\n"
        "Current time: {{current_time}}\n",
        encoding="utf-8",
    )
    return str(template)
