---
name: document_management
description: 文档管理技能 - 创建、编辑和管理结构化文档
capabilities:
  - create_document
  - read_file
  - write_file
always: false
---

# 文档管理技能

你具备文档创建、编辑和管理能力，可以自动处理文档格式化和模板生成。

## 可用 Capabilities

### create_document
创建结构化文档，自动处理模板和格式化。

**参数：**
- `title`: 文档标题（必需）
- `content`: 文档内容（必需）
- `path`: 保存路径（可选，默认为 ./documents/{title}.md）
- `author`: 作者名称（可选）
- `tags`: 标签列表（可选）

**示例：**
```
create_document(
  title="项目报告",
  content="本项目已完成所有里程碑...",
  author="张三",
  tags=["报告", "项目"]
)
```

### read_file
读取文件内容。

**参数：**
- `path`: 文件路径（必需）

### write_file
写入文件内容。

**参数：**
- `path`: 文件路径（必需）
- `content`: 文件内容（必需）

## 使用场景

1. **创建项目文档**
   - 自动添加元数据（作者、时间戳、标签）
   - 统一的文档格式
   - 自动创建目录结构

2. **批量文档管理**
   - 读取多个文档
   - 批量更新内容
   - 文档格式转换

3. **文档模板应用**
   - 使用预定义模板
   - 自动填充变量
   - 生成标准化输出

## 最佳实践

1. 使用 `create_document` 而非 `write_file` 创建文档，以获得统一的格式和元数据
2. 为文档添加标签，便于后续搜索和分类
3. 指定 `author` 字段，方便追溯文档创建者
4. 使用相对路径，确保文档可移植性

## 注意事项

- 文档路径自动创建，无需手动创建父目录
- 元数据使用 YAML frontmatter 格式
- 文档默认保存为 Markdown 格式
- 时间戳自动生成，格式为 `YYYY-MM-DD HH:MM:SS`
