from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
import logging, asyncio

@dataclass
class WXTask:
    """封装一个待由 worker 执行的 wxauto UI操作。"""
    func: Callable
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)

# 全局的、唯一的任务队列
task_queue: asyncio.Queue[WXTask] = asyncio.Queue()

async def wxauto_worker(loop: 'ListenLoop', delay: float = 0.5):
    """
    【核心】顺序执行所有wxauto UI任务的唯一工作者。
    它从队列中获取任务，并保证一次只执行一个，从而避免UI操作冲突。
    """
    ###
    while not loop.driver.wx: await asyncio.sleep(0.1)
    wx_instance = loop.driver.wx # 从 WxDriver 获取 wx 实例
    ###
    print(f"✅ 通用 wxauto 任务工作者已启动...")

    while True:
        task = await task_queue.get()

        try:
            # “最后一刻”有效性检查，这个逻辑依然非常有用！
            # 我们可以让它更通用一些
            target_who = task.kwargs.get('who')
            if target_who:
                # 注意: 这里的检查需要访问 ListenObjectManager
                # 我们需要确保 worker 能拿到 manager 的引用
                # 一个简单的方法是通过 loop 实例: loop.manager
                manager = loop.object_manager 
                obj = await manager.get(target_who)
                if not obj:
                    logging.WARNING(f"! 任务被取消：目标对象 '{target_who}' 已不存在于管理器中。")
                    task_queue.task_done() # 标记任务完成
                    continue 

            logging.info(f"正在执行UI任务: {task.func.__name__}...")
            # 核心！在后台线程中顺序执行任务
            await asyncio.to_thread(task.func, *task.args, **task.kwargs)
            logging.info(f"任务 {task.func.__name__} 执行成功。")

        except Exception as e:
            logging.error(f"!!!执行任务 {task.func.__name__} 时发生错误: {e}")
        finally:
            # 标记任务完成，并等待一小段时间，保证账号安全
            task_queue.task_done()
            await asyncio.sleep(delay)