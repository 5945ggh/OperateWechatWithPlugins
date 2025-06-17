from __future__ import annotations

import time, datetime, logging, logging.handlers, sys, asyncio, os
from typing import Optional, Dict, List, Tuple, NamedTuple, Union, Literal, Any, Sequence, Type, TypeVar
from collections import deque, defaultdict
from enum import Enum
from abc import ABC, abstractmethod

from wxauto import WeChat
from wxauto.elements import Message, SysMessage, TimeMessage, SelfMessage, FriendMessage, RecallMessage, ChatWnd
from WxTaskQueue import task_queue, WXTask, wxauto_worker

def setup_logging(
    log_level: int = logging.INFO, 
    log_to_file: bool = True, 
    log_filename: str = f'robot{datetime.datetime.now().strftime("%Y%m%d")}.log'
):
    """
    配置全局日志记录器. 

    Args:
        log_level: 控制台输出的日志级别. 
        log_to_file: 是否将日志写入文件. 
        log_filename: 日志文件的名称. 
    """
    # 1. 创建一个根日志记录器
    # 使用 getLogger() 而不是 getLogger(__name__) 来获取根记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)  # 将根记录器的级别设置为最低(DEBUG), 以捕获所有级别的日志

    # 2. 定义日志格式
    # 我们定义两种格式：一个详细的给文件, 一个简洁的给控制台
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    file_formatter = logging.Formatter(
        '%(asctime)s - [%(name)s] - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)'
    )

    # 3. 创建并配置控制台处理器 (StreamHandler)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)  # 控制台只显示 info 及以上级别的日志
    console_handler.setFormatter(console_formatter)

    # 清除任何可能已经存在的处理器, 避免重复输出
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # 将控制台处理器添加到根记录器
    root_logger.addHandler(console_handler)

    # 4. (可选) 创建并配置一个带轮换的文件处理器 (RotatingFileHandler)
    if log_to_file:
        # 使用 RotatingFileHandler 可以防止日志文件无限增长
        # maxBytes=5*1024*1024 表示每个文件最大5MB
        # backupCount=3 表示保留最近的3个日志文件
        file_handler = logging.handlers.RotatingFileHandler(
            log_filename, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)  # 文件中记录所有 DEBUG 及以上级别的日志
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    logging.info("日志系统配置完成. 控制台级别: %s, 文件日志: %s", 
                 logging.getLevelName(log_level), 
                 "启用" if log_to_file else "禁用")


# 定义辅助类型
class ListenObjectType(str, Enum): 
    """定义监听对象的类型常量. """
    ADMIN = "admin"
    GROUP = "group"
    FRIEND = "friend"

class MsgType(str, Enum):
    """定义消息的类型常量, 与 wxauto 的消息类型保持一致. """
    SYS = "sys"
    TIME = "time"
    RECALL = "recall"
    SELF = "self"
    FRIEND = "friend"


# 消息历史类
class MessageHistory():
    """
    一个高效、定长的消息历史记录器. 

    该类基于 collections.deque 实现, 提供了添加、获取和清除消息的线程安全操作, 
    并支持动态调整历史记录的最大容量. 

    Attributes:
        max_size (int): 能够存储的最大消息数量. 
    """
    def __init__(self, max_size:int):
        """
        初始化消息历史记录器. 

        Args:
            max_size: 历史记录的最大容量, 必须为正整数. 
        
        Raises:
            ValueError: 如果 max_size 不是一个正整数. 
        """
        if max_size<=0:
            raise ValueError("max_size must be a positive integer")
        self._messages: deque[Message] = deque(maxlen=max_size)

    @property
    def max_size(self) -> int:
        """获取或设置历史记录的最大容量. """
        return self._messages.maxlen

    @max_size.setter
    def max_size(self, new_size: int):
        if new_size <= 0:
            raise ValueError("'new_size' must be a positive integer.")
        if new_size != self._messages.maxlen:
            self._messages = deque(self._messages, maxlen=new_size)
    
    def add(self, msg: Message) -> None:
        """
        向历史记录中添加一条新消息. 
        
        如果历史记录已满, 最老的一条消息将被自动丢弃. 

        Args:
            msg: 要添加的 Message 对象. 
        """
        self._messages.append(msg)

    def add_many(self, msgs: Sequence[Message]) -> None:
        """
        批量添加多条消息. 

        Args:
            msgs: 一个包含 Message 对象的可迭代序列 (如 list, tuple). 
        """
        self._messages.extend(msgs)
    
    def get_all(self) -> List[Message]:
        """
        获取历史记录中所有消息的列表拷贝. 

        Returns:
            一个包含所有 Message 对象的新列表. 
        """
        return list(self._messages)

    def clear(self, num: Optional[int] = None) -> int:
        """
        从历史记录的开头（最老的消息）清除指定数量的消息. 

        Args:
            num: 要清除的消息数量. 
                 - 如果为 None 或大于等于当前总数, 将清除所有消息. 
                 - 如果为 0 或负数, 则不执行任何操作. 

        Returns:
            实际被清除的消息数量. 
        """
        original_len = len(self._messages)
        if num is None or num >= original_len:
            self._messages.clear()
            return original_len
        if num <= 0:
            return 0
        
        for _ in range(num):
            self._messages.popleft()
        
        return num
    
    def __len__(self) -> int:
        """返回当前存储的消息数量. """
        return len(self._messages)

    def __repr__(self) -> str:
        """提供一个清晰的、可调试的类表示. """
        return f"<{self.__class__.__name__}(size={len(self)}, max_size={self.max_size})>"
    

# 监听对象类
class ListenObject(ABC):
    """
    所有监听对象的抽象基类 (Abstract Base Class). 

    它定义了一个监听对象（如好友、群聊）所需的核心属性和行为, 
    包括身份信息、消息历史记录和状态控制. 

    Attributes:
        name (str): 监听对象的唯一标识名 (通常是微信备注名). 
    """
    def __init__(self, name:str, objtype:ListenObjectType, savepic:Literal[1,0]|bool = False, savevoice:Literal[1,0]|bool = False, savefile:Literal[1,0]|bool = False, max_msgs:int = 100):
        """
        初始化一个监听对象. 

        Args:
            name: 监听对象的微信备注名称, 不能为空. 
            objtype: 监听对象的类型 (Admin, Group, or Friend). 
            savepic: 是否自动保存该对象发送的图片. 
            savevoice: 是否自动保存该对象发送的语音. 
            savefile: 是否自动保存该对象发送的文件. 
            max_msgs: 消息历史记录的最大容量. 

        Raises:
            ValueError: 如果 name 为空或 max_msgs 不是正整数. 
            TypeError: 如果 objtype 不是 ListenObjectType 的实例. 
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError("`name` cannot be empty or just whitespace.")
        if not isinstance(objtype, ListenObjectType):
            raise TypeError("`objtype` must be an instance of ListenObjectType Enum.")
        if not isinstance(max_msgs, int) or max_msgs <= 0:
            raise ValueError("`max_msgs` must be a positive integer.")

        self.name: str = name.strip()
        self._type: ListenObjectType = objtype
        self._savepic: bool = bool(savepic)
        self._savevoice: bool = bool(savevoice)
        self._savefile: bool = bool(savefile)
        self.messages: MessageHistory = MessageHistory(max_msgs)
        self._paused: bool = False

        logging.info(f"<{self._type.name.capitalize()} '{self.name}'> has been created.")

    @property
    def type(self)->ListenObjectType:
        """获取监听对象的类型"""
        return self._type
    
    @property
    def savepic(self)->bool:
        """是否保存图片"""
        return self._savepic
    
    @property
    def savevoice(self)->bool:
        """是否保存语音"""
        return self._savevoice
    
    @property
    def savefile(self)->bool:
        """是否保存文件"""
        return self._savefile
    
    @property
    def max_msgs(self) -> int:
        """获取或设置消息历史的最大容量. """
        return self.messages.max_size
    
    @max_msgs.setter
    def max_msgs(self, value: int) -> None:
        self.messages.max_size = value
    
    def get_messages(self) -> List[Message]:
        """获取此对象所有历史消息的列表拷贝. """
        return self.messages.get_all()
  
    def add_msg(self, msg: Message) -> None:
        """向消息历史中添加一条消息. """
        self.messages.add(msg)

    def add_msgs(self, msgs: Sequence[Message]) -> None:
        """
        批量添加多条消息.
        """
        self.messages.add_many(msgs)

    def clear_msg(self, num: Optional[int] = None) -> int:
        """
        从历史记录的开头（最老的消息）清除指定数量的消息. 

        Args:
            num: 要清除的消息数量. 
                 - 如果为 None 或大于等于当前总数, 将清除所有消息. 
                 - 如果为 0 或负数, 则不执行任何操作. 

        Returns:
            实际被清除的消息数量. 
        """
        return self.messages.clear(num)
    
    def pause(self)->None:  
        """暂停对该对象的监听, 停止除Command以外的其他plugin的响应"""
        self._paused = True
    
    def resume(self)->None:  
        """恢复对该对象的监听."""
        self._paused = False
    
    def is_paused(self) -> bool:  
        """判断该对象是否处于暂停状态. """
        return self._paused
    
    def __repr__(self) -> str:
        """(可调试性) 提供一个清晰的、可调试的类表示. """
        status = "Paused" if self._paused else "Active"
        return (f"<{self.__class__.__name__}(name='{self.name}', "
                f"status={status}, msgs={len(self.messages)})>")
    

class Admin(ListenObject):
    """代表一个管理员用户. """
    def __init__(self, name:str, savepic:Literal[1,0] = 0, savevoice:Literal[1,0] = 0, savefile:Literal[1,0] = 0, max_msgs:int = 50, level:Optional[int] = 0):
        """
        Args:
            name: 监听对象的微信备注名(优先)或微信名
            savepic: 是否保存图片
            savevoice: 是否保存语音
            savefile: 是否保存文件
            level: 管理员级别(开发者可以在后续Command类的实现中自行处理级别相关的逻辑, 这里不做要求)
        """
        super().__init__(name, ListenObjectType.ADMIN, savepic, savevoice, savefile, max_msgs)
        self.level = level


class Group(ListenObject):
    """代表一个被监听的群聊. """
    def __init__(self, name:str, savepic:Literal[1,0] = 0, savevoice:Literal[1,0] = 0, savefile:Literal[1,0] = 0, max_msgs:Optional[int] = 200, group_managers:Optional[Dict[str, int]] = None):
        """
        Args:
            name: 监听对象的微信备注名称
            savepic: 是否保存图片
            savevoice: 是否保存语音
            savefile: 是否保存文件
            group_managers: 群管理员字典, 格式为 {"管理员1_name": level, "管理员2_name": level}
            请尽量确保你对群管理员的level定义与Admin中level的定义一致, 后续在Command类的实现中自行控制逻辑
        
        提示: 
            如果添加了群聊备注, 则name属性为备注名称
            群管理员的name为备注名称(如果有)或微信名
            ***群管理员的name永远不应该是其群聊昵称***

        建议将所有监听对象都手动备注, 防止因其更改微信名而引起程序的不可用
        
        特别地, 为防止出现意外情况, 请一定将<群管理员>*独一无二*地备注, 并使用备注名.
        """
        super().__init__(name, ListenObjectType.GROUP, savepic, savevoice, savefile, max_msgs)
        self._group_manager_dict: Dict[str, int] = dict(group_managers) if group_managers is not None else {}
    
    def get_group_manager_dict(self)->Dict[str]:
        """获取群管理员字典的浅拷贝"""
        return self._group_manager_dict.copy()
    
    def is_manager(self, name:str)->bool:
        """判断name是否为群管理员"""
        return name in self._group_manager_dict
    
    def get_manager_level(self, name:str)->Optional[int]:
        """获取name的群管理员级别"""
        return self._group_manager_dict.get(name, None)
    
    def add_group_manager(self, name: str, level: int = 0) -> bool:
        """添加或更新一位群管理员及其等级.
        
        如果添加成功, 返回True; 如果已存在, 则只更新等级并返回False.
        """
        if name in self._group_manager_dict:
            self._group_manager_dict[name] = level # 更新等级
            return False # 表示是更新而非新增
        self._group_manager_dict[name] = level
        return True # 表示是新增
    
    def remove_group_manager(self, name: str) -> bool:
        """移除一位群管理员.
        
        如果成功移除, 返回True; 如果该管理员不存在, 返回False.
        """
        if name in self._group_manager_dict:
            del self._group_manager_dict[name]
            return True
        return False
    

class Friend(ListenObject):
    """代表一个被监听的好友. """
    def __init__(self, name:str, savepic:Literal[1,0] = 0, savevoice:Literal[1,0] = 0, savefile:Literal[1,0] = 0, max_msgs:int = 100):
        super().__init__(name, ListenObjectType.FRIEND, savepic, savevoice, savefile, max_msgs)


class ListenObjectManager:
    """
    一个纯粹的、协程安全的状态管理器, 负责维护所有 ListenObject 的集合. 
    """
    
    def __init__(self):
        self._objects: Dict[str, ListenObject] = {}
        self._lock = asyncio.Lock()

    async def setup_initial_objects(self, initial_objects: List[ListenObject]):
        """
        用初始对象列表安全地填充管理器, 会清除所有旧数据. 

        Args:
            initial_objects: 一个包含 ListenObject 实例的列表. 

        Returns:
            一个包含已添加对象的列表拷贝, 用于初始同步. 
        
        Raises:
            ValueError: 如果初始列表中存在重复的 `name`. 
        """
        async with self._lock:
            self._objects.clear()
            for obj in initial_objects:
                if obj.name in self._objects:
                    raise ValueError(f"初始化失败：对象名称 '{obj.name}' 重复. ")
                self._objects[obj.name] = obj
            # 返回所有对象的浅拷贝, 供初始同步使用
            return list(self._objects.values())

    async def add(self, obj: ListenObject) -> bool:
        """
        向管理器中添加一个新的监听对象, 如果名称已存在, 则会覆盖旧的对象. 
        返回 True如果是新添加, False如果是覆盖. 
        """
        async with self._lock:
            is_new = obj.name not in self._objects
            self._objects[obj.name] = obj
            return is_new

    async def remove(self, name: str) -> Optional[ListenObject]:
        """
        从管理器中移除一个监听对象. 
        如果成功移除, 返回被移除的对象；否则返回 None. 
        """
        async with self._lock:
            return self._objects.pop(name, None)

    async def get(self, name: str) -> Optional[ListenObject]:
        """根据名称安全地获取一个监听对象. """
        async with self._lock:
            return self._objects.get(name)
        
    async def get_all_dict(self) -> Dict[str, ListenObject]:
        """安全地获取所有监听对象的字典拷贝. """
        async with self._lock:
            return self._objects.copy()

    async def get_all_list(self) -> List[ListenObject]:
        """安全地获取所有监听对象的列表拷贝. """
        async with self._lock:
            return list(self._objects.values())

    async def __len__(self) -> int:
        """返回当前管理的监听对象数量. """
        async with self._lock:
            return len(self._objects)
        

# Wxauto API 封装
class WxDriver:
    """封装所有wxauto I/O操作的驱动程序. 

    此类是框架与`wxauto`库交互的唯一通道. 它通过将所有UI"写"操作
    (如发送消息)序列化到任务队列中, 从根本上解决了UI自动化的并发安全问题. 
    而"读"操作则可以并发执行以提高效率. 

    Attributes:
        wx (Optional[WeChat]): 底层的wxauto WeChat实例, 在connect()成功后被赋值. 
        sending_delay (float): 每个UI"写"操作后的强制延迟, 用于保障账户安全. 
    """
    _MIN_SENDING_DELAY: float = 0.1  #最小延迟
    def __init__(self, language: Literal['cn', 'cn_t', 'en'] = 'cn', sending_delay = 0.4):
        """初始化WxDriver实例. 

        Args:
            language: 微信客户端的语言. 这会影响`wxauto`查找窗口的方式. 
            sending_delay: 发送消息等UI操作后的延迟（秒）. 为保障账号安全, 
                           不建议设置得过小. 如果设置值低于最小阈值, 
                           将被强制重置为最小阈值. 
        """
        self._language = language
        self.wx: Optional[WeChat] = None
        if sending_delay < self._MIN_SENDING_DELAY:
            logging.warning(
                f"指定的 sending_delay ({sending_delay}s) 低于安全阈值 "
                f"({self._MIN_SENDING_DELAY}s), 已强制重置. "
            )
            self.sending_delay = self._MIN_SENDING_DELAY
        else:
            self.sending_delay = sending_delay
    
    def _check_connected(self) -> None:
        """(健壮性) 检查wx实例是否已连接, 未连接则抛出异常. """
        if not self.wx:
            raise ConnectionError(
                "WxDriver is not connected. Please call `connect()` and ensure "
                "it completes successfully before performing other operations."
            )

    async def connect(self):
        """连接到本地正在运行的微信PC客户端. 

        这是一个阻塞操作, 会在后台线程中运行直到连接成功或失败. 
        必须在调用任何其他方法之前成功执行此方法. 

        Raises:
            ConnectionError: 如果未能找到微信进程或连接失败. 
        """
        logging.info("正在尝试连接到微信客户端...")
        try:
            # 在独立的线程中执行同步的、可能阻塞的wxauto初始化
            self.wx = await asyncio.to_thread(WeChat, self._language)
            if not self.wx.UiaAPI.ProcessId:
                raise ConnectionError("wxauto WeChat object created, but failed to attach to process.")
            
        except Exception as e:
            # 捕获所有可能的初始化异常
            self.wx = None  # 确保连接失败时wx实例为None
            raise ConnectionError(f"连接微信客户端失败: {e}") from e
        
        logging.info("成功连接到微信客户端 (PID: %s)", self.wx.UiaAPI.ProcessId)
        
    # ----- 以下所有方法都是创建任务并入队 -----

    async def sync_object_to_wx(self, obj: ListenObject):
        """【异步任务】请求将一个监听对象同步到wxauto的监听列表. 

        Args:
            obj: 需要被添加到`wxauto`监听的`ListenObject`实例. 
        """
        self._check_connected()
        task = WXTask(
            func=self.wx.AddListenChat,
            kwargs={
                'who': obj.name,
                'savepic': obj.savepic,
                'savevoice': obj.savevoice,
                'savefile': obj.savefile
            }
        )
        await task_queue.put(task)
        logging.info("已提交任务 [AddListenChat] -> %s", obj.name)

    async def remove_object_from_wx(self, name: str):
        """【异步任务】请求从wxauto的监听列表中移除一个对象. 

        Args:
            name: 需要被移除的监听对象的名称. 
        
        Raises:
            ValueError: 如果 `name` 为空字符串. 
        """
        self._check_connected()
        if not name:
            raise ValueError("Cannot remove an object with an empty name.")
        
        task = WXTask(func=self.wx.RemoveListenChat, kwargs={'who': name})
        await task_queue.put(task)
        logging.info("已提交任务 [RemoveListenChat] -> %s", name)
        
    async def send_text(self, who: str, text: str, at: list = None):
        """【异步任务】请求发送一条文本消息. 

        Args:
            who: 消息接收方（好友或群聊）的名称. 
            text: 要发送的文本内容. 
            at: (可选) 在群聊中要@的成员昵称列表. 
        
        Raises:
            ValueError: 如果 `who` 或 `text` 为空字符串. 
        """
        self._check_connected()
        if not who or not text:
            raise ValueError("Receiver 'who' and 'text' content cannot be empty.")
        
        kwargs = {'who': who, 'msg': text}
        if at:
            kwargs['at'] = at
        task = WXTask(func=self.wx.SendMsg, kwargs=kwargs)
        await task_queue.put(task)
        logging.info("已提交任务 [SendMsg] -> %s", who)
        
    async def send_file(self, who: str, file_path: str):
        """【异步任务】请求发送一个文件. 

        Args:
            who: 文件接收方（好友或群聊）的名称. 
            file_path: 要发送的文件的绝对或相对路径. 
        
        Raises:
            ValueError: 如果 `who` 或 `file_path` 为空. 
            FileNotFoundError: 如果在任务入队前, 文件路径不存在. 
        """
        self._check_connected()
        if not who or not file_path:
            raise ValueError("Receiver 'who' and 'file_path' cannot be empty.")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found at path: {file_path}")
        
        task = WXTask(func=self.wx.SendFiles, kwargs={'who': who, 'filepath': file_path})
        await task_queue.put(task)
        logging.info("已提交任务 [SendFiles] -> %s, Path: %s", who, file_path)
    
    async def quote(self, msg: Union[FriendMessage, SelfMessage], content: str) -> None:
        """【异步任务】请求引用一条消息进行回复. 

        Args:
            msg: 要引用的消息对象, 必须是 `FriendMessage` 或 `SelfMessage`. 
            content: 回复的文本内容. 
            
        Raises:
            ValueError: 如果 `content` 为空. 
            TypeError: 如果 `msg` 不是可引用的消息类型. 
        """
        self._check_connected()
        if not content:
            raise ValueError("Quote content cannot be empty.")
        if not isinstance(msg, (FriendMessage, SelfMessage)):
            raise TypeError("Only FriendMessage or SelfMessage objects can be quoted.")
        
        task = WXTask(func=msg.quote, kwargs={'msg': content})
        await task_queue.put(task)
        logging.info("已提交任务 [Quote] -> Quote with message from %s", msg.sender)

    # 注意：获取消息的方法是例外, 它不需要进入队列
    # 因为它只是读取UI状态, 不涉及鼠标操作, 可以并发执行
    async def get_listen_messages(self) -> Dict[ChatWnd, List[Message]]:
        """【直接执行】获取所有被监听会话的新消息. 

        这是一个只读操作, 它会直接执行而无需进入任务队列, 
        因为它不涉及UI修改, 可以安全地并发执行. 

        Returns:
            一个字典, 键是`wxauto.ChatWnd`对象, 值是该会话收到的新消息列表. 
            如果没有新消息, 则返回一个空字典. 
        """
        self._check_connected()
        return await asyncio.to_thread(self.wx.GetListenMessage)
    

class LoopController:
    """一个功能受限的、专用于命令插件的安全接口. 

    此类遵循门面模式（Facade Pattern）, 为插件提供了一组稳定、简洁的API, 
    用于与机器人的核心组件（循环、状态管理器、驱动和插件管理器）进行交互, 

    同时隐藏了内部实现的复杂性, 防止插件直接操作核心状态. 
    """
    def __init__(self,
                 loop: 'ListenLoop',
                 manager: 'ListenObjectManager',
                 driver: 'WxDriver',
                 plugin_manager: 'PluginManager'):
        """初始化 LoopController. 

        Args:
            loop: ListenLoop 的实例. 
            manager: ListenObjectManager 的实例. 
            driver: WxDriver 的实例. 
            plugin_manager: PluginManager 的实例. 
        """
        self._loop = loop
        self._object_manager = manager
        self._driver = driver
        self._plugin_manager = plugin_manager

    # ----- 状态控制指令 (委托给 Loop) -----
    
    async def pause_loop(self) -> None:
        """【指令接口】请求暂停整个机器人的消息响应流程. """
        # 注意: 框架内部应统一使用 logging
        await self._loop.pause_loop()

    async def resume_loop(self) -> None:
        """【指令接口】请求恢复整个机器人的消息响应流程. """
        await self._loop.resume_loop()

    async def end_loop(self) -> None:
        """【指令接口】请求安全地关闭并结束整个机器人程序. """
        await self._loop.end_loop()

    # ----- 对象状态指令 (直接操作 ListenObject) -----
    async def clear_listen_object_msg(self, name: str) -> bool:
        """【指令接口】清空指定名称的监听对象的消息缓存. 

        Args:
            name: 要清空的 ListenObject 的名称. 

        Returns:
            True 如果成功清空, False 如果未找到该名称的对象. 
        """
        if not name:
            logging.warning("清空缓存失败：提供的名称为空. ")
            return False
        
        obj = await self._object_manager.get(name)
        if obj:
            try:
                obj.clear_msg()
                return True
            except Exception as e:
                logging.error(f"清空缓存失败：{e}")
                return False
        else:
            logging.warning(f"清空缓存失败：未找到名为 '{name}' 的监听对象. ")
            return False
        
    async def pause_listen_object(self, name: str) -> bool:
        """【指令接口】暂停对指定名称的监听对象的消息响应. 

        Args:
            name: 要暂停的 ListenObject 的名称. 

        Returns:
            True 如果成功暂停, False 如果未找到该名称的对象. 
        """
        if not name:
            logging.warning("暂停对象失败：提供的名称为空. ")
            return False
        
        obj = await self._object_manager.get(name)
        if obj:
            obj.pause() # ListenObject.pause 是同步的, 所以无需 await
            logging.info(f"⏸已暂停对 '{name}' 的监听. ")
            return True
        
        logging.warning(f"暂停失败：未找到名为 '{name}' 的监听对象. ")
        return False

    async def resume_listen_object(self, name: str) -> bool:
        """【指令接口】恢复对指定名称的监听对象的消息响应. 

        Args:
            name: 要恢复的 ListenObject 的名称. 

        Returns:
            True 如果成功恢复, False 如果未找到该名称的对象. 
        """
        if not name:
            logging.warning("恢复对象失败：提供的名称为空. ")
            return False
        
        obj = await self._object_manager.get(name)
        if obj:
            obj.resume()
            logging.info(f"▶已恢复对 '{name}' 的监听. ")
            return True
        logging.warning(f"恢复失败：未找到名为 '{name}' 的监听对象. ")
        return False

    # ----- 结构变更指令 (协同 Manager 和 Driver) -----

    async def add_listen_object(self, listen_object: ListenObject) -> bool:
        """【指令接口】安全地新增或更新一个监听对象. 

        此操作会先更新内存中的状态, 然后向UI任务队列提交一个同步操作. 

        Args:
            listen_object: 要添加或更新的 ListenObject 实例. 

        Returns:
            True 表示操作请求已成功提交. 
        
        Raises:
            TypeError: 如果传入的 listen_object 不是 ListenObject 的实例. 
        """
        if not isinstance(listen_object, ListenObject):
            raise TypeError("add_listen_object 必须接收一个 ListenObject 实例. ")
        
        logging.info(f"正在处理添加/更新 '{listen_object.name}' 的请求...")
        try:
            # 1. 委托 Manager 更新状态
            await self._object_manager.add(listen_object)
            # 2. 委托 Driver 执行 I/O
            await self._driver.sync_object_to_wx(listen_object)
            logging.info(f"'{listen_object.name}' 已被添加/更新. ")
            return True
        except Exception as e:
            logging.error(f"添加/更新 '{listen_object.name}' 失败：{e}")

    async def remove_listen_object(self, name: str) -> bool:
        """【指令接口】安全地移除一个监听对象. 

        此操作会先更新内存状态, 如果成功, 再向UI任务队列提交一个移除操作. 

        Args:
            name: 要移除的 ListenObject 的名称. 

        Returns:
            True 如果成功移除, False 如果未找到该名称的对象. 
        """
        if not name:
            logging.warning("移除对象失败：提供的名称为空. ")
            return False
        
        logging.info(f"正在处理移除 '{name}' 的请求...")
        # 1. 委托 Manager 更新状态, 并检查对象是否存在
        removed_obj = await self._object_manager.remove(name)

        if removed_obj:
            # 2. 如果对象确实存在并被移除了, 再委托 Driver 执行 I/O
            await self._driver.remove_object_from_wx(name)
            logging.info(f"请求处理完成：'{name}' 已被移除. ")
            return True
        else:
            logging.warning(f"移除失败：未找到名为 '{name}' 的监听对象. ")
            return False
        
    # ----- 插件管理能力 (委托给 PluginManager) -----
    
    async def get_plugin(self, name: str) -> Optional['PluginBase']:
        """【指令接口】根据名称获取一个已注册的插件实例. """
        if not name:
            return None
        return self._plugin_manager.get_plugin(name)

    async def get_all_plugins(self) -> Dict[PluginBase]:
        """[指令接口] 获取所有插件. """
        plugin_dict = {}
        plugin_dict["OpeningUp"] = self._plugin_manager.get_opening_ups()
        plugin_dict["Command"] = self._plugin_manager.get_commands()
        plugin_dict["MsgFilter"] = self._plugin_manager.get_filters()
        plugin_dict["MsgResponser"] = self._plugin_manager.get_responsers()
        plugin_dict["EndingUp"] = self._plugin_manager.get_ending_ups()
        return plugin_dict
    async def get_all_plugins(self) -> Dict[str, 'PluginBase']:
        """
        【指令接口】获取所有已注册插件的字典. 

        返回的字典键是插件名称, 值是插件实例. 此方法是类型无关的, 
        能正确返回所有类型的已注册插件. 

        Returns:
            一个包含所有插件的字典的拷贝. 
        """
        return await self._plugin_manager.get_all_plugins()
    
    async def pause_plugin(self, name: str) -> bool:
        """【指令接口】暂停一个指定的、可暂停的插件. """
        if not name:
            return False
        return self._plugin_manager.pause_plugin(name)

    async def resume_plugin(self, name: str) -> bool:
        """【指令接口】恢复一个指定的、可暂停的插件. """
        if not name:
            return False
        return self._plugin_manager.resume_plugin(name)


## 以下为插件基类
class PluginBase(ABC):
    """所有插件的抽象基类. 

    提供了一个所有插件共享的基础接口, 包括一个可选的描述. 

    Attributes:
        description (Optional[str]): 对插件功能的简短描述. 
    """
    plugin_type = "plugin"
    def __init__(self, description:Optional[str] = None):
        self.description = description or self.__class__.__name__
        self.plugin_type = "plugin"

    @abstractmethod
    async def execute(self, *args, **kwargs):
        """插件的核心执行逻辑. """
        raise NotImplementedError

class OpeningUp(PluginBase):
    """在机器人启动时, 为每个监听对象发送“开场白”的插件基类. """
    plugin_type = "opening_up"

    def __init__(self, description = None):
        super().__init__(description)
        self.plugin_type = "opening_up"

    @abstractmethod
    async def execute(self, listen_object:ListenObject)->Optional[str]:
        """为指定的监听对象生成开场白文本. 

        此方法在机器人主循环开始前, 会为每一个非暂停状态的监听对象调用一次. 

        Args:
            listen_object: 当前正在处理的监听对象. 

        Returns:
            一个包含开场白内容的字符串. 如果返回 None 或空字符串, 则不会为该对象发送消息. 

        Example:
            >>> class WelcomePlugin(OpeningUp):
            ...     def execute(self, listen_object: ListenObject) -> Optional[str]:
            ...         if listen_object.type == ListenObjectType.GROUP:
            ...             return f"{listen_object.name}啊, 我已归来."
            ...         return "{listen_object.name}, 我开始冲浪啦."
        """
        pass
    
class CommandScope(str, Enum):
    """
    定义命令可以被触发的作用域, 旨在提供清晰、无歧义的权限控制. 

    框架会使用此作用域在 ListenLoop 中进行高效的预过滤, 
    仅在满足条件时才调用命令的 `execute` 方法, 从而提升性能并减少插件中的重复代码. 
    """

    # ====================================================================
    # == 精确权限作用域 (Precise Privilege Scopes)
    # ====================================================================

    ADMIN_DIRECT = "admin_direct"
    """严格限定：仅能由 `Admin` 在与机器人的私聊中触发. """

    GROUP_MANAGER = "group_manager"
    """严格限定：仅能由已注册的`群管理员`在其所管理的群聊中触发. """

    # ====================================================================
    # == 组合与扩展作用域 (Combined & Broader Scopes)
    # ====================================================================

    ADMIN_OR_MANAGER = "admin_or_manager"
    """组合权限：可以由 `Admin` 在私聊中触发, 或者由 `群管理员` 在群内触发. 
    这是 `ADMIN_DIRECT` 和 `GROUP_MANAGER` 的并集, 非常适合通用的管理命令. 
    """

    ANYONE_IN_GROUP = "anyone_in_group"
    """公共群组命令：可以由被监听群聊中的`任何成员`触发. 
    非常适合用于查询信息、获取帮助等公开功能. 
    """

    # ====================================================================
    # == 完全开放作用域 (Open Scopes)
    # ====================================================================

    ANY_FRIEND_DIRECT = "any_friend_direct"
    """好友私聊：可以由任何已注册的`Friend`或`Admin`在私聊中触发. 
    （在私聊中, Admin 本质上也是一个特殊的好友）. 
    """

    ANYONE = "anyone"
    """【开发者掌控】终极作用域
    框架将放弃所有预过滤, 将每一条收到的消息都传递给此命令的 `execute` 方法. 
    开发者需要在此方法内部自行实现所有的判断逻辑. 请谨慎使用. 
    """

class CommandContext(NamedTuple): 
    """封装了触发命令时的完整上下文信息. 

    这是一个不可变的数据结构, 作为单个参数传递给命令的 `execute` 方法, 
    以简化方法签名并提供丰富的运行时信息. 

    Attributes:
        is_admin: 消息是否来自一个已注册的 `Admin` 对象. 
        admin_level: 如果是 `Admin`, 其对应的权限等级. 
        is_group_manager: 消息是否来自一个群聊中已注册的群管理员. 
        group_manager_level: 如果是群管理员, 其对应的权限等级. 
        listen_object: 产生此消息的 `ListenObject` 实例. 
        msg: 触发命令的原始 `wxauto.Message` 对象. 
    """
    is_admin: bool
    admin_level: Optional[int]
    is_group_manager: bool
    group_manager_level: Optional[int]
    listen_object: ListenObject # 消息来源的 ListenObject
    msg: Message # 原始消息实例

class Command(PluginBase):
    """处理特定指令的命令插件基类. """
    plugin_type = "command"

    def __init__(self, 
                 description: Optional[str] = None,
                 scope: CommandScope = CommandScope.ADMIN_DIRECT, # 默认为仅限Admin私聊触发
                 ):
        """初始化一个命令插件. 

        Args:
            description: 对该命令功能的描述. 
            scope: 命令的作用域, 决定了谁可以触发此命令. 
        """
        super().__init__(description)
        self.scope = scope
        self.plugin_type = "command"
    @abstractmethod
    async def execute(self, controller: LoopController, driver: WxDriver, context:CommandContext) -> None:
        """
        执行命令的核心逻辑. 

        此方法在 `ListenLoop` 确定一条消息符合此命令的作用域后被调用. 
        命令不受监听对象或主循环的暂停状态影响, 总会被执行. 

        Args:
            controller: 用于与主循环交互的`LoopController`安全接口. 
            driver: 用于执行发送消息等I/O操作的`WxDriver`实例. 
            context: 包含所有相关信息的 `CommandContext` 对象. 
        """
        pass

class MsgFilter(PluginBase):
    plugin_type = "msg_filter"

    """在消息处理流程中, 用于过滤消息的插件基类. 
    使得被过滤的消息不存入ListenObject的消息队列中, 也不进入任何MsgResponser类插件. 
    被过滤的消息仍会进入Command类插件."""
    def __init__(self, description:Optional[str] = None):
        super().__init__(description)
        self._paused: bool = False
        self.plugin_type = "msg_filter"
    def pause(self) -> None:  
        """暂停此`MsgFilter`, 使其暂时失效. """
        self._paused = True
    
    def resume(self) -> None:  
        """恢复此`MsgFilter`, 使其重新生效. """
        self._paused = False
    
    def is_paused(self) -> bool:  
        """判断该`MsgFilter`是否处于暂停状态"""
        return self._paused

    @abstractmethod
    def execute(self, listen_object:ListenObject, msg:Message) -> bool:
        """
        根据消息内容和来源, 判断是否应放行此消息. 

        多个过滤器会按注册顺序依次执行. 只要有一个活动的过滤器返回 `False`, 
        该消息就会被立即拦截, 不再进入后续的`MsgFilter`和`MsgResponser`. 

        Args:
            listen_object: 消息来源的 `ListenObject` 实例. 
            msg: 正在被处理的 `wxauto.Message` 对象. 

        Returns:
            bool: 返回 `True` 表示消息通过过滤, `False` 表示拦截. 

        Example:
            >>> class KeywordFilter(MsgFilter):
            ...     def execute(self, listen_object: ListenObject, msg: Message) -> bool:
            ...         if "广告" in msg.content:
            ...             return False  # 拦截包含"广告"的消息
                        if msg.type == MsgType.SYS:
            ...             return False  # 拦截系统消息
            ...         if msg.content == "[动画表情]":
            ...             return False  # 拦截动画表情
            ...         return True   # 其他消息一律放行
        """
        pass
    
class MsgResponser(PluginBase):
    plugin_type = "msg_responser"
    """用于对通过过滤的消息进行响应的插件基类. """
    def __init__(self, description:Optional[str] = None):
        super().__init__(description)
        self._paused: bool = False
        self.plugin_type = "msg_responser"
    def pause(self)->None:  
        """暂停该MsgResponser"""
        self._paused = True
    
    def resume(self)->None:  
        """恢复该MsgResponser"""
        self._paused = False
    
    def is_paused(self) -> bool:  
        """判断该MsgResponser是否处于暂停状态"""
        return self._paused
        
    @abstractmethod
    async def execute(self, 
                      driver:WxDriver, 
                      listen_object:ListenObject, 
                      msg:Message)->Optional[str]:
        """
        (API) 对消息执行具体的响应动作, 不返回任何值. 

        所有响应动作（如发送文本、文件、调用API等）都应通过传入的 `driver`
        对象来完成. 

        Args:
            driver: 用于安全执行I/O操作的 `WxDriver` 实例. 
            listen_object: 消息来源的 `ListenObject` 实例. 
            msg: 正在被处理的 `wxauto.Message` 对象. 

        Example:
            >>> class GreatResponser(MsgResponser):
            ...     async def execute(self, driver: WxDriver, listen_object: ListenObject, msg: Message):
            ...         if listen_object.name == "小红":
            ...             await driver.send_text(listen_object.name, f"啥也别说了我喜欢你.")
            ...         if "回答我!" in msg.content:
            ...             await driver.quote(msg, "啥")
        """
        pass
    
class EndingUp(PluginBase):
    """在机器人通过Command类插件正常关闭前, 为每个监听对象发送“结束语”的插件基类. """
    plugin_type = "ending_up"
    def __init__(self, description = None):
        super().__init__(description)
        self.plugin_type = "msg_responser"
    @abstractmethod
    async def execute(self, listen_object:ListenObject)->Optional[str]:
        """(API) 为指定的监听对象生成结束语文本. 

        此方法在机器人主循环即将结束时, 会为每一个非暂停状态的监听对象调用一次. 

        Args:
            listen_object: 当前正在处理的监听对象. 

        Returns:
            一个包含结束语内容的字符串. 如果返回 `None` 或空字符串, 则不会为该对象发送消息. 
        """
        pass


P = TypeVar('P', bound=PluginBase)
class PluginManager:
    """一个统一、高效且可扩展的插件管理器. 

    负责插件的注册、存储、按名称查找、按类型检索以及生命周期管理
    （如暂停/恢复）. 它采用单一注册表和按类型缓存的策略, 
    以确保数据一致性、高性能和对未来插件类型的良好支持. 
    """
    def __init__(self):
        # 主注册表：通过插件名称快速查找插件实例. 
        self._plugins: Dict[str, PluginBase] = {}
        # 按类型缓存的插件列表：通过插件类型快速获取该类型的所有已注册插件. 
        # 使用 defaultdict 可以简化添加逻辑. 
        self._plugins_by_type: Dict[Type[PluginBase], List[PluginBase]] = defaultdict(list)
    
    def register(self, plugin: PluginBase, name: Optional[str] = None) -> 'PluginManager':
        """注册一个插件实例. 

        如果未提供名称, 则默认使用插件的类名. 插件名称必须唯一. 

        Args:
            plugin: 要注册的插件实例, 必须是 `PluginBase` 的子类. 
            name: (可选) 为插件指定的唯一名称. 

        Returns:
            PluginManager: 当前实例, 支持链式调用. 

        Raises:
            ValueError: 如果插件名称已存在. 
            TypeError: 如果传入的 `plugin` 不是 `PluginBase` 的实例. 
        """
        if not isinstance(plugin, PluginBase):
            raise TypeError(f"Object to register must be an instance of PluginBase, got {type(plugin)}.")

        plugin_name = name or plugin.__class__.__name__

        if plugin_name in self._plugins:
            raise ValueError(f"Plugin name '{plugin_name}' already exists. Please provide a unique name.")

        self._plugins[plugin_name] = plugin
        self._plugins_by_type[plugin.plugin_type].append(plugin) # (核心改进) 直接按类型加入缓存列表

        logging.info(f"插件 '{plugin_name}' (类型: {plugin.plugin_type}) 已成功注册. ")
        return self

    def register_all(self, plugins: List[PluginBase]) -> 'PluginManager':
        """批量注册一组插件. 

        插件将按照列表中的顺序被注册. 

        Args:
            plugins: 一个包含 `PluginBase` 实例的列表. 

        Returns:
            PluginManager: 当前实例, 支持链式调用. 
        """
        for plugin in plugins:
            self.register(plugin)
        
        return self

    def unregister(self, name: str) -> bool:
        """根据名称注销一个插件. 

        Args:
            name: 要注销的插件的名称. 

        Returns:
            True 如果插件成功被注销, False 如果未找到该名称的插件. 
        """
        plugin = self._plugins.pop(name, None)
        if plugin:
            plugin_type = type(plugin)
            if plugin_type in self._plugins_by_type and (plugin in self._plugins_by_type[plugin_type]):
                self._plugins_by_type[plugin.plugin_type].remove(plugin)
                # 如果移除后该类型的列表为空, 从字典中删除该键, 保持清洁
                if not self._plugins_by_type[plugin.plugin_type]:
                    del self._plugins_by_type[plugin.plugin_type]
            logging.info(f"插件 '{name}' (类型: {plugin_type.__name__}) 已成功注销. ")
            return True
        logging.warning(f"尝试注销插件失败：未找到名为 '{name}' 的插件. ")
        return False
    
    # --- 为 ListenLoop 提供的访问器 ---
    def get_plugins_by_type(self, plugin_type: Type[P]) -> List[P]:
        """根据指定的插件类型获取所有已注册的该类型插件. 

        返回的是一个列表的拷贝, 以防止外部修改影响内部状态. 

        Args:
            plugin_type: 插件的类型 (例如, `Command`, `MsgFilter`). 

        Returns:
            一个包含所有匹配类型插件的列表. 如果无此类型插件, 则返回空列表. 
        
        Example:
            >>> command_plugins = manager.get_plugins_by_type(Command)
            >>> for cmd_plugin in command_plugins:
            ...     # Process command_plugin
        """
        # (性能) 直接从缓存中获取, 并返回一个拷贝以确保封装性
        return list(self._plugins_by_type[plugin_type])

    def get_plugins_by_type(self, plugin_type: str) -> List[P]:
        return list(self._plugins_by_type[plugin_type])
    
    def get_commands(self) -> List[Command]:
        return self.get_plugins_by_type("command")

    def get_filters(self) -> List[MsgFilter]:
        return self.get_plugins_by_type("msg_filter")

    def get_responsers(self) -> List[MsgResponser]:
        return self.get_plugins_by_type("msg_responser")

    def get_opening_ups(self) -> List[OpeningUp]:
        return self.get_plugins_by_type("opening_up")

    def get_ending_ups(self) -> List[EndingUp]:
        return self.get_plugins_by_type("ending_up")

    # --- 为 LoopController 提供的管理接口 ---
    def get_plugin(self, name: str) -> Optional[PluginBase]:
        """根据名称获取任何类型的插件实例. 

        Args:
            name: 插件的唯一名称. 

        Returns:
            如果找到, 则返回插件实例；否则返回 None. 
        """
        return self._plugins.get(name)
    
    async def get_all_plugins(self) -> Dict[str, PluginBase]:
        """安全地获取所有已注册插件的字典拷贝. 
        
        Returns:
            一个以插件名称为键, 插件实例为值的字典拷贝. 
        """
        # 由于self._plugins是同步数据结构, 此操作无需异步, 但保持接口为async以备未来扩展
        return self._plugins.copy()
    
    def pause_plugin(self, name: str) -> bool:
        """暂停一个可暂停的插件（如果插件实现了 `pause` 方法）. 

        Args:
            name: 要暂停的插件的名称. 

        Returns:
            True 如果插件被成功暂停, False 如果未找到插件或插件不可暂停. 
        """
        plugin = self.get_plugin(name)
        if plugin and hasattr(plugin, 'pause') and callable(plugin.pause):
            plugin.pause()
            logging.info(f"⏸️ 插件 '{name}' 已暂停. ")
            return True
        logging.warning(f"暂停插件 '{name}' 失败：未找到或插件不支持暂停. ")
        return False
    
    def resume_plugin(self, name: str) -> bool:
        """恢复一个可暂停的插件（如果插件实现了 `resume` 方法）. 

        Args:
            name: 要恢复的插件的名称. 

        Returns:
            True 如果插件被成功恢复, False 如果未找到插件或插件不可恢复. 
        """
        plugin = self.get_plugin(name)
        if plugin and hasattr(plugin, 'resume') and callable(plugin.resume):
            plugin.resume()
            logging.info(f"▶️ 插件 '{name}' 已恢复. ")
            return True
        logging.warning(f"恢复插件 '{name}' 失败：未找到或插件不支持恢复. ")
        return False


class ProcessingMode(str, Enum):
    """定义消息处理的并发模式, 允许在上下文保证和吞吐量之间进行权衡. """

    SERIAL = "serial"
    """
    【上下文最优先】: 严格串行模式. 
    保证所有会话、所有消息都按照接收顺序依次处理. 
    - 优点: 绝对的顺序保证, 不会发生任何回复交错. 
    - 缺点: 总体吞吐量最低. 
    """

    HALF_CONCURRENT = "half_concurrent"
    """
    【推荐/平衡模式】: 会话间并发, 会话内串行. 
    框架会并发处理来自不同聊天会话的任务, 但保证每个会话内部的消息是按顺序处理的. 
    - 优点: 极大地提升了处理多个会话时的吞吐量, 同时保证了单个会话内的上下文连贯性. 
    - 缺点: 来自不同会话的回复消息可能会在UI层面发生交错. 
    """

    CONCURRENT = "concurrent"
    """
    【吞吐量最优先】: 完全并发模式. 
    框架将每条消息都视为独立任务进行并发处理, 适用于无需上下文的场景. 
    - 警告: 无法保证任何消息（包括同一会话内）的回复顺序, 可能导致对话逻辑混乱. 
    - 优点: 理论上的最大吞吐量. 
    """

class ListenLoop:
    """机器人的核心协调器. 

    它驱动异步事件循环, 通过依赖注入的方式集成所有核心组件, 
    并以清晰的逻辑流水线处理所有传入的消息. 
    """
    def __init__(self, 
                 manager: ListenObjectManager = ListenObjectManager(), 
                 driver: WxDriver = WxDriver(),
                 plugin_manager: PluginManager = PluginManager(),
                 processing_mode: ProcessingMode = ProcessingMode.SERIAL,
                 concurrency_limit: int = 8, # 仅在并发模式下生效
                 loop_wait: float = 0.5):
        """初始化核心监听循环. 

        Args:
            manager: 已初始化的 `ListenObjectManager` 实例. 
            driver: 已初始化的 `WxDriver` 实例. 
            plugin_manager: 已初始化的 `PluginManager` 实例. 
            processing_mode: 消息处理模式 (SERIAL 或 CONCURRENT). 
            concurrency_limit: 在 CONCURRENT 模式下的最大并发任务数. 
            loop_wait: 每次轮询消息后的等待时间（秒）. 
        """
        self.object_manager = manager
        self.driver = driver
        self.plugin_manager = plugin_manager
        self.controller = LoopController(self, self.object_manager, self.driver, self.plugin_manager)

        self._processing_mode = processing_mode
        self._concurrency_semaphore: Optional[asyncio.Semaphore] = None
        if self._processing_mode == ProcessingMode.CONCURRENT:
            self._concurrency_semaphore = asyncio.Semaphore(concurrency_limit)
            logging.info(f"已启用并发处理模式, 最大并发数: {concurrency_limit}")
        
        self._loop_wait = max(0.1, loop_wait) # 最小等待时间为 0.1 秒
        self._is_paused = False
        self._should_end = False


    # --- 核心生命周期方法 ---
    async def _run_main_loop(self):
        """内部主循环, 包含核心的轮询和处理逻辑. """
        logging.info("主监听循环已启动... 按 CTRL+C 退出. ")
        while not self._should_end:
            try:
                # 1. 获取所有会话的新消息
                incoming_chats = await self.driver.get_listen_messages()
                if not incoming_chats:
                    await asyncio.sleep(self._loop_wait)
                    continue

                # 2. 将每个会话的所有消息打包成一个“会话级”任务
                chat_level_tasks = []
                for chat, messages in incoming_chats.items():
                    if not messages:
                        continue
                    
                    listen_obj = await self.object_manager.get(chat.who)
                    if not listen_obj:
                        logging.warning(f"收到来自未被管理对象 '{chat.who}' 的消息, 已忽略. ")
                        continue
                    
                    # 将会话处理作为一个独立的协程任务
                    chat_level_tasks.append(
                        self._process_message_batch(listen_obj, messages)
                    )

                # 3. 根据 ProcessingMode 决定如何执行这些“会话级”任务
                if chat_level_tasks:
                    if self._processing_mode == ProcessingMode.SERIAL:
                        # 串行执行每个会话的处理, 保证回复的绝对上下文连续性
                        for task in chat_level_tasks:
                            await task
                    else: # HALF_CONCURRENT 和 CONCURRENT 模式
                        # 并发执行所有会话的处理, 接受不同会话间的回复交错
                        await asyncio.gather(*chat_level_tasks)

                await asyncio.sleep(self._loop_wait)

            except Exception as e:
                logging.error(f"主循环发生未捕获异常: {e}", exc_info=True)
                await asyncio.sleep(2)


    async def _process_one_message(self, listen_obj: ListenObject, msg: Message):
        """
        (核心) 单一消息的处理流水线. 
        在并发模式下, 此方法会使用信号量来限制同时执行的数量. 
        """
        async def process():
            # 步骤A: 执行命令 (不受任何暂停影响)
            try:
                await self._execute_commands(listen_obj, msg)
            except Exception as e:
                logging.error(f"执行命令时出错: {e}", exc_info=True)

            # 步骤B: 检查全局或单个对象的暂停状态
            if self._is_paused or listen_obj.is_paused():
                return

            # 步骤C: 执行消息过滤器
            if not self._execute_filters(listen_obj, msg):
                return  # 消息被过滤

            # 步骤D: 将通过所有过滤器的消息存入历史
            listen_obj.add_msg(msg)

            # 步骤E: 执行消息响应器
            try:
                await self._execute_responsers(listen_obj, msg)
            except Exception as e:
                logging.error(f"执行响应器时出错: {e}", exc_info=True)
        
        # 使用信号量（如果已配置）来包裹整个处理流程
        if self._concurrency_semaphore:
            async with self._concurrency_semaphore:
                await process()
        else:
            await process()
    
    async def _process_message_batch(self, listen_obj: ListenObject, messages: List[Message]):
        """处理单个聊天会话内的一批消息. """
        
        # 根据模式决定会话内的处理方式
        if self._processing_mode == ProcessingMode.CONCURRENT:
            # 【会话内并发】: 为会话内的每条消息创建一个任务并并发执行
            message_level_tasks = [
                self._process_one_message(listen_obj, msg) for msg in messages
            ]
            await asyncio.gather(*message_level_tasks)
        else: # SERIAL 和 HALF_CONCURRENT 模式
            # 【会话内串行】: 保证会话内的消息按顺序处理
            for msg in messages:
                await self._process_one_message(listen_obj, msg)
    
    # --- 插件执行辅助方法 ---

    async def _execute_opening_ups(self):
        """执行所有开场白插件. """
        all_objects = await self.object_manager.get_all_dict()
        plugins = self.plugin_manager.get_opening_ups()

        for obj in all_objects.values():
            if obj.is_paused(): continue
            for plugin in plugins:
                text = await plugin.execute(obj)
                if text:
                    await self.driver.send_text(obj.name, text)
    
    async def _execute_commands(self, listen_obj: ListenObject, msg: Message):
        """执行所有命令插件. """
        is_admin_direct_chat = isinstance(listen_obj, Admin)
        is_group_chat = isinstance(listen_obj, Group)

        sender_is_manager = is_group_chat and listen_obj.is_manager(msg.sender)

        context = CommandContext(
            is_admin= is_admin_direct_chat,
            admin_level = listen_obj.level if is_admin_direct_chat else None,
            is_group_manager = sender_is_manager,
            group_manager_level = listen_obj.get_manager_level(msg.sender) if sender_is_manager else None,
            listen_object = listen_obj,
            msg=msg
        )

        command_plugins = self.plugin_manager.get_commands()
        for plugin in command_plugins:
            scope = plugin.scope
            should_execute = False

            if scope == CommandScope.ANYONE:
                should_execute = True
            elif scope == CommandScope.ADMIN_DIRECT:
                should_execute = context.is_admin
            elif scope == CommandScope.GROUP_MANAGER:
                should_execute = context.is_group_manager
            elif scope == CommandScope.ADMIN_OR_MANAGER:
                should_execute = context.is_admin or context.is_group_manager
            elif scope == CommandScope.ANYONE_IN_GROUP:
                should_execute = is_group_chat
            elif scope == CommandScope.ANY_FRIEND_DIRECT:
                should_execute = listen_obj.type in (ListenObjectType.FRIEND, ListenObjectType.ADMIN)
            
            if should_execute:
                try:
                    await plugin.execute(self.controller, self.driver, context)
                except Exception as e:
                    logging.warning(
                        f"执行命令插件 '{plugin.description}' 时发生异常: {e}", exc_info=True
                    )
    
    def _execute_filters(self, listen_obj: ListenObject, msg: Message) -> bool:
        """如果任何一个活动的过滤器返回False, 则消息被过滤. """
        filters = self.plugin_manager.get_filters()
        return all(
            plugin.execute(listen_obj, msg) 
            for plugin in filters
            if not plugin.is_paused()
        )

    async def _execute_responsers(self, listen_obj: ListenObject, msg: Message):
        """执行所有消息响应插件"""
        responsers = self.plugin_manager.get_responsers()
        for plugin in responsers:
            if plugin.is_paused(): continue
            await plugin.execute(self.driver, listen_obj, msg)
    
    async def _execute_ending_ups(self):
        """执行所有结束语插件. """
        all_objects = await self.object_manager.get_all_list()
        ending_ups = self.plugin_manager.get_ending_ups()
        for obj in all_objects:
            if obj.is_paused(): continue
            for plugin in ending_ups:
                text = await plugin.execute(obj)
                if text:
                    await self.driver.send_text(obj.name, text)
    
    async def _startup_and_run(self, initial_objects: List[ListenObject]):
        """内部的异步方法, 封装了所有启动和运行的逻辑. """
        worker_task = None
        try:
            # 1. 连接微信
            await self.driver.connect()
            
            # 2. 启动核心的UI任务工作者
            #worker_task = asyncio.create_task(wxauto_worker(self, delay=self.driver.sending_delay))

            # 3. 初始化对象管理器并同步到微信

            ###卡住
            objects_to_sync = await self.object_manager.setup_initial_objects(initial_objects)
            logging.info("正在提交初始同步任务...")
            
            for obj in objects_to_sync:
                # 逐个提交UI任务到队列, 此操作本身是非阻塞的
                await self.driver.sync_object_to_wx(obj)
            
            worker_task = asyncio.create_task(wxauto_worker(self, delay=self.driver.sending_delay))

            logging.info("等待所有初始同步任务被执行...")
            await task_queue.join()
            logging.info("✅ 初始同步完成. ")

            # 4. 执行开场白
            await self._execute_opening_ups()

            # 5. 运行核心循环
            await self._run_main_loop()

        finally:
            # 6. 关闭
            logging.info("正在执行收尾程序...")
            await self._execute_ending_ups()
            
            logging.info("等待所有排队的UI任务完成...")
            await task_queue.join()
            
            if worker_task and not worker_task.done():
                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass  # 这是预期的取消行为
            logging.info("wxauto worker 已成功关闭. ")
    
    def launch(self, initial_objects: List[ListenObject]):
        """【用户调用的唯一入口】启动并运行整个机器人应用. 

        此方法会阻塞当前线程, 直到机器人被关闭 (例如, 通过 CTRL+C). 
        它负责处理完整的启动、运行和关闭的生命周期. 

        Args:
            initial_objects: 一个包含初始监听对象的列表. 
        """
        logging.info("正在启动监听循环...")
        #worker_task = None
        try:
            asyncio.run(self._startup_and_run(initial_objects))
        except KeyboardInterrupt:
            logging.info("\n收到用户中断信号 (CTRL+C). ")
        except Exception as e:
            logging.critical(f"!!!监听循环启动或运行时发生致命错误: {e}", exc_info=True)
        finally:
            logging.info("正在关闭监听循环...")
            # 确保即使在启动失败时, 清理逻辑也能被调用
            # (注意: 此处的清理逻辑在 asyncio.run 结束后执行, 在同步上下文中)
            logging.info("监听循环已完全停止. ")

    # --- 状态控制方法 (供 Controller 调用) ---

    async def pause_loop(self):
        if self._is_paused:
            logging.info("主循环已处于暂停状态")
            return
        self._is_paused = True
        logging.info("⏸主循环已暂停")
        
    async def resume_loop(self):
        if not self._is_paused:
            logging.info("主循环已处于运行状态")
            return
        self._is_paused = False
        logging.info("▶主循环已恢复")
        
    async def end_loop(self):
        if self._should_end:
            logging.info("主循环已处于结束状态")
            return
        self._should_end = True
        logging.info("已设置主循环结束标志")
    
    