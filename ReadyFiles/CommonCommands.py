from OWCP4b2 import PluginBase, Command, CommandContext, CommandScope
from typing import List
import random

class CommonAdminCommand(Command):
    """
    一个内置的、处理通用管理员指令的命令插件。

    它提供了一组基础的机器人控制功能，如暂停、恢复和关闭，
    并为其他命令插件提供了一个可参考的实现范例。
    """
    def __init__(self, description: str = "内置的通用管理员指令集"):
        """初始化通用管理员命令。

        默认作用域为 ADMIN_DIRECT，确保只有管理员在私聊时才能触发。

        Args:
            description: 插件的描述。
        """
        super().__init__(description, scope=CommandScope.ADMIN_DIRECT)

        # (设计模式) 使用“命令分派”字典，替代冗长的 if/elif 链条。
        # 将命令关键字映射到对应的处理方法。
        self.command_handlers = {
            # 命令关键字 -> (处理函数, 帮助说明)
            "help": (self._handle_help, "[Level 0] 显示此帮助菜单"),
            "pause": (self._handle_pause, "[Level 0] 暂停机器人所有响应"),
            "resume": (self._handle_resume, "[Level 0] 恢复机器人所有响应"),
            "end": (self._handle_end, "[Level 1] 安全关闭机器人程序"),
            # 未来新增命令，只需在此处添加
        }

    async def execute(self, controller: 'LoopController', driver: 'WxDriver', context: 'CommandContext'):
        """
        解析并执行管理员指令。
        """
        original_content: str = context.msg.content.strip()
        
        if not original_content.startswith("/"):
            return  # 不是一个有效的命令前缀

        command_body = original_content.lstrip("/")
        if not command_body:
            return  # 用户只输入了一个 "/"
        
        # 使用 shlex.split 可以更健壮地处理带引号的参数，但对于简单场景 split() 足够
        parts = command_body.split(" ")
        command_key = parts[0].lower()
        args = []
        if len(parts) > 1:
            args = parts[1:]
        print(args)
        # 从分派字典中获取对应的处理函数
        handler_tuple = self.command_handlers.get(command_key)

         # 如果找到了处理函数，则调用它
        if handler_tuple:
            handler, _ = handler_tuple
            await handler(controller, driver, context, args)
        else:
            pass
            #await driver.quote(context.msg, f"未知指令: '{command_key}'\n发送 /help 查看可用指令。")

    # --- 命令处理函数 (Command Handlers) ---

    async def _handle_help(self, controller: 'LoopController', driver: 'WxDriver', context: 'CommandContext', args: List[str]):
        """处理 /help 指令，动态生成帮助文本。"""
        
        # 自动从 command_handlers 构建帮助文本
        help_items = ["--- 机器人管理员帮助 ---"]
        for command, (_, description) in self.command_handlers.items():
            help_items.append(f"▫️ /{command} - {description}")
            
        help_text = "\n".join(help_items)
        await driver.send_text(context.listen_object.name, help_text)

    async def _handle_pause(self, controller: 'LoopController', driver: 'WxDriver', context: 'CommandContext', args: List[str]):
        """处理 /pause 指令。"""

        try:
            await controller.pause_loop()
            await driver.quote(context.msg, "*监听循环已暂停*")
        except Exception as e:
            await driver.quote(context.msg, f"!暂停监听循环失败: {e}")

    async def _handle_resume(self, controller: 'LoopController', driver: 'WxDriver', context: 'CommandContext', args: List[str]):
        """处理 /resume 指令。"""

        try:
            await controller.resume_loop()
            await driver.quote(context.msg, "*监听循环已恢复*")
        except Exception as e:
            await driver.quote(context.msg, f"!恢复监听循环失败: {e}")

    async def _handle_end(self, controller: 'LoopController', driver: 'WxDriver', context: 'CommandContext', args: List[str]):
        """处理 /end 指令，包含权限检查。"""
        if context.admin_level < 1: 
            await driver.quote(context.msg, f"你的权限不足，无法执行`end`操作")
            return
        try:
            await controller.end_loop()
            await driver.quote(context.msg, "*监听循环已关闭*")
        except Exception as e:
            await driver.quote(context.msg, f"!关闭监听循环失败: {e}")


