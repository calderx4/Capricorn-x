"""
Bia Tools — 行为纠偏规则工具

让 LLM 主动更新 bia.md（行为纠偏规则），用于自进化中环。
支持：时间戳、相似规则去重、Token 上限、超限 LLM 压缩。
"""

import re
from datetime import datetime
from typing import Any, Dict, List

from loguru import logger
from pathlib import Path

from core.base_tool import BaseTool
from core.utils import atomic_write

BIA_MAX_TOKENS = 1500
_RULE_RE = re.compile(r'^- \[(\d{4}-\d{2}-\d{2})\] (.+)', re.MULTILINE)


class BiaUpdateTool(BaseTool):
    auto_discover = False

    def __init__(self, bia_path: str, llm_client=None):
        self._bia_path = Path(bia_path)
        self._llm_client = llm_client

    @property
    def name(self) -> str:
        return "bia_update"

    @property
    def description(self) -> str:
        return (
            "更新行为纠偏规则（bia.md）。发现反复犯错的模式时，添加持久的行为修正规则。"
            "相似规则会自动去重（新的覆盖旧的）。"
            "mode=append 追加规则，mode=replace 替换全部。默认 append。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要添加的行为修正规则",
                },
                "mode": {
                    "type": "string",
                    "enum": ["append", "replace"],
                    "description": "append=追加，replace=替换全部。默认 append。",
                    "default": "append",
                },
            },
            "required": ["content"],
        }

    async def execute(self, content: str, mode: str = "append") -> str:
        try:
            self._bia_path.parent.mkdir(parents=True, exist_ok=True)

            if mode == "replace":
                stamped = _stamp_rules(content)
                atomic_write(self._bia_path, stamped)
                return f"已替换行为纠偏规则（{_token_count(stamped)}/{BIA_MAX_TOKENS} token）"

            today = datetime.now().strftime("%Y-%m-%d")
            new_entry = f"- [{today}] {content.strip()}"

            existing = self._read()
            header = _extract_header(existing)
            rules = _parse_rules(existing)

            idx = _find_similar(rules, content)
            if idx is not None:
                rules[idx] = new_entry
                logger.info(f"BIA dedup: replaced rule [{idx}]")
            else:
                rules.append(new_entry)

            body = header + "\n".join(rules) + "\n"

            if _token_count(body) > BIA_MAX_TOKENS:
                body = await self._enforce_limit(self._llm_client, header, rules)

            atomic_write(self._bia_path, body)
            return f"已更新行为纠偏规则（{_token_count(body)}/{BIA_MAX_TOKENS} token）"

        except Exception as e:
            logger.error(f"bia_update failed: {e}")
            return f"Error: {e}"

    def _read(self) -> str:
        return self._bia_path.read_text(encoding="utf-8") if self._bia_path.exists() else ""


# ── helpers ──────────────────────────────────────────────────


def _extract_header(content: str) -> str:
    lines = content.split("\n")
    hdr = []
    for line in lines:
        if _RULE_RE.match(line):
            break
        hdr.append(line)
    text = "\n".join(hdr).rstrip("\n")
    return text + "\n\n" if text else ""


def _parse_rules(content: str) -> List[str]:
    rules, current = [], None
    for line in content.split("\n"):
        if _RULE_RE.match(line):
            if current:
                rules.append(current)
            current = line
        elif current and line.startswith("  "):
            current += "\n" + line
    if current:
        rules.append(current)
    return rules


def _find_similar(rules: List[str], new_content: str) -> int | None:
    new_norm = _normalize(new_content)
    if not new_norm:
        return None
    for i, rule in enumerate(rules):
        m = _RULE_RE.match(rule.split("\n")[0])
        if not m:
            continue
        rule_norm = _normalize(m.group(2))
        if not rule_norm:
            continue
        if new_norm in rule_norm or rule_norm in new_norm:
            return i
        new_w = set(new_norm.split())
        rule_w = set(rule_norm.split())
        if new_w and rule_w:
            overlap = len(new_w & rule_w) / min(len(new_w), len(rule_w))
            if overlap > 0.7:
                return i
    return None


def _normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', '', text.lower())).strip()


def _stamp_rules(content: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    out = []
    for line in content.strip().split("\n"):
        s = line.strip()
        if not s:
            continue
        if _RULE_RE.match(s) or s.startswith(">") or s.startswith("#"):
            out.append(s)
        else:
            out.append(f"- [{today}] {s}")
    return "\n".join(out) + "\n"


def _token_count(text: str) -> int:
    from core.token_counter import TokenCounter
    return TokenCounter.estimate_tokens(text)


async def _enforce_limit(llm_client, header: str, rules: List[str]) -> str:
    if llm_client:
        body = header + "\n".join(rules) + "\n"
        compressed = await _compress(llm_client, body)
        if compressed and _token_count(compressed) <= BIA_MAX_TOKENS:
            return compressed
        if compressed:
            rules = _parse_rules(compressed)
    while rules and _token_count(header + "\n".join(rules)) > BIA_MAX_TOKENS:
        rules.pop(0)
        logger.info("BIA pruned oldest rule")
    return header + "\n".join(rules) + "\n"


async def _compress(llm_client, content: str) -> str | None:
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        resp = await llm_client.ainvoke([
            SystemMessage(content=(
                f"合并以下行为规则中的相似项，移除重复。"
                f"总 token 不超过 {BIA_MAX_TOKENS}。"
                f"保持格式 `- [YYYY-MM-DD] 规则内容`，只输出规则。"
            )),
            HumanMessage(content=content),
        ])
        return resp.content.strip() + "\n"
    except Exception as e:
        logger.error(f"BIA compress failed: {e}")
        return None
