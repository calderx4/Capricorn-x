# Capricorn

原生 Function Calling 驱动的 LLM Agent 框架。

没有 ReAct、没有状态图、没有 think/act 拆分。决策权完全交给模型的原生 FC 能力，循环只负责调用、执行、转发。

## 架构

```
┌─────────────────────────────────────┐
│             Agent 层                │
│     原生 FC 循环（LLM → 工具 → LLM） │
├─────────────────────────────────────┤
│         CapabilityRegistry          │
├──────────┬──────────┬───────────────┤
│ 内置工具  │ MCP 工具  │ 工作流        │
│ 文件读写  │ 外部 API  │ 多步骤编排     │
│ Shell    │ 联网服务  │ 记忆整合       │
│ Cron     │          │               │
└──────────┴──────────┴───────────────┘
          │
     ┌────┴────┐
     │ 记忆系统 │ Session / MEMORY.md / HISTORY.md
     └─────────┘
```

## 特性

- **原生 FC 循环** — 直接使用 LLM function calling，工具通过 ToolRegistry 并发执行（asyncio.gather），含参数类型转换与校验，迭代上限保护
- **三层能力** — 内置工具 / MCP 协议 / 工作流，统一注册、分层管理，目录扫描自动发现
- **MCP 集成** — 支持 stdio、SSE、streamable_http 三种传输方式，工具自动发现并命名空间隔离（`mcp_{server}_{tool}`），每 server 独立并发锁
- **多 LLM 提供商** — Anthropic Claude、OpenAI 兼容 API（DeepSeek、MiniMax、GLM、Qwen 等），配置切换即可。自动兼容各厂商思考模式的非标准字段
- **记忆系统** — 原子写入持久化（JSONL）、长期记忆（MEMORY.md）、历史日志（HISTORY.md）。Session 完整保存 tool call 轮次（含 reasoning_content）
- **自动记忆整合** — 对话超过阈值时自动调用 LLM 整合记忆，整合裁剪保持 tool call 轮次完整性，含失败熔断机制
- **技能系统** — SKILL.md 定义，渐进式披露：system prompt 列出可用技能摘要，LLM 通过 `skill_view` tool 按需加载完整指令
- **Cron 定时任务** — 60 秒 tick 轮询，LLM 通过 FC 管理定时任务（create/list/pause/resume/remove），协程执行，防递归
- **通知系统** — cron 任务结果通过 NotificationBus 推送：SSE 实时推送（`GET /events`）、REST 查询（`GET /notifications`）、Agent 下次对话自动提及
- **Gateway HTTP** — aiohttp 轻量服务，POST /chat 远程对话，POST /task 异步任务，GET /health 健康检查
- **WebUI** — Streamlit Web 聊天界面，和终端对话完全等价，侧边栏管理 Cron 任务和查看通知
- **沙盒安全** — 文件路径限制在工作区内，命令黑名单拦截危险操作

## 核心：FC 循环

整个 Agent 的核心就是一个 `for` 循环，每轮做的事：

1. 把完整消息列表 + 工具 schema 发给 LLM
2. 收到响应后检查是否有 `tool_calls`
3. 有 → 通过 ToolRegistry 并发执行所有工具（经 cast_params + validate_params 校验），把 `AIMessage`（含 tool_calls）和对应的 `ToolMessage` 追加到消息列表，回到步骤 1
4. 没有 → 模型给出最终回复，结束循环

模型自己决定调不调工具、调哪个、什么时候停。循环本身只负责执行和转发。

## 三层能力

| 层级 | 说明 | 当前工具 |
|------|------|----------|
| **Layer 1 内置工具** | 原子操作，本地执行 | read_file、write_file、list_files、exec、todo、cron、skill_view |
| **Layer 2 MCP 工具** | 通过 MCP 协议连接外部服务 | MiniMax MCP、高德地图（可扩展） |
| **Layer 3 工作流** | 多步骤编排 | 文档创建、自检、记忆整合 |

所有工具统一注册到 `ToolRegistry`，通过 `BaseTool` 基类标准化（JSON Schema 参数定义、LangChain 工具桥接）。Builtin 工具和 Workflow 放入 `extensions/` 目录自动发现注册，MCP 工具通过配置加载，技能通过 SKILL.md 自动发现。

## 记忆系统

| 组件 | 存储 | 用途 |
|------|------|------|
| **Session** | JSONL 文件（原子写入） | 完整对话记录，含 tool call 轮次和 reasoning_content |
| **MEMORY.md** | Markdown（原子写入） | 长期知识，注入每轮 system prompt |
| **HISTORY.md** | Markdown | 对话时间线摘要，可搜索 |

整合流程：每轮对话前检查消息数，超阈值时提取旧消息 → 调用 LLM 生成摘要和记忆更新 → 写入 HISTORY.md 和 MEMORY.md → 裁剪 session 文件（保持 tool call 轮次完整性，去除孤儿消息）。

## Cron 定时任务

通过 `cron` FC 工具管理定时任务。每个任务有显式 `type` 字段区分一次性/重复：

| type | 说明 | 终止条件 |
|---|---|---|
| `"once"` | 执行一次 | 执行完 completed |
| `"recurring"` | 按 schedule 重复 | `repeat` 次数 / `end_at` 截止时间 / 无限 |

```
用户：每天早上 9 点帮我检查 GitHub issue，持续一周
LLM：cron(action="create", type="recurring", name="检查 issue",
      schedule="0 9 * * *", end_at="2026-05-06T09:00:00",
      prompt="访问 GitHub 仓库 xxx/issues，列出过去 24 小时新建的 issue")

用户：3分钟后提醒我背单词
LLM：cron(action="create", type="once", name="背单词提醒",
      schedule="3m", prompt="提醒：该背单词了！")
```

支持 cron 表达式、间隔（`every 30m`）、延迟（`3m`）、时间（`13:25`）、日期时间。详见 [docs/v0.2.3/cron-design.md](docs/v0.2.3/cron-design.md)。

## 快速开始

### 环境要求

- Python 3.12+
- pip

### 安装

```bash
git clone https://github.com/calderx4/Capricorn-x.git
cd Capricorn-x
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

### 配置

1. 复制环境变量模板：

```bash
cp .env.example .env
```

2. 编辑 `.env`，填入 API Key：

```env
DEEPSEEK_API_KEY=your_api_key_here
AMAP_MAPS_API_KEY=your_amap_key_here   # 可选
```

3. 按需修改 `config/config.json`。

### 运行

```bash
# CLI 交互模式（默认）
python run.py

# Gateway 模式：HTTP API + Cron，纯后台
python run.py --mode gateway

# Gateway + WebUI：HTTP API + Cron + Web 聊天界面
python run.py --mode gateway_with_webui
```

三种模式都走同一个 workspace、同一套 session/记忆。区别只在交互入口：

| 模式 | CLI | API | WebUI | Cron |
|---|---|---|---|---|
| 默认 | ✅ | - | - | - |
| `gateway` | - | ✅ | - | ✅ |
| `gateway_with_webui` | - | ✅ | ✅ | ✅ |

## Gateway API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/chat` | POST | 远程对话（共享 session） |
| `/task` | POST | 异步任务（立即返回 task_id） |
| `/task/{id}` | GET | 查询异步任务状态 |
| `/health` | GET | 健康检查 |
| `/events` | GET | SSE 实时推送通知（cron 任务结果） |
| `/notifications` | GET | 查询通知列表 |
| `/notifications/read` | POST | 标记通知已读 |

`gateway_with_webui` 模式额外启动 Streamlit 前端（端口 8081）。

详见 [docs/v0.2.3/gateway-api-guide.md](docs/v0.2.3/gateway-api-guide.md)。

## 项目结构

```
agent/                     # Agent 层
│   ├── agent.py           # 原生 FC 循环（CapricornGraph）
│   ├── executor.py        # 编排器 / 生命周期管理
│   ├── scheduler.py       # Cron 定时任务调度器
│   ├── notification.py    # 通知总线（NotificationBus）
│   ├── gateway.py         # HTTP Gateway 服务（aiohttp）
│   └── webui/
│       └── app.py          # Streamlit Web 前端
capabilities/              # 能力层
│   ├── capability_registry.py  # 统一能力注册中心
│   ├── skills/            # 技能系统
│   │   ├── loader.py      # SKILL.md 解析器
│   │   ├── manager.py     # 技能生命周期管理
│   │   ├── skill_tool.py  # skill_view tool（LLM 按需加载）
│   │   └── skills/        # 技能定义（SKILL.md）
│   └── tools/             # 工具系统
│       ├── registry.py    # 工具注册与并发执行
│       ├── builtin/       # Layer 1：内置工具
│       │   └── extensions/ # 内置工具扩展（cron_tools 等）
│       ├── mcp/           # Layer 2：MCP 工具
│       └── workflow/      # Layer 3：工作流
config/                    # 配置层
│   ├── config.json        # 运行时配置（${ENV_VAR} 注入）
│   ├── prompts/           # System prompt 模板
│   │   ├── system.md      # 主 agent prompt 模板
│   │   └── cron.md        # cron 任务 prompt 模板
│   └── settings.py        # Pydantic v2 配置模型
core/                      # 核心抽象
│   ├── base_tool.py       # 工具基类（JSON Schema + LangChain 桥接）
│   ├── base_workflow.py   # 工作流基类
│   ├── sandbox.py         # 路径与命令沙盒校验
│   ├── token_counter.py   # Token 计数
│   ├── trace.py           # 决策链路追踪（JSONL）
│   ├── prompt_utils.py    # prompt section 构建工具
│   └── utils.py           # 工具函数
memory/                    # 记忆层
│   ├── session.py         # JSONL 会话管理
│   ├── long_term.py       # MEMORY.md 管理
│   └── history.py         # HISTORY.md 管理
gateway/                   # 运行时目录（代码生成，不提交）
│   ├── jobs.json          # cron 任务定义
│   ├── notifications.jsonl # 通知记录
│   ├── output/            # cron 执行记录
│   ├── workspaces/       # cron job 工作空间
│   └── tasks/            # HTTP /task 状态
run.py                     # CLI 入口（--mode gateway / gateway_with_webui）
requirements.txt
└── pyproject.toml
```

## 配置说明

配置文件位于 `config/config.json`，支持通过 `${ENV_VAR}` 语法注入环境变量（支持全量和嵌入式替换）。

| 字段 | 说明 |
|------|------|
| `workspace.root` | 工作空间目录路径 |
| `workspace.sandbox` | 是否限制文件操作在工作区内（默认 true） |
| `llm.provider` | LLM 提供商（`openai` / `anthropic`） |
| `llm.model` | 模型名称 |
| `llm.api_key` | API Key（建议使用 `${DEEPSEEK_API_KEY}`） |
| `llm.api_base` | 自定义 API 地址（OpenAI 兼容服务） |
| `llm.max_tokens` | 最大输出 token 数 |
| `mcp_servers` | MCP 服务器配置（支持 stdio / sse / streamable_http） |
| `memory.message_threshold` | 触发整合的消息数阈值（默认 120） |
| `memory.messages_to_keep` | 整合后保留的消息数（默认 60） |
| `memory.token_threshold` | 触发整合的 token 阈值（默认 100000） |
| `memory.context_budget` | 总上下文 token 上限（默认 1280000） |
| `agent.max_iterations` | FC 循环迭代上限（默认 50） |
| `blocked_commands` | 命令黑名单 |
| `cron.enabled` | 是否启用 Cron 定时任务（默认 true） |
| `cron.tick_interval` | tick 轮询间隔秒数（默认 60） |
| `cron.fresh_session` | 新建 cron 任务的默认 fresh_session（默认 false） |
| `cron.default_timeout` | 任务执行超时秒数（默认 300） |
| `gateway.host` | HTTP 服务监听地址（默认 127.0.0.1） |
| `gateway.port` | HTTP 服务端口（默认 8080） |

## 多厂商兼容

`provider: "openai"` 分支支持所有 OpenAI 兼容 API。初始化时自动 patch LangChain 的消息序列化，确保各厂商返回的非标准字段（如 DeepSeek 的 `reasoning_content`）在多轮对话中正确保留和回传。无需额外配置，切换 `api_base` 和 `api_key` 即可使用不同厂商。

已验证兼容：DeepSeek、MiniMax、GLM、Qwen。

## 许可证

[MIT License](LICENSE)

---

<sup>参考实现：[NanoBot](https://github.com/HKUDS/nanobot)（工具注册与并发架构）、[Hermes](https://github.com/NousResearch/hermes-agent)（原生 FC 循环模式）</sup>
