#!/bin/bash

# Admin密码重置工具 - Linux/macOS版本

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印横幅
print_banner() {
    echo
    echo "========================================"
    echo "🔐 PPT翻译系统 - Admin密码重置工具"
    echo "========================================"
    echo
}

# 检查Python
check_python() {
    if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
        echo -e "${RED}❌ 未找到Python，请先安装Python${NC}"
        exit 1
    fi
    
    # 优先使用python3
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    else
        PYTHON_CMD="python"
    fi
}

# 显示菜单
show_menu() {
    echo -e "${BLUE}📝 选择重置方式:${NC}"
    echo
    echo "1. 重置为默认密码 (admin123)"
    echo "2. 设置自定义密码"
    echo "3. 交互式修改密码"
    echo "4. 退出"
    echo
}

# 快速重置
quick_reset() {
    local password="$1"
    echo -e "${YELLOW}🔄 重置admin密码...${NC}"
    
    if [ -z "$password" ]; then
        $PYTHON_CMD reset_admin.py
    else
        $PYTHON_CMD reset_admin.py "$password"
    fi
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}  密码重置成功！${NC}"
    else
        echo -e "${RED}❌ 密码重置失败！${NC}"
        return 1
    fi
}

# 交互式修改
interactive_change() {
    echo -e "${YELLOW}🔧 启动交互式修改工具...${NC}"
    $PYTHON_CMD change_admin_password.py
}

# 主函数
main() {
    print_banner
    check_python
    
    # 如果有命令行参数，直接使用
    if [ $# -gt 0 ]; then
        quick_reset "$1"
        return $?
    fi
    
    # 交互式菜单
    while true; do
        show_menu
        read -p "请选择 (1-4): " choice
        
        case $choice in
            1)
                echo
                quick_reset
                break
                ;;
            2)
                echo
                read -s -p "请输入新密码: " custom_password
                echo
                if [ -z "$custom_password" ]; then
                    echo -e "${RED}❌ 密码不能为空${NC}"
                    continue
                fi
                quick_reset "$custom_password"
                break
                ;;
            3)
                echo
                interactive_change
                break
                ;;
            4)
                echo -e "${YELLOW}👋 再见！${NC}"
                exit 0
                ;;
            *)
                echo -e "${RED}❌ 无效选择，请重新输入${NC}"
                echo
                ;;
        esac
    done
    
    echo
    echo "========================================"
    echo -e "${GREEN}  操作完成！${NC}"
    echo "========================================"
}

# 错误处理
trap 'echo -e "\n${RED}❌ 操作被中断${NC}"; exit 1' INT

# 执行主函数
main "$@"
