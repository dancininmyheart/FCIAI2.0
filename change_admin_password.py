#!/usr/bin/env python3
"""
Admin密码修改工具
命令行工具，用于修改admin用户密码
"""
import os
import sys
import getpass
import mysql.connector
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash
from datetime import datetime
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

def print_banner():
    """打印工具横幅"""
    print("=" * 60)
    print("🔐 PPT翻译系统 - Admin密码修改工具")
    print("=" * 60)
    print()

def validate_password(password):
    """验证密码强度"""
    if len(password) < 6:
        return False, "密码长度至少6个字符"
    
    if len(password) < 8:
        print("⚠️ 建议：密码长度至少8个字符以提高安全性")
    
    # 检查密码复杂度
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password)
    
    complexity_score = sum([has_upper, has_lower, has_digit, has_special])
    
    if complexity_score < 2:
        print("⚠️ 建议：密码包含大小写字母、数字和特殊字符以提高安全性")
    
    return True, "密码验证通过"

def test_database_connection():
    """测试数据库连接"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor()
        cursor.execute("SELECT VERSION()")
        version = cursor.fetchone()
        cursor.close()
        connection.close()
        print(f"  数据库连接成功，MySQL版本: {version[0]}")
        return True
    except mysql.connector.Error as e:
        print(f"❌ 数据库连接失败: {e}")
        print("\n💡 请检查：")
        print("  1. MySQL服务是否启动")
        print("  2. 数据库配置是否正确")
        print("  3. 数据库用户权限是否足够")
        return False

def find_admin_user():
    """查找admin用户"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # 查找admin用户
        cursor.execute("SELECT * FROM users WHERE username = 'admin'")
        admin_user = cursor.fetchone()
        
        cursor.close()
        connection.close()
        
        if admin_user:
            print(f"  找到admin用户:")
            print(f"   用户ID: {admin_user['id']}")
            print(f"   用户名: {admin_user['username']}")
            print(f"   邮箱: {admin_user['email'] or '未设置'}")
            print(f"   状态: {admin_user['status']}")
            print(f"   注册时间: {admin_user['register_time']}")
            if admin_user['sso_provider']:
                print(f"   SSO提供者: {admin_user['sso_provider']}")
                print("⚠️ 警告: 这是一个SSO用户，修改密码可能影响SSO登录")
            return admin_user
        else:
            print("❌ 未找到admin用户")
            print("\n💡 可能的原因：")
            print("  1. admin用户尚未创建")
            print("  2. 用户名不是'admin'")
            print("  3. 数据库表结构不正确")
            return None
            
    except mysql.connector.Error as e:
        print(f"❌ 查找admin用户失败: {e}")
        return None

def change_admin_password(admin_user, new_password):
    """修改admin用户密码"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor()
        
        # 生成密码哈希
        password_hash = generate_password_hash(new_password)
        
        # 更新密码
        cursor.execute(
            "UPDATE users SET password = %s WHERE id = %s",
            (password_hash, admin_user['id'])
        )
        
        connection.commit()
        cursor.close()
        connection.close()
        
        print("  admin密码修改成功！")
        print(f"   用户: {admin_user['username']}")
        print(f"   修改时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return True
        
    except mysql.connector.Error as e:
        print(f"❌ 修改密码失败: {e}")
        return False

def interactive_mode():
    """交互式模式"""
    print("🔧 交互式密码修改模式")
    print("-" * 30)
    
    # 测试数据库连接
    print("\n📡 步骤 1: 测试数据库连接")
    if not test_database_connection():
        return False
    
    # 查找admin用户
    print("\n🔍 步骤 2: 查找admin用户")
    admin_user = find_admin_user()
    if not admin_user:
        return False
    
    # 确认修改
    print(f"\n❓ 确认要修改用户 '{admin_user['username']}' 的密码吗？")
    confirm = input("请输入 'yes' 确认: ").strip().lower()
    if confirm != 'yes':
        print("❌ 操作已取消")
        return False
    
    # 输入新密码
    print("\n🔑 步骤 3: 设置新密码")
    while True:
        try:
            new_password = getpass.getpass("请输入新密码: ")
            if not new_password:
                print("❌ 密码不能为空，请重新输入")
                continue
            
            # 验证密码
            is_valid, message = validate_password(new_password)
            if not is_valid:
                print(f"❌ {message}")
                continue
            
            # 确认密码
            confirm_password = getpass.getpass("请确认新密码: ")
            if new_password != confirm_password:
                print("❌ 两次输入的密码不一致，请重新输入")
                continue
            
            break
            
        except KeyboardInterrupt:
            print("\n❌ 操作已取消")
            return False
    
    # 最终确认
    print(f"\n⚠️ 最终确认: 即将修改用户 '{admin_user['username']}' 的密码")
    final_confirm = input("请输入 'CONFIRM' 确认修改: ").strip()
    if final_confirm != 'CONFIRM':
        print("❌ 操作已取消")
        return False
    
    # 修改密码
    print("\n🔄 步骤 4: 修改密码")
    return change_admin_password(admin_user, new_password)

def command_line_mode(new_password):
    """命令行模式"""
    print("⚡ 命令行密码修改模式")
    print("-" * 30)
    
    # 验证密码
    is_valid, message = validate_password(new_password)
    if not is_valid:
        print(f"❌ {message}")
        return False
    
    # 测试数据库连接
    if not test_database_connection():
        return False
    
    # 查找admin用户
    admin_user = find_admin_user()
    if not admin_user:
        return False
    
    # 修改密码
    return change_admin_password(admin_user, new_password)

def show_help():
    """显示帮助信息"""
    print("📖 使用说明:")
    print("-" * 30)
    print("1. 交互式模式:")
    print("   python change_admin_password.py")
    print()
    print("2. 命令行模式:")
    print("   python change_admin_password.py --password <新密码>")
    print("   python change_admin_password.py -p <新密码>")
    print()
    print("3. 显示帮助:")
    print("   python change_admin_password.py --help")
    print("   python change_admin_password.py -h")
    print()
    print("📋 密码要求:")
    print("  - 长度至少6个字符（建议8个字符以上）")
    print("  - 建议包含大小写字母、数字和特殊字符")
    print("  - 避免使用常见密码或个人信息")
    print()
    print("🔒 安全提醒:")
    print("  - 请在安全的环境中运行此工具")
    print("  - 修改后请妥善保管新密码")
    print("  - 建议定期更换密码")

def main():
    """主函数"""
    print_banner()
    
    # 解析命令行参数
    if len(sys.argv) == 1:
        # 无参数，进入交互式模式
        success = interactive_mode()
    elif len(sys.argv) == 2 and sys.argv[1] in ['-h', '--help']:
        # 显示帮助
        show_help()
        return
    elif len(sys.argv) == 3 and sys.argv[1] in ['-p', '--password']:
        # 命令行模式
        new_password = sys.argv[2]
        success = command_line_mode(new_password)
    else:
        # 参数错误
        print("❌ 参数错误")
        print()
        show_help()
        return
    
    # 显示结果
    print("\n" + "=" * 60)
    if success:
        print("🎉 密码修改完成！")
        print("\n📝 后续建议:")
        print("  1. 使用新密码登录系统验证")
        print("  2. 清除浏览器中保存的旧密码")
        print("  3. 通知其他管理员密码已更改")
        print("  4. 考虑启用双因素认证")
    else:
        print("❌ 密码修改失败！")
        print("\n🔧 故障排除:")
        print("  1. 检查数据库连接配置")
        print("  2. 确认MySQL服务正在运行")
        print("  3. 验证数据库用户权限")
        print("  4. 检查admin用户是否存在")
    print("=" * 60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ 操作被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 程序执行异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
