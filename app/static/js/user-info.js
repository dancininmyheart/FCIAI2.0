/**
 * 用户信息卡片交互功能
 */

// 用户信息卡片状态
let userInfoExpanded = false;

// 初始化用户信息卡片
document.addEventListener('DOMContentLoaded', function() {
    initUserInfoCard();
    loadUserStatus();
});

/**
 * 初始化用户信息卡片
 */
function initUserInfoCard() {
    const userCard = document.getElementById('user-info-card');
    if (!userCard) return;

    // 从localStorage读取展开状态
    const savedState = localStorage.getItem('userInfoExpanded');
    if (savedState === 'true') {
        expandUserInfo();
    }

    // 添加点击外部关闭功能
    document.addEventListener('click', function(event) {
        if (!userCard.contains(event.target) && userInfoExpanded) {
            collapseUserInfo();
        }
    });

    // 添加键盘快捷键支持 (Ctrl+U)
    document.addEventListener('keydown', function(event) {
        if (event.ctrlKey && event.key === 'u') {
            event.preventDefault();
            toggleUserInfo();
        }
    });

    // 添加鼠标悬停效果
    userCard.addEventListener('mouseenter', function() {
        if (!userInfoExpanded) {
            userCard.style.transform = 'translateY(calc(100% - 70px))';
        }
    });

    userCard.addEventListener('mouseleave', function() {
        if (!userInfoExpanded) {
            userCard.style.transform = 'translateY(calc(100% - 60px))';
        }
    });
}

/**
 * 切换用户信息卡片展开/收起状态
 */
function toggleUserInfo() {
    if (userInfoExpanded) {
        collapseUserInfo();
    } else {
        expandUserInfo();
    }
}

/**
 * 展开用户信息卡片
 */
function expandUserInfo() {
    const userCard = document.getElementById('user-info-card');
    if (!userCard) return;

    userCard.classList.add('expanded');
    userInfoExpanded = true;
    
    // 保存状态到localStorage
    localStorage.setItem('userInfoExpanded', 'true');
    
    // 更新切换按钮图标
    const toggleIcon = userCard.querySelector('.user-info-toggle i');
    if (toggleIcon) {
        toggleIcon.className = 'bi bi-chevron-down';
    }
}

/**
 * 收起用户信息卡片
 */
function collapseUserInfo() {
    const userCard = document.getElementById('user-info-card');
    if (!userCard) return;

    userCard.classList.remove('expanded');
    userInfoExpanded = false;
    
    // 保存状态到localStorage
    localStorage.setItem('userInfoExpanded', 'false');
    
    // 更新切换按钮图标
    const toggleIcon = userCard.querySelector('.user-info-toggle i');
    if (toggleIcon) {
        toggleIcon.className = 'bi bi-chevron-up';
    }
}

/**
 * 加载用户在线状态
 */
function loadUserStatus() {
    // 添加在线状态指示器
    const userDetails = document.querySelector('.user-details');
    if (userDetails) {
        const statusIndicator = document.createElement('span');
        statusIndicator.className = 'user-status-indicator';
        statusIndicator.title = '在线';
        userDetails.appendChild(statusIndicator);
    }

    // 定期更新最后活动时间
    updateLastActivity();
    setInterval(updateLastActivity, 60000); // 每分钟更新一次
}

/**
 * 更新最后活动时间
 */
function updateLastActivity() {
    const now = new Date();
    const timeString = now.toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit'
    });
    
    // 更新页面标题显示当前时间
    const originalTitle = document.title;
    if (!originalTitle.includes('|')) {
        document.title = `${originalTitle} | ${timeString}`;
    } else {
        document.title = originalTitle.split('|')[0] + `| ${timeString}`;
    }
}

/**
 * 修改密码功能
 */
function changePassword() {
    // 创建修改密码模态框
    const modal = createPasswordModal();
    document.body.appendChild(modal);
    
    // 显示模态框
    modal.style.display = 'block';
    
    // 聚焦到当前密码输入框
    setTimeout(() => {
        const currentPasswordInput = modal.querySelector('#currentPassword');
        if (currentPasswordInput) {
            currentPasswordInput.focus();
        }
    }, 100);
}

/**
 * 创建修改密码模态框
 */
function createPasswordModal() {
    const modal = document.createElement('div');
    modal.className = 'password-modal';
    modal.innerHTML = `
        <div class="password-modal-content">
            <div class="password-modal-header">
                <h3><i class="bi bi-key"></i> 修改密码</h3>
                <button class="password-modal-close" onclick="closePasswordModal()">&times;</button>
            </div>
            <div class="password-modal-body">
                <form id="changePasswordForm" onsubmit="submitPasswordChange(event)">
                    <div class="form-group">
                        <label for="currentPassword">当前密码</label>
                        <input type="password" id="currentPassword" name="currentPassword" required>
                    </div>
                    <div class="form-group">
                        <label for="newPassword">新密码</label>
                        <input type="password" id="newPassword" name="newPassword" required minlength="6">
                    </div>
                    <div class="form-group">
                        <label for="confirmPassword">确认新密码</label>
                        <input type="password" id="confirmPassword" name="confirmPassword" required>
                    </div>
                    <div class="password-modal-actions">
                        <button type="button" class="btn btn-secondary" onclick="closePasswordModal()">取消</button>
                        <button type="submit" class="btn btn-primary">确认修改</button>
                    </div>
                </form>
            </div>
        </div>
    `;
    
    // 添加样式
    const style = document.createElement('style');
    style.textContent = `
        .password-modal {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.5);
            z-index: 2000;
            display: none;
        }
        
        .password-modal-content {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: var(--brand-milk-white);
            border-radius: 8px;
            width: 400px;
            max-width: 90vw;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
        }
        
        .password-modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            border-bottom: 1px solid #e9ecef;
        }
        
        .password-modal-header h3 {
            margin: 0;
            color: var(--brand-readable-gray);
            font-size: 18px;
        }
        
        .password-modal-close {
            background: none;
            border: none;
            font-size: 24px;
            cursor: pointer;
            color: var(--brand-cool-gray);
        }
        
        .password-modal-body {
            padding: 20px;
        }
        
        .form-group {
            margin-bottom: 16px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 4px;
            font-weight: 500;
            color: var(--brand-readable-gray);
        }
        
        .form-group input {
            width: 100%;
            padding: 8px 12px;
            border: 1px solid #ced4da;
            border-radius: 4px;
            font-size: 14px;
        }
        
        .form-group input:focus {
            outline: none;
            border-color: var(--brand-sky-blue);
            box-shadow: 0 0 0 0.2rem rgba(0, 148, 217, 0.25);
        }
        
        .password-modal-actions {
            display: flex;
            justify-content: flex-end;
            gap: 8px;
            margin-top: 20px;
        }
        
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
        }
        
        .btn-secondary {
            background: var(--brand-cool-gray);
            color: var(--brand-milk-white);
        }
        
        .btn-primary {
            background: var(--brand-sky-blue);
            color: var(--brand-milk-white);
        }
        
        .btn:hover {
            opacity: 0.9;
        }
    `;
    
    modal.appendChild(style);
    return modal;
}

/**
 * 关闭修改密码模态框
 */
function closePasswordModal() {
    const modal = document.querySelector('.password-modal');
    if (modal) {
        modal.remove();
    }
}

/**
 * 提交密码修改
 */
function submitPasswordChange(event) {
    event.preventDefault();
    
    const form = event.target;
    const currentPassword = form.currentPassword.value;
    const newPassword = form.newPassword.value;
    const confirmPassword = form.confirmPassword.value;
    
    // 验证新密码和确认密码是否一致
    if (newPassword !== confirmPassword) {
        alert('新密码和确认密码不一致');
        return;
    }
    
    // 发送修改密码请求
    fetch('/auth/change-password', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            current_password: currentPassword,
            new_password: newPassword
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert('密码修改成功');
            closePasswordModal();
        } else {
            alert(data.message || '密码修改失败');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('密码修改过程中发生错误');
    });
}

/**
 * 格式化时间显示
 */
function formatTime(date) {
    if (!date) return '';
    
    const now = new Date();
    const diff = now - date;
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);
    
    if (minutes < 1) return '刚刚';
    if (minutes < 60) return `${minutes}分钟前`;
    if (hours < 24) return `${hours}小时前`;
    if (days < 7) return `${days}天前`;
    
    return date.toLocaleDateString('zh-CN');
}

/**
 * 添加用户信息项
 */
function addUserInfoItem(icon, text, container) {
    const item = document.createElement('div');
    item.className = 'user-info-item';
    item.innerHTML = `
        <i class="bi bi-${icon}"></i>
        <span>${text}</span>
    `;
    container.appendChild(item);
}

// 导出函数供全局使用
window.toggleUserInfo = toggleUserInfo;
window.changePassword = changePassword;
window.closePasswordModal = closePasswordModal;
window.submitPasswordChange = submitPasswordChange;
