"""一个轻量级、异步、插件化的Python微信机器人框架"""

__version__ = "0.1.0"  

from .core import (
    # 核心循环
    ListenLoop,
    
    # 监听对象
    ListenObject,
    Admin,
    Group,
    Friend,
    
    # 驱动和控制器
    WxDriver,
    LoopController,
    
    # 插件基类
    PluginBase,
    OpeningUp,
    Command,
    MsgFilter,
    MsgResponser,
    
    # 辅助类型
    CommandScope,
    CommandContext,
    ListenObjectType,
    MsgType
)

# 从插件模块导出官方插件，方便用户直接使用
from .plugins.common_commands import CommonAdminCommand
from .plugins.common_responsers import ChatGPTResponser
