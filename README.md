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
└──────────┴──────────┴───────────────┘
          │
     ┌────┴────┐
     │ 记忆系统 │ Session / MEMORY.md / HISTORY.md
     └─────────┘
```

## 特性

- **原生 FC 循环** — 直接使用 LLM function calling，工具并发执行（asyncio.gather），迭代上限保护
- **三层能力** — 内置工具 / MCP 协议 / 工作流，统一注册、分层管理
- **MCP 集成** — 支持 stdio、SSE、streamable_http 三种传输方式，工具自动发现并命名空间隔离（`mcp_{server}_{tool}`）
- **多 LLM 提供商** — Anthropic Claude、OpenAI 兼容 API（MiniMax 等），配置切换即可
- **记忆系统** — 会话持久化（JSONL）、长期记忆（MEMORY.md）、历史日志（HISTORY.md）
- **自动记忆整合** — 对话超过阈值时自动调用 LLM 整合记忆，含失败熔断机制（连续失败 3 次后回退为原始归档）
- **技能系统** — SKILL.md 定义，支持常驻注入（always）和按需加载两种模式

## 核心：FC 循环

整个 Agent 的核心就是一个 `for` 循环，每轮做的事：

1. 把完整消息列表 + 工具 schema 发给 LLM
2. 收到响应后检查是否有 `tool_calls`
3. 有 → 并发执行所有工具，把 `AIMessage`（含 tool_calls）和对应的 `ToolMessage` 追加到消息列表，回到步骤 1
4. 没有 → 模型给出最终回复，结束循环

模型自己决定调不调工具、调哪个、什么时候停。循环本身只负责执行和转发。

## 三层能力

| 层级 | 说明 | 当前工具 |
|------|------|----------|
| **Layer 1 内置工具** | 原子操作，本地执行 | read_file、write_file、list_files、exec |
| **Layer 2 MCP 工具** | 通过 MCP 协议连接外部服务 | 高德地图、文件系统、Web 搜索（可扩展） |
| **Layer 3 工作流** | 多步骤编排 | 文档创建、自检、记忆整合 |

所有工具统一注册到 `ToolRegistry`，通过 `BaseTool` 基类标准化（JSON Schema 参数定义、LangChain 工具桥接）。MCP 工具和 Workflow 通过适配器模式接入。

## 记忆系统

| 组件 | 存储 | 用途 |
|------|------|------|
| **Session** | JSONL 文件 | 完整对话记录，每轮追加 |
| **MEMORY.md** | Markdown | 长期知识，注入每轮 system prompt |
| **HISTORY.md** | Markdown | 对话时间线摘要，可搜索 |

整合流程：每轮对话前检查消息数和 token 估算，超阈值时提取旧消息 → 调用 LLM 生成摘要和记忆更新 → 写入 HISTORY.md 和 MEMORY.md → 裁剪 session 文件。

## 技能系统

技能以 `SKILL.md` 文件定义，YAML frontmatter 声明名称、描述、所需工具和加载模式：

- **always = true** — 每轮注入完整技能内容到 system prompt
- **always = false** — prompt 中仅展示摘要，按需加载完整内容

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

2. 编辑 `.env`，填入 API Key：

```env
MINIMAX_API_KEY=your_api_key_here
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
│   └── executor.py         # Agent 编排器 / 生命周期管理 / 记忆整合触发
├── capabilities/           # 能力层
│   ├── capability_registry.py  # 统一能力注册中心
│   ├── skills/             # 技能系统
│   │   ├── loader.py       # SKILL.md 解析器
│   │   ├── manager.py      # 技能生命周期管理
│   │   └── skills/         # 技能定义文件
│   └── tools/              # 工具系统
│       ├── registry.py     # 工具注册与并发执行
│       ├── builtin/        # Layer 1：内置工具
│       ├── mcp/            # Layer 2：MCP 工具
│       └── workflow/       # Layer 3：工作流
├── config/                 # 配置层
│   ├── config.json         # 运行时配置（支持 ${ENV_VAR} 注入）
│   └── settings.py         # Pydantic v2 配置模型
├── core/                   # 核心抽象
│   ├── base_tool.py        # 工具基类（JSON Schema + LangChain 桥接）
│   ├── base_workflow.py    # 工作流基类
│   ├── interfaces.py       # Protocol 接口定义
│   └── token_counter.py    # Token 计数（tiktoken + 启发式回退）
├── memory/                 # 记忆层
│   ├── session.py          # JSONL 会话管理（内存缓存 + 磁盘持久化）
│   ├── long_term.py        # MEMORY.md 管理
│   └── history.py          # HISTORY.md 管理
├── run.py                  # CLI 入口
├── requirements.txt
└── tests/                  # pytest 测试
```

## 配置说明

配置文件位于 `config/config.json`，支持通过 `${ENV_VAR}` 语法注入环境变量（支持全量和嵌入式替换）。

| 字段 | 说明 |
|------|------|
| `workspace.root` | 工作空间目录路径 |
| `llm.provider` | LLM 提供商（`openai` / `anthropic`） |
| `llm.model` | 模型名称 |
| `llm.api_key` | API Key（建议使用 `${MINIMAX_API_KEY}`） |
| `llm.max_tokens` | 最大输出 token 数 |
| `mcp_servers` | MCP 服务器配置（支持 stdio / sse / streamable_http） |
| `memory.message_threshold` | 触发整合的消息数阈值（默认 20） |
| `memory.token_threshold` | 触发整合的 token 阈值（默认 8000） |
| `agent.max_iterations` | FC 循环迭代上限（默认 50） |

## 许可证

[MIT License](LICENSE)

---

<sup>参考实现：[NanoBot](https://github.com/HKUDS/nanobot)（工具注册与并发架构）、[Hermes](https://github.com/NousResearch/hermes-agent)（原生 FC 循环模式）</sup>
