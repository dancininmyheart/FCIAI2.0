"""
logger_config.py
简易日志配置模块，提供项目所需的日志功能
"""

import logging
import sys
import os
from datetime import datetime, timedelta
import inspect
import functools

# 全局日志记录器字典
_loggers = {}

def setup_default_logging(level=logging.INFO):
    """
    设置默认的日志配置
    
    Args:
        level: 日志级别，默认为INFO
    
    Returns:
        logger: 配置好的日志记录器
    """
    # 创建主日志记录器
    logger = logging.getLogger("pyuno.main")
    logger.propagate = False
    
    # 避免重复配置
    if logger.handlers:
        return logger
    
    logger.setLevel(level)
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    # 创建格式化器
    formatter = logging.Formatter(
        fmt='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    
    # 添加处理器到日志记录器
    logger.addHandler(console_handler)
    
    # 存储到全局字典
    _loggers["pyuno.main"] = logger
    
    logger.info("默认日志配置初始化完成")
    return logger

def setup_subprocess_logging(log_file, level=logging.INFO):
    """
    设置子进程的日志配置
    
    Args:
        log_file: 日志文件路径
        level: 日志级别，默认为INFO
    
    Returns:
        logger: 配置好的日志记录器
    """
    # 创建子进程日志记录器
    logger = logging.getLogger("pyuno.subprocess")
    
    # 避免重复配置
    if logger.handlers:
        return logger
    
    logger.setLevel(level)
    
    # 确保日志目录存在
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # 创建文件处理器
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(level)
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    # 创建格式化器
    formatter = logging.Formatter(
        fmt='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # 添加处理器到日志记录器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # 存储到全局字典
    _loggers["pyuno.subprocess"] = logger
    
    logger.info(f"子进程日志配置初始化完成，日志文件: {log_file}")
    return logger

def get_logger(name="pyuno.main"):
    """
    获取指定名称的日志记录器
    
    Args:
        name: 日志记录器名称
    
    Returns:
        logger: 日志记录器实例
    """
    # 如果已存在，直接返回
    if name in _loggers:
        return _loggers[name]
    
    # 如果不存在，创建新的日志记录器
    logger = logging.getLogger(name)
    
    # 如果没有处理器，使用默认配置
    if not logger.handlers:
        if name == "pyuno.subprocess":
            # 为子进程创建基本配置
            logger.setLevel(logging.INFO)
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                fmt='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        else:
            # 使用默认配置
            return setup_default_logging()
    
    # 存储到全局字典
    _loggers[name] = logger
    return logger

def log_function_call(logger, function_name, **kwargs):
    """
    记录函数调用信息
    
    Args:
        logger: 日志记录器
        function_name: 函数名称
        **kwargs: 函数参数
    """
    if not logger:
        return
    
    # 格式化参数信息
    args_str = ", ".join([f"{k}={v}" for k, v in kwargs.items()])
    
    logger.debug(f"调用函数 {function_name}({args_str})")

def log_execution_time(logger, operation_name, start_time):
    """
    记录操作执行时间
    
    Args:
        logger: 日志记录器
        operation_name: 操作名称
        start_time: 开始时间
    """
    if not logger:
        return
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    logger.info(f"{operation_name} 执行完成，耗时: {duration:.2f} 秒")

def create_file_logger(name, log_file, level=logging.INFO):
    """
    创建文件日志记录器
    
    Args:
        name: 日志记录器名称
        log_file: 日志文件路径
        level: 日志级别
    
    Returns:
        logger: 配置好的日志记录器
    """
    logger = logging.getLogger(name)
    
    # 避免重复配置
    if logger.handlers:
        return logger
    
    logger.setLevel(level)
    
    # 确保日志目录存在
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # 创建文件处理器
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(level)
    
    # 创建格式化器
    formatter = logging.Formatter(
        fmt='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    
    # 添加处理器到日志记录器
    logger.addHandler(file_handler)
    
    # 存储到全局字典
    _loggers[name] = logger
    
    return logger

def set_log_level(logger_name, level):
    """
    设置日志记录器的日志级别
    
    Args:
        logger_name: 日志记录器名称
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    if logger_name in _loggers:
        if isinstance(level, str):
            level = getattr(logging, level.upper())
        _loggers[logger_name].setLevel(level)
        for handler in _loggers[logger_name].handlers:
            handler.setLevel(level)

def timing_decorator(logger_name="pyuno.main"):
    """
    函数执行时间装饰器
    
    Args:
        logger_name: 日志记录器名称
    
    Returns:
        decorator: 装饰器函数
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger(logger_name)
            start_time = datetime.now()
            
            try:
                result = func(*args, **kwargs)
                log_execution_time(logger, func.__name__, start_time)
                return result
            except Exception as e:
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                logger.error(f"{func.__name__} 执行失败，耗时: {duration:.2f} 秒，错误: {str(e)}")
                raise
        
        return wrapper
    return decorator

def log_memory_usage(logger, operation_name="内存使用"):
    """
    记录当前内存使用情况（如果psutil可用）
    
    Args:
        logger: 日志记录器
        operation_name: 操作名称
    """
    try:
        import psutil
        process = psutil.Process()
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / 1024 / 1024
        logger.debug(f"{operation_name} - 内存使用: {memory_mb:.2f} MB")
    except ImportError:
        # psutil不可用时跳过
        pass
    except Exception as e:
        logger.debug(f"获取内存使用信息失败: {str(e)}")

def cleanup_old_logs(log_directory, days_to_keep=7):
    """
    清理旧的日志文件
    
    Args:
        log_directory: 日志目录
        days_to_keep: 保留天数，默认7天
    """
    if not os.path.exists(log_directory):
        return
    
    logger = get_logger("pyuno.main")
    cutoff_date = datetime.now() - timedelta(days=days_to_keep)
    
    try:
        for filename in os.listdir(log_directory):
            if filename.endswith('.log'):
                file_path = os.path.join(log_directory, filename)
                file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                
                if file_mtime < cutoff_date:
                    os.remove(file_path)
                    logger.info(f"已删除旧日志文件: {filename}")
    except Exception as e:
        logger.warning(f"清理旧日志文件时出错: {str(e)}")

# 预定义的日志级别常量
DEBUG = logging.DEBUG
INFO = logging.INFO  
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL

# 初始化时的一些设置
def _init_logging():
    """
    初始化日志系统
    """
    # 设置root logger的级别，避免重复输出
    logging.getLogger().setLevel(logging.WARNING)

# 模块加载时初始化
_init_logging()

# 示例使用
if __name__ == "__main__":
    # 演示用法
    print("=" * 60)
    print("日志配置模块演示")
    print("=" * 60)
    
    # 创建默认日志记录器
    logger = setup_default_logging()
    logger.info("这是一条信息日志")
    logger.warning("这是一条警告日志")
    logger.error("这是一条错误日志")
    
    # 创建子进程日志记录器
    subprocess_logger = setup_subprocess_logging("test_logs/subprocess.log")
    subprocess_logger.info("这是子进程日志")
    
    # 使用函数调用记录
    log_function_call(logger, "test_function", param1="value1", param2=123)
    
    # 使用执行时间记录
    import time
    start = datetime.now()
    time.sleep(0.1)  # 模拟耗时操作
    log_execution_time(logger, "模拟操作", start)
    
    # 使用装饰器
    @timing_decorator("pyuno.main")
    def example_function():
        time.sleep(0.05)
        return "完成"
    
    result = example_function()
    logger.info(f"函数返回: {result}")
    
    print("=" * 60)
    print("演示完成")
    print("=" * 60)
