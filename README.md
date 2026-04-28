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
│ Todo     │          │               │
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
| **Layer 1 内置工具** | 原子操作，本地执行 | read_file、write_file、list_files、exec、todo、skill_view |
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

## 技能系统

技能以 `SKILL.md` 文件定义，YAML frontmatter 声明名称、描述和可用性：

```yaml
---
name: code-review
description: 代码审查技能
available: true
---
```

工作流程采用**渐进式披露**：

1. `available: true` 的技能摘要（name + description）注入 system prompt，LLM 知道有哪些技能可用
2. 当用户请求匹配某个技能时，LLM 调用 `skill_view(name)` tool 加载完整指令
3. LLM 按照技能指令执行任务

`available: false` 的技能不会出现在 system prompt 中，LLM 无法感知。

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
python run.py
```

进入交互式对话界面后直接输入问题即可：

```
🚀 Capricorn Agent 启动中...
✓ Agent 已就绪
💡 输入 'exit' 或 'quit' 退出，'help' 查看帮助

👤 You: 帮我在工作区创建一个 hello.py

🤖 Assistant: 已在工作区创建 hello.py...
```

## 项目结构

```
capricorn/
├── agent/                  # Agent 层
│   ├── agent.py            # 原生 FC 循环（核心调度）
│   └── executor.py         # Agent 编排器 / 生命周期管理 / LangChain 兼容性 patch
├── capabilities/           # 能力层
│   ├── capability_registry.py  # 统一能力注册中心
│   ├── skills/             # 技能系统
│   │   ├── loader.py       # SKILL.md 解析器
│   │   ├── manager.py      # 技能生命周期管理
│   │   ├── skill_tool.py   # skill_view tool（LLM 按需加载技能）
│   │   └── skills/         # 技能定义文件
│   └── tools/              # 工具系统
│       ├── registry.py     # 工具注册与并发执行（含参数校验）
│       ├── builtin/        # Layer 1：内置工具
│       ├── mcp/            # Layer 2：MCP 工具（含并发锁）
│       └── workflow/       # Layer 3：工作流
├── config/                 # 配置层
│   ├── config.json         # 运行时配置（支持 ${ENV_VAR} 注入）
│   ├── prompts/            # System prompt 模板
│   └── settings.py         # Pydantic v2 配置模型
├── core/                   # 核心抽象
│   ├── base_tool.py        # 工具基类（JSON Schema + LangChain 桥接）
│   ├── base_workflow.py    # 工作流基类
│   ├── sandbox.py          # 路径与命令沙盒校验
│   ├── token_counter.py    # Token 计数（tiktoken + 启发式回退）
│   ├── trace.py            # 结构化决策链路追踪（JSONL）
│   └── utils.py            # 工具函数（thinking tag 清理等）
├── memory/                 # 记忆层
│   ├── session.py          # JSONL 会话管理（原子写入 + tool call 完整保存）
│   ├── long_term.py        # MEMORY.md 管理（原子写入）
│   └── history.py          # HISTORY.md 管理
├── run.py                  # CLI 入口
├── pyproject.toml          # 项目配置（pip install -e . 可编辑安装）
├── requirements.txt
└── tests/                  # pytest 测试（111 tests）
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

## 多厂商兼容

`provider: "openai"` 分支支持所有 OpenAI 兼容 API。初始化时自动 patch LangChain 的消息序列化，确保各厂商返回的非标准字段（如 DeepSeek 的 `reasoning_content`）在多轮对话中正确保留和回传。无需额外配置，切换 `api_base` 和 `api_key` 即可使用不同厂商。

已验证兼容：DeepSeek、MiniMax、GLM、Qwen。

## 许可证

[MIT License](LICENSE)

---

<sup>参考实现：[NanoBot](https://github.com/HKUDS/nanobot)（工具注册与并发架构）、[Hermes](https://github.com/NousResearch/hermes-agent)（原生 FC 循环模式）</sup>
