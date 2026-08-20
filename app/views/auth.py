import hashlib
import logging
import math
import secrets
import time

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy.exc import IntegrityError
from ..models.user import User
from ..models.user import Role
from .. import db
from ..demo_access import mark_demo_access_session_verified
from ..services.sso_service import get_sso_service

logger = logging.getLogger(__name__)

bp = Blueprint('auth', __name__)

_DEFAULT_DEMO_USERNAME = 'ppt_demo_guest'
_DEFAULT_DEMO_EMAIL = 'ppt-demo@localhost.invalid'
_DEMO_USER_MARKER = 'ppt-agent-studio-demo-v1'
_DEMO_LOGIN_MAX_CONTENT_LENGTH = 8 * 1024
_DEMO_LOGIN_MAX_ATTEMPTS_LIMIT = 100
_DEMO_LOGIN_LOCKOUT_SECONDS_LIMIT = 86400
_DEMO_LOGIN_FAILURES_KEY = 'demo_login_failures'
_DEMO_LOGIN_LOCKED_UNTIL_KEY = 'demo_login_locked_until'


@bp.after_request
def _disable_demo_login_caching(response):
    if (
        current_app.config.get('DEMO_MODE', False)
        and request.endpoint in {'auth.login', 'auth.demo_login'}
    ):
        response.headers['Cache-Control'] = 'no-store'
    return response


def _demo_access_is_configured() -> bool:
    password = current_app.config.get('DEMO_ACCESS_PASSWORD')
    return (
        isinstance(password, str)
        and len(password) >= 12
        and bool(password.strip())
    )


def _constant_time_text_matches(submitted: str, expected: str) -> bool:
    return secrets.compare_digest(
        hashlib.sha256(submitted.encode('utf-8')).digest(),
        hashlib.sha256(expected.encode('utf-8')).digest(),
    )


def _positive_config_int(key: str, default: int, maximum: int) -> int:
    try:
        value = int(current_app.config.get(key, default))
    except (TypeError, ValueError, OverflowError):
        return default
    return min(value, maximum) if value > 0 else default


def _active_demo_lock(now: float) -> float | None:
    lock_was_stored = _DEMO_LOGIN_LOCKED_UNTIL_KEY in session
    try:
        locked_until = float(session.get(_DEMO_LOGIN_LOCKED_UNTIL_KEY, 0))
    except (TypeError, ValueError, OverflowError):
        locked_until = 0
    if math.isfinite(locked_until) and locked_until > now:
        return locked_until
    if lock_was_stored:
        session.pop(_DEMO_LOGIN_LOCKED_UNTIL_KEY, None)
        session.pop(_DEMO_LOGIN_FAILURES_KEY, None)
    return None


def _render_demo_lockout(now: float, locked_until: float):
    flash('登录尝试次数过多，请稍后再试。')
    response = _render_login_page(429)
    response.headers['Retry-After'] = str(
        max(1, math.ceil(locked_until - now))
    )
    return response


def _render_login_page(status_code: int = 200):
    demo_mode = bool(current_app.config.get('DEMO_MODE', False))

    if demo_mode:
        sso_enabled = False
        sso_provider = current_app.config.get('SSO_PROVIDER', 'oauth2')
        demo_login_nonce = secrets.token_urlsafe(32)
        session['demo_login_nonce'] = demo_login_nonce
    else:
        demo_login_nonce = None
        try:
            sso_service = get_sso_service()
            sso_enabled = sso_service.is_enabled()
            sso_provider = current_app.config.get('SSO_PROVIDER', 'oauth2')
        except Exception:
            sso_enabled = False
            sso_provider = 'oauth2'

    return make_response(
        render_template(
            'auth/login.html',
            demo_mode=demo_mode,
            demo_login_nonce=demo_login_nonce,
            demo_access_configured=_demo_access_is_configured(),
            sso_enabled=sso_enabled,
            sso_provider=sso_provider,
        ),
        status_code,
    )


def _demo_identity() -> tuple[str, str]:
    username = str(
        current_app.config.get('DEMO_USER_USERNAME', _DEFAULT_DEMO_USERNAME)
    ).strip()
    email = str(
        current_app.config.get('DEMO_USER_EMAIL', _DEFAULT_DEMO_EMAIL)
    ).strip().lower()
    return username or _DEFAULT_DEMO_USERNAME, email or _DEFAULT_DEMO_EMAIL


def _is_managed_demo_user(user: User, username: str, email: str) -> bool:
    """Only reuse the reserved, locally-created identity."""
    return (
        user.username == username
        and (user.email or '').lower() == email
        and user.sso_provider is None
        and user.sso_subject == _DEMO_USER_MARKER
    )


def _get_or_create_demo_role() -> Role:
    role = Role.query.filter_by(name='user').first()
    if role is not None:
        return role

    role = Role(name='user')
    db.session.add(role)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        role = Role.query.filter_by(name='user').first()
    if role is None:
        logger.error('Demo user role could not be provisioned')
        abort(503, description='Demo identity is unavailable.')
    return role


def _get_or_create_demo_user() -> User:
    username, email = _demo_identity()
    user = User.query.filter_by(username=username).first()

    if user is None:
        if User.query.filter_by(email=email).first() is not None:
            logger.error('Reserved demo email is already assigned to another account')
            abort(409, description='Demo identity is unavailable.')

        default_role = _get_or_create_demo_role()
        user = User(
            username=username,
            email=email,
            display_name='Demo Visitor',
            sso_subject=_DEMO_USER_MARKER,
            status='approved',
            role=default_role,
        )
        # The demo never publishes a password. A high-entropy random secret
        # keeps the underlying local-account model valid without introducing a
        # reusable credential into source code, logs, or the UI.
        user.set_password(secrets.token_urlsafe(48))
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            # A second local request may have created the reserved user between
            # our lookup and commit. Re-read it and validate the marker rather
            # than replacing an unrelated account.
            db.session.rollback()
            user = User.query.filter_by(username=username).first()

    if user is None or not _is_managed_demo_user(user, username, email):
        logger.error('Reserved demo username conflicts with a non-demo account')
        abort(409, description='Demo identity is unavailable.')

    if (
        user.status != 'approved'
        or user.role is None
        or user.role.name != 'user'
    ):
        logger.error('Reserved demo identity has an unsafe status or role')
        abort(409, description='Demo identity is unavailable.')

    changed = False
    if user.display_name != 'Demo Visitor':
        user.display_name = 'Demo Visitor'
        changed = True
    if changed:
        db.session.commit()
    return user


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_app.config.get('DEMO_MODE', False):
        abort(404)

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # 验证输入
        if not username or not password:
            flash('请填写所有必填字段')
            return redirect(url_for('auth.register'))
        
        # 验证用户名长度
        if len(username) < 3 or len(username) > 20:
            flash('用户名长度必须在3-20个字符之间')
            return redirect(url_for('auth.register'))
            
        # 验证密码长度
        if len(password) < 6:
            flash('密码长度必须大于6个字符')
            return redirect(url_for('auth.register'))
        
        # 检查用户是否已存在
        if User.query.filter_by(username=username).first():
            flash('用户名已存在')
            return redirect(url_for('auth.register'))
        
        try:
            # 创建新用户
            user = User(username=username)
            user.set_password(password)
            
            # 设置默认用户角色
            default_role = Role.query.filter_by(name='user').first()
            if default_role:
                user.role = default_role
            
            db.session.add(user)
            db.session.commit()
            
            flash('注册成功！请登录')
            return redirect(url_for('auth.login'))
            
        except Exception as e:
            db.session.rollback()
            flash('注册失败，请重试')
            print(f"Registration error: {str(e)}")
            return redirect(url_for('auth.register'))
    
    return render_template('auth/register.html')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_app.config.get('DEMO_MODE', False) and request.method != 'GET':
        abort(404)

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form['password']
        email = request.form.get('email') # 从前端获取email，但非SSO用户登录时可能不需要

        if not username:
            flash('请输入用户名')
            return redirect(url_for('auth.login'))
        
        user = User.query.filter_by(username=username).first()
        
        # 如果用户存在且是SSO用户，则需要验证邮箱
        if user and user.is_sso_user():
            if not email or user.email != email:
                flash('SSO用户登录需要提供正确的邮箱')
                return redirect(url_for('auth.login'))
        # 如果用户存在但不是SSO用户，则不需要验证邮箱
        elif user and not user.is_sso_user():
            pass # 不需要邮箱验证
        # 如果用户不存在，则直接返回用户名或密码错误
        else:
            flash('用户名或密码错误')
            return redirect(url_for('auth.login'))
        if user and user.check_password(password):
            if user.status == 'pending':
                flash('您的账号正在等待管理员审批')
                return redirect(url_for('auth.login'))
            elif user.status == 'rejected':
                flash('您的注册申请已被拒绝')
                return redirect(url_for('auth.login'))
            elif user.status == 'disabled':
                flash('您的账号已被禁用，请联系管理员')
                return redirect(url_for('auth.login'))
            
            login_user(user)
            # 设置 session
            session['username'] = user.username
            session.permanent = True  # 启用永久 session

            # 更新最后登录时间
            from datetime import datetime
            import pytz
            user.last_login = datetime.now(pytz.timezone('Asia/Shanghai'))
            db.session.commit()

            flash('登录成功！')
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('main.index'))
        else:
            flash('用户名或密码错误')
            
    return _render_login_page()


@bp.route('/demo', methods=['POST'])
def demo_login():
    """Enter the local interview workspace after the configured access check."""
    if not current_app.config.get('DEMO_MODE', False):
        abort(404)

    request.max_content_length = _DEMO_LOGIN_MAX_CONTENT_LENGTH
    if request.content_length is None:
        # Force Flask's per-request stream limit to run for chunked requests
        # before form parsing. If the WSGI server cannot prove that the stream
        # terminates, Flask safely reads no body instead of accepting it.
        request.get_data(cache=True)
    elif request.content_length > _DEMO_LOGIN_MAX_CONTENT_LENGTH:
        abort(413)

    expected_nonce = session.pop('demo_login_nonce', None)
    submitted_nonce = request.form.get('demo_login_nonce', '')
    nonce_matches = (
        isinstance(expected_nonce, str)
        and bool(expected_nonce)
        and bool(submitted_nonce)
        and _constant_time_text_matches(submitted_nonce, expected_nonce)
    )
    if not nonce_matches:
        flash('演示登录请求无效或已过期。')
        return _render_login_page(400)

    if not _demo_access_is_configured():
        flash('演示访问尚未配置，请联系运维人员。')
        return _render_login_page(503)

    now = time.time()
    locked_until = _active_demo_lock(now)
    if locked_until is not None:
        return _render_demo_lockout(now, locked_until)

    expected_username = str(
        current_app.config.get('DEMO_ACCESS_USERNAME', 'demo') or 'demo'
    )
    expected_password = current_app.config['DEMO_ACCESS_PASSWORD']
    submitted_username = request.form.get('username', '')
    submitted_password = request.form.get('password', '')
    username_matches = _constant_time_text_matches(
        submitted_username,
        expected_username,
    )
    password_matches = _constant_time_text_matches(
        submitted_password,
        expected_password,
    )
    if not (username_matches and password_matches):
        max_attempts = _positive_config_int(
            'DEMO_LOGIN_MAX_ATTEMPTS',
            5,
            _DEMO_LOGIN_MAX_ATTEMPTS_LIMIT,
        )
        try:
            failures = int(session.get(_DEMO_LOGIN_FAILURES_KEY, 0))
        except (TypeError, ValueError, OverflowError):
            failures = 0
        failures = min(max(failures, 0) + 1, max_attempts)
        session[_DEMO_LOGIN_FAILURES_KEY] = failures
        if failures >= max_attempts:
            locked_until = now + _positive_config_int(
                'DEMO_LOGIN_LOCKOUT_SECONDS',
                300,
                _DEMO_LOGIN_LOCKOUT_SECONDS_LIMIT,
            )
            session[_DEMO_LOGIN_LOCKED_UNTIL_KEY] = locked_until
            return _render_demo_lockout(now, locked_until)
        flash('演示用户名或密码不正确。')
        return _render_login_page(401)

    from app.utils.timezone_helper import now_with_timezone

    user = _get_or_create_demo_user()
    user.last_login = now_with_timezone()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        if current_user.is_authenticated:
            logout_user()
        session.clear()
        flash('演示会话暂时无法启动，请稍后重试。')
        return _render_login_page(503)

    if current_user.is_authenticated:
        logout_user()
    session.clear()
    if not login_user(user):
        abort(503, description='Demo session could not be started.')
    session['username'] = user.username
    session.permanent = False
    if not mark_demo_access_session_verified():
        logout_user()
        session.clear()
        abort(503, description='Demo session could not be verified.')
    return redirect(url_for('main.index'))


@bp.route('/logout')
@login_required
def logout():
    # 检查是否为SSO用户
    if current_user.is_sso_user():
        # 重定向到SSO登出
        return redirect(url_for('sso.sso_logout'))

    logout_user()
    session.clear() # Clear all session data
    flash('已退出登录')
    return redirect(url_for('auth.login'))


@bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """修改密码API"""
    try:
        # 检查用户是否可以修改密码
        if not current_user.can_change_password():
            return jsonify({
                'success': False,
                'message': 'SSO用户无法修改密码'
            }), 400

        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'message': '请求数据格式错误'
            }), 400

        current_password = data.get('current_password')
        new_password = data.get('new_password')

        if not current_password or not new_password:
            return jsonify({
                'success': False,
                'message': '当前密码和新密码不能为空'
            }), 400

        # 验证当前密码
        if not current_user.check_password(current_password):
            return jsonify({
                'success': False,
                'message': '当前密码错误'
            }), 400

        # 验证新密码长度
        if len(new_password) < 6:
            return jsonify({
                'success': False,
                'message': '新密码长度至少为6位'
            }), 400

        # 更新密码
        current_user.set_password(new_password)
        db.session.commit()

        logger.info(f"用户 {current_user.username} 修改密码成功")

        return jsonify({
            'success': True,
            'message': '密码修改成功'
        })

    except Exception as e:
        logger.error(f"修改密码失败: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': '密码修改过程中发生错误'
        }), 500


@bp.route('/user-info')
@login_required
def user_info():
    """获取当前用户信息API"""
    try:
        user_data = {
            'id': current_user.id,
            'username': current_user.username,
            'email': current_user.email,
            'display_name': current_user.get_display_name(),
            'full_name': current_user.get_full_name(),
            'role': current_user.role.name if current_user.role else None,
            'is_sso_user': current_user.is_sso_user(),
            'sso_provider': current_user.sso_provider,
            'is_administrator': current_user.is_administrator(),
            'can_change_password': current_user.can_change_password(),
            'last_login': current_user.last_login.isoformat() if current_user.last_login else None,
            'register_time': current_user.register_time.isoformat() if current_user.register_time else None,
            'status': current_user.status
        }

        return jsonify({
            'success': True,
            'data': user_data
        })

    except Exception as e:
        logger.error(f"获取用户信息失败: {e}")
        return jsonify({
            'success': False,
            'message': '获取用户信息失败'
        }), 500
