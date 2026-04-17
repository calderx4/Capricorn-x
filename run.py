#!/usr/bin/env python3
"""
Run - CLI 交互界面

职责：
- 命令行交互界面
- 会话管理
- 配置加载
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from agent.executor import CapricornAgent
from config.settings import Config
from loguru import logger


class CapricornCLI:
    """CLI 交互界面"""

    def __init__(self, config_path: str = "config/config.json"):
        """
        初始化 CLI

        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path
        self.config = None
        self.agent = None

    async def start(self):
        """启动 CLI"""
        print("🚀 Capricorn Agent 启动中...")

        try:
            # 加载配置
            self.config = Config.load(self.config_path)
            logger.info(f"Configuration loaded from {self.config_path}")

            # 初始化 Agent
            self.agent = await CapricornAgent.create(self.config, self.config_path)

            print("✓ Agent 已就绪")
            print("💡 输入 'exit' 或 'quit' 退出，'help' 查看帮助\n")

            # 交互循环
            await self._interaction_loop()

        except FileNotFoundError as e:
            print(f"❌ 错误: 配置文件未找到 - {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Startup failed: {e}")
            print(f"❌ 启动失败: {e}")
            sys.exit(1)

    async def _interaction_loop(self):
        """交互循环"""
        while True:
            try:
                user_input = input("👤 You: ").strip()

                if not user_input:
                    continue

                # 命令处理
                if user_input.lower() in ('exit', 'quit'):
                    await self._shutdown()
                    print("👋 再见！")
                    break

                if user_input.lower() == 'help':
                    self._show_help()
                    continue

                if user_input.lower() == 'clear':
                    self._clear_screen()
                    continue

                # 调用 Agent
                response = await self.agent.chat(user_input)
                print(f"\n🤖 Assistant: {response}\n")

            except KeyboardInterrupt:
                print("\n")
                await self._shutdown()
                print("👋 再见！")
                break
            except Exception as e:
                logger.error(f"Error in interaction: {e}")
                print(f"\n❌ 错误: {e}\n")

    async def _shutdown(self):
        """清理资源"""
        if self.agent:
            await self.agent.cleanup()

    def _show_help(self):
        """显示帮助"""
        print("""
📖 可用命令：
  - exit/quit: 退出程序
  - help: 显示帮助
  - clear: 清空屏幕

💡 使用提示：
  - 直接输入问题与 Agent 对话
  - Agent 会自动调用相应的工具和技能
        """)

    def _clear_screen(self):
        """清空屏幕"""
        import os
        os.system('clear' if os.name == 'posix' else 'cls')


def main():
    """入口函数"""
    # 配置日志
    logger.remove()  # 移除默认处理器
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO"
    )

    # 启动 CLI
    cli = CapricornCLI()
    asyncio.run(cli.start())


if __name__ == "__main__":
    main()
