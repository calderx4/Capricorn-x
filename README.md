# Capricorn-x

> v0.2.12 | 原生 Function Calling 驱动的轻量级通用 Agent Runtime

轻量级 Agent Runtime。不约束 LLM 怎么做，只告诉它有什么能用，让它自己规划和决策。

---

## 快速开始

```bash
git clone https://github.com/calderx4/Capricorn-x.git
cd Capricorn-x
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填入 API Key

python run.py --mode gateway_with_webui
# 浏览器打开 http://localhost:8080
```

---

## 设计理念

**Thin layer on top of LLM.** Capricorn 是 LLM 上层的调度层，不是框架。

| Capricorn 做 | LLM 做 |
|-------------|--------|
| 注册工具、提供能力 | 判断用什么工具、怎么组合 |
| 管理 session / memory | 决定什么时候需要 spawn team |
| 调度 cron | 决定任务拆分和执行策略 |
| 维护 bia 行为规则 | 发现模式、自我纠偏 |

LLM 越强，Capricorn 越薄。不硬编码业务规则，不规定步骤数，不限制执行方式。

---

## 架构

```
用户（CLI / WebUI / HTTP API / 飞书）
  │
  ▼
Gateway（aiohttp, Auth, SSE）
  │
  ├── POST /upload      — 文件上传（保存到 workspace）
  ├── POST /chat         — 对话（支持图片多模态）
  ├── POST /chat/stream  — SSE 流式对话（实时推送 FC 循环进度）
  │
  ▼
Channel Manager（飞书 / 微信 / QQ / Telegram ...）
  │
  ▼
Capricorn Agent
  │
  ├── FC 循环      — LLM → tool_calls → execute → repeat
  ├── SSE 事件     — thinking / tool_call / round / consolidation / response
  ├── 多模态       — 图片通过 base64 注入 LLM 原生视觉
  ├── 三层工具      — builtin / MCP / workflow，自动发现
  ├── Agent Teams   — spawn executor / verifier，LLM 自己决定是否需要
  ├── Cron          — 定时任务，支持角色配置，结果推回来源 Channel
  ├── 三层记忆      — session / MEMORY.md / HISTORY.md
  ├── BIA 自进化    — 行为规则去重、压缩、上限管理
  └── Tasklist      — 任务列表管理，SSE 实时同步
```

### 工具系统

工具通过 `BaseTool` 基类定义，按目录自动发现注册：

- **builtin** — 文件读写（offset/limit + 行号）、文件搜索（glob/grep）、命令执行、任务管理、质量检查等
- **MCP** — 通过 MCP 协议接入外部服务（搜索、图像理解等）
- **workflow** — 多步编排的复杂任务

### SSE 流式事件

FC 循环的每一步都通过事件系统实时推送：

| 事件 | 说明 |
|------|------|
| `run_start` | Agent 开始执行 |
| `thinking` | LLM 正在思考 |
| `tool_call_start` / `tool_call_end` | 工具调用开始 / 完成（含延迟和状态） |
| `round_start` / `round_end` | FC 循环每轮开始 / 结束 |
| `consolidation_start` / `consolidation_end` | 记忆整合开始 / 完成 |
| `tasklist_update` | 任务列表变更 |
| `response` | 最终回复 |
| `run_end` | Agent 执行结束 |

通过 `POST /chat/stream`（SSE）或 CLI 模式均可接收。

### Agent Teams

主 Agent 可以 spawn 子 Agent（executor 执行任务，verifier 验收质量）。不硬编码何时 spawn，LLM 自行判断。重试时自动注入上次验收反馈。

### 记忆管理

| 层 | 存储 | 机制 |
|----|------|------|
| 会话记忆 | JSONL | FC 循环每轮写盘，防崩溃丢失 |
| 长期记忆 | MEMORY.md | LLM 整合，有 token 上限（默认 3000） |
| 历史摘要 | HISTORY.md | 可搜索的行动日志，有条目上限（默认 100） |
| 行为规则 | bia.md | 时间戳 + 去重 + 1500 token 上限 + LLM 压缩 |

### 角色化

角色将身份（WHO）、权限（WHAT）、指令（HOW）三层解耦：

| 层 | 决定 | 位置 |
|----|------|------|
| 身份 | 行为准则 | `prompts/roles/executor.md` |
| 权限 | 可用工具白名单 | `roles/executor.yaml` |
| 指令 | 具体任务内容 | spawn brief / cron prompt |

### Prompt 模板

所有 prompt 都是 Markdown 模板，通过 `{{placeholder}}` 组装（workspace / tools / skills / memory / bia）。换垂类只需换 prompt 文件和工具配置。

---

## 核心能力

| 能力 | 说明 |
|------|------|
| FC 循环 | LLM → tool_calls → execute，无 ReAct，无状态机 |
| SSE 流式 | FC 循环每步实时推送，WebUI / CLI / HTTP 均可接收 |
| 多模态 | WebUI 上传图片 → base64 注入 LLM 原生视觉理解 |
| 文件上传 | WebUI 上传文件 → 自动保存到 workspace，Agent 用工具读取 |
| 三层工具 | builtin / MCP / workflow，自动发现注册 |
| Agent Teams | spawn executor / verifier，LLM 自主决策 |
| Cron | 定时调度，支持角色配置，结果推回来源 Channel |
| Channel | 飞书（WebSocket 长连接 + 图片/表情），可扩展微信/QQ/Telegram |
| Channel Prompt | 按平台自动注入专属指令（格式约束、风格规范） |
| 三层记忆 | session + MEMORY.md + HISTORY.md，自动整合 |
| BIA 自进化 | 行为规则管理（去重、压缩、上限） |
| 技能系统 | autoload + on-demand，按需加载领域技能 |
| Gateway API | HTTP + SSE + 多会话 + 认证 + 文件上传 |
| Tasklist | 任务列表工具，整表替换模式，SSE 实时同步 |

---

## 配置

环境变量用 `${VAR_NAME}` 注入：

```json
{
  "llm": {
    "model": "MiniMax-M3",
    "api_key": "${MINIMAX_API_KEY}",
    "api_base": "https://api.minimaxi.com/v1"
  },
  "workspace": { "sandbox": true },
  "team": {
    "max_concurrent": 5,
    "max_attempts": 3,
    "max_questions": 3
  },
  "memory": {
    "max_memory_tokens": 3000,
    "max_history_entries": 100
  }
}
```

---

## 测试

```bash
pytest tests/ -q
```

---

## 版本历史

| 版本 | 主题 |
|------|------|
| v0.2.12 | 飞书 Channel（WebSocket 长连接 + 图片/表情接收 + Channel Prompt）+ Cron 源路由（结果推回来源 Channel）+ Config 清理 |
| v0.2.11 | SSE 断连后台执行 + 进度持久化 + sandbox 统一 + config 简化 |
| v0.2.10 | glob/grep 搜索工具 + read_file offset/limit + 代码简化清理 |
| v0.2.9 | SSE 流式事件 + Tasklist 工具 + 指数退避重试 |
| v0.2.8 | Memory 优化（整合逻辑重构、配置调优） |
| v0.2.7 | 文件上传 + 图片多模态 + 安全修复 |
| v0.2.6 | 简化 LLM 约束 + BIA/memory 上限管理 |
| v0.2.5 | BIA / Team / Cron / Quality 工具 + 代码简化清理 |
| v0.2.4 | 初始版本 |

---

## License

MIT
