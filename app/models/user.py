from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db
from app.utils.timezone_helper import now_with_timezone

# 角色-权限关联表
role_permissions = db.Table('role_permissions',
    db.Column('role_id', db.Integer, db.ForeignKey('role.id')),
    db.Column('permission_id', db.Integer, db.ForeignKey('permission.id'))
)

class Permission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))

class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    permissions = db.relationship('Permission', secondary=role_permissions, backref='roles')

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    first_name = db.Column(db.String(50), nullable=True)
    last_name = db.Column(db.String(50), nullable=True)
    display_name = db.Column(db.String(100), nullable=True)

    # SSO相关字段
    sso_provider = db.Column(db.String(50), nullable=True)  # oauth2, saml, oidc
    sso_subject = db.Column(db.String(255), nullable=True)  # SSO提供者的用户ID
    last_login = db.Column(db.DateTime(timezone=True), nullable=True)

    role_id = db.Column(db.Integer, db.ForeignKey('role.id'))
    role = db.relationship('Role', backref='users')
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    register_time = db.Column(db.DateTime(timezone=True), default=now_with_timezone)
    approve_time = db.Column(db.DateTime(timezone=True))
    approve_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approve_user = db.relationship('User', remote_side=[id], backref='approved_users')

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)

    def has_permission(self, permission_name):
        if not self.role:
            return False
        return any(p.name == permission_name for p in self.role.permissions)

    @property
    def is_active(self):
        return self.status == 'approved'

    def is_administrator(self):
        """Check the role in the current database, not a process-global ID cache."""
        return bool(self.role and self.role.name == 'admin')

    def is_sso_user(self):
        """检查是否为SSO用户"""
        return bool(self.sso_provider)

    def can_change_password(self):
        """检查用户是否可以修改密码（SSO用户不能修改密码）"""
        return not self.is_sso_user()

    def get_display_name(self):
        """获取显示名称"""
        if self.display_name:
            return self.display_name
        elif self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        else:
            return self.username

    def get_full_name(self):
        """获取全名"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.username
