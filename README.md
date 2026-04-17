# Capricorn

基于 [LangGraph](https://github.com/langchain-ai/langgraph) 的可扩展 LLM Agent 系统。

Capricorn 实现了一个 **ReAct（Reason + Act）模式**的 Agent，采用三层能力架构，支持工具调用、MCP 协议集成、技能系统和长期记忆管理。本项目用于学习和探索 LLM Agent 的设计与实现。

> 本项目参考了以下开源实现的思想：
> - [nanobot (HKUDS)](https://github.com/HKUDS/nanobot) — LLM Agent 的工具注册、并发执行架构
> - [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — 记忆系统（MEMORY.md / HISTORY.md）、技能系统（SKILL.md）、自动记忆整合机制

## 架构概览

```
┌─────────────────────────────────────────────┐
│                  Agent 层                    │
│  LangGraph ReAct 循环（think → act → think） │
├─────────────────────────────────────────────┤
│              能力注册中心                      │
│         CapabilityRegistry                   │
├──────────┬──────────┬───────────────────────┤
│ Layer 1  │ Layer 2  │ Layer 3               │
│ 内置工具  │ MCP 工具  │ 工作流                 │
│ 文件读写  │ 外部 API  │ 多步骤编排              │
│ Shell 执行│ 联网服务  │ 文档生成/记忆整合        │
└──────────┴──────────┴───────────────────────┘
         │
    ┌────┴────┐
    │ 记忆系统 │  长期记忆 / 会话管理 / 历史日志
    └─────────┘
```

### 三层能力体系

| 层级 | 说明 | 示例 |
|------|------|------|
| **Layer 1 - 内置工具** | 原子操作，本地执行，速度快 | 读取文件、写入文件、列出文件、Shell 执行 |
| **Layer 2 - MCP 工具** | 通过 Model Context Protocol 连接外部服务 | 高德地图 API、文件系统、Web 搜索 |
| **Layer 3 - 工作流** | 多步骤编排，适合复杂任务 | 文档创建工作流、记忆整合工作流、自检工作流 |

## 功能特性

- **ReAct Agent**：基于 LangGraph 的 think → act 循环，支持多轮工具调用
- **三层能力架构**：内置工具 / MCP 工具 / 工作流，统一注册、分层管理
- **MCP 协议集成**：支持 stdio、SSE、streamable_http 三种传输方式
- **多 LLM 提供商**：支持 Anthropic Claude 和 OpenAI 兼容 API（MiniMax 等）
- **记忆系统**：长期记忆（MEMORY.md）、会话持久化（JSONL）、历史日志（HISTORY.md）
- **自动记忆整合**：对话超过阈值时自动调用 LLM 整合记忆
- **技能系统**：基于 SKILL.md 定义，支持 always-on 和按需加载两种模式

## 快速开始

### 环境要求

- Python 3.12+
- pip

### 安装

```bash
git clone https://github.com/your-username/capricorn.git
cd capricorn
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 配置

1. 复制环境变量模板：

```bash
cp .env.example .env
```

2. 编辑 `.env`，填入你的 API Key：

```env
MINIMAX_API_KEY=your_api_key_here
AMAP_MAPS_API_KEY=your_amap_key_here   # 可选
```

3. 按需修改 `config/config.json`（LLM 模型、MCP 服务器等）。

### 运行

```bash
python run.py
```

进入交互式对话界面后，直接输入问题与 Agent 对话：

```
🚀 Capricorn Agent 启动中...
✓ Agent 已就绪
💡 输入 'exit' 或 'quit' 退出，'help' 查看帮助

👤 You: 帮我在工作区创建一个 hello.py 文件

🤖 Assistant: 已在工作区创建 hello.py 文件...
```

## 项目结构

```
capricorn/
├── agent/                  # Agent 层
│   ├── agent.py            # LangGraph ReAct 状态图
│   └── executor.py         # Agent 编排器 / 生命周期管理
├── capabilities/           # 能力层
│   ├── capability_registry.py  # 统一能力注册中心
│   ├── skills/             # 技能系统
│   │   ├── loader.py       # SKILL.md 解析器
│   │   ├── manager.py      # 技能生命周期管理
│   │   └── skills/         # 技能定义文件
│   └── tools/              # 工具系统
│       ├── registry.py     # 工具注册与执行
│       ├── builtin/        # Layer 1：内置工具
│       ├── mcp/            # Layer 2：MCP 工具
│       └── workflow/       # Layer 3：工作流工具
├── config/                 # 配置层
│   ├── config.json         # 运行时配置
│   └── settings.py         # Pydantic 配置模型
├── core/                   # 核心抽象
│   ├── base_tool.py        # 工具基类
│   ├── base_workflow.py    # 工作流基类
│   ├── interfaces.py       # Protocol 接口定义
│   └── token_counter.py    # Token 计数
├── memory/                 # 记忆层
│   ├── history.py          # HISTORY.md 管理
│   ├── long_term.py        # MEMORY.md 管理
│   └── session.py          # JSONL 会话管理
├── run.py                  # CLI 入口
├── requirements.txt        # Python 依赖
└── docs/                   # 项目文档
```

## 技术栈

| 组件 | 技术 |
|------|------|
| Agent 框架 | [LangGraph](https://github.com/langchain-ai/langgraph) |
| LLM 集成 | [LangChain](https://github.com/langchain-ai/langchain) (Core / Anthropic / OpenAI) |
| 配置验证 | [Pydantic](https://github.com/pydantic/pydantic) v2 |
| MCP 协议 | [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) |
| 日志 | [Loguru](https://github.com/Delgan/loguru) |

## 配置说明

配置文件位于 `config/config.json`，支持通过 `${ENV_VAR}` 语法注入环境变量。

主要配置项：

| 字段 | 说明 |
|------|------|
| `workspace.root` | 工作空间目录路径 |
| `llm.provider` | LLM 提供商（`openai` / `anthropic`） |
| `llm.model` | 模型名称 |
| `llm.api_key` | API Key（建议使用 `${MINIMAX_API_KEY}` 环境变量） |
| `mcp_servers` | MCP 服务器配置（支持 stdio / sse / streamable_http） |
| `hooks.memory_consolidation` | 记忆整合 Hook 配置 |
| `skills` | 技能系统配置 |

详细配置参考见 [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md)。

## 许可证

[MIT License](LICENSE)
