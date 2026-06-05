"""
Agent - 原生 Function Calling 循环

职责：
- 构建 System Prompt
- FC 循环：LLM 调用 → 工具执行 → 终止判断
- 并发工具执行
- 迭代上限和熔断保护
"""

import asyncio
import time
from datetime import datetime
from typing import Dict

TOOL_TIMEOUT = 300  # 单个工具执行全局超时 5 分钟

from langchain_core.messages import (
    HumanMessage, AIMessage, SystemMessage, ToolMessage, BaseMessage,
)
from loguru import logger

from pathlib import Path

from core.utils import strip_thinking_tags
from core import trace
from core.prompt_utils import (
    build_tools_section, build_skills_section, build_memory_section,
    build_bia_section, build_prompt,
)
from agent.events import EventCallback, safe_emit, current_on_event


class CapricornGraph:
    """Capricorn Agent — 原生 Function Calling 循环"""

    def __init__(
        self,
        capability_registry,
        skill_manager,
        session_manager,
        long_term_memory,
        llm_client=None,
        sandbox: bool = True,
        max_iterations: int = 50,
        exclude_tools: list = None,
        system_prompt_override: str = None,
        system_prompt_path: str = None,
        bia_path: str = None,
    ):
        self.capability_registry = capability_registry
        self.skill_manager = skill_manager
        self.session_manager = session_manager
        self.long_term_memory = long_term_memory
        self.llm_client = llm_client
        self.sandbox = sandbox
        self.max_iterations = max_iterations
        self._exclude_tools = set(exclude_tools or [])
        self.system_prompt_override = system_prompt_override
        self.system_prompt_path = system_prompt_path
        self.bia_path = bia_path

        # 预绑定工具（排除指定工具）
        if self.llm_client:
            tools = self.capability_registry.get_langchain_tools()
            if self._exclude_tools:
                tools = [t for t in tools if t.name not in self._exclude_tools]
            self._llm_with_tools = self.llm_client.bind_tools(tools)
        else:
            self._llm_with_tools = None
            logger.warning("LLM client not initialized")

    async def _emit(self, on_event: EventCallback, event_type: str, data: dict):
        """安全发出事件（委托给 safe_emit）"""
        await safe_emit(on_event, event_type, data)

    async def run(self, user_input: str, thread_id: str = "default",
                  notifications: str = "", images: list = None,
                  attachments: list = None,
                  on_event: EventCallback = None) -> str:
        """运行 FC 循环"""
        logger.info(f"Running agent with thread_id: {thread_id}")

        session = self.session_manager.get_session(thread_id)

        system_prompt = self._build_system_prompt()
        if notifications:
            system_prompt += f"\n\n{notifications}"
        history_messages = session.get_history()

        # 构建 prompt 文本（附加文件信息）
        prompt_text = user_input
        if attachments:
            file_list = "\n".join(f"- {a}" for a in attachments)
            prompt_text += f"\n\n[用户上传了以下文件]\n{file_list}"
            if images:
                prompt_text += (
                    "\n图片已直接传入你的视觉，直接看图回答。"
                    "\n仅当模型自身没有多模态能力时，才调用图像识别工具兜底。"
                    "\n如果都不行，告知用户当前没有识别图片的能力。"
                    "\n其他非图片文件请用 read_file 等工具读取。"
                )
            else:
                prompt_text += "\n请根据需要使用 read_file 等工具读取文件内容。"

        # 构造 HumanMessage（支持多模态）
        if images:
            content = [{"type": "text", "text": prompt_text}]
            for img in images:
                # 支持 dict {"base64": ..., "content_type": ...} 或纯 base64 字符串
                if isinstance(img, dict):
                    img_b64 = img["base64"]
                    mime = img.get("content_type", "image/png")
                else:
                    img_b64 = img
                    mime = "image/png"
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{img_b64}"}
                })
            human_msg = HumanMessage(content=content)
        else:
            human_msg = HumanMessage(content=prompt_text)

        messages = [
            SystemMessage(content=system_prompt),
            *[self._dict_to_message(msg) for msg in history_messages],
            human_msg,
        ]

        session.add_message("user", prompt_text,
                            images_count=len(images or []),
                            attachments=attachments or [])

        # 记录本轮输入的 messages 结构
        logger.debug(f"[Trace] 输入 messages 结构: {self._summarize_messages(messages)}")
        logger.debug(f"[Trace] 用户输入: {user_input}")

        if not self._llm_with_tools:
            return "LLM 客户端未初始化"

        await self._emit(on_event, "run_start", {
            "thread_id": thread_id,
            "max_iterations": self.max_iterations,
        })

        tools_used = []
        i = -1

        try:
            for i in range(self.max_iterations):
                round_start_ts = time.monotonic()
                logger.info(f"Thinking... (iteration {i + 1})")
                trace.round_start(i + 1, len(messages))

                await self._emit(on_event, "round_start", {"round": i + 1})
                await self._emit(on_event, "thinking", {"round": i + 1})

                try:
                    for retry in range(3):
                        try:
                            response = await self._llm_with_tools.ainvoke(messages)
                            break
                        except Exception as invoke_err:
                            err_str = str(invoke_err)
                            if "429" in err_str or "rate" in err_str.lower():
                                wait = 3 * (2 ** retry)  # 3s, 6s, 12s
                                logger.warning(f"Rate limited, retrying in {wait}s... (attempt {retry + 1}/3)")
                                await asyncio.sleep(wait)
                            else:
                                raise
                    else:
                        raise RuntimeError("Max retries exceeded for rate limit")
                except RuntimeError:
                    raise
                messages.append(response)

                response_content = self._extract_content(response)
                logger.debug(f"[Trace] LLM 响应 (iter {i + 1}): {response_content[:500]}")

                if not (hasattr(response, "tool_calls") and response.tool_calls):
                    round_latency = int((time.monotonic() - round_start_ts) * 1000)
                    trace.round_end(i + 1, 0, round_latency)
                    logger.debug(f"[Trace] 无工具调用，FC 循环结束 (iter {i + 1})")
                    break

                tool_names = [tc["name"] for tc in response.tool_calls]
                tool_args = [{"name": tc["name"], "args": tc["args"]} for tc in response.tool_calls]
                logger.info(f"Tool calls: {tool_names}")
                logger.debug(f"[Trace] 工具调用详情: {tool_args}")

                # 保存 AI 工具调用到 session（含 reasoning_content）
                ai_tool_calls = []
                for tc in response.tool_calls:
                    ai_tool_calls.append({
                        "id": tc["id"],
                        "name": tc["name"],
                        "args": tc["args"],
                    })
                rc = response.additional_kwargs.get("reasoning_content")
                session.add_message("assistant", response_content or "",
                                    tool_calls=ai_tool_calls,
                                    reasoning_content=rc)

                # 并发执行工具（带 trace + 事件）
                tool_messages = await self._execute_tools(
                    response.tool_calls, round=i + 1, on_event=on_event,
                )
                messages.extend(tool_messages)
                tools_used.extend(tool_names)

                # 保存工具返回到 session
                for tm in tool_messages:
                    session.add_message("tool", tm.content, tool_call_id=tm.tool_call_id)

                # 每轮写盘（防崩溃丢消息）
                self.session_manager.save_session(session)

                round_latency = int((time.monotonic() - round_start_ts) * 1000)
                trace.round_end(i + 1, len(tool_names), round_latency)
                await self._emit(on_event, "round_end", {
                    "round": i + 1,
                    "tool_count": len(tool_names),
                    "latency_ms": round_latency,
                })

                for tm in tool_messages:
                    logger.debug(f"[Trace] 工具返回 (id={tm.tool_call_id}): {tm.content}")

            final_response = self._extract_content(messages[-1])

            # 迭代上限检查
            if i >= self.max_iterations - 1 and (hasattr(messages[-1], "tool_calls") and messages[-1].tool_calls):
                logger.warning(f"FC loop hit max_iterations={self.max_iterations}")
                final_response += (
                    f"\n\n⚠ 已达到最大迭代次数 ({self.max_iterations})，"
                    f"任务可能未完成。"
                )

            logger.debug(f"[Trace] 最终回复: {final_response[:500]}")
            logger.debug(f"[Trace] 总迭代: {i + 1}, 使用工具: {tools_used}")
            final_rc = messages[-1].additional_kwargs.get("reasoning_content") if hasattr(messages[-1], "additional_kwargs") else None
            session.add_message("assistant", final_response, tools_used=tools_used,
                                reasoning_content=final_rc)
            self.session_manager.save_session(session)

            await self._emit(on_event, "response", {"content": final_response})
            await self._emit(on_event, "run_end", {
                "thread_id": thread_id,
                "total_rounds": i + 1,
                "tools_used": tools_used,
            })

            return final_response

        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            error_msg = "执行失败，请稍后重试"
            session.add_message("assistant", error_msg)
            self.session_manager.save_session(session)
            # 即使异常也发出终止事件，确保 SSE 客户端不挂起
            await self._emit(on_event, "response", {"content": error_msg})
            await self._emit(on_event, "run_end", {
                "thread_id": thread_id,
                "total_rounds": max(i + 1, 0),
                "tools_used": tools_used,
            })
            return error_msg

    def _summarize_tool_args(self, args: dict, max_len: int = 200) -> str:
        """生成工具参数摘要（截断 + 单行化）"""
        if not args:
            return ""
        parts = []
        for k, v in args.items():
            s = str(v).replace('\n', '\\n').replace('\r', '')
            if len(s) > 60:
                s = s[:57] + "..."
            parts.append(f"{k}='{s}'" if isinstance(v, str) else f"{k}={s}")
        result = ", ".join(parts)
        return result[:max_len] + "..." if len(result) > max_len else result

    async def _execute_tools(self, tool_calls, round: int = 0,
                             on_event: EventCallback = None) -> list:
        async def _run_one(call):
            name, args = call["name"], call["args"]
            call_id = call.get("id", "")

            await self._emit(on_event, "tool_call_start", {
                "round": round,
                "tool_name": name,
                "tool_args_preview": self._summarize_tool_args(args),
                "call_id": call_id,
            })

            start = time.monotonic()
            try:
                current_on_event.set(on_event)
                result = await asyncio.wait_for(
                    self.capability_registry.tools.execute(name, args),
                    timeout=TOOL_TIMEOUT,
                )
                content = str(result)
                latency = int((time.monotonic() - start) * 1000)
                status = "ok"
                logger.info(f"  {name} -> {content[:100]}")
                trace.tool_call(round, name, args, latency, "ok")
            except asyncio.TimeoutError:
                content = f"Error: Tool '{name}' execution timed out after {TOOL_TIMEOUT} seconds"
                latency = int((time.monotonic() - start) * 1000)
                status = "timeout"
                logger.error(f"Tool {name} timed out")
                trace.tool_call(round, name, args, latency, "timeout")
            except Exception as e:
                content = f"Error: {e}"
                latency = int((time.monotonic() - start) * 1000)
                status = "error"
                logger.error(f"Tool {name} failed: {e}")
                trace.tool_call(round, name, args, latency, "error")

            await self._emit(on_event, "tool_call_end", {
                "round": round,
                "tool_name": name,
                "latency_ms": latency,
                "status": status,
                "result_preview": content[:200],
            })

            return ToolMessage(content=content, tool_call_id=call["id"])

        return await asyncio.gather(*[_run_one(tc) for tc in tool_calls])

    def _summarize_messages(self, messages: list) -> str:
        """生成 messages 列表的结构摘要"""
        summary = []
        for idx, msg in enumerate(messages):
            role = type(msg).__name__
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                preview = f"[multimodal: {len(content)} blocks]"
            elif content:
                preview = content[:80].replace("\n", " ")
            else:
                preview = "(empty)"
            summary.append(f"  [{idx}] {role}: {preview}...")
        return f"共 {len(messages)} 条:\n" + "\n".join(summary)

    def _dict_to_message(self, msg: Dict) -> BaseMessage:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            return HumanMessage(content=content)
        elif role == "system":
            return SystemMessage(content=content)
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            if not tool_call_id:
                logger.warning(f"Dropping tool message with empty tool_call_id: {content[:80]}")
                return HumanMessage(content=f"[orphan tool result] {content[:200]}")
            return ToolMessage(
                content=content,
                tool_call_id=tool_call_id,
            )
        else:
            ai_msg = AIMessage(content=content)
            if msg.get("tool_calls"):
                ai_msg.tool_calls = msg["tool_calls"]
            if msg.get("reasoning_content") is not None:
                ai_msg.additional_kwargs["reasoning_content"] = msg["reasoning_content"]
            return ai_msg

    def _extract_content(self, message) -> str:
        content = getattr(message, "content", "")

        if isinstance(content, list):
            text_parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            content = "\n".join(text_parts) if text_parts else str(content)

        content = strip_thinking_tags(content)
        return content

    def _build_system_prompt(self) -> str:
        if self.system_prompt_override:
            return self.system_prompt_override

        workspace_root = getattr(
            getattr(self.session_manager, "workspace", None), "root", "./workspace"
        )
        sandbox_note = "（沙盒模式：路径限制在工作区内）" if self.sandbox else "（可访问工作区外的路径）"
        workspace_section = (
            f"# Workspace\n\n"
            f"工作区根目录：`{workspace_root}` {sandbox_note}\n"
            f"所有工具（read_file、write_file、list_files、exec）都以工作区根目录为基准。"
            f" 路径直接写相对路径，不要加 `{workspace_root}/` 前缀。\n\n"
            f"```\n"
            f"workspace/\n"
            f"├── main/<任务名>/    任务产出，每个任务一个文件夹\n"
            f"├── team/            SubAgent 协作空间\n"
            f"│   ├── reports/     executor 产出\n"
            f"│   ├── audit/       verifier 审核\n"
            f"│   ├── summary/     质量汇总\n"
            f"│   ├── quality_signals/  质量信号\n"
            f"│   └── changelog/        变更日志\n"
            f"├── memory/          系统记忆（自动管理）\n"
            f"└── sessions/        会话记录（自动管理）\n"
            f"```\n\n"
            f"规则：\n"
            f"- 任务产出 → `main/<任务名>/`，每个任务一个独立文件夹\n"
            f"- 项目配置（requirements.md 等）→ `main/<当前项目>/` 下\n"
            f"- SubAgent 产出 → `team/reports/` 或 `team/summary/`\n"
            f"- `memory/` 和 `sessions/` 由系统自动管理，不要手动写入\n"
            f"- `exec` 默认在工作区根目录下运行\n"
            f"- 操作前先用 `list_files` 查看当前结构\n"
            f"- 禁止嵌套 `main/main/`，`main/` 只出现一次"
        )

        agent_md_section = ""
        agent_md_path = Path("agent.md")
        if agent_md_path.exists():
            content = agent_md_path.read_text(encoding="utf-8").strip()
            if content:
                agent_md_section = f"# Project Context\n\n{content}"

        return build_prompt(
            self.system_prompt_path,
            workspace_section=workspace_section,
            bia_section=build_bia_section(self.bia_path),
            memory_section=build_memory_section(self.long_term_memory),
            agent_md_section=agent_md_section,
            tools_section=build_tools_section(self.capability_registry),
            skills_section=build_skills_section(self.skill_manager),
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
