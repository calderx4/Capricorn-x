"""
FeishuChannel - 飞书/Lark 消息通道

使用 lark-oapi SDK 的 WebSocket 长连接模式：
- 不需要公网 IP 或 webhook
- 不需要部署到云服务器
- 本地开发即可使用

要求：
  pip install lark-oapi

飞书开放平台配置：
  1. 创建企业自建应用
  2. 开通「机器人」能力
  3. 订阅事件：im.message.receive_v1
  4. 获取 App ID + App Secret
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import threading
from typing import Any

from loguru import logger

from agent.channels import BaseChannel

# ── 飞书 SDK 可选导入 ──────────────────────────────────

try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateMessageReactionRequest,
        CreateMessageReactionRequestBody,
        CreateMessageRequest,
        CreateMessageRequestBody,
        Emoji,
        GetMessageResourceRequest,
        P2ImMessageReceiveV1,
    )

    FEISHU_AVAILABLE = True
except ImportError:
    FEISHU_AVAILABLE = False
    lark = None
    Emoji = None


# ── 常量 ──────────────────────────────────────────────

MSG_TYPE_MAP = {
    "image": "[图片]",
    "audio": "[语音]",
    "file": "[文件]",
    "sticker": "[表情]",
    "video": "[视频]",
}

# 飞书 image_key 后缀 → MIME 类型
_IMAGE_MIME_MAP = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
}

# 文件头 magic bytes → MIME 类型（优先于 image_key 猜测）
_MAGIC_MAP = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG": "image/png",
    b"GIF8": "image/gif",
    b"RIFF": "image/webp",
    b"BM": "image/bmp",
}

_IMAGE_DOWNLOAD_TIMEOUT = 30  # 图片下载超时（秒）
_MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 图片大小上限 10MB

FEISHU_MAX_CONTENT_LEN = 28000  # 飞书 Interactive Card 内容长度上限（留余量）

# 飞书 @机器人 的文本中会包含 @_user_1 这样的占位符
_AT_BOT_RE = re.compile(r"@_user_\d+\s*")


# ── 富文本 / 帖子解析 ──────────────────────────────────

def _extract_post_text(content_json: dict) -> str:
    """从飞书 post（富文本）消息中提取纯文本。"""
    if not isinstance(content_json, dict):
        return ""

    def _from_lang(lang_content: dict) -> str | None:
        if not isinstance(lang_content, dict):
            return None
        title = lang_content.get("title", "")
        content_blocks = lang_content.get("content", [])
        if not isinstance(content_blocks, list):
            return None
        parts = []
        if title:
            parts.append(title)
        for block in content_blocks:
            if not isinstance(block, list):
                continue
            for element in block:
                if isinstance(element, dict):
                    tag = element.get("tag")
                    if tag == "text":
                        parts.append(element.get("text", ""))
                    elif tag == "a":
                        parts.append(element.get("text", ""))
                    elif tag == "at":
                        parts.append(f"@{element.get('user_name', 'user')}")
        return " ".join(parts).strip() if parts else None

    # 先尝试直接格式
    if "content" in content_json:
        result = _from_lang(content_json)
        if result:
            return result
    # 再尝试多语言格式
    for lang_key in ("zh_cn", "en_us", "ja_jp"):
        result = _from_lang(content_json.get(lang_key))
        if result:
            return result
    return ""


class FeishuChannel(BaseChannel):
    """飞书/Lark 通道（WebSocket 长连接，无需公网 IP）。"""

    name = "feishu"
    display_name = "飞书"

    def __init__(self, config: Any, agent):
        super().__init__(config, agent)
        self.config = config
        self._client: Any = None          # lark.Client（发消息用）
        self._ws_client: Any = None       # lark.ws.Client（收消息用，子线程创建）
        self._ws_thread: threading.Thread | None = None
        self._ws_loop: asyncio.AbstractEventLoop | None = None  # 子线程的 event loop
        self._stop_event = threading.Event()  # 跨线程停止信号（替代 _running 布尔值）

    # ── 生命周期 ──────────────────────────────────────

    async def start(self) -> None:
        """启动飞书 WebSocket 长连接。"""
        if not FEISHU_AVAILABLE:
            logger.error("[Feishu] SDK not installed. Run: pip install lark-oapi")
            return

        app_id = getattr(self.config, "app_id", "")
        app_secret = getattr(self.config, "app_secret", "")
        if not app_id or not app_secret:
            logger.error("[Feishu] app_id and app_secret not configured")
            return

        self._stop_event.clear()
        self._loop = asyncio.get_running_loop()

        # 创建 Lark Client（用于发送消息）— 不涉及 event loop，主线程创建即可
        self._client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.WARNING)  # 静默 SDK INFO 日志（默认会打印含 access_key/ticket 的 wss URL）
            .build()
        )

        # 准备配置参数（传给子线程）
        encrypt_key = getattr(self.config, "encrypt_key", "") or ""
        verification_token = getattr(self.config, "verification_token", "") or ""

        # 说明：这两个字段在 HTTP webhook 模式下用于验签/解密，但本项目走
        # WebSocket 长连接——SDK 在 WSS 模式下调 _do_without_validation()
        # （lark_oapi/event/dispatcher_handler.py），不执行 do() 里的
        # _decrypt / token 校验 / _verify_sign，所以这两个字段配了也不会被读取。
        # WSS 连接本身已由飞书服务端用 app_secret 握手鉴权（事件无法伪造），
        # 但“是哪个用户发的”SDK 不校验——这一层完全靠 allow_from 兜底。
        # 因此真实风险只在 allow_from=["*"]，启动摘要里会单独告警，不再误导
        # 用户去补两个永远不生效的验签字段。
        allow_from = getattr(self.config, "allow_from", [])
        allow_all = allow_from == ["*"]

        # ── 子线程：创建 WebSocket 客户端并运行 ──
        # 根因修复：lark-oapi SDK 的 ws/client.py 在模块级用
        #   loop = asyncio.get_event_loop()
        # 捕获了 import 时的 event loop（即主线程的 loop）。
        # 然后 start() 调用 loop.run_until_complete() 会报
        # "This event loop is already running"。
        # 解决：在子线程创建独立 loop，并覆盖 SDK 的模块级 loop 变量。
        def _run_ws():
            ws_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(ws_loop)
            self._ws_loop = ws_loop

            # 覆盖 SDK 模块级 loop，让 start() 用我们的 loop
            import lark_oapi.ws.client as _ws_mod
            _ws_mod.loop = ws_loop

            try:
                # 在子线程中创建事件处理器和 WebSocket 客户端
                event_handler = (
                    lark.EventDispatcherHandler.builder(encrypt_key, verification_token)
                    .register_p2_im_message_receive_v1(self._on_message_sync)
                    .register_p2_im_message_reaction_created_v1(self._on_reaction_sync)
                    .register_p2_im_message_message_read_v1(self._on_message_read_sync)
                    .build()
                )
                ws_client = lark.ws.Client(
                    app_id,
                    app_secret,
                    event_handler=event_handler,
                    log_level=lark.LogLevel.WARNING,  # 同上，避免 wss 连接 URL（含凭证）落到终端
                )
                self._ws_client = ws_client

                while not self._stop_event.is_set():
                    try:
                        ws_client.start()
                    except Exception as e:
                        logger.warning(f"[Feishu] WebSocket error: {e}")
                        if not self._stop_event.is_set():
                            import time
                            time.sleep(5)
            finally:
                ws_loop.close()
                logger.debug("[Feishu] WS thread exited")

        self._ws_thread = threading.Thread(target=_run_ws, daemon=True)
        self._ws_thread.start()

        # ── 启动摘要 ──
        # 等宽终端下 CJK 字符占 2 列，按显示宽度对齐「—」
        app_id_short = f"{app_id[:6]}...{app_id[-4:]}" if len(app_id) > 12 else app_id
        if allow_all:
            allow_desc = '全部放开 ["*"]'
        elif allow_from:
            allow_desc = f"{len(allow_from)} 个 open_id 白名单"
        else:
            allow_desc = "空（将拒绝所有消息）"

        logger.info("[Feishu] ✅ 已启动 (WebSocket 长连接，无需公网 IP)")
        logger.info(f"[Feishu]   · App ID   — {app_id_short}")
        logger.info("[Feishu]   · 事件订阅 — im.message.receive_v1 (+reaction/read)")
        logger.info(f"[Feishu]   · 白名单   — {allow_desc}")
        logger.info("[Feishu]   · 图片支持 — 已启用 (自动下载/解析)")

        if allow_all:
            logger.warning(
                "[Feishu] ⚠ 白名单全开：WebSocket 模式下 SDK 不校验发送者身份，"
                "任何能加到本 bot 的飞书用户都可驱动 agent 执行工具。"
                "本地自测可接受；公开/多用户部署前请改为显式 open_id 白名单。"
            )

        # 保持运行直到 stop()
        while not self._stop_event.is_set():
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """停止飞书连接。"""
        self._stop_event.set()

        # lark-oapi 的 ws.Client 没有 stop() 方法，
        # 但 start() 内部阻塞在 loop.run_until_complete(_select())（无限 sleep）。
        # 停止子线程的 event loop 会打破那个阻塞，让 start() 抛异常退出。
        if self._ws_loop and self._ws_loop.is_running():
            self._ws_loop.call_soon_threadsafe(self._ws_loop.stop)

        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=5)

        self._ws_client = None
        logger.info("[Feishu] 已停止")

    # ── 发送消息 ──────────────────────────────────────

    async def send(self, chat_id: str, content: str, **kwargs) -> None:
        """发送消息到飞书。

        自动判断 chat_id 类型：
        - oc_ 开头：群聊（receive_id_type = chat_id）
        - ou_ / 其他：私聊（receive_id_type = open_id）

        内容以 Interactive Card（交互卡片）发送，支持 Markdown。
        超长内容自动截断（飞书卡片有长度限制）。
        """
        if not self._client:
            logger.warning("[Feishu] Client not initialized")
            return

        try:
            receive_id_type = "chat_id" if chat_id.startswith("oc_") else "open_id"

            # 截断超长内容
            if len(content) > FEISHU_MAX_CONTENT_LEN:
                content = content[:FEISHU_MAX_CONTENT_LEN] + "\n\n... (内容过长，已截断)"

            # 构建飞书 Interactive Card
            card = {
                "config": {"wide_screen_mode": True},
                "elements": [{"tag": "markdown", "content": content}],
            }

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self._send_message_sync,
                receive_id_type,
                chat_id,
                "interactive",
                json.dumps(card, ensure_ascii=False),
            )
        except Exception as e:
            logger.error(f"[Feishu] Error sending message: {e}")

    def _send_message_sync(
        self, receive_id_type: str, receive_id: str, msg_type: str, content: str
    ) -> bool:
        """同步发送消息（在线程池中执行）。"""
        try:
            request = (
                CreateMessageRequest.builder()
                .receive_id_type(receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(receive_id)
                    .msg_type(msg_type)
                    .content(content)
                    .build()
                )
                .build()
            )
            response = self._client.im.v1.message.create(request)
            if not response.success():
                logger.error(
                    f"[Feishu] Send failed: code={response.code}, msg={response.msg}"
                )
                return False
            return True
        except Exception as e:
            logger.error(f"[Feishu] Send error: {e}")
            return False

    # ── 接收消息 ──────────────────────────────────────

    def _on_message_sync(self, data: "P2ImMessageReceiveV1") -> None:
        """WebSocket 线程中的同步回调，调度到主事件循环。"""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._on_message(data), self._loop)
        else:
            logger.debug("[Feishu] Message dropped: main event loop not available")

    def _on_reaction_sync(self, data) -> None:
        """用户给消息添加表情回应。"""
        try:
            event = data.event
            emoji = event.reaction_type.emoji_type if event.reaction_type else "?"
            user_id = event.user_id.open_id if event.user_id else "unknown"
            message_id = event.message_id
            logger.debug(f"[Feishu] Reaction on {message_id}: {emoji} by {user_id}")
        except Exception:
            pass

    def _on_message_read_sync(self, data) -> None:
        """用户已读消息。"""
        try:
            event = data.event
            reader = event.reader.open_id if event.reader else "unknown"
            count = len(event.message_id_list) if event.message_id_list else 0
            logger.debug(f"[Feishu] Messages read by {reader}: {count} message(s)")
        except Exception:
            pass

    async def _on_message(self, data: "P2ImMessageReceiveV1") -> None:
        """处理收到的飞书消息。"""
        try:
            event = data.event
            message = event.message
            sender = event.sender

            # 去重
            message_id = message.message_id
            if self._is_duplicate(message_id):
                return

            # 跳过机器人自己发的消息
            if sender.sender_type == "bot":
                return

            sender_id = sender.sender_id.open_id if sender.sender_id else "unknown"
            chat_id = message.chat_id
            chat_type = message.chat_type
            msg_type = message.message_type

            # 解析消息内容
            content = self._parse_message_content(msg_type, message)

            # 图片/表情：下载并构建 images 列表
            images = None
            if msg_type in ("image", "sticker"):
                try:
                    content_json = json.loads(message.content) if message.content else {}
                    image_key = content_json.get("image_key", "")
                    if image_key:
                        img_data = await self._download_image(message_id, image_key)
                        if img_data:
                            images = [img_data]
                            # 图片下载成功时用描述性文本替代占位符
                            content = "请描述和分析这张图片" if msg_type == "image" else "[表情]"
                        else:
                            logger.warning("[Feishu] Image download failed, using placeholder")
                    else:
                        logger.warning("[Feishu] Image message missing image_key")
                except asyncio.TimeoutError:
                    logger.warning(f"[Feishu] Image download timed out ({_IMAGE_DOWNLOAD_TIMEOUT}s)")
                except Exception as e:
                    logger.error(f"[Feishu] Image processing error: {e}")

            # 群聊：清理 @_user_N 占位符，然后检查是否有效
            if chat_type == "group":
                content = _AT_BOT_RE.sub("", content).strip()
                # nanobot 行为一致：群聊中只有 @机器人 或非空文本才响应
                if not content:
                    return

            if not content or not content.strip():
                return

            # 添加表情回应（表示已收到）
            await self._add_reaction(message_id, "THUMBSUP")

            # 群聊时回复到群，私聊时回复到个人
            reply_to = chat_id if chat_type == "group" else sender_id

            logger.info(
                f"[Feishu] Message from {sender_id} ({chat_type}/{msg_type}): "
                f"{content[:80]}{'...' if len(content) > 80 else ''}"
            )

            # 调度到 Agent
            await self._dispatch(
                sender_id=sender_id,
                chat_id=reply_to,
                content=content,
                images=images,
                metadata={
                    "message_id": message_id,
                    "chat_type": chat_type,
                    "msg_type": msg_type,
                },
            )

        except Exception as e:
            logger.error(f"[Feishu] Error processing message: {e}")

    # ── 消息解析 ──────────────────────────────────────

    def _parse_message_content(self, msg_type: str, message: Any) -> str:
        """根据消息类型解析内容（纯同步，无 I/O）。"""
        try:
            content_json = json.loads(message.content) if message.content else {}
        except json.JSONDecodeError:
            content_json = {}

        if msg_type == "text":
            return content_json.get("text", "").strip()

        elif msg_type == "post":
            return _extract_post_text(content_json).strip()

        elif msg_type in ("share_chat", "share_user", "interactive"):
            return f"[{msg_type}]"

        else:
            return MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]")

    # ── 图片下载 ──────────────────────────────────────

    @staticmethod
    def _detect_mime(image_key: str, img_bytes: bytes) -> str:
        """检测图片 MIME 类型：先 magic bytes，再 image_key 后缀，最后默认 png。"""
        # 优先用文件头 magic bytes 检测（最可靠）
        for magic, mime in _MAGIC_MAP.items():
            if img_bytes[:len(magic)] == magic:
                return mime
        # 兜底：image_key 后缀
        for ext, mime in _IMAGE_MIME_MAP.items():
            if image_key.lower().endswith(f".{ext}"):
                return mime
        return "image/png"

    def _download_image_sync(self, message_id: str, image_key: str) -> dict | None:
        """同步下载图片，返回 {"base64": ..., "content_type": ...} 或 None。"""
        if not self._client:
            return None
        try:
            request = (
                GetMessageResourceRequest.builder()
                .message_id(message_id)
                .file_key(image_key)
                .type("image")
                .build()
            )
            response = self._client.im.v1.message_resource.get(request)
            if not response.success():
                logger.warning(
                    f"[Feishu] Image download failed: code={response.code}, msg={response.msg}"
                )
                return None
            # response.file 是 BytesIO
            img_bytes = response.file.read()
            if not img_bytes:
                logger.warning("[Feishu] Image download returned empty data")
                return None
            if len(img_bytes) > _MAX_IMAGE_BYTES:
                logger.warning(
                    f"[Feishu] Image too large: {len(img_bytes)} bytes (max {_MAX_IMAGE_BYTES})"
                )
                return None
            mime = self._detect_mime(image_key, img_bytes)
            b64 = base64.b64encode(img_bytes).decode("ascii")
            logger.debug(f"[Feishu] Image downloaded: {image_key}, size={len(img_bytes)} bytes, mime={mime}")
            return {"base64": b64, "content_type": mime}
        except Exception as e:
            logger.error(f"[Feishu] Image download error: {e}")
            return None

    async def _download_image(self, message_id: str, image_key: str) -> dict | None:
        """异步包装：在线程池中下载图片，带超时保护。"""
        loop = asyncio.get_running_loop()
        coro = loop.run_in_executor(
            None, self._download_image_sync, message_id, image_key
        )
        return await asyncio.wait_for(coro, timeout=_IMAGE_DOWNLOAD_TIMEOUT)

    # ── 表情回应 ──────────────────────────────────────

    async def _add_reaction(self, message_id: str, emoji_type: str = "THUMBSUP") -> None:
        """给消息添加表情回应（非阻塞）。"""
        if not self._client or not Emoji:
            return
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, self._add_reaction_sync, message_id, emoji_type
            )
        except Exception:
            pass  # 表情回应失败不影响主流程

    def _add_reaction_sync(self, message_id: str, emoji_type: str) -> None:
        """同步添加表情回应。"""
        try:
            request = (
                CreateMessageReactionRequest.builder()
                .message_id(message_id)
                .request_body(
                    CreateMessageReactionRequestBody.builder()
                    .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
                    .build()
                )
                .build()
            )
            response = self._client.im.v1.message_reaction.create(request)
            if not response.success():
                logger.debug(f"[Feishu] Reaction failed: code={response.code}")
        except Exception:
            pass
