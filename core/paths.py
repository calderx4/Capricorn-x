"""
Paths - 项目路径常量

所有模块通过这里获取路径，不要各自用 Path(__file__).parent.parent 推算。

目录结构：
  Capricorn-x/            ← PROJECT_ROOT
  ├── agent/              ← AGENT_DIR
  ├── capabilities/       ← CAPABILITIES_DIR
  ├── config/             ← CONFIG_DIR
  ├── core/               ← CORE_DIR (本文件所在)
  ├── gateway/            ← GATEWAY_DIR
  └── workspace/
"""

from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CORE_DIR.parent

CONFIG_DIR = PROJECT_ROOT / "config"
CAPABILITIES_DIR = PROJECT_ROOT / "capabilities"
GATEWAY_DIR = PROJECT_ROOT / "gateway"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"

# 常用子路径
PROMPTS_DIR = CONFIG_DIR / "prompts"
ROLES_DIR = CONFIG_DIR / "roles"
BUILTIN_EXTENSIONS = CAPABILITIES_DIR / "tools" / "builtin" / "extensions"
WORKFLOW_EXTENSIONS = CAPABILITIES_DIR / "tools" / "workflow" / "extensions"
MEMORY_CONSOLIDATION_DIR = WORKFLOW_EXTENSIONS / "memory_consolidation"
