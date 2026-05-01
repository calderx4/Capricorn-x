---
name: minimax-multimodal
description: >
  MiniMax 多模态内容生成工具箱，通过 mmx CLI 统一调用。
  使用场景：生成图片、视频、语音、音乐、图像理解、文本对话、网页搜索。
  触发词：生成图片、生成视频、文字转语音、TTS、生成音乐、图像识别、看图说话、
  图片描述、OCR、UI 审查、chart 数据提取、object detection、
  image generation、video generation、text to speech、music generation。
  前置条件：npm install -g mmx-cli && mmx auth login --api-key sk-xxxxx
available: true
---

# MiniMax Multimodal Toolkit — Agent Skill Guide

通过 `mmx` CLI 生成图片、视频、语音、音乐，进行图像理解和网页搜索。

## 前置条件

```bash
# 安装
npm install -g mmx-cli

# 认证（持久化到 ~/.mmx/credentials.json）
mmx auth login --api-key sk-xxxxx

# 或每次调用时传入
mmx text chat --api-key sk-xxxxx --message "Hello"
```

区域自动检测，可覆盖：`--region global` 或 `--region cn`。

---

## Agent 调用标志

非交互（agent/CI）场景始终使用：

| 标志 | 用途 |
|---|---|
| `--non-interactive` | 缺少参数时直接失败，不进入交互 |
| `--quiet` | 抑制进度条，stdout 只输出纯数据 |
| `--output json` | 机器可读 JSON 输出 |
| `--async` | 异步任务立即返回 task ID（视频生成） |
| `--dry-run` | 预览 API 请求但不执行 |
| `--yes` | 跳过确认提示 |

---

## 命令参考

### 文本对话 — text chat

```bash
mmx text chat --message <text> [flags]
```

| 标志 | 类型 | 说明 |
|---|---|---|
| `--message <text>` | string, **必填**, 可重复 | 消息文本。加 `role:` 前缀设置角色 |
| `--system <text>` | string | 系统提示 |
| `--model <model>` | string | 模型 ID（默认 `MiniMax-M2.7`） |
| `--max-tokens <n>` | number | 最大 token 数 |
| `--temperature <n>` | number | 采样温度 (0.0, 1.0] |
| `--stream` | boolean | 流式输出 |

```bash
# 单轮
mmx text chat --message "user:什么是 MiniMax?" --output json --quiet

# 多轮
mmx text chat \
  --system "You are a coding assistant." \
  --message "user:用 Python 写 fizzbuzz" \
  --output json
```

---

### 图片生成 — image generate

模型：`image-01`。

```bash
mmx image generate --prompt <text> [flags]
```

| 标志 | 类型 | 说明 |
|---|---|---|
| `--prompt <text>` | string, **必填** | 图片描述 |
| `--aspect-ratio <ratio>` | string | 宽高比，如 `16:9`、`1:1` |
| `--n <count>` | number | 生成数量（默认 1） |
| `--subject-ref <params>` | string | 角色参考：`type=character,image=path-or-url` |
| `--out-dir <dir>` | string | 下载到指定目录 |
| `--out-prefix <prefix>` | string | 文件名前缀（默认 `image`） |

```bash
mmx image generate --prompt "穿宇航服的猫" --output json --quiet

mmx image generate --prompt "Logo" --n 3 --out-dir ./gen/ --quiet
```

---

### 视频生成 — video generate

默认模型：`MiniMax-Hailuo-2.3`。异步任务，默认轮询直到完成。

```bash
mmx video generate --prompt <text> [flags]
```

| 标志 | 类型 | 说明 |
|---|---|---|
| `--prompt <text>` | string, **必填** | 视频描述 |
| `--model <model>` | string | `MiniMax-Hailuo-2.3` 或 `MiniMax-Hailuo-2.3-Fast` |
| `--first-frame <path-or-url>` | string | 首帧图片 |
| `--download <path>` | string | 保存视频到指定文件 |
| `--async` | boolean | 立即返回 task ID |
| `--poll-interval <seconds>` | number | 轮询间隔（默认 5） |

```bash
# 异步：获取 task ID
mmx video generate --prompt "一个机器人。" --async --quiet

# 同步：等待并下载
mmx video generate --prompt "海浪。" --download ocean.mp4 --quiet
```

查询状态：
```bash
mmx video task get --task-id <id> --output json
```

---

### 语音合成 — speech synthesize

默认模型：`speech-2.8-hd`。最大 1 万字符。

```bash
mmx speech synthesize --text <text> [flags]
```

| 标志 | 类型 | 说明 |
|---|---|---|
| `--text <text>` | string | 待合成文本 |
| `--text-file <path>` | string | 从文件读取文本，`-` 表示 stdin |
| `--model <model>` | string | `speech-2.8-hd`、`speech-2.6`、`speech-02` |
| `--voice <id>` | string | 音色 ID（默认 `English_expressive_narrator`） |
| `--speed <n>` | number | 语速倍率 |
| `--format <fmt>` | string | 音频格式（默认 `mp3`） |
| `--out <path>` | string | 保存到文件 |

```bash
mmx speech synthesize --text "你好世界" --out hello.mp3 --quiet
```

---

### 音乐生成 — music generate

模型：`music-2.5`。支持丰富的结构化描述。

```bash
mmx music generate --prompt <text> [--lyrics <text>] [flags]
```

| 标志 | 类型 | 说明 |
|---|---|---|
| `--prompt <text>` | string | 音乐风格描述 |
| `--lyrics <text>` | string | 歌词（含结构标签） |
| `--lyrics-file <path>` | string | 从文件读取歌词 |
| `--vocals <text>` | string | 人声风格，如 `"温暖男中音"` |
| `--genre <text>` | string | 流派：pop、jazz、folk 等 |
| `--mood <text>` | string | 情绪：warm、uplifting、melancholic |
| `--instruments <text>` | string | 乐器：`"吉他, 钢琴"` |
| `--bpm <number>` | number | 精确 BPM |
| `--instrumental` | boolean | 纯音乐（无人声） |
| `--out <path>` | string | 保存到文件 |

至少提供 `--prompt` 或 `--lyrics` 之一。

```bash
# 带歌词
mmx music generate --prompt "轻快流行" --lyrics "啦啦啦..." --out song.mp3 --quiet

# 纯音乐
mmx music generate --prompt "电影配乐，紧张感递增" --instrumental --out bgm.mp3
```

---

### 图像理解 — vision describe

通过 VLM 分析图片。

```bash
mmx vision describe (--image <path-or-url> | --file-id <id>) [flags]
```

| 标志 | 类型 | 说明 |
|---|---|---|
| `--image <path-or-url>` | string | 本地路径或 URL（自动 base64） |
| `--file-id <id>` | string | 已上传文件 ID |
| `--prompt <text>` | string | 关于图片的问题（默认 "描述这张图片"） |

```bash
mmx vision describe --image photo.jpg --prompt "这是什么品种？" --output json
```

### 分析模式提示词

| 模式 | prompt 策略 |
|---|---|
| **描述** | 详细描述图片内容、主体、背景、色彩、构图 |
| **OCR** | 逐字提取所有文本，保留原始结构和格式 |
| **UI 审查** | 以 UI/UX 设计师角度分析：优点、问题、改进建议 |
| **图表提取** | 提取所有数据点、坐标轴标签、趋势摘要 |
| **物体检测** | 列出所有可识别的物体、人物、活动及位置 |

---

### 网页搜索 — search query

```bash
mmx search query --q <query>
```

```bash
mmx search query --q "MiniMax AI" --output json --quiet
```

---

### 配额查询 — quota show

```bash
mmx quota show --output json
```

---

## 工作流示例

```bash
# 图片生成 → 图像理解
URL=$(mmx image generate --prompt "日落" --quiet)
mmx vision describe --image "$URL" --quiet

# 异步视频工作流
TASK=$(mmx video generate --prompt "机器人" --async --quiet | jq -r '.taskId')
sleep 30
mmx video task get --task-id "$TASK" --output json
mmx video download --task-id "$TASK" --out robot.mp4

# 语音 + 音乐组合
mmx speech synthesize --text "旁白" --out narration.mp3 --quiet
mmx music generate --prompt "背景音乐" --instrumental --out bgm.mp3 --quiet
```

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 一般错误 |
| 2 | 参数错误 |
| 3 | 认证错误 |
| 4 | 配额不足 |
| 5 | 超时 |
| 10 | 内容过滤 |

## 参考来源

基于 [MiniMax-AI/skills/minimax-multimodal-toolkit](https://github.com/MiniMax-AI/skills/tree/main/skills/minimax-multimodal-toolkit)（MIT License）。
