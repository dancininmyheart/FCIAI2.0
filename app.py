from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from dotenv import load_dotenv
import os

# 加载环境变量
load_dotenv()

app = Flask(__name__, template_folder='app/templates')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'

# SSO配置
app.config['SSO_ENABLED'] = os.getenv('SSO_ENABLED', 'false').lower() == 'true'
app.config['SSO_PROVIDER'] = os.getenv('SSO_PROVIDER', 'oauth2')
app.config['OAUTH2_CLIENT_ID'] = os.getenv('OAUTH2_CLIENT_ID', '')
app.config['OAUTH2_CLIENT_SECRET'] = os.getenv('OAUTH2_CLIENT_SECRET', '')
app.config['OAUTH2_AUTHORIZATION_URL'] = os.getenv('OAUTH2_AUTHORIZATION_URL', '')
app.config['OAUTH2_TOKEN_URL'] = os.getenv('OAUTH2_TOKEN_URL', '')
app.config['OAUTH2_USERINFO_URL'] = os.getenv('OAUTH2_USERINFO_URL', '')
app.config['OAUTH2_LOGOUT_URL'] = os.getenv('OAUTH2_LOGOUT_URL', '')
app.config['OAUTH2_SCOPE'] = os.getenv('OAUTH2_SCOPE', 'openid profile email')
app.config['OAUTH2_REDIRECT_URI'] = os.getenv('OAUTH2_REDIRECT_URI', '')

db = SQLAlchemy(app)

# 角色-权限关联表
role_permissions = db.Table('role_permissions',
    db.Column('role_id', db.Integer, db.ForeignKey('role.id')),
    db.Column('permission_id', db.Integer, db.ForeignKey('permission.id'))
)

# 权限模型
class Permission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))

# 角色模型
class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    permissions = db.relationship('Permission', secondary=role_permissions, backref='roles')

# 用户模型
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'))
    role = db.relationship('Role', backref='users')

# 权限检查装饰器
def require_permission(permission_name):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'username' not in session:
                return redirect(url_for('login'))
            
            user = User.query.filter_by(username=session['username']).first()
            if not user or not user.role:
                flash('没有权限访问')
                return redirect(url_for('dashboard'))
                
            user_permissions = [p.name for p in user.role.permissions]
            if permission_name not in user_permissions:
                flash('没有权限访问')
                return redirect(url_for('dashboard'))
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# 根路由重定向到登录页面
@app.route('/')
def index():
    return redirect(url_for('login'))

# 注册路由
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # 检查用户是否已存在
        user = User.query.filter_by(username=username).first()
        if user:
            flash('用户名已存在')
            return redirect(url_for('register'))
        
        # 创建新用户
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        
        flash('注册成功！')
        return redirect(url_for('login'))
    
    return render_template('auth/register.html')

# 登录路由 (包含SSO支持)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['username'] = username
            flash('登录成功！')
            return redirect(url_for('dashboard'))
        else:
            flash('用户名或密码错误')

    # 获取SSO状态
    try:
        from app.services.sso_service import get_sso_service
        sso_service = get_sso_service()
        sso_enabled = sso_service.is_enabled()
        sso_provider = app.config.get('SSO_PROVIDER', 'oauth2')
    except Exception:
        sso_enabled = False
        sso_provider = 'oauth2'

    return render_template('auth/login.html',
                         sso_enabled=sso_enabled,
                         sso_provider=sso_provider)

# 仪表板路由
@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', username=session['username'])

# 登出路由
@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

# 注册SSO蓝图
try:
    from app.views.sso_auth import sso_bp
    app.register_blueprint(sso_bp)
    print("  SSO蓝图已注册")
except ImportError as e:
    print(f"⚠️ SSO蓝图注册失败: {e}")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)