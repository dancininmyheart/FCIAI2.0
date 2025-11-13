#!/usr/bin/env python3
"""
快速重置admin密码工具
简化版本，用于紧急情况下快速重置admin密码
"""
import sys
import mysql.connector
from werkzeug.security import generate_password_hash

# 数据库配置
DB_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': 'root',
    'database': 'ppt_translation',
    'charset': 'utf8mb4'
}

def reset_admin_password(new_password='admin123'):
    """重置admin密码"""
    try:
        print("🔄 正在重置admin密码...")
        
        # 连接数据库
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor()
        
        # 检查admin用户是否存在
        cursor.execute("SELECT id, username FROM users WHERE username = 'admin'")
        admin_user = cursor.fetchone()
        
        if not admin_user:
            print("❌ 未找到admin用户")
            cursor.close()
            connection.close()
            return False
        
        # 生成新密码哈希
        password_hash = generate_password_hash(new_password)
        
        # 更新密码
        cursor.execute(
            "UPDATE users SET password = %s WHERE username = 'admin'",
            (password_hash,)
        )
        
        connection.commit()
        cursor.close()
        connection.close()
        
        print("  admin密码重置成功！")
        print(f"   新密码: {new_password}")
        print("   请立即登录并修改为更安全的密码")
        return True
        
    except mysql.connector.Error as e:
        print(f"❌ 数据库操作失败: {e}")
        return False
    except Exception as e:
        print(f"❌ 重置失败: {e}")
        return False

def main():
    """主函数"""
    print("🔐 Admin密码快速重置工具")
    print("=" * 40)
    
    if len(sys.argv) == 1:
        # 默认密码
        new_password = 'admin123'
        print(f"使用默认密码: {new_password}")
    elif len(sys.argv) == 2:
        # 自定义密码
        new_password = sys.argv[1]
        print(f"使用自定义密码: {new_password}")
    else:
        print("用法:")
        print("  python reset_admin.py              # 重置为默认密码 admin123")
        print("  python reset_admin.py <新密码>     # 重置为指定密码")
        return
    
    # 密码长度检查
    if len(new_password) < 6:
        print("❌ 密码长度至少6个字符")
        return
    
    # 执行重置
    success = reset_admin_password(new_password)
    
    if success:
        print("\n🎉 重置完成！")
        print("现在可以使用以下信息登录:")
        print(f"  用户名: admin")
        print(f"  密码: {new_password}")
    else:
        print("\n❌ 重置失败！请检查数据库配置和连接")

if __name__ == "__main__":
    main()
