"""
Quality Tools — 质量检查与质量信号工具

- QualityCheckTool: LLM 驱动的产出质量评估（4 维度收敛评估）
- QualitySignalTool: 记录和查询质量信号
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from loguru import logger

from core.base_tool import BaseTool
from core.utils import atomic_write

# ── LLM 评估 prompt ─────────────────────────────────────────

EVALUATION_PROMPT = """\
你是一个严格的质量验收员。按照以下 4 个固定维度评估产出的质量。

## 评估维度

1. **task_completion（任务完成度）**
   通过：产出完整回应了任务要求，所有要点都被覆盖
   失败：有明确的遗漏或未完成的要求

2. **accuracy（内容准确性）**
   通过：信息具体、有事实支撑，无明显错误或臆造
   失败：内容模糊笼统，或包含可识别的事实错误

3. **structure（结构清晰度）**
   通过：有标题/分段/列表等结构化元素，逻辑清晰可读
   失败：大段文字堆砌，缺少结构，逻辑混乱

4. **actionability（可操作性）**
   通过：有明确的结论、建议或下一步行动
   失败：没有结论或建议，读者不知道下一步做什么

## 评估规则

- 严格按维度逐项评估，禁止整体模糊判断
- 每个维度必须给出通过或失败，不存在"部分通过"
- 失败时必须说明具体原因（一两句话）
- 产出为空或极短（<50字）时，所有维度判定失败
- 不要给维度加注释或额外字段

## 输出格式

严格输出以下 JSON，不要输出其他内容：
{"pass":true或false,"details":{"task_completion":{"pass":true或false,"reason":"..."},"accuracy":{"pass":true或false,"reason":"..."},"structure":{"pass":true或false,"reason":"..."},"actionability":{"pass":true或false,"reason":"..."}},"fail_items":["失败的维度名",...],"fail_count":数字}

"pass" = 4个维度全部通过才为 true。"""


# ── QualityCheckTool ─────────────────────────────────────────


class QualityCheckTool(BaseTool):
    """LLM 驱动的产出质量评估"""

    auto_discover = False

    def __init__(self, llm_client):
        self._llm_client = llm_client

    @property
    def name(self) -> str:
        return "quality_check"

    @property
    def description(self) -> str:
        return (
            "评估产出质量（LLM 驱动的 4 维度检查）。"
            "维度：task_completion（任务完成度）、accuracy（准确性）、"
            "structure（结构清晰度）、actionability（可操作性）。"
            "传入产出文本和原始任务描述，返回 pass/fail 及各维度详情。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "report": {
                    "type": "string",
                    "description": "要检查的产出文本",
                },
                "task_prompt": {
                    "type": "string",
                    "description": "原始任务描述（可选，帮助判断任务完成度）",
                },
            },
            "required": ["report"],
        }

    async def execute(self, report: str, task_prompt: str = "", **kwargs) -> str:
        try:
            result = await self._evaluate(report, task_prompt)
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"quality_check failed: {e}")
            return json.dumps({
                "pass": False,
                "details": {"error": str(e)},
                "fail_items": ["error"],
                "fail_count": 1,
            }, ensure_ascii=False)

    async def _evaluate(self, report: str, task_prompt: str) -> dict:
        """调用 LLM 执行评估，解析结构化结果。"""
        # 短内容快速失败
        if not report or len(report.strip()) < 50:
            return {
                "pass": False,
                "details": {
                    "task_completion": {"pass": False, "reason": "产出为空或极短"},
                    "accuracy": {"pass": False, "reason": "产出为空或极短"},
                    "structure": {"pass": False, "reason": "产出为空或极短"},
                    "actionability": {"pass": False, "reason": "产出为空或极短"},
                },
                "fail_items": ["task_completion", "accuracy", "structure", "actionability"],
                "fail_count": 4,
            }

        # 构建用户消息
        user_msg = f"## 待评估的产出\n\n{report}"
        if task_prompt:
            user_msg = f"## 原始任务要求\n\n{task_prompt}\n\n{user_msg}"

        # 调用 LLM
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content=EVALUATION_PROMPT),
            HumanMessage(content=user_msg),
        ]
        response = await self._llm_client.ainvoke(messages)
        raw = response.content.strip()

        # 解析 JSON（兼容 markdown code block 包裹）
        parsed = self._parse_json(raw)
        if parsed:
            return self._normalize(parsed)

        # 解析失败 → fallback
        logger.warning(f"quality_check LLM response parse failed: {raw[:200]}")
        return {
            "pass": False,
            "details": {"parse_error": {"pass": False, "reason": f"LLM 返回格式异常: {raw[:100]}"}},
            "fail_items": ["parse_error"],
            "fail_count": 1,
        }

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        """从 LLM 回复中提取 JSON（兼容 ```json 包裹和直接 JSON）。"""
        # 尝试直接解析
        text = text.strip()
        if text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

        # 尝试提取 ```json ... ```
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试找最外层的 { }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        return None

    @staticmethod
    def _normalize(parsed: dict) -> dict:
        """确保输出格式与 quality_signal 兼容。"""
        details = parsed.get("details", {})
        fail_items = [
            k for k, v in details.items()
            if isinstance(v, dict) and not v.get("pass", False)
        ]
        return {
            "pass": parsed.get("pass", len(fail_items) == 0),
            "details": details,
            "fail_items": fail_items,
            "fail_count": len(fail_items),
        }


# ── QualitySignalTool ────────────────────────────────────────


class QualitySignalTool(BaseTool):
    """记录和查询质量信号"""

    def __init__(self, workspace_root: str = "./workspace", sandbox: bool = True):
        self._workspace_root = workspace_root
        self._sandbox = sandbox

    @classmethod
    def from_config(cls, config: dict) -> "QualitySignalTool":
        return cls(config["workspace_root"], config.get("sandbox", True))

    @property
    def name(self) -> str:
        return "quality_signal"

    @property
    def description(self) -> str:
        return (
            "记录或查询质量信号。action=record 时记录一条质量信号（任务完成时调用），"
            "action=list 时查询最近的信号，action=summary 时统计通过率。\n"
            "质量信号存储在工作区 team/quality_signals/ 目录。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["record", "list", "summary"],
                    "description": "record=记录信号，list=查询列表，summary=统计汇总",
                },
                "task_id": {
                    "type": "string",
                    "description": "任务 ID（record 时必填）",
                },
                "quality": {
                    "type": "object",
                    "description": "quality_check 的返回结果（record 时必填）",
                },
                "limit": {
                    "type": "integer",
                    "description": "查询数量限制（list/summary 时使用，默认 20）",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        task_id: str = None,
        quality: dict = None,
        limit: int = 20,
    ) -> str:
        try:
            signals_dir = Path(self._workspace_root) / "team" / "quality_signals"
            signals_dir.mkdir(parents=True, exist_ok=True)

            if action == "record":
                if not task_id or not quality:
                    return "Error: task_id and quality are required for record"
                signal = {
                    "task_id": task_id,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "status": "completed",
                    "quality": quality,
                }
                safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', task_id)
                signal_path = signals_dir / f"{safe_name}.json"
                atomic_write(signal_path, json.dumps(signal, ensure_ascii=False, indent=2))
                logger.info(f"Quality signal recorded: {task_id}")
                return f"Quality signal recorded for {task_id}"

            elif action == "list":
                files = sorted(signals_dir.glob("*.json"), reverse=True)
                signals = []
                for f in files[:limit]:
                    try:
                        signals.append(json.loads(f.read_text(encoding="utf-8")))
                    except (json.JSONDecodeError, Exception):
                        continue
                return json.dumps(signals, ensure_ascii=False, indent=2)

            elif action == "summary":
                files = sorted(signals_dir.glob("*.json"), reverse=True)
                signals = []
                for f in files[:limit]:
                    try:
                        signals.append(json.loads(f.read_text(encoding="utf-8")))
                    except (json.JSONDecodeError, Exception):
                        continue

                if not signals:
                    return json.dumps({"total": 0, "pass_rate": 0}, ensure_ascii=False)

                total = len(signals)
                passed = sum(1 for s in signals if s.get("quality", {}).get("pass", False))
                fail_counts: Dict[str, int] = {}
                for s in signals:
                    for item in s.get("quality", {}).get("fail_items", []):
                        fail_counts[item] = fail_counts.get(item, 0) + 1

                consecutive_fails = self._find_consecutive_fails(signals)

                summary = {
                    "total": total,
                    "passed": passed,
                    "failed": total - passed,
                    "pass_rate": round(passed / total * 100, 1) if total else 0,
                    "fail_distribution": fail_counts,
                    "consecutive_fails": consecutive_fails,
                }
                return json.dumps(summary, ensure_ascii=False, indent=2)

            return f"Error: unknown action '{action}'"

        except Exception as e:
            logger.error(f"quality_signal failed: {e}")
            return f"Error: {e}"

    @staticmethod
    def _find_consecutive_fails(signals: list) -> Dict[str, int]:
        """找出每个质量维度连续不通过的最大次数。"""
        if not signals:
            return {}

        all_dims = set()
        for s in signals:
            all_dims.update(s.get("quality", {}).get("fail_items", []))

        result = {}
        for dim in all_dims:
            max_streak = 0
            current = 0
            for s in reversed(signals):
                if dim in s.get("quality", {}).get("fail_items", []):
                    current += 1
                    max_streak = max(max_streak, current)
                else:
                    current = 0
            if max_streak >= 2:
                result[dim] = max_streak
        return result
