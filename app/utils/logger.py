"""
日志管理模块
支持多级别日志记录和文件轮转
"""
import os
import sys
import logging
import logging.handlers
import re
import glob
from typing import Optional, Dict, Any, Union, List
from datetime import datetime
from app.utils.timezone_helper import parse_datetime

class LogManager:
    """日志管理器，支持控制台和文件输出"""

    def __init__(self):
        """初始化日志管理器，但不创建处理器，等待配置"""
        # 默认配置
        self.log_level = logging.INFO
        self.log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        self.date_format = '%Y-%m-%d %H:%M:%S'
        self.max_bytes = 10 * 1024 * 1024  # 10MB
        self.backup_count = 5
        self.log_dir = 'logs'

        # 日志记录器
        self.logger = logging.getLogger('app')
        self.initialized = False

        # 处理器列表
        self.handlers = []

        # 日志记录器注册表
        self._loggers = {}

        # 注册默认的日志记录器
        self._register_default_loggers()

    def configure(self, log_level: Optional[Union[str, int]] = None,
                log_format: Optional[str] = None,
                date_format: Optional[str] = None,
                max_bytes: Optional[int] = None,
                backup_count: Optional[int] = None,
                log_dir: Optional[str] = None) -> None:
        """
        配置日志管理器

        Args:
            log_level: 日志级别
            log_format: 日志格式
            date_format: 日期格式
            max_bytes: 单个日志文件最大字节数
            backup_count: 保留的备份文件数量
            log_dir: 日志文件目录
        """
        # 更新配置
        if log_level is not None:
            if isinstance(log_level, str):
                self.log_level = getattr(logging, log_level.upper())
            else:
                self.log_level = log_level
        if log_format is not None:
            self.log_format = log_format
        if date_format is not None:
            self.date_format = date_format
        if max_bytes is not None:
            self.max_bytes = max_bytes
        if backup_count is not None:
            self.backup_count = backup_count
        if log_dir is not None:
            self.log_dir = log_dir

        # 如果已经初始化，需要重新创建处理器
        if self.initialized:
            self._remove_handlers()

        # 创建新的处理器
        self._setup_logger()
        self.initialized = True

        self.logger.info(
            f"日志管理器已配置 - 级别: {logging.getLevelName(self.log_level)}, "
            f"目录: {self.log_dir}, 最大文件大小: {self.max_bytes/1024/1024:.1f}MB"
        )

    def _setup_logger(self) -> None:
        """设置日志记录器"""
        # 创建日志目录
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)

        # 设置日志级别
        self.logger.setLevel(self.log_level)
        self.logger.propagate = False

        # 创建格式化器
        formatter = logging.Formatter(
            fmt=self.log_format,
            datefmt=self.date_format
        )

        # 创建控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self.handlers.append(console_handler)
        self.logger.addHandler(console_handler)

        # 创建文件处理器
        log_file = os.path.join(self.log_dir, 'app.log')
        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_file,
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        self.handlers.append(file_handler)
        self.logger.addHandler(file_handler)

        # 创建错误日志文件处理器
        error_log_file = os.path.join(self.log_dir, 'error.log')
        error_handler = logging.handlers.RotatingFileHandler(
            filename=error_log_file,
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        self.handlers.append(error_handler)
        self.logger.addHandler(error_handler)

    def _remove_handlers(self) -> None:
        """移除所有处理器"""
        for handler in self.handlers:
            self.logger.removeHandler(handler)
            handler.close()
        self.handlers.clear()

    def get_logger(self, name: str = None) -> logging.Logger:
        """
        获取日志记录器

        Args:
            name: 日志记录器名称

        Returns:
            日志记录器实例
        """
        if not self.initialized:
            raise RuntimeError("日志管理器未初始化")

        if name:
            return logging.getLogger(f"app.{name}")
        return self.logger

    def _register_default_loggers(self):
        """注册默认的日志记录器"""
        default_loggers = [
            'app',
            'app.main',
            'app.auth',
            'app.translation',
            'app.upload',
            'app.tasks',
            'app.tasks.cleanup',
            'app.function.ppt_translate',
            'app.function.pdf_annotate_async',
            'app.utils.thread_pool_executor',
            'app.utils.enhanced_task_queue',
            'werkzeug',
            'sqlalchemy.engine'
        ]

        for logger_name in default_loggers:
            self._loggers[logger_name] = {
                'name': logger_name,
                'level': 'INFO',
                'description': f'{logger_name} 日志记录器'
            }

    def get_loggers(self) -> List[str]:
        """
        获取所有已注册的日志记录器名称列表

        Returns:
            日志记录器名称列表
        """
        # 获取当前Python日志系统中的所有记录器
        current_loggers = set()

        # 获取根记录器的所有子记录器
        for name in logging.Logger.manager.loggerDict:
            if name.startswith('app') or name in ['werkzeug', 'sqlalchemy.engine']:
                current_loggers.add(name)

        # 合并默认注册的记录器和当前活跃的记录器
        all_loggers = set(self._loggers.keys()) | current_loggers

        return sorted(list(all_loggers))

    def get_logs(self, name: str, start_time: Optional[datetime] = None,
                 end_time: Optional[datetime] = None, level: Optional[str] = None,
                 limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取指定日志记录器的日志内容

        Args:
            name: 日志记录器名称
            start_time: 开始时间
            end_time: 结束时间
            level: 日志级别过滤
            limit: 返回记录数限制

        Returns:
            日志记录列表
        """
        logs = []

        try:
            # 读取主日志文件
            log_file = os.path.join(self.log_dir, 'app.log')
            if os.path.exists(log_file):
                logs.extend(self._read_log_file(log_file, name, start_time, end_time, level))

            # 读取轮转的日志文件
            for i in range(1, self.backup_count + 1):
                backup_file = f"{log_file}.{i}"
                if os.path.exists(backup_file):
                    logs.extend(self._read_log_file(backup_file, name, start_time, end_time, level))

            # 按时间戳字符串排序，而不是使用timestamp对象
            logs.sort(key=lambda x: x['timestamp_str'] if x.get('timestamp_str') else '', reverse=True)
            return logs[:limit]

        except Exception as e:
            return [{'error': f'读取日志失败: {str(e)}'}]

    def _read_log_file(self, file_path: str, logger_name: str,
                       start_time: Optional[datetime] = None,
                       end_time: Optional[datetime] = None,
                       level: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        读取单个日志文件

        Args:
            file_path: 日志文件路径
            logger_name: 日志记录器名称
            start_time: 开始时间
            end_time: 结束时间
            level: 日志级别

        Returns:
            日志记录列表
        """
        logs = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    # 解析日志行
                    log_entry = self._parse_log_line(line)
                    if not log_entry:
                        continue

                    # 过滤日志记录器名称（改进匹配逻辑）
                    if logger_name and logger_name != 'all' and logger_name != '':
                        entry_logger = log_entry.get('logger', '')
                        # 支持精确匹配和前缀匹配
                        if not (logger_name == entry_logger or
                               entry_logger.startswith(logger_name + '.') or
                               logger_name in entry_logger):
                            continue

                    # 过滤时间范围 - 使用timestamp_str进行比较
                    # 因为timestamp已经是ISO格式字符串，我们需要使用timestamp_str进行比较
                    if start_time and log_entry.get('timestamp_str'):
                        # 解析日志条目的时间戳
                        entry_time = parse_datetime(log_entry.get('timestamp_str'))
                        if entry_time and entry_time < start_time:
                            continue
                    
                    if end_time and log_entry.get('timestamp_str'):
                        # 解析日志条目的时间戳
                        entry_time = parse_datetime(log_entry.get('timestamp_str'))
                        if entry_time and entry_time > end_time:
                            continue

                    # 过滤日志级别
                    if level and level != 'all' and level != '':
                        if log_entry.get('level', '').upper() != level.upper():
                            continue

                    logs.append(log_entry)

        except Exception as e:
            logs.append({'error': f'读取文件 {file_path} 失败: {str(e)}'})

        return logs

    def _parse_log_line(self, line: str) -> Optional[Dict[str, Any]]:
        """
        解析日志行

        Args:
            line: 日志行文本

        Returns:
            解析后的日志信息字典
        """
        if not line.strip():
            return None
        
        # 尝试匹配不同的日志格式
        patterns = [
            # 标准格式: 2023-05-01 12:34:56,789 - logger - LEVEL - message
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) - ([^-]+) - ([A-Z]+) - (.*)',
            # 简化格式: 2023-05-01 12:34:56 - logger - LEVEL - message
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - ([^-]+) - ([A-Z]+) - (.*)',
            # ISO格式: 2023-05-01T12:34:56Z - logger - LEVEL - message
            r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?) - ([^-]+) - ([A-Z]+) - (.*)',
        ]
        
        for pattern in patterns:
            match = re.match(pattern, line)
            if match:
                timestamp_str, logger, level, message = match.groups()
                
                # 解析时间戳
                timestamp = parse_datetime(timestamp_str.strip())
                
                # 将datetime对象转换为ISO格式字符串，以便JSON序列化
                timestamp_iso = timestamp.isoformat() if timestamp else None
                
                return {
                    'timestamp': timestamp_iso,  # 使用ISO格式字符串而不是datetime对象
                    'timestamp_str': timestamp_str.strip(),
                    'logger': logger.strip(),
                    'level': level.strip(),
                    'message': message.strip(),
                    'raw_line': line
                }
        
        # 如果所有格式都不匹配，尝试简单解析
        if line.strip():
            return {
                'timestamp': None,
                'timestamp_str': '',
                'logger': 'unknown',
                'level': 'INFO',
                'message': line.strip(),
                'raw_line': line
            }
        
        return None

    def set_level(self, name: str, level: str, handler_type: str = 'both'):
        """
        设置指定日志记录器的级别

        Args:
            name: 日志记录器名称
            level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            handler_type: 处理器类型 ('console', 'file', 'both')
        """
        try:
            # 获取日志级别
            log_level = getattr(logging, level.upper())

            # 获取或创建日志记录器
            if name == 'app' or name == 'root':
                logger = self.logger
            else:
                logger = logging.getLogger(name)

            # 设置记录器级别
            logger.setLevel(log_level)

            # 设置处理器级别
            if handler_type in ['console', 'both']:
                for handler in logger.handlers:
                    if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                        handler.setLevel(log_level)

            if handler_type in ['file', 'both']:
                for handler in logger.handlers:
                    if isinstance(handler, logging.FileHandler):
                        handler.setLevel(log_level)

            # 更新注册表
            if name in self._loggers:
                self._loggers[name]['level'] = level.upper()
            else:
                self._loggers[name] = {
                    'name': name,
                    'level': level.upper(),
                    'description': f'{name} 日志记录器'
                }

        except AttributeError:
            raise ValueError(f"无效的日志级别: {level}")
        except Exception as e:
            raise RuntimeError(f"设置日志级别失败: {str(e)}")

    def debug_log_query(self, name: str = 'app', limit: int = 10) -> Dict[str, Any]:
        """
        调试日志查询功能

        Args:
            name: 日志记录器名称
            limit: 返回记录数限制

        Returns:
            调试信息字典
        """
        debug_info = {
            'log_dir': self.log_dir,
            'log_dir_exists': os.path.exists(self.log_dir),
            'log_files': [],
            'sample_lines': [],
            'parsed_logs': [],
            'query_result': []
        }

        try:
            # 检查日志目录
            if os.path.exists(self.log_dir):
                debug_info['log_files'] = os.listdir(self.log_dir)

            # 检查主日志文件
            log_file = os.path.join(self.log_dir, 'app.log')
            if os.path.exists(log_file):
                debug_info['main_log_exists'] = True
                debug_info['main_log_size'] = os.path.getsize(log_file)

                # 读取前几行作为样本
                with open(log_file, 'r', encoding='utf-8') as f:
                    sample_lines = []
                    for i, line in enumerate(f):
                        if i >= 5:  # 只读取前5行
                            break
                        sample_lines.append(line.strip())
                    debug_info['sample_lines'] = sample_lines

                # 解析样本行
                parsed_logs = []
                for line in sample_lines:
                    if line:
                        parsed = self._parse_log_line(line)
                        parsed_logs.append(parsed)
                debug_info['parsed_logs'] = parsed_logs
            else:
                debug_info['main_log_exists'] = False

            # 执行实际查询
            logs = self.get_logs(name=name, limit=limit)
            debug_info['query_result'] = logs
            debug_info['query_count'] = len(logs)

        except Exception as e:
            debug_info['error'] = str(e)

        return debug_info

    def get_stats(self) -> Dict[str, Any]:
        """
        获取日志统计信息

        Returns:
            统计信息字典
        """
        return {
            'level': logging.getLevelName(self.log_level),
            'format': self.log_format,
            'date_format': self.date_format,
            'max_bytes': self.max_bytes,
            'backup_count': self.backup_count,
            'log_dir': self.log_dir,
            'handlers': len(self.handlers),
            'registered_loggers': len(self._loggers),
            'active_loggers': len(self.get_loggers())
        }

# 创建全局日志管理器实例
log_manager = LogManager()
