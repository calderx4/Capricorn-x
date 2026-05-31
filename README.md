# Capricorn-x

> v0.2.5 | 原生 Function Calling 驱动的轻量级通用 Agent Runtime

轻量级 Agent Runtime，支持 Cron 定时调度、Agent Teams 协作、垂直领域一键扩展。

---

## 快速开始

```bash
git clone https://github.com/calderx4/Capricorn-x.git
cd Capricorn-x
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# 编辑 .env 填入 API Key

python run.py --mode gateway_with_webui
# 浏览器打开 http://localhost:8080
```

---

## 使用案例

### 1. 文件任务

在 WebUI 中输入"帮我创建一个 Python 项目"，Agent 自动调用 read_file / write_file / exec 等工具完成项目搭建，包括目录结构、配置文件、主程序。

### 2. 批量处理

配置 Cron 定时任务（如每天早上 9 点），Agent 自动汇总项目状态，检查待办、生成报告，通过 SSE 实时推送结果。

### 3. 质量检查

通过 quality_check 工具按维度（正确性、规范性、可维护性等）检查代码质量，发现问题自动记录并可回滚。

---

## 架构设计

### 整体架构

```
用户
  │
  ▼
Capricorn（主 Agent）
  │
  ├── FC 循环       — LLM → tool_calls → execute → repeat
  ├── spawn()       — 派发子 Agent（executor 执行 / verifier 验收）
  └── cron()        — 定时任务，支持角色化配置
```

### 三层记忆

| 记忆层 | 存储位置 | 用途 |
|--------|----------|------|
| 会话记忆 | JSONL 文件 | 单次对话上下文 |
| 长期记忆 | MEMORY.md | Agent 需要始终记住的事实和偏好 |
| 历史摘要 | HISTORY.md | 可搜索的行动历史记录 |

### 角色化设计

角色化将身份、权限、指令三层解耦：

| 层 | 决定 | 位置 |
|----|------|------|
| 身份（WHO）| 行为准则 | prompts/roles/executor.md |
| 权限（WHAT）| 可用工具白名单 | roles/executor.yaml |
| 指令（HOW）| 具体任务内容 | cron prompt / spawn brief |

不同角色使用不同工具集合，executor 负责产出，verifier 负责验收，两者对抗协作提升质量。

### 工具注册

工具统一通过 BaseTool 基类注册，自动发现并加载：

- **内置工具** — 文件读写、命令执行、任务管理等
- **MCP 工具** — 通过 MCP 协议接入外部服务
- **工作流** — 多步编排的复杂任务

---

## 核心能力

| 能力 | 说明 |
|------|------|
| 原生 FC 循环 | LLM → tool_calls → execute，无 ReAct / 无状态机 |
| 三层记忆 | 会话（JSONL）+ 长期（MEMORY.md）+ 历史（HISTORY.md）|
| MCP 协议 | stdio / SSE 接入外部服务（搜索、图像理解等）|
| 工具系统 | 文件、命令、任务、质量、变更日志等 |
| 技能系统 | 按需加载领域专属技能 |
| Gateway API | HTTP + SSE 实时推送，支持多会话 |

---

## 配置

环境变量用 `${VAR_NAME}` 注入：

```json
{
  "llm": {
    "model": "MiniMax-M2.7",
    "api_key": "${MINIMAX_API_KEY}",
    "api_base": "https://api.minimaxi.com/v1"
  },
  "workspace": { "sandbox": true },
  "verticals": ["default"]
}
```

---

## 测试

```bash
pytest tests/ -q
```

---

## License

MIT
