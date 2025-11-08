"""
应用配置
"""
import os
import json
from typing import Dict, Any, Optional, Set
from pathlib import Path
from dotenv import load_dotenv
from datetime import timedelta

# 加载环境变量
load_dotenv()

class Config:
    """基础配置"""
    
    # 基本配置
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hard to guess string'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # 文件存储配置
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or 'uploads'
    MAX_CONTENT_LENGTH = 12 * 1024 * 1024 * 1024  # 允许约12GB请求体，满足10GB上传需求
    USER_STORAGE_QUOTA = 1024 * 1024 * 1024  # 用户存储配额：1GB
    FILE_CLEANUP_DAYS = 7  # 文件保留天数
    TEMP_FILE_CLEANUP_HOURS = 24  # 临时文件保留小时数
    
    # 文件类型配置
    UPLOAD_SUBDIRS = {
        'ppt': 'ppt',
        'pdf': 'pdf',
        'annotation': 'annotation',
        'temp': 'temp'
    }
    
    ALLOWED_EXTENSIONS = {
        'ppt': {'ppt', 'pptx'},
        'pdf': {'pdf'},
        'annotation': {'json', 'xml'},
        'temp': {'*'}  # 允许所有类型
    }
    
    # 阿里云OSS配置
    OSS_REGION = os.environ.get('OSS_REGION', 'cn-beijing')
    OSS_BUCKET = os.environ.get('OSS_BUCKET', 'fciai')
    
    @classmethod
    def get_oss_config(cls):
        """获取OSS配置字典"""
        return {
            'access_key_id': cls.OSS_ACCESS_KEY_ID,
            'access_key_secret': cls.OSS_ACCESS_KEY_SECRET,
            'region': cls.OSS_REGION,
            'bucket': cls.OSS_BUCKET
        }
    
    @classmethod
    def is_oss_configured(cls):
        """检查OSS是否已正确配置"""
        return bool(cls.OSS_ACCESS_KEY_ID and cls.OSS_ACCESS_KEY_SECRET)
    
    # 数据库配置
    DB_TYPE = os.environ.get('DB_TYPE') or 'mysql'
    DB_USER = os.environ.get('DB_USER') or 'root'
    DB_PASSWORD = os.environ.get('DB_PASSWORD') or 'password'
    DB_HOST = os.environ.get('DB_HOST') or 'localhost'
    DB_PORT = int(os.environ.get('DB_PORT') or 3306)
    DB_NAME = os.environ.get('DB_NAME') or 'app'
    
    # 数据库连接池配置
    DB_POOL_SIZE = int(os.environ.get('DB_POOL_SIZE') or 10)
    DB_MAX_OVERFLOW = int(os.environ.get('DB_MAX_OVERFLOW') or 20)
    DB_POOL_TIMEOUT = int(os.environ.get('DB_POOL_TIMEOUT') or 10)
    DB_POOL_RECYCLE = int(os.environ.get('DB_POOL_RECYCLE') or 3600)
    
    # Redis配置
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'
    
    # 缓存配置
    CACHE_TYPE = os.environ.get('CACHE_TYPE') or 'simple'
    CACHE_REDIS_URL = REDIS_URL
    CACHE_DEFAULT_TIMEOUT = 300
    
    # 会话配置
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    
    # 邮件配置
    MAIL_SERVER = os.environ.get('MAIL_SERVER') or 'smtp.googlemail.com'
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', 'on', '1']
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')

    # SSO配置
    SSO_ENABLED = os.environ.get('SSO_ENABLED', 'false').lower() == 'true'
    SSO_PROVIDER = os.environ.get('SSO_PROVIDER', 'oauth2')  # oauth2, saml, oidc
    SSO_AUTO_CREATE_USER = os.environ.get('SSO_AUTO_CREATE_USER', 'true').lower() == 'true'
    SSO_DEFAULT_ROLE = os.environ.get('SSO_DEFAULT_ROLE', 'user')

    # OAuth2/OIDC配置
    OAUTH2_CLIENT_ID = os.environ.get('OAUTH2_CLIENT_ID', '')
    OAUTH2_CLIENT_SECRET = os.environ.get('OAUTH2_CLIENT_SECRET', '')
    OAUTH2_AUTHORIZATION_URL = os.environ.get('OAUTH2_AUTHORIZATION_URL', '')
    OAUTH2_TOKEN_URL = os.environ.get('OAUTH2_TOKEN_URL', '')
    OAUTH2_USERINFO_URL = os.environ.get('OAUTH2_USERINFO_URL', '')
    OAUTH2_LOGOUT_URL = os.environ.get('OAUTH2_LOGOUT_URL', '')
    OAUTH2_SCOPE = os.environ.get('OAUTH2_SCOPE', 'openid profile email')
    OAUTH2_REDIRECT_URI = os.environ.get('OAUTH2_REDIRECT_URI', 'http://localhost:5000/auth/sso/callback')

    # SAML配置
    SAML_SP_ENTITY_ID = os.environ.get('SAML_SP_ENTITY_ID', 'http://localhost:5000')
    SAML_SP_ACS_URL = os.environ.get('SAML_SP_ACS_URL', 'http://localhost:5000/auth/sso/saml/acs')
    SAML_SP_SLS_URL = os.environ.get('SAML_SP_SLS_URL', 'http://localhost:5000/auth/sso/saml/sls')
    SAML_IDP_ENTITY_ID = os.environ.get('SAML_IDP_ENTITY_ID', '')
    SAML_IDP_SSO_URL = os.environ.get('SAML_IDP_SSO_URL', '')
    SAML_IDP_SLS_URL = os.environ.get('SAML_IDP_SLS_URL', '')
    SAML_IDP_X509_CERT = os.environ.get('SAML_IDP_X509_CERT', '')

    # 用户属性映射配置
    SSO_USER_MAPPING = {
        'username': os.environ.get('SSO_ATTR_USERNAME', 'preferred_username'),
        'email': os.environ.get('SSO_ATTR_EMAIL', 'email'),
        'first_name': os.environ.get('SSO_ATTR_FIRST_NAME', 'given_name'),
        'last_name': os.environ.get('SSO_ATTR_LAST_NAME', 'family_name'),
        'display_name': os.environ.get('SSO_ATTR_DISPLAY_NAME', 'name'),
        'groups': os.environ.get('SSO_ATTR_GROUPS', 'groups')
    }
    
    # 直接设置数据库URI字符串，而不是使用属性
    SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://root:password@localhost:3306/app"
    
    # 应用程序名称
    APP_NAME = os.environ.get('APP_NAME', '翻译系统')
    
    # 时区配置
    TIMEZONE = os.environ.get('TIMEZONE', 'Asia/Shanghai')
    
    @property
    def UPLOAD_PATH(self):
        """获取上传目录的绝对路径"""
        return os.path.abspath(self.UPLOAD_FOLDER)
    
    @classmethod
    def init_app(cls, app):
        """初始化应用"""
        # 确保上传目录存在
        upload_path = os.path.abspath(cls.UPLOAD_FOLDER)
        os.makedirs(upload_path, exist_ok=True)
        
        # 根据环境变量动态设置数据库URI
        db_type = os.environ.get('DB_TYPE') or cls.DB_TYPE
        db_user = os.environ.get('DB_USER') or cls.DB_USER
        db_password = os.environ.get('DB_PASSWORD') or cls.DB_PASSWORD
        db_host = os.environ.get('DB_HOST') or cls.DB_HOST
        db_port = int(os.environ.get('DB_PORT') or cls.DB_PORT)
        db_name = os.environ.get('DB_NAME') or cls.DB_NAME
        
        app.config['SQLALCHEMY_DATABASE_URI'] = f"{db_type}+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

class DevelopmentConfig(Config):
    """开发环境配置"""
    DEBUG = True
    SQLALCHEMY_ECHO = True

class TestingConfig(Config):
    """测试环境配置"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False

class ProductionConfig(Config):
    """生产环境配置"""
    # 生产环境特定配置
    pass

# 配置映射
config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}

class AppConfig:
    """配置管理器，负责加载和管理所有配置参数"""
    
    def __init__(self):
        """初始化配置管理器"""
        # 加载环境变量
        load_dotenv()
        
        # 基础配置
        self.env = os.getenv('FLASK_ENV', 'development')
        self.debug = self.env == 'development'
        self.testing = self.env == 'testing'
        
        # 服务器配置
        self.server = {
            'host': os.getenv('SERVER_HOST', '0.0.0.0'),
            'port': int(os.getenv('SERVER_PORT', '5000')),
            'workers': int(os.getenv('SERVER_WORKERS', '4'))
        }
        
        # 数据库配置
        self.database = {
            'type': os.getenv('DB_TYPE', 'sqlite'),
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': int(os.getenv('DB_PORT', '5432')),
            'database': os.getenv('DB_NAME', 'app'),
            'user': os.getenv('DB_USER', 'postgres'),
            'password': os.getenv('DB_PASSWORD', ''),
            'pool_size': int(os.getenv('DB_POOL_SIZE', '10')),
            'max_overflow': int(os.getenv('DB_MAX_OVERFLOW', '20')),
            'pool_timeout': int(os.getenv('DB_POOL_TIMEOUT', '30')),
            'pool_recycle': int(os.getenv('DB_POOL_RECYCLE', '3600'))
        }
        
        # 线程池配置
        self.thread_pool = {
            'max_workers': int(os.getenv('THREAD_POOL_MAX_WORKERS', '32')),
            'io_bound_workers': int(os.getenv('THREAD_POOL_IO_WORKERS', '24')),
            'cpu_bound_workers': int(os.getenv('THREAD_POOL_CPU_WORKERS', '8')),
            'thread_name_prefix': os.getenv('THREAD_POOL_NAME_PREFIX', 'app')
        }
        
        # 任务队列配置 - 限制最大并发翻译任务为10个
        self.task_queue = {
            'max_concurrent_tasks': int(os.getenv('TASK_QUEUE_MAX_CONCURRENT', '10')),
            'task_timeout': int(os.getenv('TASK_QUEUE_TIMEOUT', '3600')),
            'retry_times': int(os.getenv('TASK_QUEUE_RETRY_TIMES', '3'))
        }
        
        # HTTP 客户端配置
        self.http_client = {
            'max_connections': int(os.getenv('HTTP_CLIENT_MAX_CONNECTIONS', '100')),
            'default_timeout': int(os.getenv('HTTP_CLIENT_TIMEOUT', '60')),
            'retry_times': int(os.getenv('HTTP_CLIENT_RETRY_TIMES', '3')),
            'retry_delay': int(os.getenv('HTTP_CLIENT_RETRY_DELAY', '1'))
        }
        
        # 文件上传配置
        self.upload = {
            'max_file_size': int(os.getenv('UPLOAD_MAX_FILE_SIZE', str(12 * 1024 * 1024 * 1024))),  # 默认支持约12GB
            'allowed_extensions': set(os.getenv('UPLOAD_ALLOWED_EXTENSIONS', 'ppt,pptx').split(',')),
            'upload_folder': os.getenv('UPLOAD_FOLDER', 'uploads')
        }
        
        # 日志配置
        self.logging = {
            'level': os.getenv('LOG_LEVEL', 'INFO'),
            'format': os.getenv(
                'LOG_FORMAT',
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ),
            'date_format': os.getenv('LOG_DATE_FORMAT', '%Y-%m-%d %H:%M:%S'),
            'max_bytes': int(os.getenv('LOG_MAX_BYTES', '10485760')),  # 10MB
            'backup_count': int(os.getenv('LOG_BACKUP_COUNT', '5')),
            'log_dir': os.getenv('LOG_DIR', 'logs')
        }
        
        # 安全配置
        self.security = {
            'secret_key': os.getenv('SECRET_KEY', 'your-secret-key'),
            'token_expire_hours': int(os.getenv('TOKEN_EXPIRE_HOURS', '24')),
            'password_salt': os.getenv('PASSWORD_SALT', 'your-password-salt')
        }
        
        # 缓存配置
        self.cache = {
            'type': os.getenv('CACHE_TYPE', 'simple'),
            'redis_url': os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
            'default_timeout': int(os.getenv('CACHE_TIMEOUT', '300'))
        }
        
        # 初始化派生配置
        self._init_derived_config()
    
    def _init_derived_config(self):
        """初始化派生配置"""
        # 数据库 URI
        if self.database['type'] == 'sqlite':
            self.database['uri'] = f"sqlite:///{self.database['database']}.db"
        else:
            self.database['uri'] = (
                f"{self.database['type']}://"
                f"{self.database['user']}:{self.database['password']}@"
                f"{self.database['host']}:{self.database['port']}/"
                f"{self.database['database']}"
            )
        
        # 上传目录
        self.upload['upload_path'] = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            self.upload['upload_folder']
        )
        
        # 日志目录
        self.logging['log_path'] = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            self.logging['log_dir']
        )
    
    def get_flask_config(self) -> Dict[str, Any]:
        """
        获取 Flask 配置
        
        Returns:
            Flask 配置字典
        """
        return {
            'ENV': self.env,
            'DEBUG': self.debug,
            'TESTING': self.testing,
            'SECRET_KEY': self.security['secret_key'],
            'UPLOAD_FOLDER': self.upload['upload_path'],
            'MAX_CONTENT_LENGTH': self.upload['max_file_size'],
            'SQLALCHEMY_DATABASE_URI': self.database['uri'],
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
            'SQLALCHEMY_POOL_SIZE': self.database['pool_size'],
            'SQLALCHEMY_MAX_OVERFLOW': self.database['max_overflow'],
            'SQLALCHEMY_POOL_TIMEOUT': self.database['pool_timeout'],
            'SQLALCHEMY_POOL_RECYCLE': self.database['pool_recycle'],
            'CACHE_TYPE': self.cache['type'],
            'CACHE_REDIS_URL': self.cache['redis_url'],
            'CACHE_DEFAULT_TIMEOUT': self.cache['default_timeout'],
            'MAIL_SERVER': self.mail['server'],
            'MAIL_PORT': self.mail['port'],
            'MAIL_USE_TLS': self.mail['use_tls'],
            'MAIL_USERNAME': self.mail['username'],
            'MAIL_PASSWORD': self.mail['password'],
            'MAIL_DEFAULT_SENDER': self.mail['default_sender']
        }
    
    def save_env_file(self, path: Optional[str] = None) -> None:
        """
        保存配置到 .env 文件
        
        Args:
            path: 文件路径，默认为项目根目录
        """
        if path is None:
            path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
        
        # 构建环境变量
        env_vars = {
            # 服务器配置
            'FLASK_ENV': self.env,
            'SERVER_HOST': self.server['host'],
            'SERVER_PORT': str(self.server['port']),
            'SERVER_WORKERS': str(self.server['workers']),
            
            # 数据库配置
            'DB_TYPE': self.database['type'],
            'DB_HOST': self.database['host'],
            'DB_PORT': str(self.database['port']),
            'DB_NAME': self.database['database'],
            'DB_USER': self.database['user'],
            'DB_PASSWORD': self.database['password'],
            'DB_POOL_SIZE': str(self.database['pool_size']),
            'DB_MAX_OVERFLOW': str(self.database['max_overflow']),
            'DB_POOL_TIMEOUT': str(self.database['pool_timeout']),
            'DB_POOL_RECYCLE': str(self.database['pool_recycle']),
            
            # 线程池配置
            'THREAD_POOL_MAX_WORKERS': str(self.thread_pool['max_workers']),
            'THREAD_POOL_IO_WORKERS': str(self.thread_pool['io_bound_workers']),
            'THREAD_POOL_CPU_WORKERS': str(self.thread_pool['cpu_bound_workers']),
            'THREAD_POOL_NAME_PREFIX': self.thread_pool['thread_name_prefix'],
            
            # 任务队列配置
            'TASK_QUEUE_MAX_CONCURRENT': str(self.task_queue['max_concurrent_tasks']),
            'TASK_QUEUE_TIMEOUT': str(self.task_queue['task_timeout']),
            'TASK_QUEUE_RETRY_TIMES': str(self.task_queue['retry_times']),
            
            # HTTP 客户端配置
            'HTTP_CLIENT_MAX_CONNECTIONS': str(self.http_client['max_connections']),
            'HTTP_CLIENT_TIMEOUT': str(self.http_client['default_timeout']),
            'HTTP_CLIENT_RETRY_TIMES': str(self.http_client['retry_times']),
            'HTTP_CLIENT_RETRY_DELAY': str(self.http_client['retry_delay']),
            
            # 文件上传配置
            'UPLOAD_MAX_FILE_SIZE': str(self.upload['max_file_size']),
            'UPLOAD_ALLOWED_EXTENSIONS': ','.join(self.upload['allowed_extensions']),
            'UPLOAD_FOLDER': self.upload['upload_folder'],
            
            # 日志配置
            'LOG_LEVEL': self.logging['level'],
            'LOG_FORMAT': self.logging['format'],
            'LOG_DATE_FORMAT': self.logging['date_format'],
            'LOG_MAX_BYTES': str(self.logging['max_bytes']),
            'LOG_BACKUP_COUNT': str(self.logging['backup_count']),
            'LOG_DIR': self.logging['log_dir'],
            
            # 安全配置
            'SECRET_KEY': self.security['secret_key'],
            'TOKEN_EXPIRE_HOURS': str(self.security['token_expire_hours']),
            'PASSWORD_SALT': self.security['password_salt'],
            
            # 缓存配置
            'CACHE_TYPE': self.cache['type'],
            'REDIS_URL': self.cache['redis_url'],
            'CACHE_TIMEOUT': str(self.cache['default_timeout']),
            
            # 邮件配置
            'MAIL_SERVER': self.mail['server'],
            'MAIL_PORT': str(self.mail['port']),
            'MAIL_USE_TLS': str(self.mail['use_tls']).lower(),
            'MAIL_USERNAME': self.mail['username'],
            'MAIL_PASSWORD': self.mail['password'],
            'MAIL_DEFAULT_SENDER': self.mail['default_sender']
        }
        
        # 写入文件
        with open(path, 'w', encoding='utf-8') as f:
            for key, value in env_vars.items():
                f.write(f"{key}={value}\n")
    
    def load_env_file(self, path: Optional[str] = None) -> None:
        """
        从 .env 文件加载配置
        
        Args:
            path: 文件路径，默认为项目根目录
        """
        if path is None:
            path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
        
        # 加载环境变量
        load_dotenv(path)
        
        # 重新初始化配置
        self.__init__()
    
    def to_dict(self) -> Dict[str, Any]:
        """
        将配置转换为字典
        
        Returns:
            配置字典
        """
        return {
            'env': self.env,
            'debug': self.debug,
            'testing': self.testing,
            'server': self.server,
            'database': self.database,
            'thread_pool': self.thread_pool,
            'task_queue': self.task_queue,
            'http_client': self.http_client,
            'upload': self.upload,
            'logging': self.logging,
            'security': self.security,
            'cache': self.cache,
            'mail': self.mail
        }
    
    def to_json(self, path: Optional[str] = None) -> None:
        """
        将配置保存为 JSON 文件
        
        Args:
            path: 文件路径，默认为项目根目录下的 config.json
        """
        if path is None:
            path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
    
    @classmethod
    def from_json(cls, path: str) -> 'AppConfig':
        """
        从 JSON 文件加载配置
        
        Args:
            path: 文件路径
            
        Returns:
            配置实例
        """
        with open(path, 'r', encoding='utf-8') as f:
            config_dict = json.load(f)
        
        instance = cls()
        for key, value in config_dict.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        
        instance._init_derived_config()
        return instance

# 创建全局配置实例
app_config = AppConfig()

# 加载.env文件
load_dotenv()

def _parse_bool(value: str) -> bool:
    """解析布尔值的环境变量"""
    return value.lower() in ('true', '1', 'yes', 'on')

def _parse_set(value: str) -> Set[str]:
    """解析集合类型的环境变量"""
    return set(x.strip() for x in value.split(','))

def _get_env_int(key: str, default: int) -> int:
    """获取整数类型的环境变量"""
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default

# 线程池配置
THREAD_POOL_CONFIG = {
    'max_workers': _get_env_int('MAX_WORKERS', 32),
    'io_bound_workers': _get_env_int('IO_BOUND_WORKERS', 24),
    'cpu_bound_workers': _get_env_int('CPU_BOUND_WORKERS', 8),
    'thread_name_prefix': os.getenv('THREAD_NAME_PREFIX', 'ppt_system')
}

# 任务队列配置 - 限制最大并发翻译任务为10个
TASK_QUEUE_CONFIG = {
    'max_concurrent_tasks': _get_env_int('MAX_CONCURRENT_TASKS', 10),
    'task_timeout': _get_env_int('TASK_TIMEOUT', 3600),
    'retry_times': _get_env_int('TASK_RETRY_TIMES', 3)
}

# HTTP客户端配置
HTTP_CLIENT_CONFIG = {
    'max_connections': _get_env_int('MAX_CONNECTIONS', 100),
    'default_timeout': _get_env_int('HTTP_TIMEOUT', 60),
    'retry_times': _get_env_int('HTTP_RETRY_TIMES', 3)
}

# 文件上传配置
UPLOAD_CONFIG = {
    'max_file_size': _get_env_int('MAX_FILE_SIZE', 12 * 1024 * 1024 * 1024),
    'allowed_extensions': _parse_set(os.getenv('ALLOWED_EXTENSIONS', 'ppt,pptx')),
    'upload_folder': os.getenv('UPLOAD_FOLDER', 'uploads')
}

# 日志配置
LOG_CONFIG = {
    'level': os.getenv('LOG_LEVEL', 'INFO'),
    'format': os.getenv('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
    'date_format': os.getenv('LOG_DATE_FORMAT', '%Y-%m-%d %H:%M:%S'),
    'max_bytes': _get_env_int('LOG_MAX_BYTES', 10 * 1024 * 1024),
    'backup_count': _get_env_int('LOG_BACKUP_COUNT', 5)
}

# 数据库配置
DB_CONFIG = {
    'type': os.getenv('DB_TYPE', 'mysql'),
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': _get_env_int('DB_PORT', 3306),
    'database': os.getenv('DB_NAME', 'ppt_translate_db'),
    'user': os.getenv('DB_USER', 'ppt_user'),
    'password': os.getenv('DB_PASSWORD', 'your_password'),
    'pool_size': _get_env_int('DB_POOL_SIZE', 10),
    'max_overflow': _get_env_int('DB_MAX_OVERFLOW', 20),
    'pool_timeout': _get_env_int('DB_POOL_TIMEOUT', 30),
    'pool_recycle': _get_env_int('DB_POOL_RECYCLE', 3600),
    'connect_timeout': _get_env_int('DB_CONNECT_TIMEOUT', 10),
    'use_ssl': _parse_bool(os.getenv('DB_USE_SSL', 'false'))
}

# 服务器配置
SERVER_CONFIG = {
    'host': os.getenv('SERVER_HOST', '0.0.0.0'),
    'port': _get_env_int('SERVER_PORT', 5000),
    'workers': _get_env_int('SERVER_WORKERS', 2)
}

# 构建数据库URI
def get_database_uri() -> str:
    """获取数据库URI"""
    if DB_CONFIG['type'] == 'mysql':
        # 构建MySQL连接URI
        return (f"mysql+pymysql://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
                f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    else:
        # 默认使用SQLite
        return 'sqlite:///app.db'

# SQLAlchemy配置
SQLALCHEMY_CONFIG = {
    'SQLALCHEMY_DATABASE_URI': get_database_uri(),
    'SQLALCHEMY_TRACK_MODIFICATIONS': False,
    'SQLALCHEMY_ENGINE_OPTIONS': {
        'pool_size': DB_CONFIG['pool_size'],
        'max_overflow': DB_CONFIG['max_overflow'],
        'pool_timeout': DB_CONFIG['pool_timeout'],
        'pool_recycle': DB_CONFIG['pool_recycle'],
        'connect_args': {
            'connect_timeout': DB_CONFIG['connect_timeout']
        }
    }
}

# 如果启用SSL，添加SSL配置
if DB_CONFIG['use_ssl']:
    SQLALCHEMY_CONFIG['SQLALCHEMY_ENGINE_OPTIONS']['connect_args']['ssl'] = {
        'ssl_mode': 'REQUIRED'
    }

# 导出配置（改名为app_settings避免与config冲突）
app_settings: Dict[str, Any] = {
    'THREAD_POOL': THREAD_POOL_CONFIG,
    'TASK_QUEUE': TASK_QUEUE_CONFIG,
    'HTTP_CLIENT': HTTP_CLIENT_CONFIG,
    'UPLOAD': UPLOAD_CONFIG,
    'LOG': LOG_CONFIG,
    'DATABASE': DB_CONFIG,
    'SERVER': SERVER_CONFIG,
    'SQLALCHEMY': SQLALCHEMY_CONFIG
}

# 设置上传文件夹路径
basedir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 获取项目根目录
UPLOAD_FOLDER = os.path.join(basedir, 'uploads')  # 在项目根目录下创建uploads文件夹

print(f"Debug: Upload folder path: {UPLOAD_FOLDER}")

# 确保上传文件夹存在
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
    print(f"Debug: Created upload folder: {UPLOAD_FOLDER}")

PROVINCE_URLS = {
    'ah': 'https://amr.ah.gov.cn/',
    'bj': 'https://scjgj.beijing.gov.cn/',
    # ...
}

DOWNLOAD_SETTINGS = {
    'retry_times': 3,
    'timeout': 30,
    'chunk_size': 8192
} 
