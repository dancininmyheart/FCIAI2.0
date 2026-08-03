#!/usr/bin/env python3
"""
一键数据库创建脚本
自动创建数据库、表结构并初始化基础数据
"""
import os
import sys
import logging
import pymysql
from datetime import datetime

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('database_setup.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# 数据库配置
load_dotenv()
DB_TYPE = os.environ.get('DB_TYPE') or 'mysql'
DB_USER = os.environ.get('DB_USER') or 'root'
DB_PASSWORD = os.environ.get('DB_PASSWORD') or 'password'
DB_HOST = os.environ.get('DB_HOST') or 'localhost'
DB_PORT = int(os.environ.get('DB_PORT') or 3306)
DB_NAME = os.environ.get('DB_NAME') or 'app'
# 数据库配置
DB_CONFIG = {
    'host': DB_HOST,
    'port': DB_PORT,
    'user': DB_USER,
    'password': DB_PASSWORD,
    'database': DB_NAME,
    'charset': 'utf8mb4'
}

def create_database():
    """创建数据库"""
    try:
        # 连接MySQL服务器（不指定数据库）
        connection = pymysql.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            charset=DB_CONFIG['charset']
        )

        with connection.cursor() as cursor:
            # 创建数据库
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_CONFIG['database']}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            logger.info(f"数据库 '{DB_CONFIG['database']}' 创建成功")

        connection.close()
        return True

    except Exception as e:
        logger.error(f"创建数据库失败: {str(e)}")
        return False

def create_tables():
    """创建数据表"""
    try:
        # 连接到指定数据库
        connection = pymysql.connect(**DB_CONFIG)

        with connection.cursor() as cursor:
            # 创建角色表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS `role` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,
                    `name` VARCHAR(80) NOT NULL UNIQUE,
                    INDEX `idx_role_name` (`name`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # 创建权限表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS `permission` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,
                    `name` VARCHAR(80) NOT NULL UNIQUE,
                    `description` VARCHAR(255),
                    INDEX `idx_permission_name` (`name`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # 创建角色权限关联表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS `role_permissions` (
                    `role_id` INT NOT NULL,
                    `permission_id` INT NOT NULL,
                    PRIMARY KEY (`role_id`, `permission_id`),
                    FOREIGN KEY (`role_id`) REFERENCES `role`(`id`) ON DELETE CASCADE,
                    FOREIGN KEY (`permission_id`) REFERENCES `permission`(`id`) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # 创建用户表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS `users` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,
                    `username` VARCHAR(80) NOT NULL UNIQUE,
                    `password` VARCHAR(255) NOT NULL,
                    `email` VARCHAR(120) UNIQUE NULL,
                    `first_name` VARCHAR(50) NULL,
                    `last_name` VARCHAR(50) NULL,
                    `display_name` VARCHAR(100) NULL,
                    `sso_provider` VARCHAR(50) NULL COMMENT 'SSO提供者类型',
                    `sso_subject` VARCHAR(255) NULL COMMENT 'SSO提供者的用户ID',
                    `last_login` DATETIME NULL COMMENT '最后登录时间',
                    `role_id` INT,
                    `status` VARCHAR(20) DEFAULT 'pending' COMMENT '用户状态: pending, approved, rejected',
                    `register_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
                    `approve_time` DATETIME NULL,
                    `approve_user_id` INT NULL,
                    INDEX `idx_username` (`username`),
                    INDEX `idx_email` (`email`),
                    INDEX `idx_status` (`status`),
                    INDEX `idx_sso_provider` (`sso_provider`),
                    INDEX `idx_sso_subject` (`sso_subject`),
                    INDEX `idx_last_login` (`last_login`),
                    FOREIGN KEY (`role_id`) REFERENCES `role`(`id`) ON DELETE SET NULL,
                    FOREIGN KEY (`approve_user_id`) REFERENCES `users`(`id`) ON DELETE SET NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # 创建上传记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS `upload_records` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,
                    `user_id` INT NOT NULL,
                    `filename` VARCHAR(255) NOT NULL,
                    `stored_filename` VARCHAR(255) NOT NULL,
                    `file_path` VARCHAR(255) NOT NULL,
                    `file_size` INT NOT NULL,
                    `upload_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
                    `status` VARCHAR(20) DEFAULT 'pending',
                    `error_message` VARCHAR(255),
                    INDEX `idx_user_id` (`user_id`),
                    INDEX `idx_upload_time` (`upload_time`),
                    INDEX `idx_status` (`status`),
                    FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # 创建翻译记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS `translation` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,
                    `english` VARCHAR(500) NOT NULL,
                    `chinese` VARCHAR(500) NOT NULL,
                    `dutch` VARCHAR(500),
                    `category` VARCHAR(1000),
                    `user_id` INT,
                    `is_public` TINYINT(1) DEFAULT 0,
                    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
                    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX `idx_user_id` (`user_id`),
                    INDEX `idx_english` (`english`(100)),
                    FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # 创建停止词表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS `stop_words` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,
                    `word` VARCHAR(100) NOT NULL,
                    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
                    `user_id` INT NOT NULL,
                    INDEX `idx_word` (`word`),
                    INDEX `idx_user_id` (`user_id`),
                    UNIQUE KEY `unique_word_per_user` (`word`, `user_id`),
                    FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

            # 创建成分表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS `ingredient` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,
                    `food_name` VARCHAR(200) NOT NULL,
                    `ingredient` TEXT,
                    `path` VARCHAR(500),
                    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
                    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX `idx_food_name` (`food_name`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

        connection.commit()
        connection.close()
        logger.info("数据表创建成功")
        return True

    except Exception as e:
        logger.error(f"创建数据表失败: {str(e)}")
        return False

def init_basic_data():
    """初始化基础数据"""
    try:
        connection = pymysql.connect(**DB_CONFIG)

        with connection.cursor() as cursor:
            # 插入基础权限
            permissions = [
                ('admin', '管理员权限'),
                ('user_management', '用户管理'),
                ('file_upload', '文件上传'),
                ('translation', '翻译功能'),
                ('pdf_annotation', 'PDF注释'),
                ('view_logs', '查看日志'),
                ('dictionary_management', '词库管理'),
                ('stop_words_management', '停翻词管理'),
                ('ingredient_search', '成分搜索'),
                ('batch_process', '批量处理'),
                ('sso_login', 'SSO登录'),
                ('download_files', '文件下载')
            ]

            for name, desc in permissions:
                cursor.execute(
                    "INSERT IGNORE INTO `permission` (`name`, `description`) VALUES (%s, %s)",
                    (name, desc)
                )

            # 插入基础角色
            roles = [
                ('admin', '管理员'),
                ('user', '普通用户')
            ]

            for name, _ in roles:
                cursor.execute(
                    "INSERT IGNORE INTO `role` (`name`) VALUES (%s)",
                    (name,)
                )

            # 为管理员角色分配所有权限
            cursor.execute("SELECT id FROM `role` WHERE name = 'admin'")
            admin_role_id = cursor.fetchone()[0]

            cursor.execute("SELECT id FROM `permission`")
            permission_ids = [row[0] for row in cursor.fetchall()]

            for perm_id in permission_ids:
                cursor.execute(
                    "INSERT IGNORE INTO `role_permissions` (`role_id`, `permission_id`) VALUES (%s, %s)",
                    (admin_role_id, perm_id)
                )

            # 为普通用户角色分配基础权限
            cursor.execute("SELECT id FROM `role` WHERE name = 'user'")
            user_role_id = cursor.fetchone()[0]

            basic_permissions = [
                'file_upload', 'translation', 'pdf_annotation',
                'dictionary_management', 'stop_words_management',
                'ingredient_search', 'download_files'
            ]
            for perm_name in basic_permissions:
                cursor.execute("SELECT id FROM `permission` WHERE name = %s", (perm_name,))
                perm_result = cursor.fetchone()
                if perm_result:
                    cursor.execute(
                        "INSERT IGNORE INTO `role_permissions` (`role_id`, `permission_id`) VALUES (%s, %s)",
                        (user_role_id, perm_result[0])
                    )

            # 创建默认管理员账户
            admin_password = generate_password_hash('admin123')
            cursor.execute(
                """INSERT IGNORE INTO `users` (`username`, `password`, `role_id`, `status`, `approve_time`)
                   VALUES (%s, %s, %s, 'approved', %s)""",
                ('admin', admin_password, admin_role_id, datetime.now())
            )

        connection.commit()
        connection.close()
        logger.info("基础数据初始化成功")
        return True

    except Exception as e:
        logger.error(f"初始化基础数据失败: {str(e)}")
        return False

def update_table_structure():
    """检查并更新表结构"""
    try:
        connection = pymysql.connect(**DB_CONFIG)
        
        with connection.cursor() as cursor:
            # 检查并添加缺失的列
            # 检查 translation 表结构
            cursor.execute("DESCRIBE translation")
            columns = cursor.fetchall()
            column_names = [column[0] for column in columns]
            
            # 检查 is_public 列
            if 'is_public' not in column_names:
                try:
                    cursor.execute("ALTER TABLE translation ADD COLUMN is_public TINYINT(1) DEFAULT 0")
                    logger.info("已添加 is_public 列到 translation 表")
                except Exception as e:
                    logger.error(f"添加 is_public 列时出错: {e}")
            else:
                # 更新所有 NULL 值为 0 (False)
                try:
                    cursor.execute("UPDATE translation SET is_public = 0 WHERE is_public IS NULL")
                    affected_rows = cursor.rowcount
                    if affected_rows > 0:
                        logger.info(f"已更新 {affected_rows} 条记录中的 is_public 列 NULL 值为 0")
                except Exception as e:
                    logger.error(f"更新 is_public 列中的 NULL 值时出错: {e}")
                
                # 检查 is_public 列是否有默认值
                for column in columns:
                    if column[0] == 'is_public' and 'DEFAULT' not in str(column[4]):
                        try:
                            cursor.execute("ALTER TABLE translation MODIFY COLUMN is_public TINYINT(1) DEFAULT 0")
                            logger.info("已为 is_public 列设置默认值")
                        except Exception as e:
                            logger.error(f"为 is_public 列设置默认值时出错: {e}")
            
            # 检查 user_id 列是否允许 NULL
            for column in columns:
                if column[0] == 'user_id' and 'YES' not in column:
                    try:
                        cursor.execute("ALTER TABLE translation MODIFY COLUMN user_id INT NULL")
                        logger.info("已修改 user_id 列允许 NULL 值")
                    except Exception as e:
                        logger.error(f"修改 user_id 列时出错: {e}")
            
        connection.commit()
        connection.close()
        return True
        
    except Exception as e:
        logger.error(f"更新表结构失败: {str(e)}")
        return False

def test_database_connection():
    """测试数据库连接"""
    try:
        connection = pymysql.connect(**DB_CONFIG)

        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            version = cursor.fetchone()[0]
            logger.info(f"数据库连接成功，MySQL版本: {version}")

            # 检查表是否存在
            cursor.execute("SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]
            logger.info(f"数据库中的表: {', '.join(tables)}")

            # 检查管理员账户
            cursor.execute("SELECT username, status FROM users WHERE role_id = (SELECT id FROM role WHERE name = 'admin')")
            admin_users = cursor.fetchall()
            if admin_users:
                logger.info(f"管理员账户: {[user[0] for user in admin_users]}")

        connection.close()
        return True

    except Exception as e:
        logger.error(f"数据库连接测试失败: {str(e)}")
        return False




def create_directories():
    """创建必要的目录结构"""
    directories = [
        'uploads',
        'uploads/temp',
        'uploads/translated',
        'uploads/pdf_annotations',
        'logs',
        'static/uploads',
        'static/temp',
        'instance'
    ]

    for directory in directories:
        try:
            os.makedirs(directory, exist_ok=True)
            print(f"  创建目录: {directory}")
        except Exception as e:
            print(f"❌ 创建目录失败 {directory}: {e}")


def create_env_file():
    """创建环境变量文件"""
    env_content = f"""# 数据库配置
DB_TYPE=mysql
DB_HOST={DB_CONFIG['host']}
DB_PORT={DB_CONFIG['port']}
DB_USER={DB_CONFIG['user']}
DB_PASSWORD={DB_CONFIG['password']}
DB_NAME={DB_CONFIG['database']}

# Flask配置
SECRET_KEY=your-secret-key-here-change-this-in-production
FLASK_ENV=production
FLASK_DEBUG=False

# 上传配置
UPLOAD_FOLDER=uploads
MAX_CONTENT_LENGTH=52428800

# 邮件配置
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-email-password

# API配置
DASHSCOPE_API_KEY=your-dashscope-api-key
QWEN_API_KEY=your-dashscope-api-key
QWEN_MODEL=qwen3.7-plus

# 任务队列配置 - 限制最大并发翻译任务为10个
TASK_QUEUE_MAX_CONCURRENT=10
TASK_QUEUE_TIMEOUT=3600
TASK_QUEUE_RETRY_TIMES=3
MAX_CONCURRENT_TASKS=10
TASK_TIMEOUT=3600
TASK_RETRY_TIMES=3

# SSO配置
SSO_ENABLED=False
SSO_PROVIDER=authing
SSO_APP_ID=your-sso-app-id
SSO_APP_SECRET=your-sso-app-secret
SSO_DOMAIN=https://your-sso-domain.com
SSO_CALLBACK_URL=http://localhost:5000/auth/sso/callback

# Redis配置（可选）
REDIS_URL=redis://localhost:6379/0

# 日志配置
LOG_LEVEL=INFO
SQLALCHEMY_ECHO=false
LOG_LEVEL_SQLALCHEMY=WARNING
LOG_FILE=app.log
LOG_MAX_SIZE=10485760
LOG_BACKUP_COUNT=5

# 文件清理配置
CLEANUP_ENABLED=True
CLEANUP_DAYS=30

# 翻译配置
TRANSLATION_TIMEOUT=300
TRANSLATION_MAX_RETRIES=3
PPTX_XML_ENGINE=structured_v2
PPTX_XML_RUNTIME_FALLBACK=0
PPTX_SEMANTIC_QA_MODE=enforce
PPTX_XML_AUTOFIT_POLICY=editable

# PDF配置
PDF_MAX_SIZE=52428800
PDF_ALLOWED_EXTENSIONS=pdf

# PPT配置
PPT_MAX_SIZE=52428800
PPT_ALLOWED_EXTENSIONS=ppt,pptx
"""

    try:
        with open('.env', 'w', encoding='utf-8') as f:
            f.write(env_content)
        logger.info("环境变量文件 .env 创建成功")
        return True
    except Exception as e:
        logger.error(f"创建环境变量文件失败: {str(e)}")
        return False

def create_directories():
    """创建必要的目录"""
    directories = [
        'uploads',
        'uploads/temp',
        'uploads/translated',
        'uploads/pdf_annotations',
        'uploads/ppt',
        'uploads/pdf',
        'uploads/annotation',
        'logs',
        'static/uploads',
        'static/temp',
        'instance'
    ]

    try:
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
            logger.info(f"目录创建成功: {directory}")
        return True
    except Exception as e:
        logger.error(f"创建目录失败: {str(e)}")
        return False

def main():
    """主函数"""
    print("=" * 60)
    print("PPT翻译系统 - 一键数据库创建脚本")
    print("=" * 60)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 显示配置信息
    print(f"\n数据库配置:")
    print(f"  主机: {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print(f"  用户: {DB_CONFIG['user']}")
    print(f"  数据库: {DB_CONFIG['database']}")

    # 确认执行
    confirm = input(f"\n确认使用以上配置创建数据库? (y/N): ").strip().lower()
    if confirm != 'y':
        print("操作已取消")
        return False

    success_count = 0
    total_steps = 7

    print(f"\n开始执行数据库创建流程...")

    # 步骤1: 创建数据库
    print(f"\n[1/{total_steps}] 创建数据库...")
    if create_database():
        success_count += 1
        print("  数据库创建成功")
    else:
        print("❌ 数据库创建失败")

    # 步骤2: 创建数据表
    print(f"\n[2/{total_steps}] 创建数据表...")
    if create_tables():
        success_count += 1
        print("  数据表创建成功")
    else:
        print("❌ 数据表创建失败")

    # 步骤3: 初始化基础数据
    print(f"\n[3/{total_steps}] 初始化基础数据...")
    if init_basic_data():
        success_count += 1
        print("  基础数据初始化成功")
    else:
        print("❌ 基础数据初始化失败")

    # 步骤4: 更新表结构
    print(f"\n[4/{total_steps}] 更新表结构...")
    if update_table_structure():
        success_count += 1
        print("  表结构更新成功")
    else:
        print("❌ 表结构更新失败")

    # 步骤5: 测试数据库连接
    print(f"\n[5/{total_steps}] 测试数据库连接...")
    if test_database_connection():
        success_count += 1
        print("  数据库连接测试成功")
    else:
        print("❌ 数据库连接测试失败")


    # 总结结果
    print(f"\n" + "=" * 60)
    print("数据库创建完成")
    print("=" * 60)
    print(f"成功步骤: {success_count}/{total_steps}")

    if success_count == total_steps:
        print("🎉 所有步骤执行成功！")
        print(f"\n  数据库设置完成:")
        print(f"   - 数据库: {DB_CONFIG['database']}")
        print(f"   - 管理员账户: admin")
        print(f"   - 管理员密码: admin123")
        print(f"   - 环境配置: .env")
        print(f"   - 日志文件: database_setup.log")

        print(f"\n🚀 下一步操作:")
        print(f"   1. 检查并修改 .env 文件中的配置")
        print(f"   2. 安装Python依赖: pip install -r requirements.txt")
        print(f"   3. 启动应用: python app.py")
        print(f"   4. 访问系统并使用管理员账户登录")

        return True
    else:
        print("⚠️ 部分步骤执行失败，请检查日志文件")
        print("请解决问题后重新运行脚本")
        return False

if __name__ == "__main__":
    try:
        success = main()
        input(f"\n按回车键退出...")
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print(f"\n操作被用户中断")
        sys.exit(1)
    except Exception as e:
        logger.error(f"脚本执行异常: {str(e)}")
        print(f"脚本执行异常: {str(e)}")
        input(f"按回车键退出...")
        sys.exit(1)
