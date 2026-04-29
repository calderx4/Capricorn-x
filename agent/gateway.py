"""
Gateway - HTTP 服务

职责：
- POST /chat：远程调用 agent（共享 session）
- POST /task：异步任务
- GET /task/{task_id}：查询任务状态
- GET /health：健康检查
- GET /events：SSE 实时推送通知
- GET /notifications：查询通知列表
- POST /notifications/read：标记通知已读
"""

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Dict

from aiohttp import web
from loguru import logger


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
        self.tasks_dir = Path("gateway/tasks")
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._thread_locks: Dict[str, asyncio.Lock] = {}

    async def start(self):
        """启动 HTTP 服务"""
        app = web.Application()
        app.add_routes([
            web.post("/chat", self._handle_chat),
            web.post("/task", self._handle_task_create),
            web.get("/task/{task_id}", self._handle_task_status),
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

        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await runner.cleanup()

    # ── Handlers ──────────────────────────────────────

    async def _handle_chat(self, request: web.Request) -> web.Response:
        """POST /chat"""
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        prompt = body.get("prompt", "").strip()
        if not prompt:
            return web.json_response({"error": "prompt is required"}, status=400)

        thread_id = body.get("thread_id", "default")

        try:
            if thread_id not in self._thread_locks:
                self._thread_locks[thread_id] = asyncio.Lock()
            async with self._thread_locks[thread_id]:
                response = await self.agent.chat(prompt, thread_id=thread_id)
            return web.json_response({"response": response})
        except Exception as e:
            logger.error(f"/chat error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_task_create(self, request: web.Request) -> web.Response:
        """POST /task"""
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        prompt = body.get("prompt", "").strip()
        if not prompt:
            return web.json_response({"error": "prompt is required"}, status=400)

        task_id = uuid.uuid4().hex[:8]
        task_data = {
            "task_id": task_id,
            "status": "pending",
            "prompt": prompt,
            "result": None,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "finished_at": None,
            "error": None,
        }
        self._save_task(task_data)

        asyncio_task = asyncio.create_task(self._run_task(task_id, prompt))
        self._running_tasks[task_id] = asyncio_task

        return web.json_response({"task_id": task_id, "status": "pending"})

    async def _handle_task_status(self, request: web.Request) -> web.Response:
        """GET /task/{task_id}"""
        task_id = request.match_info["task_id"]
        task_data = self._load_task(task_id)
        if not task_data:
            return web.json_response({"error": "Task not found"}, status=404)
        return web.json_response(task_data)

    async def _handle_health(self, request: web.Request) -> web.Response:
        """GET /health"""
        cron_jobs = 0
        if hasattr(self.agent, "_cron_scheduler") and self.agent._cron_scheduler:
            cron_jobs = len(self.agent._cron_scheduler.list_jobs())

        return web.json_response({
            "status": "ok",
            "cron_jobs": cron_jobs,
            "uptime": int(time.time() - self.start_time),
        })

    async def _handle_sse(self, request: web.Request) -> web.StreamResponse:
        """GET /events — SSE 实时推送通知"""
        if not self._notification_bus:
            return web.json_response({"error": "Notification service not available"}, status=503)

        resp = web.StreamResponse()
        resp.content_type = "text/event-stream"
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Connection"] = "keep-alive"
        resp.headers["Access-Control-Allow-Origin"] = "*"
        await resp.prepare(request)

        queue = self._notification_bus.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    data = json.dumps(event, ensure_ascii=False)
                    resp.write(f"data: {data}\n\n".encode("utf-8"))
                    await resp.drain()
                except asyncio.TimeoutError:
                    resp.write(b":keepalive\n\n")
                    await resp.drain()
        except (ConnectionResetError, ConnectionError, asyncio.CancelledError):
            pass
        except Exception:
            pass
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
        self._notification_bus.mark_read(ids)
        return web.json_response({"ok": True})

    # ── 异步任务执行 ──────────────────────────────────

    async def _run_task(self, task_id: str, prompt: str):
        task_data = self._load_task(task_id)
        task_data["status"] = "running"
        self._save_task(task_data)

        try:
            result = await self.agent.chat(prompt, thread_id=f"task_{task_id}")
            task_data["status"] = "done"
            task_data["result"] = result
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            task_data["status"] = "failed"
            task_data["error"] = str(e)
        finally:
            task_data["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            self._save_task(task_data)
            self._running_tasks.pop(task_id, None)

    # ── 持久化 ────────────────────────────────────────

    def _task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.json"

    def _save_task(self, data: dict):
        path = self._task_path(data["task_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_task(self, task_id: str) -> dict | None:
        path = self._task_path(task_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
