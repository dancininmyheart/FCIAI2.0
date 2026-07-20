"""
增强版翻译任务队列
支持多线程并发处理和异步I/O操作
"""
import asyncio
import threading
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable
import os
import logging
from concurrent.futures import ThreadPoolExecutor
import uuid
import traceback
import weakref
from contextlib import contextmanager

from .thread_pool_executor import thread_pool, TaskType, TaskStatus, Task
from app.utils.timezone_helper import now_with_timezone

# 配置日志记录器
logger = logging.getLogger(__name__)


def _thread_task_outcome(thread_task) -> str:
    if thread_task.status == TaskStatus.CANCELED:
        return "canceled"
    if thread_task.status == TaskStatus.COMPLETED and thread_task.result is True:
        return "completed"
    return "failed"


class TranslationTask:
    """翻译任务类，用于存储任务信息"""

    def __init__(self, task_id: str, user_id: int, user_name: str,
                file_path: str,model:str, task_type: str = 'ppt_translate',
                source_language: str = 'en', target_language: str = 'zh-cn',
                priority: int = 0, annotation_filename: str = None,
                annotation_json: Dict = None, select_page: List[int] = None,
                bilingual_translation: str = 'paragraph_up', 
                enable_text_splitting: str = "False", enable_uno_conversion: bool = True,
                custom_translations: Dict[str, str] = None, **kwargs):
        """
        初始化翻译任务

        Args:
            task_id: 任务ID
            user_id: 用户ID
            user_name: 用户名
            file_path: 文件路径
            task_type: 任务类型 (ppt_translate, pdf_annotate)
            source_language: 源语言
            target_language: 目标语言
            priority: 优先级
            annotation_filename: 注释文件名
            annotation_json: 注释数据（直接传递）
            select_page: 选择的页面列表
            bilingual_translation: 是否双语翻译
            translation_model: 翻译模型 (qwen, deepseek, gpt-4o)
            custom_translations: 自定义翻译词典 {source: target}
            **kwargs: 其他参数
        """
        self.task_id = task_id
        self.user_id = user_id
        self.user_name = user_name
        self.file_path = file_path
        self.task_type = task_type
        self.source_language = source_language
        self.target_language = target_language
        self.priority = priority
        self.annotation_filename = annotation_filename
        self.annotation_json = annotation_json  # 添加注释数据字段
        self.select_page = select_page or []
        self.bilingual_translation = bilingual_translation
        self.model = model
        self.enable_text_splitting = enable_text_splitting
        self.enable_uno_conversion = enable_uno_conversion
        self.custom_translations = custom_translations or {}  # 添加自定义翻译词典

        # PDF注释相关参数
        self.annotations = kwargs.get('annotations', [])
        self.output_path = kwargs.get('output_path', '')
        self.ocr_language = kwargs.get('ocr_language', 'chi_sim+eng')
        self.original_filename = kwargs.get('original_filename', os.path.basename(file_path))
        self.unique_filename = kwargs.get('unique_filename', os.path.basename(file_path))
        self.enable_image_ocr = kwargs.get('enable_image_ocr', False)

        # 状态信息
        self.status = "waiting"  # waiting, processing, completed, failed, canceled
        self.progress = 0  # 0-100
        self.error = None
        self.start_time = None
        self.end_time = None
        self.retry_count = 0

        # 事件通知
        self.event = threading.Event()

        # 任务状态信息
        self.position = 0
        self.created_at = now_with_timezone()
        self.started_at = None
        self.completed_at = None

        # 进度信息
        self.current_slide = 0
        self.total_slides = 0

        # 处理结果
        self.result = None

        # 执行此任务的Thread Task对象
        self.thread_task: Optional[Task] = None

        # 详细日志
        self.logs = []
        self.current_stage = "等待中"
        self.current_operation = "排队等待处理"

        # 获取任务专用的日志记录器
        self.logger = logging.getLogger(f"{__name__}.task.{user_id}")
        self.ledger_progress_callback = kwargs.get('ledger_progress_callback')
        self.ledger_completion_callback = kwargs.get('ledger_completion_callback')
        self.ledger_execution_preflight = kwargs.get('ledger_execution_preflight')
        self.ledger_attempt = kwargs.get('ledger_attempt', 0)
        self.logger.info(f"创建新任务: 用户={user_name}, 文件={os.path.basename(file_path)}, 模型={model}, 词典条目={len(self.custom_translations)}")

class EnhancedTranslationQueue:
    """增强版翻译任务队列，支持多线程并发处理"""

    def __init__(self):
        """初始化翻译队列，但不创建处理器，等待配置"""
        # 默认配置 - 限制最大并发翻译任务为10个
        self.max_concurrent_tasks = 10
        self.task_timeout = 3600  # 1小时
        self.retry_times = 3

        # 任务存储
        self.tasks: Dict[str, TranslationTask] = {}
        self.user_tasks: Dict[int, str] = {}
        self.active_tasks: Dict[str, TranslationTask] = {}

        # 状态控制
        self.initialized = False
        self.running = False
        self.lock = threading.RLock()
        self.task_available = threading.Event()
        self.recycle_stop_event = threading.Event()
        self.recycle_thread = None
        self.app = None
        
        # 线程池健康状态
        self.last_pool_check = time.time()
        self.pool_check_interval = 300  # 5分钟检查一次线程池健康状态
        self.db_recycle_interval = 1800  # 30分钟回收一次数据库连接

        # 日志记录器
        self.logger = logging.getLogger(f"{__name__}.queue")

    def configure(self, max_concurrent_tasks: Optional[int] = None,
                task_timeout: Optional[int] = None,
                retry_times: Optional[int] = None,
                app=None) -> None:
        """
        配置任务队列参数

        Args:
            max_concurrent_tasks: 最大并发任务数
            task_timeout: 任务超时时间（秒）
            retry_times: 任务重试次数
        """
        with self.lock:
            # 更新配置
            if max_concurrent_tasks is not None:
                self.max_concurrent_tasks = max_concurrent_tasks
            if task_timeout is not None:
                self.task_timeout = task_timeout
            if retry_times is not None:
                self.retry_times = retry_times
            if app is not None:
                self.app = app

            self.initialized = True

    @contextmanager
    def _application_context(self):
        """Run worker-owned work in the configured Flask application context."""
        from flask import has_app_context

        if has_app_context():
            yield
            return

        app = self.app
        if app is None:
            from app import create_app

            app = create_app()

        with app.app_context():
            yield

    def add_task(self, user_id: int, user_name: str, file_path: str,model:str,
                task_type: str = 'ppt_translate', source_language: str = 'en',
                target_language: str = 'zh-cn', priority: int = 0,
                annotation_filename: str = None, annotation_json: Dict = None,
                select_page: List[int] = None, bilingual_translation: str = "paragraph_up",
                enable_text_splitting: str = "False", enable_uno_conversion: bool = True,
                custom_translations: Dict[str, str] = None, **kwargs) -> int:
        """
        添加任务到队列

        Args:
            user_id: 用户ID
            user_name: 用户名
            file_path: 文件路径
            task_type: 任务类型 (ppt_translate, pdf_annotate)
            source_language: 源语言
            target_language: 目标语言
            priority: 优先级
            annotation_filename: 注释文件名
            annotation_json: 注释数据（直接传递）
            select_page: 选择的页面列表
            bilingual_translation: 是否双语翻译
            model: 模型类型
            custom_translations: 自定义翻译词典
            **kwargs: 其他参数

        Returns:
            队列位置
        """
        if not self.initialized:
            raise RuntimeError("任务队列未初始化")

        with self.lock:
            # 检查当前活跃任务数量，确保不超过限制
            active_count = len(self.active_tasks)
            waiting_count = len([t for t in self.tasks.values() if t.status == "waiting"])
            total_count = active_count + waiting_count

            if total_count >= self.max_concurrent_tasks:
                self.logger.warning(
                    f"任务队列已满 - 活跃任务: {active_count}, 等待任务: {waiting_count}, "
                    f"最大限制: {self.max_concurrent_tasks}"
                )
                raise RuntimeError(f"任务队列已满，当前有 {total_count} 个任务，最大限制为 {self.max_concurrent_tasks} 个")

            # 生成任务ID
            task_id = f"task_{int(time.time())}_{user_id}"

            # 创建任务对象
            task = TranslationTask(
                task_id=task_id,
                user_id=user_id,
                user_name=user_name,
                file_path=file_path,
                task_type=task_type,
                source_language=source_language,
                target_language=target_language,
                priority=priority,
                annotation_filename=annotation_filename,
                annotation_json=annotation_json,  # 添加注释数据
                select_page=select_page,
                bilingual_translation=bilingual_translation,
                model=model,
                enable_text_splitting=enable_text_splitting,
                enable_uno_conversion=enable_uno_conversion,
                custom_translations=custom_translations,  # 传递自定义翻译词典
                **kwargs
            )
            
            # 记录任务创建信息
            self.logger.info(f"创建任务 {task_id}，参数:")
            self.logger.info(f"  - 模型: {model}")
            self.logger.info(f"  - 文本分割: {enable_text_splitting}")
            self.logger.info(f"  - UNO转换: {enable_uno_conversion}")
            self.logger.info(f"  - 词典条目数: {len(custom_translations) if custom_translations else 0}")

            # 存储任务
            self.tasks[task_id] = task
            self.user_tasks[user_id] = task_id

            # 通知处理器有新任务
            self.task_available.set()

            self.logger.info(
                f"新任务已添加 - ID: {task_id}, 用户: {user_name}, "
                f"文件: {os.path.basename(file_path)}"
            )

            # 返回队列中等待的任务数
            return len([t for t in self.tasks.values() if t.status == "waiting"])

    def add_claimed_task(self, task: TranslationTask) -> int:
        if not self.initialized:
            raise RuntimeError("任务队列未初始化")

        with self.lock:
            active_count = len(self.active_tasks)
            waiting_count = len([queued for queued in self.tasks.values() if queued.status == "waiting"])
            if active_count + waiting_count >= self.max_concurrent_tasks:
                raise RuntimeError("任务队列已满")
            self.tasks[task.task_id] = task
            self.user_tasks[task.user_id] = task.task_id
            self.task_available.set()
            return waiting_count + 1

    def has_available_slot(self) -> bool:
        with self.lock:
            active_count = len(self.active_tasks)
            waiting_count = len([queued for queued in self.tasks.values() if queued.status == "waiting"])
            return active_count + waiting_count < self.max_concurrent_tasks

    def start_processor(self) -> None:
        """启动任务处理器"""
        with self.lock:
            if not self.running:
                self.logger.info("正在启动任务处理器...")
                if not self.initialized:
                    self.configure()
                self.running = True

                # 检查线程池健康状态
                self._check_thread_pool_health()

                # 创建处理器线程 - 改为daemon=True，确保主线程退出时不会阻塞
                self.processor_thread = threading.Thread(
                    target=self._processor_loop,
                    name="translation_processor",
                    daemon=True  # 设置为守护线程，这样主线程退出时它会自动终止
                )
                self.processor_thread.start()

                self.logger.info(
                    f"任务处理器已启动 - 最大并发任务数: {self.max_concurrent_tasks}, "
                    f"超时时间: {self.task_timeout}秒"
                )
                self.schedule_db_connection_recycling()

    def stop_processor(self) -> None:
        """停止任务处理器"""
        self.logger.info("正在停止任务处理器...")
        
        # 使用安全关闭机制
        self.safe_shutdown(wait=True, timeout=10.0)
        
        self.logger.info("任务处理器已停止")

    def _processor_loop(self) -> None:
        """任务处理器主循环"""
        # 设置线程本地变量，标记为处理器线程
        thread_local = threading.local()
        thread_local.is_processor_thread = True
        
        # 记录线程ID，便于调试
        processor_thread_id = threading.get_ident()
        self.logger.info(f"处理器线程已启动，线程ID: {processor_thread_id}")
        
        while self.running:
            try:
                # 添加定期检查running标志的逻辑，确保能及时响应终止请求
                if not self.running:
                    self.logger.info("检测到终止信号，处理器线程退出")
                    break
                    
                # 等待新任务或检查间隔，使用较短的超时确保能及时响应终止请求
                self.task_available.wait(timeout=0.5)  # 减少超时时间，提高响应性
                self.task_available.clear()
                
                # 再次检查running标志
                if not self.running:
                    self.logger.info("检测到终止信号，处理器线程退出")
                    break
                
                # 定期检查线程池健康状态
                current_time = time.time()
                if current_time - self.last_pool_check > self.pool_check_interval:
                    self._check_thread_pool_health()
                    self.last_pool_check = current_time

                # 如果线程池未初始化或不健康，不处理新任务
                if not thread_pool.initialized:
                    self.logger.warning("线程池未初始化或不健康，暂停处理新任务")
                    # 尝试初始化线程池
                    thread_pool.configure()
                    # 短暂等待后继续
                    time.sleep(0.5)  # 减少等待时间，提高响应性
                    continue

                with self.lock:
                    # 检查是否可以启动新任务
                    if len(self.active_tasks) >= self.max_concurrent_tasks:
                        continue

                    # 获取等待中的任务
                    waiting_tasks = [
                        t for t in self.tasks.values()
                        if t.status == "waiting"
                    ]

                    if not waiting_tasks:
                        continue

                    # 按优先级排序
                    waiting_tasks.sort(key=lambda x: x.priority)

                    # 选择要处理的任务
                    for task in waiting_tasks:
                        if len(self.active_tasks) >= self.max_concurrent_tasks:
                            break

                        if task.task_id not in self.active_tasks:
                            # 提交任务到线程池
                            self._process_task(task)

            except Exception as e:
                self.logger.error(f"任务处理器错误: {str(e)}")
                time.sleep(0.5)  # 发生错误时短暂暂停，减少等待时间
                
                # 如果发生异常，检查线程池健康状态
                self._check_thread_pool_health()
        
        # 线程退出前记录日志
        self.logger.info(f"处理器线程已退出，线程ID: {processor_thread_id}")

    def _check_thread_pool_health(self) -> bool:
        """
        检查线程池健康状态，如果异常则尝试重新初始化
        
        Returns:
            线程池是否健康
        """
        try:
            # 首先检查线程池是否已初始化
            if not hasattr(thread_pool, 'initialized') or not thread_pool.initialized:
                self.logger.warning("线程池未初始化，尝试重新初始化")
                thread_pool.configure()
                # 等待一小段时间确保初始化完成
                time.sleep(0.5)
                # 再次检查初始化状态
                if not thread_pool.initialized:
                    self.logger.error("线程池初始化失败")
                    return False
                else:
                    self.logger.info("线程池初始化成功")
                    return True
            
            # 检查线程池健康状态
            if hasattr(thread_pool, 'get_health_status'):
                health_status = thread_pool.get_health_status()
                
                # 如果健康，记录基本信息并返回
                if health_status.get('healthy', False):
                    # 获取线程池统计信息
                    io_count = thread_pool.get_io_active_count()
                    cpu_count = thread_pool.get_cpu_active_count()
                    
                    self.logger.debug(f"线程池健康状态正常 - IO线程: {io_count}, CPU线程: {cpu_count}")
                    return True
                
                # 不健康，记录详细诊断信息
                diagnosis = health_status.get('diagnosis', [])
                if diagnosis:
                    self.logger.warning(f"线程池健康状态异常: {', '.join(diagnosis)}")
                else:
                    self.logger.warning(f"线程池健康状态异常: {health_status}")
                
                # 检查是否需要重新初始化
                needs_reinit = False
                
                # 如果线程池已关闭或未运行，需要重新初始化
                if not health_status.get('running', False):
                    self.logger.warning("线程池未运行，需要重新初始化")
                    needs_reinit = True
                
                # 如果执行器已关闭，需要重新初始化
                if not health_status.get('io_executor_alive', False) or not health_status.get('cpu_executor_alive', False):
                    self.logger.warning("线程池执行器已关闭，需要重新初始化")
                    needs_reinit = True
                
                # 如果调度线程未运行，需要重新初始化
                if not health_status.get('scheduler_thread_alive', False):
                    self.logger.warning("线程池调度线程未运行，需要重新初始化")
                    needs_reinit = True
                
                # 尝试重新初始化线程池
                if needs_reinit:
                    self.logger.info("尝试重新初始化线程池")
                    thread_pool.configure()
                    # 等待一小段时间确保初始化完成
                    time.sleep(0.5)
                    # 再次检查健康状态
                    new_health_status = thread_pool.get_health_status()
                    if new_health_status.get('healthy', False):
                        self.logger.info("线程池重新初始化成功")
                        return True
                    else:
                        self.logger.error(f"线程池重新初始化失败: {new_health_status}")
                        return False
                
                return False
            
            # 如果没有健康状态检查方法，使用基本检查
            # 获取线程池统计信息
            stats = thread_pool.get_stats()
            io_count = thread_pool.get_io_active_count()
            cpu_count = thread_pool.get_cpu_active_count()
            
            self.logger.info(f"线程池基本检查 - IO线程: {io_count}, CPU线程: {cpu_count}, " 
                            f"总任务: {stats.get('total_tasks_created', 0)}")
            
            # 检查线程池是否正常工作
            if io_count == 0 and stats.get('total_tasks_created', 0) > 0:
                self.logger.warning("线程池IO线程数为0，可能异常，尝试重新初始化")
                thread_pool.configure()
                # 等待一小段时间确保初始化完成
                time.sleep(0.5)
                return thread_pool.initialized
                
            return True
        except Exception as e:
            self.logger.error(f"检查线程池健康状态时出错: {str(e)}")
            # 出错时尝试重新初始化线程池
            try:
                thread_pool.configure()
                # 等待一小段时间确保初始化完成
                time.sleep(0.5)
                return thread_pool.initialized
            except Exception as e2:
                self.logger.error(f"重新初始化线程池失败: {str(e2)}")
                return False

    def _process_task(self, task: TranslationTask) -> None:
        """
        处理任务，将任务提交到线程池执行
        
        确保线程安全，正确处理任务状态更新和错误处理
        使用异步回调避免线程自己加入自己
        
        Args:
            task: 要处理的任务
        """
        try:
            # 如果任务已经取消或失败，直接返回
            if task.status in ["canceled", "failed"]:
                self.logger.debug(f"跳过已取消或失败的任务: {task.task_id}")
                return

            if task.ledger_execution_preflight and not task.ledger_execution_preflight():
                task.status = "canceled"
                task.completed_at = now_with_timezone()
                task.event.set()
                self.logger.info(f"跳过失效的账本任务: {task.task_id}")
                return
            
            # 更新任务状态
            task.status = "processing"
            task.started_at = now_with_timezone()
            
            # 添加到活跃任务列表
            with self.lock:
                self.active_tasks[task.task_id] = task
            
            # 检查线程池健康状态
            if not self._check_thread_pool_health():
                self.logger.warning(f"线程池健康检查失败，任务可能无法正常执行: {task.task_id}")
            
            # 记录任务日志
            self.logger.info(f"提交任务到线程池: {task.task_id}, 用户: {task.user_id}")
            task.logger.info(f"准备处理翻译任务: {os.path.basename(task.file_path)}")
            
            # 创建全局清理线程池（如果不存在）
            if not hasattr(self, 'cleanup_executor') or self.cleanup_executor is None:
                self.cleanup_executor = ThreadPoolExecutor(
                    max_workers=5,  # 最多5个清理线程
                    thread_name_prefix="task_cleanup"
                )
                self.logger.info("已创建任务清理线程池")
            
            # 定义任务完成回调函数 - 使用弱引用避免循环引用
            weak_self = weakref.ref(self)
            
            def task_done_callback(thread_task):
                """
                任务完成回调函数
                
                处理任务完成后的状态更新、资源清理和通知
                使用线程池安全地执行资源清理
                
                Args:
                    thread_task: 线程任务对象
                """
                application_context = None
                context_entered = False
                try:
                    # 获取实际的队列实例（使用弱引用避免循环引用）
                    queue_instance = weak_self()
                    if queue_instance is None:
                        # 队列实例已被垃圾回收，无法继续处理
                        return

                    application_context = queue_instance._application_context()
                    application_context.__enter__()
                    context_entered = True
                    
                    # 记录当前线程ID，用于调试和安全检查
                    callback_thread_id = threading.get_ident()
                    queue_instance.logger.debug(
                        f"任务回调执行 - 任务: {task.task_id}, "
                        f"线程ID: {callback_thread_id}, "
                        f"任务线程ID: {getattr(thread_task, 'thread_id', 'unknown')}"
                    )
                    
                    # 检查回调线程是否是任务执行线程
                    is_same_thread = (getattr(thread_task, 'thread_id', None) == callback_thread_id)
                    if is_same_thread:
                        queue_instance.logger.warning(
                            f"回调在任务执行线程中运行，这可能导致问题 - 任务: {task.task_id}"
                        )
                    
                    # 线程池的 COMPLETED 仅表示函数正常返回；业务任务还必须显式返回 True。
                    outcome = _thread_task_outcome(thread_task)
                    if outcome == "completed":
                        queue_instance.logger.info(f"任务完成: {task.task_id}")
                    elif outcome == "failed":
                        task.error = str(
                            getattr(thread_task, "error", None)
                            or task.error
                            or "translation processor returned an unsuccessful result"
                        )
                        queue_instance.logger.error(f"任务失败: {task.task_id}, 错误: {task.error}")
                    elif outcome == "canceled":
                        queue_instance.logger.info(f"任务已取消: {task.task_id}")

                    task.completed_at = now_with_timezone()
                    # Persist the history projection before exposing a terminal task status.
                    history_persisted = queue_instance._schedule_database_update(task, status=outcome)
                    legacy_ppt_history_failed = (
                        outcome == "completed"
                        and task.task_type == "ppt_translate"
                        and task.ledger_completion_callback is None
                        and not history_persisted
                    )
                    if legacy_ppt_history_failed:
                        task.status = "failed"
                        task.error = "翻译已完成，但历史记录保存失败，请重试或联系管理员"
                        queue_instance.logger.error(
                            f"任务历史记录保存失败，拒绝发布完成状态: {task.task_id}"
                        )
                    else:
                        task.status = outcome
                    if task.ledger_completion_callback:
                        try:
                            task.ledger_completion_callback(task)
                        except Exception as completion_error:
                            task.status = "failed"
                            task.error = f"任务完成持久化失败: {completion_error}"
                            task.event.set()
                            # The normal asynchronous cleanup is below this callback and would be skipped.
                            queue_instance._cleanup_task_resources(task)
                            raise
                    task.event.set()

                    # 确保全局清理线程池存在
                    if not hasattr(queue_instance, 'cleanup_executor') or queue_instance.cleanup_executor is None:
                        queue_instance.cleanup_executor = ThreadPoolExecutor(
                            max_workers=5,  # 限制最大清理线程数
                            thread_name_prefix="task_cleanup"
                        )
                        queue_instance.logger.info("已创建任务清理线程池")
                    
                    # 定义安全的资源清理函数
                    def safe_cleanup_task(task_id):
                        """
                        安全地清理任务资源
                        
                        Args:
                            task_id: 任务ID
                        """
                        try:
                            # 记录清理线程ID
                            cleanup_thread_id = threading.get_ident()
                            
                            # 再次获取队列实例（可能在此期间被垃圾回收）
                            queue_instance = weak_self()
                            if queue_instance is None:
                                return
                            
                            queue_instance.logger.debug(
                                f"开始清理任务资源 - 任务: {task_id}, "
                                f"清理线程ID: {cleanup_thread_id}"
                            )
                            
                            # 获取任务对象（可能在此期间被移除）
                            task_to_clean = None
                            with queue_instance.lock:
                                if task_id in queue_instance.active_tasks:
                                    task_to_clean = queue_instance.active_tasks[task_id]
                            
                            if task_to_clean is None:
                                queue_instance.logger.debug(f"任务不在活跃列表中，跳过清理: {task_id}")
                                return
                            
                            # 清理任务资源
                            queue_instance._cleanup_task_resources(task_to_clean)
                            
                            # 从活跃任务列表中移除
                            with queue_instance.lock:
                                if task_id in queue_instance.active_tasks:
                                    del queue_instance.active_tasks[task_id]
                                    queue_instance.logger.debug(f"已从活跃任务列表中移除: {task_id}")
                            
                            # 通知任务队列有新的处理空间
                            queue_instance.task_available.set()
                            
                        except Exception as e:
                            # 使用全局日志记录器，避免依赖queue_instance
                            logger = logging.getLogger(f"{__name__}.cleanup")
                            logger.error(
                                f"任务资源清理出错: {task_id}, "
                                f"错误: {str(e)}\n{traceback.format_exc()}"
                            )
                    
                    # 提交清理任务到线程池
                    try:
                        # 检查清理线程池是否已关闭
                        if (not hasattr(queue_instance, 'cleanup_executor') or 
                            queue_instance.cleanup_executor is None or 
                            getattr(queue_instance.cleanup_executor, '_shutdown', False)):
                            # 线程池已关闭，直接在当前线程执行清理
                            queue_instance.logger.warning(f"清理线程池已关闭，在当前线程执行清理 - 任务: {task.task_id}")
                            safe_cleanup_task(task.task_id)
                        else:
                            # 检查线程池是否已关闭（再次检查，防止在检查和提交之间关闭）
                            try:
                                # 使用线程池执行清理
                                queue_instance.cleanup_executor.submit(safe_cleanup_task, task.task_id)
                                queue_instance.logger.debug(f"已提交清理任务到线程池 - 任务: {task.task_id}")
                            except RuntimeError as e:
                                if "cannot schedule new futures after shutdown" in str(e):
                                    # 线程池已关闭，直接在当前线程执行清理
                                    queue_instance.logger.warning(f"清理线程池已关闭(提交时检测)，在当前线程执行清理 - 任务: {task.task_id}")
                                    safe_cleanup_task(task.task_id)
                                else:
                                    raise
                        
                    except Exception as e:
                        # 记录提交失败
                        queue_instance.logger.error(
                            f"提交清理任务失败: {task.task_id}, "
                            f"错误: {str(e)}\n{traceback.format_exc()}"
                        )
                        
                        # 尝试在当前线程执行清理
                        try:
                            queue_instance.logger.warning(f"尝试在当前线程执行清理 - 任务: {task.task_id}")
                            safe_cleanup_task(task.task_id)
                        except Exception as e2:
                            queue_instance.logger.error(f"当前线程执行清理失败: {str(e2)}")
                        
                        # 确保任务被从活跃列表中移除
                        try:
                            with queue_instance.lock:
                                if task.task_id in queue_instance.active_tasks:
                                    del queue_instance.active_tasks[task.task_id]
                            queue_instance.task_available.set()
                        except Exception as e2:
                            queue_instance.logger.error(f"移除活跃任务失败: {str(e2)}")
                
                except Exception as e:
                    # 获取日志记录器
                    logger = logging.getLogger(f"{__name__}.callback")
                    logger.error(
                        f"任务完成回调出错: {task.task_id}, "
                        f"错误: {str(e)}\n{traceback.format_exc()}"
                    )
                    
                    # 确保任务被从活跃列表中移除（最后的安全网）
                    try:
                        queue_instance = weak_self()
                        if queue_instance is not None:
                            with queue_instance.lock:
                                if task.task_id in queue_instance.active_tasks:
                                    del queue_instance.active_tasks[task.task_id]
                            queue_instance.task_available.set()
                    except Exception as e2:
                        logger.error(f"最终清理失败: {str(e2)}")
                finally:
                    if context_entered and application_context is not None:
                        try:
                            application_context.__exit__(None, None, None)
                        except Exception as e:
                            logger = logging.getLogger(f"{__name__}.callback")
                            logger.error(f"释放任务回调应用上下文失败: {str(e)}")

            # 提交任务到线程池，始终使用异步回调避免线程安全问题
            thread_task = thread_pool.submit(
                func=self._execute_task,
                args=(task,),
                kwargs={},
                task_type=TaskType.IO_BOUND,
                priority=task.priority,
                task_id=task.task_id,
                timeout=self.task_timeout,
                use_async_callback=True  # 始终使用异步回调，避免线程自己加入自己
            )
            
            # 添加任务完成回调
            thread_task.add_callback(task_done_callback)
            
            # 保存线程任务引用
            task.thread_task = thread_task
            
            self.logger.debug(f"任务已提交到线程池: {task.task_id}")
            
        except Exception as e:
            # 记录错误
            error_msg = f"提交任务到线程池失败: {str(e)}"
            self.logger.exception(error_msg)
            task.logger.error(error_msg)
            
            # 更新任务状态为失败
            task.error = f"{str(e)}\n{traceback.format_exc()}"
            task.status = "failed"
            task.completed_at = now_with_timezone()
            task.event.set()
            
            # 从活跃任务列表中移除
            with self.lock:
                if task.task_id in self.active_tasks:
                    del self.active_tasks[task.task_id]
            
            # 通知任务队列有新的处理空间
            self.task_available.set()
            
            # 处理任务错误
            self._handle_task_error(task, error_msg)

    def _execute_task(self, task: TranslationTask) -> bool:
        """
        执行翻译任务
        
        安全地执行任务，处理异常和资源清理
        记录线程ID和执行状态
        
        Args:
            task: 要执行的任务
            
        Returns:
            任务是否成功执行
        """
        # 记录当前线程ID，用于线程安全检查
        current_thread_id = threading.get_ident()
        
        application_context = None
        context_entered = False
        
        try:
            # 设置任务开始时间
            task_start_time = time.time()
            self.logger.info(
                f"开始执行任务: {task.task_id}, "
                f"类型: {task.task_type}, "
                f"线程ID: {current_thread_id}"
            )

            # 记录任务日志
            current_time = now_with_timezone()
            task.logs.append({
                'timestamp': current_time,
                'message': f"开始执行任务: {os.path.basename(task.file_path)}",
                'level': 'info'
            })
            
            # 检查任务是否被取消
            if task.status == "canceled" or (task.thread_task and task.thread_task.should_cancel()):
                self.logger.info(f"任务已被取消，跳过执行: {task.task_id}")
                task.status = "canceled"
                return False

            # Worker threads do not inherit the request/dispatcher context.
            try:
                application_context = self._application_context()
                application_context.__enter__()
                context_entered = True
                self.logger.debug(f"任务 {task.task_id} 已进入应用上下文")
            except Exception as e:
                self.logger.error(f"创建应用上下文失败: {str(e)}")
                task.error = f"创建应用上下文失败: {str(e)}"
                return False

            try:
                # 记录数据库连接使用情况
                db_conn_before = self._get_db_connection_info()

                # 进度回调函数
                def progress_callback(current, total):
                    # 检查任务是否被取消
                    if task.status == "canceled" or (task.thread_task and task.thread_task.should_cancel()):
                        raise RuntimeError("任务已被用户取消")

                    progress = int((current / total) * 100) if total > 0 else 0
                    task.progress = progress
                    task.current_slide = current
                    task.total_slides = total

                    # 记录任务进度
                    if progress % 10 == 0 or progress == 100:  # 每10%记录一次
                        log_message = f"处理进度: {current}/{total} ({progress}%)"
                        task.logger.info(log_message)

                        # 添加到任务日志
                        task.logs.append({
                            'timestamp': now_with_timezone(),
                            'message': log_message,
                            'level': 'info'
                        })

                    # 保留最近的50条日志
                    if len(task.logs) > 50:
                        task.logs = task.logs[-50:]
                    if task.ledger_progress_callback:
                        task.ledger_progress_callback(progress)

                from app.jobs.executor import execute_legacy_task

                success = execute_legacy_task(task, progress_callback)
                if not success and not task.error:
                    task.error = "translation processor returned an unsuccessful result"

                # 记录数据库连接使用情况变化
                db_conn_after = self._get_db_connection_info()

                # 检查是否有连接泄漏
                if db_conn_after and db_conn_before and db_conn_after.get('checkedout', 0) > db_conn_before.get('checkedout', 0):
                    self.logger.warning(
                        f"任务 {task.task_id} 完成后检测到可能的连接泄漏: "
                        f"签出连接数从 {db_conn_before.get('checkedout', 0)} 增加到 {db_conn_after.get('checkedout', 0)}"
                    )

                    # 尝试主动回收连接
                    self._recycle_db_connections()

                # 任务完成时间
                task_end_time = time.time()
                elapsed_time = task_end_time - task_start_time

                # 记录任务完成日志
                log_level = 'info' if success else 'error'
                log_message = f"任务{'成功完成' if success else '执行失败'}，耗时: {elapsed_time:.2f}秒"

                # 记录完成日志
                task.logger.log(logging.INFO if success else logging.ERROR, log_message)
                task.logs.append({
                    'timestamp': now_with_timezone(),
                    'message': log_message,
                    'level': log_level
                })

                # 对于特别长时间运行的任务，进行垃圾回收
                if elapsed_time > 1800:  # 30分钟
                    self._perform_gc()

                # 返回任务结果
                return success

            except Exception as e:
                # 记录错误信息
                error_msg = f"任务执行异常: {str(e)}"
                task.error = f"{str(e)}\n{traceback.format_exc()}"
                task.logger.error(error_msg)

                # 记录错误日志
                task.logs.append({
                    'timestamp': now_with_timezone(),
                    'message': error_msg,
                    'level': 'error'
                })

                return False
            
        except Exception as e:
            # 记录错误信息
            error_msg = f"任务执行异常: {str(e)}"
            task.error = f"{str(e)}\n{traceback.format_exc()}"
            task.logger.error(error_msg)

            # 记录错误日志
            task.logs.append({
                'timestamp': now_with_timezone(),
                'message': error_msg,
                'level': 'error'
            })

            return False
        finally:
            if context_entered and application_context is not None:
                try:
                    application_context.__exit__(None, None, None)
                except Exception as e:
                    self.logger.error(f"释放应用上下文失败: {str(e)}")

    def _get_db_connection_info(self):
        """获取数据库连接信息"""
        try:
            from flask import current_app
            engine = current_app.extensions['sqlalchemy'].db.engine
            return {
                'checkedin': engine.pool.checkedin(),
                'checkedout': engine.pool.checkedout(),
                'overflow': engine.pool.overflow()
            }
        except Exception as e:
            self.logger.warning(f"获取数据库连接信息失败: {str(e)}")
            return None
            
    def _recycle_db_connections(self):
        """尝试回收数据库连接"""
        try:
            from flask import current_app
            from sqlalchemy import text
            engine = current_app.extensions['sqlalchemy'].db.engine
            
            # 尝试执行一个简单查询来回收连接
            with engine.connect() as conn:
                conn.execute(text("/* 回收连接检查 */ SELECT 1"))
                
            # 强制回收所有空闲连接
            engine.dispose()
            self.logger.info("已回收数据库连接")
            
        except Exception as e:
            self.logger.error(f"回收数据库连接失败: {str(e)}")
            
    def _perform_gc(self):
        """执行垃圾回收"""
        try:
            import gc
            count = gc.collect()
            self.logger.info(f"执行垃圾回收，回收了 {count} 个对象")
        except Exception as e:
            self.logger.error(f"执行垃圾回收失败: {str(e)}")

    def _execute_ppt_translation_task(self, task: TranslationTask, progress_callback) -> bool:
        """Compatibility wrapper for PPT execution through the typed job executor."""
        from app.jobs.executor import execute_legacy_task

        try:
            return execute_legacy_task(task, progress_callback)
        except Exception as e:
            self.logger.error(f"执行PPT翻译任务时出错: {str(e)}")
            return False
    def _execute_pdf_annotation_task(self, task: TranslationTask, progress_callback) -> bool:
        """Compatibility wrapper for PDF annotation through the typed job executor."""
        from app.jobs.executor import execute_legacy_task

        try:
            return execute_legacy_task(task, progress_callback)
        except Exception as e:
            self.logger.error(f"执行PDF注释任务时出错: {str(e)}")
            return False
    def _schedule_database_update(self, task: TranslationTask, status: Optional[str] = None) -> bool:
        """
        调度数据库更新任务

        Args:
            task: 翻译任务对象
        """
        # 记录基本信息（不需要应用上下文）
        self.logger.info(f"任务完成 - ID: {task.task_id}, 用户: {task.user_name}, 文件: {os.path.basename(task.file_path)}")
        
        try:
            with self._application_context():
                from app import db
                from app.models import UploadRecord

                try:
                    file_path = task.file_path
                    stored_filename = os.path.basename(file_path)
                    file_directory = os.path.dirname(file_path)

                    record = UploadRecord.query.filter_by(
                        user_id=task.user_id,
                        file_path=file_directory,
                        stored_filename=stored_filename,
                    ).first()

                    if record:
                        record_status = status or task.status
                        if record_status == "completed":
                            record.status = "completed"
                            self.logger.info(f"更新记录状态为completed: {record.id}, 文件: {record.filename}")
                        elif record_status == "failed":
                            record.status = "failed"
                            if task.error:
                                record.error_message = task.error[:255]
                            self.logger.info(f"更新记录状态为failed: {record.id}, 文件: {record.filename}")

                        db.session.commit()
                        self.logger.info(f"成功更新数据库记录状态: {record.id}")
                        return True
                    else:
                        # End the read transaction so a reused callback thread sees later uploads.
                        db.session.rollback()
                        self.logger.warning(
                            f"未找到对应的上传记录 - 用户ID: {task.user_id}, "
                            f"文件路径: {file_directory}, "
                            f"存储文件名: {stored_filename}"
                        )
                        return False
                except Exception as e:
                    self.logger.error(f"更新数据库记录状态失败: {str(e)}")
                    try:
                        db.session.rollback()
                    except Exception as rollback_error:
                        self.logger.error(f"回滚事务失败: {str(rollback_error)}")
                    return False
                finally:
                    # A callback thread must never retain a scoped session between tasks.
                    db.session.remove()
        except Exception as e:
            self.logger.error(f"创建应用上下文失败: {str(e)}")
            return False

    def _handle_task_error(self, task: TranslationTask, error: str) -> None:
        """
        处理任务错误
        
        Args:
            task: 出错的任务
            error: 错误信息
        """
        self.logger.error(f"任务错误: {task.task_id}, 错误: {error}")
        task.logger.error(f"翻译任务失败: {error}")
        
        # 更新任务错误信息
        task.error = error
        
        application_context = None
        context_entered = False
        try:
            application_context = self._application_context()
            application_context.__enter__()
            context_entered = True
        except Exception as e:
            self.logger.error(f"创建应用上下文失败: {str(e)}")
            self._handle_task_error_without_context(task, error)
            return
        
        try:
            # 检查是否可以重试
            if task.retry_count < self.retry_times:
                task.retry_count += 1
                task.status = "waiting"
                task.progress = 0
                task.logger.info(f"准备重试任务 (第{task.retry_count}次)")
                
                # 更新当前操作信息
                current_time = now_with_timezone()
                task.logs.append({
                    'timestamp': current_time,
                    'message': f"任务失败，准备重试 ({task.retry_count}/{self.retry_times}): {error}",
                    'level': 'warning'
                })
                
                # 保留最近的50条日志
                if len(task.logs) > 50:
                    task.logs = task.logs[-50:]
                
                # 从活跃任务列表中移除
                with self.lock:
                    if task.task_id in self.active_tasks:
                        del self.active_tasks[task.task_id]
                
                # 通知任务队列有新的处理空间
                self.task_available.set()
                
            else:
                # 超过重试次数，标记为失败
                task.status = "failed"
                task.completed_at = now_with_timezone()
                task.event.set()  # 设置事件，通知等待的线程
                
                # 任务最终失败后清理资源
                self._cleanup_task_resources(task)
                
                # 更新当前操作信息
                current_time = now_with_timezone()
                task.logs.append({
                    'timestamp': current_time,
                    'message': f"任务最终失败 (已重试{task.retry_count}次): {error}",
                    'level': 'error'
                })
                
                # 保留最近的50条日志
                if len(task.logs) > 50:
                    task.logs = task.logs[-50:]
                
                # 从活跃任务列表中移除
                with self.lock:
                    if task.task_id in self.active_tasks:
                        del self.active_tasks[task.task_id]
                
                # 通知任务队列有新的处理空间
                self.task_available.set()
                
                # 更新数据库中的任务状态
                self._schedule_database_update(task)
        
        except Exception as e:
            self.logger.error(f"处理任务错误时出现异常: {str(e)}")
            # 如果处理过程中出现异常，执行基本操作
            self._handle_task_error_without_context(task, error)
        
        finally:
            if context_entered and application_context is not None:
                try:
                    from app import db

                    db.session.remove()
                except Exception as e:
                    self.logger.warning(f"清理数据库会话失败: {str(e)}")
                try:
                    application_context.__exit__(None, None, None)
                except Exception as e:
                    self.logger.error(f"释放任务错误处理应用上下文失败: {str(e)}")
    
    def _handle_task_error_without_context(self, task: TranslationTask, error: str) -> None:
        """
        在没有应用上下文的情况下处理任务错误的基本操作
        
        Args:
            task: 出错的任务
            error: 错误信息
        """
        # 更新任务状态
        task.status = "failed"
        task.completed_at = now_with_timezone()
        task.event.set()  # 设置事件，通知等待的线程
        
        # 更新当前操作信息
        current_time = now_with_timezone()
        task.logs.append({
            'timestamp': current_time,
            'message': f"任务最终失败 (无应用上下文): {error}",
            'level': 'error'
        })
        
        # 从活跃任务列表中移除
        with self.lock:
            if task.task_id in self.active_tasks:
                del self.active_tasks[task.task_id]
        
        # 通知任务队列有新的处理空间
        self.task_available.set()
        
        # 尝试更新数据库记录状态
        try:
            self._schedule_database_update(task)
        except Exception as e:
            self.logger.error(f"无应用上下文时更新数据库记录失败: {str(e)}")

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务状态

        Args:
            task_id: 任务ID

        Returns:
            任务状态信息字典
        """
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return None

            return {
                'task_id': task.task_id,
                'status': task.status,
                'progress': task.progress,
                'current_slide': getattr(task, 'current_slide', 0),
                'total_slides': getattr(task, 'total_slides', 0),
                'error': task.error,
                'start_time': task.start_time,
                'end_time': task.end_time,
                'retry_count': task.retry_count
            }

    def get_task_status_by_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        按用户ID获取任务状态

        Args:
            user_id: 用户ID

        Returns:
            任务状态信息字典
        """
        with self.lock:
            # 从用户任务映射中获取任务ID
            task_id = self.user_tasks.get(user_id)
            if not task_id:
                return None

            # 获取任务对象
            task = self.tasks.get(task_id)
            if not task:
                return None

            # 计算队列位置（仅对等待中的任务）
            position = 0
            if task.status == "waiting":
                waiting_tasks = [t for t in self.tasks.values() if t.status == "waiting"]
                waiting_tasks.sort(key=lambda x: x.created_at)
                for i, waiting_task in enumerate(waiting_tasks):
                    if waiting_task.task_id == task_id:
                        position = i + 1
                        break

            return {
                'task_id': task.task_id,
                'status': task.status,
                'progress': task.progress,
                'current_slide': getattr(task, 'current_slide', 0),
                'total_slides': getattr(task, 'total_slides', 0),
                'position': position,
                'error': task.error,
                'start_time': task.start_time,
                'end_time': task.end_time,
                'retry_count': task.retry_count,
                'created_at': task.created_at,
                'started_at': getattr(task, 'started_at', None),
                'completed_at': getattr(task, 'completed_at', None)
            }

    def get_queue_stats(self) -> Dict[str, Any]:
        """
        获取队列统计信息

        Returns:
            统计信息字典
        """
        with self.lock:
            waiting_tasks = len([t for t in self.tasks.values() if t.status == "waiting"])
            processing_tasks = len(self.active_tasks)
            completed_tasks = len([t for t in self.tasks.values() if t.status == "completed"])
            failed_tasks = len([t for t in self.tasks.values() if t.status == "failed"])
            canceled_tasks = len([t for t in self.tasks.values() if t.status == "canceled"])

            return {
                'waiting': waiting_tasks,
                'processing': processing_tasks,
                'completed': completed_tasks,
                'failed': failed_tasks,
                'canceled': canceled_tasks,
                'total': len(self.tasks),
                'max_concurrent': self.max_concurrent_tasks,
                'task_timeout': self.task_timeout,
                'retry_times': self.retry_times
            }

    def get_queue_size(self) -> int:
        """
        获取队列总大小
        
        Returns:
            队列中的任务总数
        """
        with self.lock:
            return len(self.tasks)
    
    def get_active_count(self) -> int:
        """
        获取活动任务数
        
        Returns:
            当前正在处理的任务数
        """
        with self.lock:
            return len(self.active_tasks)
    
    def get_waiting_count(self) -> int:
        """
        获取等待任务数
        
        Returns:
            等待处理的任务数
        """
        with self.lock:
            return len([t for t in self.tasks.values() if t.status == "waiting"])
    
    def get_completed_count(self) -> int:
        """
        获取已完成任务数
        
        Returns:
            已完成的任务数
        """
        with self.lock:
            return len([t for t in self.tasks.values() if t.status == "completed"])
    
    def get_failed_count(self) -> int:
        """
        获取失败任务数
        
        Returns:
            失败的任务数
        """
        with self.lock:
            return len([t for t in self.tasks.values() if t.status == "failed"])

    def recycle_idle_connections(self) -> Dict[str, Any]:
        """
        回收闲置的数据库连接
        
        该方法会关闭所有空闲的数据库连接并强制回收连接池中的资源
        对于长时间运行的应用程序，定期调用此方法可以防止连接泄漏
        
        Returns:
            回收结果的状态信息
        """
        application_context = None
        context_entered = False
        try:
            application_context = self._application_context()
            application_context.__enter__()
            context_entered = True
        except Exception as e:
            self.logger.error(f"创建应用上下文失败: {str(e)}")
            return {
                'success': False,
                'message': f'创建应用上下文失败: {str(e)}',
                'error': str(e)
            }
        
        try:
            from flask import current_app
            from sqlalchemy import text
            import time
            
            # 获取当前数据库引擎
            engine = current_app.extensions['sqlalchemy'].db.engine
            
            # 记录回收前的连接池状态
            before_status = {
                'pool_size': engine.pool.size(),
                'checkedin': engine.pool.checkedin(),
                'checkedout': engine.pool.checkedout(),
                'overflow': engine.pool.overflow()
            }
            
            # 创建一个临时连接执行回收命令
            start_time = time.time()
            with engine.connect() as conn:
                # 执行连接池回收
                conn.execute(text("/* 回收空闲连接 */ SELECT 1"))
                
            # 强制回收所有空闲连接
            engine.dispose()
            
            # 记录回收后的连接池状态
            after_status = {
                'pool_size': engine.pool.size(),
                'checkedin': engine.pool.checkedin(),
                'checkedout': engine.pool.checkedout(),
                'overflow': engine.pool.overflow()
            }
            
            execution_time = time.time() - start_time
            
            result = {
                'success': True,
                'message': '成功回收空闲连接',
                'before': before_status,
                'after': after_status,
                'execution_time': execution_time
            }
            
            return result
        
        except Exception as e:
            self.logger.error(f"回收连接失败: {str(e)}")
            return {
                'success': False,
                'message': f'回收连接失败: {str(e)}',
                'error': str(e)
            }
        
        finally:
            if context_entered and application_context is not None:
                try:
                    application_context.__exit__(None, None, None)
                except Exception as e:
                    self.logger.error(f"释放连接回收应用上下文失败: {str(e)}")

    def _cleanup_task_resources(self, task: TranslationTask) -> None:
        """
        清理任务资源
        
        当任务完成或失败时，清理相关资源，确保内存和数据库连接被正确释放
        
        Args:
            task: 要清理资源的任务
        """
        application_context = None
        context_entered = False
        try:
            # 记录开始清理
            self.logger.info(f"清理任务资源: {task.task_id}, 用户: {task.user_id}")
            
            application_context = self._application_context()
            application_context.__enter__()
            context_entered = True

            if hasattr(task, 'db_session') and task.db_session:
                try:
                    task.db_session.close()
                    self.logger.info(f"已关闭任务专用数据库会话: {task.task_id}")
                except Exception as e:
                    self.logger.warning(f"关闭任务数据库会话失败: {str(e)}")
            
            # 以下操作不需要应用上下文
            # 强制垃圾回收大型对象
            if hasattr(task, 'result') and task.result:
                task.result = None
            
            # 清理任务中可能持有的大型数据
            for attr in ['annotations', 'annotation_json', 'custom_translations']:
                if hasattr(task, attr) and getattr(task, attr):
                    setattr(task, attr, None)
            
            # 如果任务持续时间超过30分钟，记录日志
            if task.started_at and task.completed_at:
                duration = (task.completed_at - task.started_at).total_seconds()
                if duration > 1800:  # 30分钟
                    self.logger.info(f"长时间运行任务({duration:.1f}秒)完成，建议回收连接池")
                    
            self.logger.info(f"任务资源清理完成: {task.task_id}")
            
        except Exception as e:
            self.logger.error(f"清理任务资源时出错: {str(e)}")
        finally:
            if context_entered and application_context is not None:
                try:
                    from app import db

                    db.session.remove()
                except Exception as e:
                    self.logger.warning(f"清理数据库会话失败: {str(e)}")
                try:
                    application_context.__exit__(None, None, None)
                except Exception as e:
                    self.logger.error(f"释放资源清理应用上下文失败: {str(e)}")

    def schedule_db_connection_recycling(self, interval=None):
        """
        启动定期回收数据库连接的后台线程
        
        Args:
            interval: 回收间隔（秒），默认使用self.db_recycle_interval
        """
        if interval is not None:
            self.db_recycle_interval = interval
        if self.recycle_thread is not None and self.recycle_thread.is_alive():
            return
        self.recycle_stop_event = threading.Event()
            
        def _recycle_job():
            self.logger.info(f"启动数据库连接定期回收线程，间隔：{self.db_recycle_interval}秒")
            while self.running:
                try:
                    # 等待指定间隔
                    if self.recycle_stop_event.wait(self.db_recycle_interval):
                        break
                    
                    # 如果任务队列不再运行，退出循环
                    if not self.running:
                        break
                    
                    # 执行回收（已经在recycle_idle_connections方法中创建应用上下文）
                    self.logger.info("执行定期数据库连接回收")
                    result = self.recycle_idle_connections()
                    
                    if result and result.get('success'):
                        self.logger.info(f"定期回收数据库连接成功：回收前 {result['before']}，回收后 {result['after']}")
                    else:
                        self.logger.warning(f"定期回收数据库连接失败：{result.get('message', '未知错误')}")
                        
                except Exception as e:
                    self.logger.error(f"定期回收数据库连接异常: {str(e)}")
                    # 出错后短暂暂停，避免频繁失败
                    time.sleep(60)
                    
        # 启动后台线程
        self.recycle_thread = threading.Thread(
            target=_recycle_job,
            name="db_connection_recycler",
            daemon=True  # 使用守护线程，主线程结束时自动结束
        )
        self.recycle_thread.start()
        
        self.logger.info("数据库连接定期回收线程已启动")

    def safe_shutdown(self, wait: bool = False, timeout: float = 10.0) -> None:
        """
        安全关闭任务队列和线程池
        
        可以在任何线程中调用，不会导致线程安全问题
        
        Args:
            wait: 是否等待关闭完成
            timeout: 等待超时时间（秒）
        """
        self.logger.info("开始安全关闭任务队列...")
        
        # 使用锁保护关闭过程
        with self.lock:
            # 检查是否已经关闭
            if not self.running:
                self.logger.info("任务队列已经关闭，无需再次关闭")
                return
            
            # 标记为不再运行
            self.running = False
            self.recycle_stop_event.set()
        
        # 唤醒处理器线程
        self.task_available.set()
        
        # 获取当前线程ID
        current_thread_id = threading.get_ident()
        
        # 检查是否在处理器线程中
        is_processor_thread = (
            hasattr(self, 'processor_thread') and 
            self.processor_thread.ident == current_thread_id
        )
        
        # 检查是否在线程池线程中
        is_pool_thread = False
        if hasattr(thread_pool, 'get_health_status'):
            try:
                # 获取线程池状态
                pool_status = thread_pool.get_health_status()
                
                # 检查IO线程池
                if pool_status.get('io_executor_alive', False):
                    io_threads = getattr(thread_pool.io_executor, '_threads', [])
                    thread_ids = [t.ident for t in io_threads if hasattr(t, 'ident') and t.ident]
                    if current_thread_id in thread_ids:
                        is_pool_thread = True
                        self.logger.debug(f"当前线程ID {current_thread_id} 在IO线程池中")
                
                # 检查CPU线程池
                if not is_pool_thread and pool_status.get('cpu_executor_alive', False):
                    cpu_threads = getattr(thread_pool.cpu_executor, '_threads', [])
                    thread_ids = [t.ident for t in cpu_threads if hasattr(t, 'ident') and t.ident]
                    if current_thread_id in thread_ids:
                        is_pool_thread = True
                        self.logger.debug(f"当前线程ID {current_thread_id} 在CPU线程池中")
            except Exception as e:
                self.logger.error(f"检查线程池状态时出错: {str(e)}")
                # 安全起见，假设当前线程可能在线程池中
                is_pool_thread = True
        
        # 如果在处理器线程或线程池线程中，使用专用线程关闭
        if is_processor_thread or is_pool_thread:
            self.logger.warning(
                f"从{'处理器' if is_processor_thread else '线程池'}线程中调用关闭，"
                f"将使用专用线程，当前线程ID: {current_thread_id}"
            )
            
            # 创建关闭事件
            shutdown_event = threading.Event()
            
            # 创建关闭线程
            shutdown_thread = threading.Thread(
                target=self._shutdown_worker,
                name="task_queue_shutdown",
                args=(shutdown_event,),
                daemon=True  # 设置为守护线程，确保主线程退出时不会阻塞
            )
            
            # 启动关闭线程
            shutdown_thread.start()
            
            # 如果需要等待关闭完成
            if wait:
                try:
                    shutdown_event.wait(timeout)
                    if not shutdown_event.is_set():
                        self.logger.warning(f"等待任务队列关闭超时（{timeout}秒）")
                except Exception as e:
                    self.logger.error(f"等待关闭完成时出错: {str(e)}")
        else:
            # 直接关闭
            try:
                self._shutdown_worker(None)
            except Exception as e:
                self.logger.error(f"直接关闭任务队列时出错: {str(e)}")
    
    def _shutdown_worker(self, shutdown_event: threading.Event = None) -> None:
        """
        在专用线程中执行关闭操作
        
        Args:
            shutdown_event: 关闭完成事件
        """
        try:
            self.logger.info("执行任务队列关闭...")
            
            # 首先将running标志设置为False，确保处理器循环能够退出
            self.running = False
            
            # 唤醒处理器线程，确保它能检测到running=False
            self.task_available.set()
            
            # 等待处理器线程结束
            if hasattr(self, 'processor_thread') and self.processor_thread.is_alive():
                try:
                    self.logger.debug("等待处理器线程结束...")
                    # 设置更长的超时时间
                    self.processor_thread.join(timeout=5.0)
                    if self.processor_thread.is_alive():
                        self.logger.warning("处理器线程未在预期时间内结束，尝试强制终止处理器循环")
                        # 再次唤醒处理器线程，确保它能检测到running=False
                        self.task_available.set()
                        # 再次等待一小段时间
                        self.processor_thread.join(timeout=2.0)
                        if self.processor_thread.is_alive():
                            self.logger.error("处理器线程无法正常终止，可能存在死锁")
                            # 由于设置了daemon=True，主线程退出时会自动终止，所以这里不再尝试强制终止
                            self.logger.info("处理器线程设置为守护线程，主线程退出时将自动终止")
                        else:
                            self.logger.debug("处理器线程已成功终止")
                    else:
                        self.logger.debug("处理器线程已正常结束")
                except Exception as e:
                    self.logger.error(f"等待处理器线程结束时出错: {str(e)}")

            if self.recycle_thread is not None and self.recycle_thread.is_alive():
                try:
                    self.recycle_stop_event.set()
                    self.recycle_thread.join(timeout=5.0)
                    if self.recycle_thread.is_alive():
                        self.logger.warning("数据库连接回收线程未在预期时间内结束")
                except Exception as e:
                    self.logger.error(f"等待数据库连接回收线程结束时出错: {str(e)}")
            
            # 关闭清理线程池
            if hasattr(self, 'cleanup_executor') and self.cleanup_executor:
                try:
                    self.logger.info("正在关闭清理线程池...")
                    
                    # 获取当前正在执行的任务数量
                    active_tasks = 0
                    if hasattr(self.cleanup_executor, '_work_queue'):
                        work_queue = self.cleanup_executor._work_queue
                        if hasattr(work_queue, 'unfinished_tasks'):
                            # 如果是 Queue.Queue 类型
                            active_tasks = len(self.cleanup_executor._threads) - work_queue.unfinished_tasks
                        elif hasattr(work_queue, 'qsize'):
                            # 如果是 SimpleQueue 类型，使用qsize代替
                            active_tasks = len(self.cleanup_executor._threads) - work_queue.qsize()
                        else:
                            # 保守估计：假设所有线程都在活跃
                            active_tasks = len(self.cleanup_executor._threads)
                            self.logger.warning("无法确定清理线程池中的活跃任务数量，假设所有线程都活跃")
                    
                    if active_tasks > 0:
                        self.logger.info(f"等待{active_tasks}个清理任务完成...")
                        # 等待所有任务完成，最多等待5秒
                        try:
                            # 使用shutdown(wait=True)等待任务完成
                            self.cleanup_executor.shutdown(wait=True, timeout=5.0)
                        except TypeError:  # Python 3.8之前的版本不支持timeout参数
                            self.cleanup_executor.shutdown(wait=True)
                    else:
                        # 没有活跃任务，直接关闭
                        self.cleanup_executor.shutdown(wait=False)
                    
                    self.logger.info("清理线程池已关闭")
                except Exception as e:
                    self.logger.error(f"关闭清理线程池时出错: {str(e)}")
                    # 确保线程池被标记为已关闭
                    try:
                        if not self.cleanup_executor._shutdown:
                            self.cleanup_executor._shutdown = True
                    except:
                        pass
            
            self.logger.info("任务队列已关闭")
        except Exception as e:
            self.logger.error(f"关闭任务队列时出错: {str(e)}")
        finally:
            # 设置关闭完成事件（如果提供）
            if shutdown_event is not None:
                shutdown_event.set()

# 创建全局翻译队列实例
translation_queue = EnhancedTranslationQueue()
