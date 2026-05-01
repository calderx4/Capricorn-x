"""
Test Workflow - 自检工作流

验证 Tool 注册、文件读写、Shell 执行等核心链路是否正常。
"""

from typing import Any, Dict, List
from datetime import datetime

from core.base_workflow import BaseWorkflow


class TestWorkflow(BaseWorkflow):
    """自检工作流 - 验证核心能力是否可用"""

    @property
    def name(self) -> str:
        return "self_test"

    @property
    def description(self) -> str:
        return "自检工作流，验证核心工具（write_file、read_file、exec）是否正常工作。无需参数，直接执行。\n参数：无需参数（忽略任何传入参数）。"

    @property
    def required_tools(self) -> List[str]:
        return ["read_file", "write_file", "exec"]

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, tools: Any, **kwargs: Any) -> Any:
        results = []

        # 1. 测试 write_file
        test_content = f"capricorn self-test @ {datetime.now().isoformat()}"
        write_result = await tools.execute("write_file", {
            "path": "workspace/test_self_check.txt",
            "content": test_content,
        })
        results.append(("write_file", write_result))

        # 2. 测试 read_file
        read_result = await tools.execute("read_file", {
            "path": "workspace/test_self_check.txt",
        })
        results.append(("read_file", read_result))

        read_ok = test_content in str(read_result)

        # 3. 测试 exec
        exec_result = await tools.execute("exec", {
            "command": "echo 'capricorn exec ok'",
        })
        results.append(("exec", exec_result))

        exec_ok = "capricorn exec ok" in str(exec_result)

        # 汇总
        all_ok = read_ok and exec_ok
        summary = f"self_test: {'PASS' if all_ok else 'FAIL'}\n"
        for step, result in results:
            summary += f"  - {step}: {str(result)[:120]}\n"

        return summary
