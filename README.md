
# ↻ Capricorn Agent

**原生 Function Calling 驱动的轻量级通用 Agent Runtime。**

面向任务执行与垂直落地的 Agent 框架。不依赖 ReAct、状态机或 think/act 拆分，将决策权完全交由 LLM 原生 FC，Runtime 仅负责调度与执行。核心代码透明可 Hack，方便二次开发、落地垂直领域。

- **任务通用** — 代码生成、系统操作、数据处理、长任务自动执行
- **轻量** — 无 ReAct / 无状态图 / 无复杂调度器，单循环：LLM → FC → 执行 → 回传
- **长任务** — 自动上下文压缩、JSONL 原子写入、Cron 定时 + SSE 推送
- **易二次开发** — 加工具一个文件，加技能一个 SKILL.md，改核心逻辑只看 agent.py

## 🔧 安装

```bash
git clone https://github.com/calderx4/Capricorn-x.git
cd Capricorn-x
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填入 API Key
```

## 🚀 运行

```bash
python run.py                                  # CLI 交互
python run.py --mode gateway                   # HTTP API + Cron
python run.py --mode gateway_with_webui        # HTTP API + Cron + Web 前端
```

## ⚡ 核心能力

**原生 FC 循环** — 模型自己决定调不调工具、调哪个、什么时候停。并发执行 + 5 分钟单工具超时 + 迭代上限保护。

**三层能力架构** — 统一注册、自动发现。

| 层级 | 说明 | 已有工具 |
|------|------|----------|
| 内置工具 | 本地原子操作 | read_file、write_file、edit_file、list_files、exec、todo、cron、skill_view、memory_update、history_search |
| MCP 工具 | 外部服务协议接入 | MiniMax MCP、高德地图等（配置即用） |
| 工作流 | 复杂流程封装 | create_document、self_test、memory_consolidation |

**记忆系统** — JSONL 会话 + MEMORY.md 长期记忆 + HISTORY.md 历史摘要。对话超阈值自动 LLM 整合，原子写入防崩溃。

**Cron 定时任务** — LLM 通过 FC 管理（create/list/pause/resume/remove），协程执行防递归，支持 `repeat` 次数和 `end_at` 截止限制。

**技能系统** — 8 个内置技能，通过 `skill_view(name)` 按需加载。新增技能只需一个目录 + SKILL.md。

**多 LLM** — OpenAI 兼容 API（DeepSeek、MiniMax、GLM、Qwen 等）+ Anthropic Claude，`reasoning_content` 字段自动兼容。

**Gateway HTTP** — aiohttp 轻量服务。

| 端点 | 说明 |
|------|------|
| `POST /chat` | 对话（支持 thread_id 多会话） |
| `POST /task` | 异步任务 |
| `GET /task/{id}` | 查询任务状态 |
| `GET /jobs` | 列出 Cron 任务 |
| `GET /events` | SSE 实时推送通知 |
| `GET /notifications` | 查询通知 |
| `POST /notifications/read` | 标记已读 |
| `GET /health` | 健康检查 |

## 🛠️ 技能

| 技能 | 触发场景 |
|------|----------|
| frontend-dev | 前端页面、UI 设计、动画 |
| fullstack-dev | 全栈应用、REST API、数据库 |
| minimax-multimodal | 图片/视频/语音/音乐生成、图像理解 |
| minimax-docx | Word 文档、排版、报告 |
| minimax-pdf | PDF 生成、表单填充 |
| minimax-xlsx | Excel 表格、公式、财务模型 |
| pptx-generator | PPT 演示文稿 |
| code-review | 代码审查 |

## 📁 项目结构

```
agent/               # FC 循环、调度器、通知、Gateway、WebUI
capabilities/
  ├── skills/        # 技能系统（SKILL.md 自动发现）
  └── tools/         # 工具系统（builtin / mcp / workflow 三层）
config/              # config.json + prompts 模板
core/                # BaseTool、BaseWorkflow、沙盒、token 计数、atomic_write
memory/              # Session（JSONL）、MEMORY.md、HISTORY.md
tests/               # pytest 测试
run.py               # 入口
```

## 🛠️ 二次开发

**加工具** — 在 `capabilities/tools/` 对应 layer 下新建文件，继承 `BaseTool`，实现 `name`、`description`、`parameters`、`execute`，自动发现注册。

**加技能** — 在 `capabilities/skills/skills/` 下新建目录，写 `SKILL.md`（frontmatter 含 name、description、available），自动发现注入。

**改核心** — FC 循环在 `agent/agent.py`，调度在 `agent/scheduler.py`，配置在 `config/settings.py`，逻辑透明，改哪看哪。

**接 MCP** — 在 `config.json` 的 `mcp_servers` 加配置，自动连接注册。

## 参考

参考了 NanoBot、Hermes、MiniMax Skills。

---

<p align="center">
  <em>原生 FC · 极简循环 · 拿来就能改的 Agent 框架</em>
</p>
