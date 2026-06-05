import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from agent.agent import CapricornGraph


def _make_mock_graph(max_iterations=50):
    """构造 CapricornGraph 实例，用 mock 替代所有依赖"""
    graph = object.__new__(CapricornGraph)
    graph.capability_registry = MagicMock()
    graph.capability_registry.tools = MagicMock()
    graph.capability_registry.tools.execute = AsyncMock(return_value="ok")
    graph.capability_registry.get_langchain_tools = MagicMock(return_value=[])
    graph.capability_registry.tools.get_langchain_tools = MagicMock(return_value=[])
    graph.skill_manager = MagicMock()
    graph.session_manager = MagicMock()
    graph.long_term_memory = MagicMock()
    graph.long_term_memory.read = MagicMock(return_value="")
    graph.history_log = MagicMock()
    graph.llm_client = MagicMock()
    graph.sandbox = True
    graph.max_iterations = max_iterations
    graph._llm_with_tools = MagicMock()
    graph._exclude_tools = set()
    graph.bia_path = None
    graph.system_prompt_path = None
    graph.system_prompt_override = None
    return graph


def _make_runnable_graph():
    """Graph with session + LLM mock ready for run() tests."""
    graph = _make_mock_graph()
    graph.system_prompt_override = "test prompt"
    session = MagicMock()
    session.get_history.return_value = []
    session.add_message = MagicMock()
    graph.session_manager.get_session.return_value = session
    graph.session_manager.workspace = MagicMock()
    graph.session_manager.workspace.root = "./workspace"
    graph.session_manager.save_session = MagicMock()
    response = AIMessage(content="done")
    graph._llm_with_tools.ainvoke = AsyncMock(return_value=response)
    return graph


class TestDictToMessage:
    def setup_method(self):
        self.graph = _make_mock_graph()

    def test_user_role(self):
        msg = {"role": "user", "content": "hello"}
        result = self.graph._dict_to_message(msg)
        assert isinstance(result, HumanMessage)
        assert result.content == "hello"

    def test_system_role(self):
        msg = {"role": "system", "content": "you are helpful"}
        result = self.graph._dict_to_message(msg)
        assert isinstance(result, SystemMessage)

    def test_assistant_role(self):
        msg = {"role": "assistant", "content": "response"}
        result = self.graph._dict_to_message(msg)
        assert isinstance(result, AIMessage)

    def test_tool_role(self):
        msg = {"role": "tool", "content": "file content", "tool_call_id": "call_123"}
        result = self.graph._dict_to_message(msg)
        assert isinstance(result, ToolMessage)
        assert result.tool_call_id == "call_123"
        assert result.content == "file content"

    def test_assistant_with_tool_calls(self):
        msg = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "name": "read_file", "args": {"path": "test.py"}}
            ],
        }
        result = self.graph._dict_to_message(msg)
        assert isinstance(result, AIMessage)
        assert result.tool_calls == msg["tool_calls"]

    def test_default_role_falls_back_to_ai(self):
        msg = {"role": "unknown", "content": "something"}
        result = self.graph._dict_to_message(msg)
        assert isinstance(result, AIMessage)

    def test_orphan_tool_message(self):
        msg = {"role": "tool", "content": "orphan result", "tool_call_id": ""}
        result = self.graph._dict_to_message(msg)
        assert isinstance(result, HumanMessage)
        assert "[orphan tool result]" in result.content


class TestExtractContent:
    def setup_method(self):
        self.graph = _make_mock_graph()

    def test_string_content(self):
        msg = AIMessage(content="hello")
        assert self.graph._extract_content(msg) == "hello"

    def test_list_content_with_text_blocks(self):
        msg = AIMessage(content=[
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "World"},
        ])
        assert "Hello" in self.graph._extract_content(msg)

    def test_thinking_tags_stripped(self):
        msg = AIMessage(content="<thinking>inner thought</thinking>actual response")
        result = self.graph._extract_content(msg)
        assert "<thinking>" not in result
        assert "actual response" in result

    def test_list_content_only_image_blocks(self):
        msg = AIMessage(content=[
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ])
        result = self.graph._extract_content(msg)
        assert isinstance(result, str)  # falls back to str(content)


class TestSummarizeMessages:
    def setup_method(self):
        self.graph = _make_mock_graph()

    def test_summary_format(self):
        messages = [
            SystemMessage(content="system"),
            HumanMessage(content="hello"),
            AIMessage(content="response"),
        ]
        summary = self.graph._summarize_messages(messages)
        assert "共 3 条" in summary
        assert "SystemMessage" in summary
        assert "HumanMessage" in summary

    def test_multimodal_summary(self):
        msg = AIMessage(content=[
            {"type": "text", "text": "response"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ])
        summary = self.graph._summarize_messages([msg])
        assert "[multimodal:" in summary
        assert "2 blocks" in summary


class TestMultimodalHumanMessage:
    """v0.2.7: Test multimodal HumanMessage construction with images."""

    def setup_method(self):
        self.graph = _make_runnable_graph()

    async def test_images_create_multimodal_content(self):
        await self.graph.run(
            "描述这张图",
            images=[{"base64": "abc123", "content_type": "image/png"}],
        )
        # messages[1] is the HumanMessage (index 0 is SystemMessage)
        call_args = self.graph._llm_with_tools.ainvoke.call_args[0][0]
        human_msg = call_args[1]
        assert isinstance(human_msg, HumanMessage)
        assert isinstance(human_msg.content, list)
        assert any(block.get("type") == "image_url" for block in human_msg.content)

    async def test_image_dict_with_default_mime(self):
        await self.graph.run(
            "看图",
            images=[{"base64": "abc123"}],
        )
        call_args = self.graph._llm_with_tools.ainvoke.call_args[0][0]
        human_msg = call_args[1]
        image_blocks = [b for b in human_msg.content if b.get("type") == "image_url"]
        assert len(image_blocks) == 1
        assert "image/png" in image_blocks[0]["image_url"]["url"]

    async def test_image_pure_base64_string(self):
        await self.graph.run(
            "看图",
            images=["raw_base64_data"],
        )
        call_args = self.graph._llm_with_tools.ainvoke.call_args[0][0]
        human_msg = call_args[1]
        image_blocks = [b for b in human_msg.content if b.get("type") == "image_url"]
        assert len(image_blocks) == 1

    async def test_multiple_images(self):
        await self.graph.run(
            "看这些图",
            images=[
                {"base64": "img1", "content_type": "image/png"},
                {"base64": "img2", "content_type": "image/jpeg"},
                {"base64": "img3", "content_type": "image/png"},
            ],
        )
        call_args = self.graph._llm_with_tools.ainvoke.call_args[0][0]
        human_msg = call_args[1]
        image_blocks = [b for b in human_msg.content if b.get("type") == "image_url"]
        assert len(image_blocks) == 3

    async def test_no_images_creates_simple_string(self):
        await self.graph.run("hello")
        call_args = self.graph._llm_with_tools.ainvoke.call_args[0][0]
        human_msg = call_args[1]
        assert isinstance(human_msg.content, str)


class TestAttachmentsInPrompt:
    """v0.2.7: Test attachment-related prompt text injection."""

    def setup_method(self):
        self.graph = _make_runnable_graph()

    async def test_attachments_add_file_list(self):
        await self.graph.run(
            "分析文件",
            attachments=["file1.txt", "file2.py"],
        )
        call_args = self.graph._llm_with_tools.ainvoke.call_args[0][0]
        human_msg = call_args[1]
        assert "file1.txt" in human_msg.content
        assert "file2.py" in human_msg.content
        assert "用户上传了以下文件" in human_msg.content

    async def test_images_with_attachments_adds_vision_hint(self):
        await self.graph.run(
            "看图分析",
            images=[{"base64": "abc", "content_type": "image/png"}],
            attachments=["report.pdf"],
        )
        call_args = self.graph._llm_with_tools.ainvoke.call_args[0][0]
        human_msg = call_args[1]
        text_block = human_msg.content[0]["text"]
        assert "直接看图回答" in text_block

    async def test_attachments_without_images_adds_read_hint(self):
        await self.graph.run(
            "分析",
            attachments=["data.csv"],
        )
        call_args = self.graph._llm_with_tools.ainvoke.call_args[0][0]
        human_msg = call_args[1]
        assert "read_file" in human_msg.content

    async def test_no_attachments_clean_prompt(self):
        await self.graph.run("hello")
        call_args = self.graph._llm_with_tools.ainvoke.call_args[0][0]
        human_msg = call_args[1]
        assert "用户上传了以下文件" not in human_msg.content


class TestBuildSystemPrompt:
    """Test _build_system_prompt with various configurations."""

    def test_override_returns_directly(self):
        graph = _make_mock_graph()
        graph.system_prompt_override = "custom prompt"
        assert graph._build_system_prompt() == "custom prompt"

    def test_builds_from_template(self, tmp_path):
        graph = _make_mock_graph()
        template = tmp_path / "system.md"
        template.write_text(
            "Role: Capricorn\n\n{{workspace_section}}\n\n{{tools_section}}",
            encoding="utf-8",
        )
        graph.system_prompt_path = str(template)
        graph.system_prompt_override = None
        graph.session_manager = MagicMock()
        graph.session_manager.workspace = MagicMock()
        graph.session_manager.workspace.root = "./workspace"
        prompt = graph._build_system_prompt()
        assert "Capricorn" in prompt
        assert "workspace" in prompt

    def test_sandbox_note_present(self, tmp_path):
        graph = _make_mock_graph()
        # Provide a minimal template so build_prompt doesn't crash on None path
        template = tmp_path / "system.md"
        template.write_text("{{workspace_section}}", encoding="utf-8")
        graph.system_prompt_path = str(template)
        graph.system_prompt_override = None
        graph.session_manager = MagicMock()
        graph.session_manager.workspace = MagicMock()
        graph.session_manager.workspace.root = "./workspace"
        prompt = graph._build_system_prompt()
        assert "沙盒" in prompt

    def test_sandbox_note_absent(self, tmp_path):
        graph = _make_mock_graph()
        template = tmp_path / "system.md"
        template.write_text("{{workspace_section}}", encoding="utf-8")
        graph.system_prompt_path = str(template)
        graph.system_prompt_override = None
        graph.sandbox = False
        graph.session_manager = MagicMock()
        graph.session_manager.workspace = MagicMock()
        graph.session_manager.workspace.root = "./workspace"
        prompt = graph._build_system_prompt()
        assert "沙盒模式：路径限制在工作区内" not in prompt
