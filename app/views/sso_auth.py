"""
SSO认证视图
处理SSO登录、回调和登出
"""
import logging
from flask import Blueprint, request, redirect, url_for, flash, session, current_app, jsonify, render_template
from flask_login import logout_user, current_user, login_required
from urllib.parse import urlencode

from app.services.sso_service import get_sso_service, SSOError
from app.services.user_service import sso_user_manager

logger = logging.getLogger(__name__)

# 创建SSO认证蓝图
sso_bp = Blueprint('sso', __name__, url_prefix='/auth/sso')


@sso_bp.before_request
def disable_sso_in_demo_mode():
    """Do not expose any alternate authentication path in demo mode."""
    if current_app.config.get('DEMO_MODE', False):
        return '', 404
    return None


@sso_bp.route('/login')
def sso_login():
    """SSO登录入口"""
    try:
        # 获取SSO服务实例
        sso_service = get_sso_service()

        # 检查SSO是否启用
        if not sso_service.is_enabled():
            flash('SSO登录未启用', 'error')
            return redirect(url_for('auth.login'))

        # 保存原始请求的页面
        next_page = request.args.get('next')
        if next_page:
            session['sso_next_page'] = next_page

        # 获取授权URL
        auth_url = sso_service.get_authorization_url()
        
        if auth_url == "saml_redirect_required":
            # SAML需要特殊处理
            return redirect(url_for('sso.saml_login'))
        
        logger.info("重定向到SSO提供者进行认证")
        return redirect(auth_url)
        
    except SSOError as e:
        logger.error(f"SSO登录失败: {e}")
        flash(f'SSO登录失败: {str(e)}', 'error')
        return redirect(url_for('auth.login'))
    except Exception as e:
        logger.error(f"SSO登录异常: {e}")
        flash('SSO登录出现异常，请稍后重试', 'error')
        return redirect(url_for('auth.login'))


@sso_bp.route('/callback')
def sso_callback():
    """SSO回调处理"""
    try:
        # 获取SSO服务实例
        sso_service = get_sso_service()

        # 检查SSO是否启用
        if not sso_service.is_enabled():
            flash('SSO登录未启用', 'error')
            return redirect(url_for('auth.login'))

        # 处理回调
        sso_data = sso_service.handle_callback(request.args.to_dict())

        # 映射用户属性
        user_info = sso_service.map_user_attributes(sso_data['user_info'])
        sso_data['user_info'] = user_info
        
        # 认证用户
        success, user, message = sso_user_manager.authenticate_sso_user(sso_data)
        
        if success:
            flash(message, 'success')
            logger.info(f"SSO用户认证成功: {user.username}")
            
            # 获取原始请求的页面
            next_page = session.pop('sso_next_page', None)
            if next_page:
                return redirect(next_page)
            
            return redirect(url_for('main.index'))
        else:
            flash(f'SSO认证失败: {message}', 'error')
            return redirect(url_for('auth.login'))
            
    except SSOError as e:
        logger.error(f"SSO回调处理失败: {e}")
        flash(f'SSO认证失败: {str(e)}', 'error')
        return redirect(url_for('auth.login'))
    except Exception as e:
        logger.error(f"SSO回调处理异常: {e}")
        flash('SSO认证出现异常，请稍后重试', 'error')
        return redirect(url_for('auth.login'))


@sso_bp.route('/dev-callback')
def sso_dev_callback():
    """开发环境模拟SSO回调"""
    try:
        from flask import current_app

        # 只在开发环境中启用
        if current_app.config.get('ENV') != 'development':
            logger.warning("非开发环境，拒绝访问开发回调端点")
            flash('此端点仅在开发环境可用', 'error')
            return redirect(url_for('auth.login'))

        logger.info("开发环境模拟SSO回调")

        # 模拟用户数据
        mock_user_data = {
            'provider': 'authing',
            'user_info': {
                'sub': 'dev_user_123',
                'preferred_username': 'dev_sso_user',
                'email': 'dev@example.com',
                'given_name': 'Development',
                'family_name': 'User',
                'name': 'Development User',
                'phone': '13800138000'
            }
        }

        logger.info(f"模拟用户数据: {mock_user_data}")

        # 获取SSO服务实例
        sso_service = get_sso_service()

        # 映射用户属性
        user_info = sso_service.map_user_attributes(mock_user_data['user_info'])
        mock_user_data['user_info'] = user_info

        # 认证用户
        success, user, message = sso_user_manager.authenticate_sso_user(mock_user_data)

        if success:
            flash(f'开发环境SSO登录成功！{message}', 'success')
            logger.info(f"开发环境SSO用户认证成功: {user.username}")

            # 重定向到主页
            return redirect(url_for('main.index'))
        else:
            logger.error(f"开发环境SSO用户认证失败: {message}")
            flash(f'开发环境SSO认证失败: {message}', 'error')
            return redirect(url_for('auth.login'))

    except Exception as e:
        logger.error(f"开发环境SSO回调处理异常: {e}")
        flash('开发环境SSO登录过程中发生错误', 'error')
        return redirect(url_for('auth.login'))


@sso_bp.route('/dev-test')
def sso_dev_test():
    """开发环境SSO测试页面"""
    try:
        from flask import current_app

        # 只在开发环境中启用
        if current_app.config.get('ENV') != 'development':
            logger.warning("非开发环境，拒绝访问开发测试页面")
            flash('此页面仅在开发环境可用', 'error')
            return redirect(url_for('auth.login'))

        # 获取SSO状态
        sso_service = get_sso_service()

        return render_template('auth/sso_dev_test.html',
                             sso_enabled=sso_service.is_enabled(),
                             sso_provider=current_app.config.get('SSO_PROVIDER', 'unknown'))

    except Exception as e:
        logger.error(f"开发环境SSO测试页面异常: {e}")
        flash('无法加载开发测试页面', 'error')
        return redirect(url_for('auth.login'))


@sso_bp.route('/saml/login')
def saml_login():
    """SAML登录处理"""
    try:
        # 获取SSO服务实例
        sso_service = get_sso_service()

        # 这里需要使用python3-saml库处理SAML请求
        # 由于SAML比较复杂，这里提供基本框架

        provider = sso_service.get_provider('saml')
        if not provider:
            flash('SAML提供者未配置', 'error')
            return redirect(url_for('auth.login'))
        
        # 实际的SAML实现需要更多代码
        flash('SAML登录功能正在开发中', 'info')
        return redirect(url_for('auth.login'))
        
    except Exception as e:
        logger.error(f"SAML登录异常: {e}")
        flash('SAML登录出现异常', 'error')
        return redirect(url_for('auth.login'))


@sso_bp.route('/saml/acs', methods=['POST'])
def saml_acs():
    """SAML断言消费服务"""
    try:
        # 处理SAML响应
        # 这里需要使用python3-saml库解析SAML响应
        
        flash('SAML ACS功能正在开发中', 'info')
        return redirect(url_for('auth.login'))
        
    except Exception as e:
        logger.error(f"SAML ACS异常: {e}")
        flash('SAML认证出现异常', 'error')
        return redirect(url_for('auth.login'))


@sso_bp.route('/logout')
@login_required
def sso_logout():
    """SSO登出"""
    try:
        user = current_user
        
        # 处理SSO登出
        if user.is_sso_user():
            sso_user_manager.handle_sso_logout(user)

            # 获取SSO服务实例和提供者的登出URL
            sso_service = get_sso_service()
            provider = sso_service.get_provider(user.sso_provider)
            if provider:
                logout_url = provider.get_logout_url(
                    return_url=url_for('auth.login', _external=True)
                )
                
                if logout_url:
                    # 先登出本地用户
                    logout_user()
                    flash('已退出登录', 'info')
                    
                    # 重定向到SSO提供者登出
                    return redirect(logout_url)
        
        # 普通登出
        logout_user()
        session.clear() # Clear all session data
        flash('已退出登录', 'info')
        return redirect(url_for('auth.login'))
        
    except Exception as e:
        logger.error(f"SSO登出异常: {e}")
        logout_user()
        session.clear() # Clear all session data
        flash('登出时出现异常，但已成功退出', 'warning')
        return redirect(url_for('auth.login'))
    finally:
        # 无论SSO提供者是否重定向，都确保最终重定向到本地登录页
        logout_user()
        session.clear() # Clear all session data
        flash('您已成功登出。', 'info')
        return redirect(url_for('auth.login'))


@sso_bp.route('/status')
def sso_status():
    """SSO状态检查API"""
    try:
        # 获取SSO服务实例
        sso_service = get_sso_service()

        status = {
            'enabled': sso_service.is_enabled(),
            'provider': current_app.config.get('SSO_PROVIDER'),
            'auto_create_user': current_app.config.get('SSO_AUTO_CREATE_USER'),
            'providers': list(sso_service.providers.keys())
        }
        
        return jsonify(status)
        
    except Exception as e:
        logger.error(f"获取SSO状态异常: {e}")
        return jsonify({'error': str(e)}), 500


@sso_bp.route('/config')
@login_required
def sso_config():
    """SSO配置信息（仅管理员可访问）"""
    try:
        if not current_user.is_administrator():
            return jsonify({'error': '权限不足'}), 403
        
        config = {
            'enabled': current_app.config.get('SSO_ENABLED'),
            'provider': current_app.config.get('SSO_PROVIDER'),
            'auto_create_user': current_app.config.get('SSO_AUTO_CREATE_USER'),
            'default_role': current_app.config.get('SSO_DEFAULT_ROLE'),
            'user_mapping': current_app.config.get('SSO_USER_MAPPING'),
            'oauth2': {
                'client_id': current_app.config.get('OAUTH2_CLIENT_ID'),
                'authorization_url': current_app.config.get('OAUTH2_AUTHORIZATION_URL'),
                'token_url': current_app.config.get('OAUTH2_TOKEN_URL'),
                'userinfo_url': current_app.config.get('OAUTH2_USERINFO_URL'),
                'scope': current_app.config.get('OAUTH2_SCOPE'),
                'redirect_uri': current_app.config.get('OAUTH2_REDIRECT_URI')
            },
            'saml': {
                'sp_entity_id': current_app.config.get('SAML_SP_ENTITY_ID'),
                'sp_acs_url': current_app.config.get('SAML_SP_ACS_URL'),
                'idp_entity_id': current_app.config.get('SAML_IDP_ENTITY_ID'),
                'idp_sso_url': current_app.config.get('SAML_IDP_SSO_URL')
            }
        }
        
        return jsonify(config)
        
    except Exception as e:
        logger.error(f"获取SSO配置异常: {e}")
        return jsonify({'error': str(e)}), 500


# 错误处理
@sso_bp.errorhandler(SSOError)
def handle_sso_error(error):
    """处理SSO错误"""
    logger.error(f"SSO错误: {error}")
    flash(f'SSO认证失败: {str(error)}', 'error')
    return redirect(url_for('auth.login'))


@sso_bp.errorhandler(Exception)
def handle_general_error(error):
    """处理一般错误"""
    logger.error(f"SSO模块异常: {error}")
    flash('SSO服务出现异常，请稍后重试', 'error')
    return redirect(url_for('auth.login'))


# 上下文处理器
@sso_bp.app_context_processor
def inject_sso_status():
    """向模板注入SSO状态"""
    try:
        sso_service = get_sso_service()
        return {
            'sso_enabled': sso_service.is_enabled(),
            'sso_provider': current_app.config.get('SSO_PROVIDER', 'unknown')
        }
    except Exception:
        return {
            'sso_enabled': False,
            'sso_provider': 'unknown'
        }
