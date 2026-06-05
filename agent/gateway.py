"""
Gateway - HTTP 服务

职责：
- POST /chat：远程调用 agent（共享 session）
- POST /task：异步任务
- GET /task/{task_id}：查询任务状态
- GET /jobs：列出 cron 任务
- GET /health：健康检查
- GET /events：SSE 实时推送通知
- GET /notifications：查询通知列表
- POST /notifications/read：标记通知已读
"""

import asyncio
import base64
import hmac
import json
import os
import re
import time
import uuid
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Dict

from core.paths import GATEWAY_DIR

from aiohttp import web
from loguru import logger

from core.utils import atomic_write
from agent.events import QueueEventSink

MAX_PROMPT_LENGTH = 50000
MAX_CONCURRENT_TASKS = 20
MAX_TASK_TIMEOUT = 3600  # 单个异步任务最长 1 小时
MAX_SSE_CLIENTS = 50
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 单文件上传上限 50MB
TASK_ID_RE = re.compile(r'^[0-9a-f]{8}$')


async def _sse_write(resp: web.StreamResponse, data: bytes):
    """写入 SSE 数据，兼容 sync/async 版本的 StreamResponse.write()"""
    result = resp.write(data)
    if asyncio.iscoroutine(result):
        await result
    await resp.drain()
THREAD_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')


@web.middleware
async def security_headers_middleware(request, handler):
    """安全响应头"""
    resp = await handler(request)
    if isinstance(resp, web.StreamResponse):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
    return resp


class Gateway:
    """HTTP Gateway 服务"""

    def __init__(self, agent, config, notification_bus=None, webui: bool = False):
        self.agent = agent
        self.config = config
        self._notification_bus = notification_bus
        self.webui = webui
        self.host = config.gateway.host
        self.port = config.gateway.port
        self.start_time = time.time()
        self.tasks_dir = GATEWAY_DIR / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._thread_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
        self._api_key = os.environ.get("GATEWAY_API_KEY", "")
        self._default_task_timeout = config.gateway.task_timeout

    async def start(self):
        """启动 HTTP 服务"""
        middlewares = [security_headers_middleware]
        if self._api_key:
            middlewares.append(self._make_auth_middleware())

        app = web.Application(middlewares=middlewares, client_max_size=30 * 1024 * 1024)
        app.add_routes([
            web.post("/chat", self._handle_chat),
            web.post("/chat/stream", self._handle_chat_stream),
            web.post("/upload", self._handle_upload),
            web.post("/task", self._handle_task_create),
            web.get("/task/{task_id}", self._handle_task_status),
            web.get("/sessions", self._handle_sessions),
            web.get("/history/{thread_id}", self._handle_history),
            web.delete("/sessions/{thread_id}", self._handle_session_delete),
            web.get("/jobs", self._handle_jobs),
            web.get("/health", self._handle_health),
            web.get("/events", self._handle_sse),
            web.get("/notifications", self._handle_notifications),
            web.post("/notifications/read", self._handle_notifications_read),
        ])

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logger.info(f"Gateway started on {self.host}:{self.port}" + (" (with WebUI)" if self.webui else ""))
        if not self._api_key:
            logger.warning("⚠ GATEWAY_API_KEY not set — authentication disabled. All endpoints are open.")
        if self._api_key:
            logger.info("Gateway authentication enabled")

        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await runner.cleanup()

    @property
    def _cron_scheduler(self):
        return getattr(self.agent, "_cron_scheduler", None)

    @staticmethod
    def _validate_prompt(body: dict):
        """校验 prompt，返回 (prompt, error_response)"""
        prompt = body.get("prompt", "").strip()
        if not prompt:
            return None, web.json_response({"error": "prompt is required"}, status=400)
        if len(prompt) > MAX_PROMPT_LENGTH:
            return None, web.json_response({"error": f"prompt too long (max {MAX_PROMPT_LENGTH})"}, status=400)
        return prompt, None

    def _make_auth_middleware(self):
        """创建 API Key 认证中间件（设置 GATEWAY_API_KEY 环境变量启用）"""
        api_key = self._api_key

        @web.middleware
        async def auth_middleware(request, handler):
            if request.path == "/health":
                return await handler(request)
            auth = request.headers.get("Authorization", "")
            token = auth.removeprefix("Bearer ").strip()
            if not hmac.compare_digest(token, api_key):
                return web.json_response({"error": "Unauthorized"}, status=401)
            return await handler(request)

        return auth_middleware

    # ── Handlers ──────────────────────────────────────

    async def _handle_chat(self, request: web.Request) -> web.Response:
        """POST /chat"""
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        prompt, err = self._validate_prompt(body)
        if err:
            return err

        thread_id = body.get("thread_id", "default")
        if not THREAD_ID_RE.fullmatch(thread_id):
            return web.json_response({"error": "Invalid thread_id"}, status=400)

        images = body.get("images", [])
        attachments = body.get("attachments", [])

        # 类型校验
        if not isinstance(images, list) or not isinstance(attachments, list):
            return web.json_response({"error": "images and attachments must be arrays"}, status=400)
        for img in images:
            if not isinstance(img, dict) or "base64" not in img:
                return web.json_response({"error": "Each image must be a dict with 'base64' key"}, status=400)

        # 校验 images 数量和大小
        if len(images) > 10:
            return web.json_response({"error": "Too many images (max 10)"}, status=400)
        # 计算 base64 解码后的实际字节大小
        total_image_size = sum(len(img.get("base64", "")) * 3 // 4 for img in images)
        if total_image_size > 20 * 1024 * 1024:
            return web.json_response({"error": "Images too large (max 20MB total)"}, status=400)

        try:
            lock = self._get_thread_lock(thread_id)
            async with lock:
                response = await self.agent.chat(
                    prompt, thread_id=thread_id,
                    images=images, attachments=attachments,
                )
            return web.json_response({"response": response})
        except Exception as e:
            logger.error(f"/chat error: {e}")
            return web.json_response({"error": "Internal server error"}, status=500)

    async def _handle_chat_stream(self, request: web.Request) -> web.StreamResponse:
        """POST /chat/stream — SSE 流式返回 FC 循环执行步骤"""
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        prompt, err = self._validate_prompt(body)
        if err:
            return err

        thread_id = body.get("thread_id", "default")
        if not THREAD_ID_RE.fullmatch(thread_id):
            return web.json_response({"error": "Invalid thread_id"}, status=400)

        images = body.get("images", [])
        attachments = body.get("attachments", [])

        # 类型校验（与 /chat 一致）
        if not isinstance(images, list) or not isinstance(attachments, list):
            return web.json_response({"error": "images and attachments must be arrays"}, status=400)
        for img in images:
            if not isinstance(img, dict) or "base64" not in img:
                return web.json_response({"error": "Each image must be a dict with 'base64' key"}, status=400)
        if len(images) > 10:
            return web.json_response({"error": "Too many images (max 10)"}, status=400)
        total_image_size = sum(len(img.get("base64", "")) * 3 // 4 for img in images)
        if total_image_size > 20 * 1024 * 1024:
            return web.json_response({"error": "Images too large (max 20MB total)"}, status=400)

        # 初始化 SSE 响应
        resp = web.StreamResponse()
        resp.content_type = "text/event-stream; charset=utf-8"
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Connection"] = "keep-alive"
        await resp.prepare(request)

        sink = QueueEventSink(maxsize=200)
        agent_task = None

        async def _run_agent():
            try:
                lock = self._get_thread_lock(thread_id)
                async with lock:
                    await self.agent.chat(
                        prompt, thread_id=thread_id,
                        images=images, attachments=attachments,
                        on_event=sink.emit,
                    )
            except asyncio.CancelledError:
                logger.debug("SSE /chat/stream agent task cancelled")
                await sink.emit("error", {"error": "Request cancelled"})
            except Exception as e:
                logger.error(f"SSE /chat/stream agent error: {e}")
                await sink.emit("error", {"error": "Internal server error"})
            finally:
                sink.mark_done()

        try:
            # 启动 agent task
            agent_task = asyncio.create_task(_run_agent())

            # 流式读取事件
            while True:
                try:
                    event = await asyncio.wait_for(sink.queue.get(), timeout=30)
                    event_type = event.get("type", "unknown")
                    data = json.dumps(event.get("data", {}), ensure_ascii=False)
                    await _sse_write(resp, f"event: {event_type}\ndata: {data}\n\n".encode("utf-8"))
                    # 终止事件：收到 run_end 或 error 后，再排空队列然后退出
                    if event_type in ("run_end", "error"):
                        # 排空队列中剩余事件
                        while not sink.queue.empty():
                            remaining = sink.queue.get_nowait()
                            rt = remaining.get("type", "unknown")
                            rd = json.dumps(remaining.get("data", {}), ensure_ascii=False)
                            await _sse_write(resp, f"event: {rt}\ndata: {rd}\n\n".encode("utf-8"))
                        break
                except asyncio.TimeoutError:
                    if sink._done.is_set():
                        break
                    # keepalive
                    await _sse_write(resp, b":keepalive\n\n")

            # 发送完成信号
            await _sse_write(resp, b"event: done\ndata: {}\n\n")

        except (ConnectionResetError, ConnectionError):
            logger.debug("SSE /chat/stream client disconnected")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"SSE /chat/stream error: {e}")
            try:
                error_data = json.dumps({"error": "Internal server error"}, ensure_ascii=False)
                await _sse_write(resp, f"event: error\ndata: {error_data}\n\n".encode("utf-8"))
            except Exception:
                pass
        finally:
            if agent_task and not agent_task.done():
                agent_task.cancel()
            if agent_task:
                try:
                    await agent_task
                except (asyncio.CancelledError, Exception):
                    pass

        return resp

    async def _handle_upload(self, request: web.Request) -> web.Response:
        """POST /upload — 上传文件到 workspace"""
        upload_dir = Path(self.agent.config.workspace.root) / "main" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)

        results = []
        try:
            reader = await request.multipart()
        except Exception:
            return web.json_response({"error": "Invalid multipart request"}, status=400)

        while True:
            part = await reader.next()
            if part is None:
                break
            if not part.name or not part.filename:
                continue
            data = await part.read(decode=True)
            if len(data) > MAX_UPLOAD_SIZE:
                logger.warning(f"Upload skipped (too large): {part.filename} ({len(data)} bytes)")
                results.append({
                    "filename": part.filename,
                    "status": "skipped",
                    "error": f"File too large ({len(data)} bytes, max {MAX_UPLOAD_SIZE})",
                })
                continue
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            raw_name = Path(part.filename).name  # 去掉路径组件
            rand_suffix = uuid.uuid4().hex[:4]
            safe_name = f"{ts}_{rand_suffix}_{raw_name}"
            dest = upload_dir / safe_name
            # 安全校验：确保写入路径在 upload_dir 内
            if not dest.resolve().is_relative_to(upload_dir.resolve()):
                logger.warning(f"Upload rejected (path escape): {part.filename}")
                continue
            dest.write_bytes(data)

            content_type = part.headers.get("Content-Type", "") or ""
            is_image = content_type.startswith("image/")
            result = {
                "filename": part.filename,
                "saved_as": safe_name,
                "path": f"main/uploads/{safe_name}",
                "size": len(data),
                "is_image": is_image,
            }
            if is_image:
                result["base64"] = base64.b64encode(data).decode()
                result["content_type"] = content_type
            results.append(result)
            logger.info(f"Uploaded: {part.filename} -> {safe_name} ({len(data)} bytes)")

        return web.json_response({"files": results})

    async def _handle_task_create(self, request: web.Request) -> web.Response:
        """POST /task"""
        if len(self._running_tasks) >= MAX_CONCURRENT_TASKS:
            return web.json_response({"error": "Too many concurrent tasks"}, status=429)

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        prompt, err = self._validate_prompt(body)
        if err:
            return err

        task_id = uuid.uuid4().hex[:8]
        task_timeout = body.get("timeout", self._default_task_timeout)
        if not isinstance(task_timeout, int) or task_timeout <= 0:
            task_timeout = self._default_task_timeout
        task_timeout = min(task_timeout, MAX_TASK_TIMEOUT)
        task_data = {
            "task_id": task_id,
            "status": "pending",
            "prompt": prompt,
            "result": None,
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "finished_at": None,
            "error": None,
            "steps": [],
            "timeout": task_timeout,
        }
        self._save_task(task_data)

        asyncio_task = asyncio.create_task(self._run_task(task_id, prompt))
        self._running_tasks[task_id] = asyncio_task

        return web.json_response({"task_id": task_id, "status": "pending"})

    async def _handle_task_status(self, request: web.Request) -> web.Response:
        """GET /task/{task_id}"""
        task_id = request.match_info["task_id"]
        if not TASK_ID_RE.fullmatch(task_id):
            return web.json_response({"error": "Invalid task_id"}, status=400)
        task_data = self._load_task(task_id)
        if not task_data:
            return web.json_response({"error": "Task not found"}, status=404)
        return web.json_response(task_data)

    async def _handle_jobs(self, request: web.Request) -> web.Response:
        """GET /jobs — 列出 cron 任务"""
        scheduler = self._cron_scheduler
        if not scheduler:
            return web.json_response({"jobs": []})
        return web.json_response({"jobs": scheduler.list_jobs()})

    async def _handle_health(self, request: web.Request) -> web.Response:
        """GET /health"""
        scheduler = self._cron_scheduler
        cron_jobs = len(scheduler.list_jobs()) if scheduler else 0

        return web.json_response({
            "status": "ok",
            "cron_jobs": cron_jobs,
            "uptime": int(time.time() - self.start_time),
        })

    async def _handle_sse(self, request: web.Request) -> web.StreamResponse:
        """GET /events — SSE 实时推送通知"""
        if not self._notification_bus:
            return web.json_response({"error": "Notification service not available"}, status=503)

        if len(self._notification_bus._subscribers) >= MAX_SSE_CLIENTS:
            return web.json_response({"error": "Too many SSE connections"}, status=429)

        resp = web.StreamResponse()
        resp.content_type = "text/event-stream; charset=utf-8"
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Connection"] = "keep-alive"
        await resp.prepare(request)

        queue = self._notification_bus.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    data = json.dumps(event, ensure_ascii=False)
                    await _sse_write(resp, f"data: {data}\n\n".encode("utf-8"))
                except asyncio.TimeoutError:
                    await _sse_write(resp, b":keepalive\n\n")
        except (ConnectionResetError, ConnectionError, asyncio.CancelledError):
            pass
        except Exception as e:
            logger.debug(f"SSE stream error: {e}")
        finally:
            self._notification_bus.unsubscribe(queue)

        return resp

    async def _handle_notifications(self, request: web.Request) -> web.Response:
        """GET /notifications — 查询通知列表"""
        if not self._notification_bus:
            return web.json_response({"notifications": []})

        unread_only = request.query.get("unread", "false").lower() == "true"
        try:
            limit = int(request.query.get("limit", "20"))
            limit = max(1, min(limit, 100))
        except ValueError:
            limit = 20
        notifications = self._notification_bus.get_recent(limit=limit, unread_only=unread_only)
        return web.json_response({"notifications": notifications})

    async def _handle_notifications_read(self, request: web.Request) -> web.Response:
        """POST /notifications/read — 标记通知已读"""
        if not self._notification_bus:
            return web.json_response({"error": "Notification service not available"}, status=503)

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        ids = body.get("ids", [])
        if not isinstance(ids, list) or len(ids) > 100:
            return web.json_response({"error": "Invalid ids parameter"}, status=400)
        if not all(isinstance(i, str) for i in ids):
            return web.json_response({"error": "Invalid id format"}, status=400)
        await self._notification_bus.mark_read(ids)
        return web.json_response({"ok": True})

    # ── Sessions ─────────────────────────────────────

    async def _handle_sessions(self, request: web.Request) -> web.Response:
        """GET /sessions — 列出所有会话"""
        session_dir = self.agent.session_manager.session_dir
        sessions = []
        for f in sorted(session_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            tid = f.stem
            msg_count = 0
            first_content = ""
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            if data.get("content") or data.get("tool_calls"):
                                msg_count += 1
                            if not first_content and data.get("role") == "user" and data.get("content"):
                                first_content = data["content"][:80]
                        except json.JSONDecodeError:
                            continue
            except OSError:
                continue
            sessions.append({
                "thread_id": tid,
                "message_count": msg_count,
                "first_message": first_content,
                "updated_at": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "mtime": f.stat().st_mtime,
            })
        sessions.sort(key=lambda s: s["mtime"], reverse=True)
        # 不返回 mtime 给前端
        for s in sessions:
            s.pop("mtime", None)
        return web.json_response({"sessions": sessions})

    async def _handle_history(self, request: web.Request) -> web.Response:
        """GET /history/{thread_id} — 获取会话的 user/assistant 消息"""
        thread_id = request.match_info["thread_id"]
        if not THREAD_ID_RE.fullmatch(thread_id):
            return web.json_response({"error": "Invalid thread_id"}, status=400)
        session = self.agent.session_manager.load_session(thread_id)
        if not session:
            return web.json_response({"messages": []})
        display = []
        for msg in session.messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content and content.strip() and not msg.get("tool_calls"):
                display.append({"role": role, "content": content})
        return web.json_response({"messages": display})

    async def _handle_session_delete(self, request: web.Request) -> web.Response:
        """DELETE /sessions/{thread_id} — 删除会话"""
        thread_id = request.match_info["thread_id"]
        if not THREAD_ID_RE.fullmatch(thread_id):
            return web.json_response({"error": "Invalid thread_id"}, status=400)
        self.agent.session_manager.clear_session(thread_id)
        self._thread_locks.pop(thread_id, None)
        return web.json_response({"ok": True})

    # ── Thread Lock LRU ───────────────────────────────

    def _get_thread_lock(self, thread_id: str) -> asyncio.Lock:
        if thread_id in self._thread_locks:
            self._thread_locks.move_to_end(thread_id)
            return self._thread_locks[thread_id]
        lock = asyncio.Lock()
        self._thread_locks[thread_id] = lock
        # 超容量时淘汰最早的空闲锁，跳过正在持有的
        while len(self._thread_locks) > 1024:
            oldest_id, oldest_lock = next(iter(self._thread_locks.items()))
            if oldest_lock.locked():
                break  # 最早的锁正在使用，停止淘汰
            self._thread_locks.popitem(last=False)
        return lock

    # ── 异步任务执行 ──────────────────────────────────

    async def _run_task(self, task_id: str, prompt: str):
        task_data = self._load_task(task_id)
        if not task_data:
            logger.error(f"Task {task_id} data file missing")
            self._running_tasks.pop(task_id, None)
            return

        steps = task_data.setdefault("steps", [])
        timeout = task_data.get("timeout", self._default_task_timeout)
        task_data["status"] = "running"
        steps.append({"ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "event": "started"})
        self._save_task(task_data)

        try:
            result = await asyncio.wait_for(
                self.agent.chat(prompt, thread_id=f"task_{task_id}"),
                timeout=timeout,
            )
            task_data["status"] = "done"
            task_data["result"] = result
            steps.append({"ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "event": "completed"})
        except asyncio.TimeoutError:
            logger.warning(f"Task {task_id} timed out after {timeout}s")
            task_data["status"] = "timeout"
            task_data["error"] = f"Task timed out after {timeout}s"
            steps.append({"ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "event": "timeout", "detail": f"exceeded {timeout}s limit"})
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            task_data["status"] = "failed"
            task_data["error"] = "Internal error"
            steps.append({"ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "event": "failed", "detail": str(e)[:500]})
        finally:
            task_data["finished_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            self._save_task(task_data)
            self._running_tasks.pop(task_id, None)

    # ── 持久化 ────────────────────────────────────────

    def _task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.json"

    def _save_task(self, data: dict):
        path = self._task_path(data["task_id"])
        atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))

    def _load_task(self, task_id: str) -> dict | None:
        path = self._task_path(task_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

