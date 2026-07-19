#!/bin/bash
# PPT翻译系统快速安装脚本
# 建议用于Ubuntu 24.04+；Python最低版本为3.11

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# 检查是否为root用户
check_root() {
    if [[ $EUID -eq 0 ]]; then
        log_error "请不要使用root用户运行此脚本"
        exit 1
    fi
}

# 检查操作系统
check_os() {
    if [[ ! -f /etc/os-release ]]; then
        log_error "无法检测操作系统版本"
        exit 1
    fi
    
    . /etc/os-release
    if [[ "$ID" != "ubuntu" ]] || [[ "${VERSION_ID}" < "24.04" ]]; then
        log_warn "此脚本主要针对Ubuntu 24.04+测试，其他系统必须自行提供Python 3.11+"
    fi
}

check_python_version() {
    if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
        log_error "需要Python 3.11或更高版本"
        exit 1
    fi
}

# 更新系统包
update_system() {
    log_step "更新系统包..."
    sudo apt update
    sudo apt upgrade -y
}

# 安装基础依赖
install_dependencies() {
    log_step "安装基础依赖..."
    sudo apt install -y \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        build-essential \
        libmysqlclient-dev \
        pkg-config \
        curl \
        wget \
        git \
        nginx \
        supervisor
}

# 安装MySQL
install_mysql() {
    log_step "安装MySQL..."
    
    if ! command -v mysql &> /dev/null; then
        sudo apt install -y mysql-server mysql-client
        
        # 启动MySQL服务
        sudo systemctl start mysql
        sudo systemctl enable mysql
        
        log_info "MySQL安装完成"
        log_warn "请运行 'sudo mysql_secure_installation' 进行安全配置"
    else
        log_info "MySQL已安装，跳过"
    fi
}

# 安装Redis
install_redis() {
    log_step "安装Redis..."
    
    if ! command -v redis-server &> /dev/null; then
        sudo apt install -y redis-server
        
        # 启动Redis服务
        sudo systemctl start redis
        sudo systemctl enable redis
        
        log_info "Redis安装完成"
    else
        log_info "Redis已安装，跳过"
    fi
}

# 创建项目目录和用户
setup_project() {
    log_step "设置项目环境..."
    
    PROJECT_DIR="/opt/ppt-translation"
    PROJECT_USER="pptuser"
    
    # 创建项目用户
    if ! id "$PROJECT_USER" &>/dev/null; then
        sudo useradd -r -s /bin/bash -d $PROJECT_DIR $PROJECT_USER
        log_info "创建项目用户: $PROJECT_USER"
    fi
    
    # 创建项目目录
    sudo mkdir -p $PROJECT_DIR
    sudo chown $PROJECT_USER:$PROJECT_USER $PROJECT_DIR
    
    # 复制项目文件
    log_info "复制项目文件到 $PROJECT_DIR"
    sudo cp -r . $PROJECT_DIR/
    sudo chown -R $PROJECT_USER:$PROJECT_USER $PROJECT_DIR
}

# 安装Python依赖
install_python_deps() {
    log_step "安装Python依赖..."
    
    cd $PROJECT_DIR
    
    # 创建虚拟环境
    sudo -u $PROJECT_USER python3 -m venv venv
    
    # 安装依赖
    sudo -u $PROJECT_USER $PROJECT_DIR/venv/bin/pip install --upgrade pip
    sudo -u $PROJECT_USER $PROJECT_DIR/venv/bin/pip install -r requirements.txt
    
    log_info "Python依赖安装完成"
}

verify_entrypoints() {
    log_step "验证运行入口..."

    cd "$PROJECT_DIR"
    for entrypoint in run.py app.py run_async.py run_worker.py; do
        sudo -u "$PROJECT_USER" "$PROJECT_DIR/venv/bin/python" "$entrypoint" --check
    done

    log_info "运行入口验证完成"
}

# 配置数据库
setup_database() {
    log_step "配置数据库..."
    
    # 获取MySQL root密码
    echo -n "请输入MySQL root密码: "
    read -s MYSQL_ROOT_PASSWORD
    echo
    
    # 创建数据库和用户
    mysql -u root -p$MYSQL_ROOT_PASSWORD <<EOF
CREATE DATABASE IF NOT EXISTS ppt_translate_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'pptuser'@'localhost' IDENTIFIED BY 'ppt_secure_password_2024';
GRANT ALL PRIVILEGES ON ppt_translate_db.* TO 'pptuser'@'localhost';
FLUSH PRIVILEGES;
EOF
    
    # 运行数据库初始化脚本
    cd $PROJECT_DIR
    sudo -u $PROJECT_USER $PROJECT_DIR/venv/bin/python setup_database.py
    
    log_info "数据库配置完成"
}

# 配置Nginx
setup_nginx() {
    log_step "配置Nginx..."
    
    # 创建Nginx配置文件
    sudo tee /etc/nginx/sites-available/ppt-translation > /dev/null <<EOF
server {
    listen 80;
    server_name _;
    
    client_max_body_size 12G;
    
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }
    
    location /static {
        alias $PROJECT_DIR/static;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    
    location /uploads {
        alias $PROJECT_DIR/uploads;
        expires 1d;
    }
}
EOF
    
    # 启用站点
    sudo ln -sf /etc/nginx/sites-available/ppt-translation /etc/nginx/sites-enabled/
    sudo rm -f /etc/nginx/sites-enabled/default
    
    # 测试Nginx配置
    sudo nginx -t
    
    # 重启Nginx
    sudo systemctl restart nginx
    sudo systemctl enable nginx
    
    log_info "Nginx配置完成"
}

# 配置Supervisor
setup_supervisor() {
    log_step "配置Supervisor..."
    
    # 创建Supervisor配置文件
    sudo tee /etc/supervisor/conf.d/ppt-translation.conf > /dev/null <<EOF
[group:ppt-translation]
programs=ppt-translation-web,ppt-translation-worker
priority=999

[program:ppt-translation-web]
command=$PROJECT_DIR/venv/bin/python run_async.py
directory=$PROJECT_DIR
user=$PROJECT_USER
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=$PROJECT_DIR/logs/web.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=5
environment=PATH="$PROJECT_DIR/venv/bin"

[program:ppt-translation-worker]
command=$PROJECT_DIR/venv/bin/python run_worker.py
directory=$PROJECT_DIR
user=$PROJECT_USER
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=$PROJECT_DIR/logs/worker.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=5
environment=PATH="$PROJECT_DIR/venv/bin"
EOF
    
    # 创建日志目录
    sudo mkdir -p $PROJECT_DIR/logs
    sudo chown $PROJECT_USER:$PROJECT_USER $PROJECT_DIR/logs
    
    # 重新加载Supervisor配置
    sudo supervisorctl reread
    sudo supervisorctl update
    sudo supervisorctl status 'ppt-translation:*'
    
    log_info "Supervisor配置完成"
}

# 配置防火墙
setup_firewall() {
    log_step "配置防火墙..."
    
    if command -v ufw &> /dev/null; then
        sudo ufw --force enable
        sudo ufw allow ssh
        sudo ufw allow 'Nginx Full'
        log_info "防火墙配置完成"
    else
        log_warn "UFW未安装，请手动配置防火墙"
    fi
}

# 创建管理脚本
create_management_scripts() {
    log_step "创建管理脚本..."
    
    # 创建启动脚本
    sudo tee /usr/local/bin/ppt-start > /dev/null <<EOF
#!/bin/bash
sudo supervisorctl start 'ppt-translation:*'
sudo systemctl start nginx
echo "PPT翻译系统已启动"
EOF
    
    # 创建停止脚本
    sudo tee /usr/local/bin/ppt-stop > /dev/null <<EOF
#!/bin/bash
sudo supervisorctl stop 'ppt-translation:*'
echo "PPT翻译系统已停止"
EOF
    
    # 创建重启脚本
    sudo tee /usr/local/bin/ppt-restart > /dev/null <<EOF
#!/bin/bash
sudo supervisorctl restart 'ppt-translation:*'
sudo systemctl reload nginx
echo "PPT翻译系统已重启"
EOF
    
    # 创建状态检查脚本
    sudo tee /usr/local/bin/ppt-status > /dev/null <<EOF
#!/bin/bash
echo "=== PPT翻译系统状态 ==="
echo "应用状态:"
sudo supervisorctl status 'ppt-translation:*'
echo
echo "Nginx状态:"
sudo systemctl status nginx --no-pager -l
echo
echo "MySQL状态:"
sudo systemctl status mysql --no-pager -l
echo
echo "磁盘使用:"
df -h /
echo
echo "内存使用:"
free -h
EOF
    
    # 设置执行权限
    sudo chmod +x /usr/local/bin/ppt-*
    
    log_info "管理脚本创建完成"
}

# 显示安装结果
show_result() {
    log_step "安装完成！"
    
    echo
    echo "=================================="
    echo "  PPT翻译系统安装完成"
    echo "=================================="
    echo
    echo "🌐 访问地址: http://$(hostname -I | awk '{print $1}')"
    echo "👤 管理员账户: admin"
    echo "🔑 管理员密码: admin123"
    echo
    echo "📁 项目目录: $PROJECT_DIR"
    echo "👥 运行用户: $PROJECT_USER"
    echo
    echo "🔧 管理命令:"
    echo "  启动系统: ppt-start"
    echo "  停止系统: ppt-stop"
    echo "  重启系统: ppt-restart"
    echo "  查看状态: ppt-status"
    echo
    echo "📋 重要提醒:"
    echo "  1. 请立即修改默认管理员密码"
    echo "  2. 配置 $PROJECT_DIR/.env 文件中的API密钥"
    echo "  3. 如需SSL，请配置Let's Encrypt证书"
    echo "  4. 定期备份数据库和上传文件"
    echo
    echo "📖 详细文档: DEPLOYMENT_GUIDE.md"
    echo
}

# 主函数
main() {
    echo "=================================="
    echo "  PPT翻译系统快速安装脚本"
    echo "=================================="
    echo
    
    check_root
    check_os
    
    echo "即将开始安装，这可能需要几分钟时间..."
    echo "按Enter继续，或Ctrl+C取消"
    read
    
    update_system
    install_dependencies
    check_python_version
    install_mysql
    install_redis
    setup_project
    install_python_deps
    verify_entrypoints
    setup_database
    setup_nginx
    setup_supervisor
    setup_firewall
    create_management_scripts
    show_result
}

# 运行主函数
main "$@"
