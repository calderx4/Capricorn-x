# Capricorn-x

![version](https://img.shields.io/badge/version-v0.3.0-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![python](https://img.shields.io/badge/python-3.12%2B-blue)
![tests](https://img.shields.io/badge/tests-469%20passed-brightgreen)

> **原生 Function Calling 驱动的轻量通用 Agent Runtime。**
> 薄薄一层在 LLM 之上——不约束它怎么做，只告诉它有什么能用，让它自己规划和决策。

Capricorn 不是框架，是 LLM 上层的调度层。不硬编码业务规则，不规定步骤数，不限制执行方式。**LLM 越强，Capricorn 越薄。** 因为薄，所以好读、好改、好换垂类。

---

## 🧭 Start Here

| 你想... | 去哪 |
| --- | --- |
| 5 分钟跑起来，先看到效果 | [快速开始](#-快速开始) |
| 理解设计理念（为什么「薄」） | [设计理念](#-设计理念) |
| 一眼看完全部能力 | [能力全景](#-能力全景) |
| 接入飞书 / 微信 / QQ | [渠道层](#渠道层) · [飞书接入指南](docs/guides/feishu-setup.md) |
| 做二次开发、换垂类、加工具 | [二次开发](#-二次开发) |
| 看 v0.3.0 安全基线 | [安全](#-安全) |
| 读源码级架构文档 | [docs/](docs/README.md) |

---

## ✨ v0.3.0 亮点

- 🔒 exec 命令白名单注入防护（封堵绕过 argv[0] 的注入）
- 📤 上传 per-file 大小检查
- 🛡️ 飞书 WebSocket 身份告警
- ✂️ spawn 状态机瘦身（7 态→5 态）

详见 [版本历史](#-版本历史)。

---

## 💡 设计理念

**Thin layer on top of LLM.** 不用 ReAct，不堆状态机——LLM 直接决定调什么工具，系统并发执行，循环直到最终响应。

| Capricorn 做 | LLM 做 |
|-------------|--------|
| 注册工具、提供能力 | 判断用什么工具、怎么组合 |
| 管理 session / memory | 决定什么时候需要 spawn team |
| 调度 cron | 决定任务拆分和执行策略 |
| 维护 bia 行为规则 | 发现模式、自我纠偏 |

这意味着：**换一个更强的模型，Capricorn 不用改一行代码就自动变强。** 也意味着二次开发很轻——你要做的不是「学一套框架」，而是「写一个工具 + 一段 prompt」。

---

## 🚀 快速开始

```bash
git clone https://github.com/calderx4/Capricorn-x.git
cd Capricorn-x
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 编辑 .env 填入 API Key
```

**1. 启动**（Gateway + WebUI 模式）

```bash
python run.py --mode gateway_with_webui
# 浏览器打开 http://localhost:8080
```

**2. 发第一条消息** —— 在 WebUI 对话框输入任务，看 FC 循环实时推送（thinking → tool_call → round → response）。

**3. 试试拆任务** —— 让主 Agent `spawn` 一个 executor 子任务，用 `check_status` / `get_result` 收口。或让它建个 `cron` 定时任务，到点自动跑、结果推回来源渠道。

> 其他模式：`--mode cli`（终端对话）、`--mode gateway`（纯 HTTP/SSE）。接入飞书见 [飞书指南](docs/guides/feishu-setup.md)。

---

## 🏗️ 架构

```
用户（CLI / WebUI / HTTP API / 飞书）
  │
  ▼
Gateway（aiohttp · Auth · SSE）
  │  POST /upload · /chat · /chat/stream
  ▼
Channel Manager（飞书 / 微信 / QQ / Telegram ...）
  │
  ▼
Capricorn Agent ── FC 循环：LLM → tool_calls → execute → repeat
  ├── 三层工具      builtin / MCP / workflow，自动发现
  ├── Agent Teams   spawn executor / verifier，LLM 自主决策
  ├── Cron          定时任务，支持角色，结果推回来源 Channel
  ├── 三层记忆      session / MEMORY.md / HISTORY.md
  ├── BIA 自进化    行为规则去重、压缩、上限管理
  └── Tasklist      任务列表，SSE 实时同步
```

核心理念：**所有东西围绕一个小的 agent loop 组织**——消息进来，LLM 决定何时调工具，记忆/技能只在需要时作为上下文拉入，而不是变成厚重的编排层。这让核心路径好读、好扩展。

---

## 🧰 能力全景

### 渠道层

| 能力 | 说明 |
|------|------|
| WebUI | Streamlit 对话界面，支持文件上传 + 图片多模态 |
| HTTP API | `POST /chat`、`/chat/stream`(SSE)、`/upload`、`/task`、`/sessions`、`/history` |
| 飞书 Channel | WebSocket 长连接，**无需公网 IP**；收发文本/图片/表情；群聊 @触发 |
| 可扩展 | 微信 / QQ / Telegram ——实现 `BaseChannel` 即可接入 |

### 核心层

| 能力 | 说明 |
|------|------|
| FC 循环 | LLM → tool_calls → execute，无 ReAct，无状态机 |
| SSE 流式 | FC 循环每步实时推送：`run_start` / `thinking` / `tool_call_*` / `round_*` / `consolidation_*` / `tasklist_update` / `response` / `run_end` |
| 多模态 | 图片 base64 注入 LLM 原生视觉（不贯穿上下文，回复后丢弃省 token） |
| 三层记忆 | session（JSONL 每轮写盘）+ MEMORY.md（LLM 整合，token 上限）+ HISTORY.md（可搜索行动日志） |
| BIA 自进化 | bia.md 行为规则：时间戳 + 去重 + token 上限 + LLM 压缩 |

### 工具层

通过 `BaseTool` 基类定义，按目录**自动发现注册**：

- **builtin** —— 文件读写（offset/limit + 行号）、glob/grep 搜索、exec 命令、task/spawn/check_status/get_result、quality_check、bia_update、tasklist 等
- **MCP** —— 通过 MCP 协议接入外部服务（搜索、图像理解、浏览器…）
- **workflow** —— 多步编排的复杂任务

### 扩展层

| 能力 | 说明 |
|------|------|
| Agent Teams | 主 Agent `spawn` 子 Agent：`executor` 执行 / `verifier` 验收（对抗式）。不硬编码何时 spawn，LLM 自行判断 |
| 任务状态机 | `producing → running → done / need_decision / error`（5 态）；验收/重试由主 Agent 读结论后手动驱动 |
| Cron | `once`（延迟/时刻/绝对时间）/ `recurring`（间隔/每天/标准 cron）；`role` 套角色模板；`fresh_session` 独立人格；结果推回来源渠道 |
| 技能系统 | autoload + on-demand，按需加载领域技能（self-evolution / fullstack-dev / minimax-pdf/xlsx …） |
| 角色化 | 身份(WHO) / 权限(WHAT) / 指令(HOW) 三层解耦：`roles/*.md` + `roles/*.yaml` + spawn brief |

---

## 🔒 安全

v0.3.0 把安全从「纸上」做成「代码层」：

| 维度 | 机制 |
|------|------|
| 文件路径 | `sandbox=true` 时所有文件操作限定在 workspace 内，resolve + 路径穿越校验 |
| 命令执行 | 黑名单 `blocked_commands` + **可选白名单** `allowed_commands`（OPT-IN）；白名单启用时拒绝命令注入元字符 |
| 上传 | `MAX_UPLOAD_SIZE=30MB` < `CLIENT_MAX_SIZE=50MB`，per-file 检查在请求上限前生效；文件名去路径组件；base64 CTE 解码 |
| 飞书身份 | WebSocket 模式 SDK 不校验发送者，靠 `allow_from` 白名单兜底；`["*"]` 时告警 |
| Gateway | 非回环绑定且未设 `_api_key` → 启动直接 fail-secure 报错；`MAX_CONCURRENT_AGENT_RUNS=20` 防成本滥用 |

> 公开/多用户部署前，**务必**配置 `allowed_commands` 与显式 `allow_from`。详见 [Gateway 架构](docs/presentations/gateway-architecture.html)。

---

## 🧩 二次开发

因为薄，所以好改。三件事覆盖绝大多数定制：

**1. 换垂类** —— 只换 prompt + 工具配置，不动核心：

```
config/prompts/roles/your_role.md   # 角色 prompt（身份 + 行为准则）
config/roles/your_role.yaml         # 工具白名单（WHAT）
```

**2. 加一个工具** —— 继承 `BaseTool`，实现 `name` / `description` / `parameters` / `execute`，丢进 `capabilities/tools/builtin/extensions/`，自动发现注册。

**3. 接一个 Channel** —— 继承 `BaseChannel`，实现 `start` / `send` / 消息解析，在 `config.json` 的 `channels` 注册。

所有 prompt 都是 Markdown 模板，通过 `{{placeholder}}` 组装（workspace / tools / skills / memory / bia）。

---

## ⚙️ 配置

环境变量用 `${VAR_NAME}` 注入 `config/config.json`：

```json
{
  "llm": {
    "model": "MiniMax-M3",
    "api_key": "${MINIMAX_API_KEY}",
    "api_base": "https://api.minimaxi.com/v1"
  },
  "workspace": { "sandbox": true },
  "allowed_commands": [],          // OPT-IN：留空=不启用白名单，公开部署前请配
  "team":    { "max_concurrent": 5, "max_attempts": 3, "max_questions": 3 },
  "memory":  { "max_memory_tokens": 3000, "max_history_entries": 100 }
}
```

完整字段见 [docs/guides/tools-guide.md](docs/guides/tools-guide.md)。

---

## 🧪 测试

```bash
pytest tests/ -q          # 469 tests
```

---

## 📚 文档

| 类型 | 入口 |
|------|------|
| 架构总览（推荐入门） | [docs/](docs/README.md) · [package 架构](docs/package/Capricorn/README.md) · [架构演示](docs/presentations/architecture-overview.html) |
| 模块文档 | [01-core](docs/package/Capricorn/01-core/README.md) · [02-agent](docs/package/Capricorn/02-agent/README.md) · [03-capabilities](docs/package/Capricorn/03-capabilities/README.md) · [04-memory](docs/package/Capricorn/04-memory/README.md) · [06-teams](docs/package/Capricorn/06-teams/README.md) · [07-cron](docs/package/Capricorn/07-cron/README.md) · [08-gateway](docs/package/Capricorn/08-gateway/README.md) · [09-channels](docs/package/Capricorn/09-channels/README.md) |
| 使用指南 | [飞书接入](docs/guides/feishu-setup.md) · [工具完全参考](docs/guides/tools-guide.md) · [工具对比](docs/guides/tools-comparison.md) · [Git 流程](docs/guides/git-guide.md) · [本地 LLM 迁移](docs/guides/migrate-to-local-llm.md) |
| 功能文档 | [并发模型](docs/features/concurrency-model.md) · [文件上传](docs/features/file-upload.md) · [SSE 流式](docs/features/streaming.md) · [存储架构](docs/features/storage-architecture.html) · [BaseTool vs BaseWorkflow](docs/features/adr-001-basetool-vs-baseworkflow.md) |
| 演示 | [Agent Teams](docs/presentations/agent-teams.html) · [Gateway 架构](docs/presentations/gateway-architecture.html) · [Channel](docs/presentations/channels.html) |
| 历史 | [planning.md](docs/planning.md)（优化计划 / 已知问题 / 版本变更记录） |

---

## 🗺️ Roadmap

- 🌐 **更多 Channel** —— 微信 / QQ / Telegram / Discord
- 🔧 **更多 builtin 工具** —— 浏览器、代码执行沙箱
- 🧠 **深度自进化** —— bia 规则结构化 + 效果量化
- 📦 **包分发** —— pip install 一键接入垂类

> 欢迎开 Issue / PR。

---

## 📋 版本历史

| 版本 | 主题 |
|------|------|
| v0.3.0 | 安全基线（exec 白名单注入防护 + 上传 per-file 检查 + 飞书身份告警）+ spawn 状态机瘦身（7 态→5 态） |
| v0.2.12 | 飞书 Channel（WebSocket 长连接 + 图片/表情接收 + Channel Prompt）+ Cron 源路由（结果推回来源 Channel）+ Config 清理 |
| v0.2.11 | SSE 断连后台执行 + 进度持久化 + sandbox 统一 + config 简化 |
| v0.2.10 | glob/grep 搜索工具 + read_file offset/limit + 代码简化清理 |
| v0.2.9 | SSE 流式事件 + Tasklist 工具 + 指数退避重试 |
| v0.2.8 | Memory 优化（整合逻辑重构、配置调优） |
| v0.2.7 | 文件上传 + 图片多模态 + 安全修复 |
| v0.2.6 | 简化 LLM 约束 + BIA/memory 上限管理 |
| v0.2.5 | BIA / Team / Cron / Quality 工具 + 代码简化清理 |
| v0.2.4 | scheduler + cron prompt 调整 |
| v0.2.3 | gateway/notification/scheduler + 文档生成能力（minimax-pdf/docx） |
| v0.2.2 | builtin tools extensions 扩展 |
| v0.2.1 | skills 子系统调整 |
| v0.2.0 | 早期重构（exec/file tools + mcp client） |
| v0.1.0 | 初始版本 — 完整脚手架（agent + capabilities + skills + tools） |

---

## 📄 License

MIT
