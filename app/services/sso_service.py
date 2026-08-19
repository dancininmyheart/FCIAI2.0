"""
SSO (Single Sign-On) 服务模块
支持多种SSO协议：OAuth2、SAML、OIDC
"""
import os
import json
import uuid
import base64
import logging
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlencode, parse_qs, urlparse
import requests
from flask import current_app, session, url_for

logger = logging.getLogger(__name__)


class SSOError(Exception):
    """SSO相关异常"""
    pass


class BaseSSOProvider:
    """SSO提供者基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.provider_name = self.__class__.__name__.lower().replace('ssoprovider', '')
    
    def get_authorization_url(self, state: str = None) -> str:
        """获取授权URL"""
        raise NotImplementedError
    
    def handle_callback(self, request_args: Dict[str, Any]) -> Dict[str, Any]:
        """处理回调并获取用户信息"""
        raise NotImplementedError
    
    def get_logout_url(self, return_url: str = None) -> Optional[str]:
        """获取登出URL"""
        return None


class OAuth2SSOProvider(BaseSSOProvider):
    """OAuth2/OIDC SSO提供者"""
    
    def get_authorization_url(self, state: str = None) -> str:
        """生成OAuth2授权URL"""
        if not state:
            state = str(uuid.uuid4())
        
        # 将state存储到session中
        session['oauth2_state'] = state
        
        params = {
            'client_id': self.config['client_id'],
            'response_type': 'code',
            'scope': self.config.get('scope', 'openid profile email'),
            'redirect_uri': self.config['redirect_uri'],
            'state': state
        }
        
        # 添加额外参数
        if 'extra_params' in self.config:
            params.update(self.config['extra_params'])
        
        auth_url = f"{self.config['authorization_url']}?{urlencode(params)}"
        logger.info(f"生成OAuth2授权URL: {auth_url}")
        return auth_url
    
    def handle_callback(self, request_args: Dict[str, Any]) -> Dict[str, Any]:
        """处理OAuth2回调"""
        # 验证state参数
        received_state = request_args.get('state')
        stored_state = session.pop('oauth2_state', None)
        
        if not received_state or received_state != stored_state:
            raise SSOError("Invalid state parameter")
        
        # 检查是否有错误
        if 'error' in request_args:
            error_desc = request_args.get('error_description', request_args['error'])
            raise SSOError(f"OAuth2 error: {error_desc}")
        
        # 获取授权码
        code = request_args.get('code')
        if not code:
            raise SSOError("No authorization code received")
        
        # 交换访问令牌
        token_data = self._exchange_code_for_token(code)
        
        # 获取用户信息
        user_info = self._get_user_info(token_data['access_token'])
        
        return {
            'provider': 'oauth2',
            'user_info': user_info,
            'token_data': token_data
        }
    
    def _exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """交换授权码获取访问令牌"""
        token_data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': self.config['redirect_uri'],
            'client_id': self.config['client_id'],
            'client_secret': self.config['client_secret']
        }
        
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        
        try:
            response = requests.post(
                self.config['token_url'],
                data=token_data,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            
            token_response = response.json()
            logger.info("成功获取访问令牌")
            return token_response
            
        except requests.RequestException as e:
            logger.error(f"获取访问令牌失败: {e}")
            raise SSOError(f"Failed to get access token: {e}")
    
    def _get_user_info(self, access_token: str) -> Dict[str, Any]:
        """使用访问令牌获取用户信息"""
        headers = {'Authorization': f'Bearer {access_token}'}
        
        try:
            response = requests.get(
                self.config['userinfo_url'],
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            
            user_info = response.json()
            logger.info(f"成功获取用户信息: {user_info.get('sub', 'unknown')}")
            return user_info
            
        except requests.RequestException as e:
            logger.error(f"获取用户信息失败: {e}")
            raise SSOError(f"Failed to get user info: {e}")
    
    def get_logout_url(self, return_url: str = None) -> Optional[str]:
        """获取OAuth2登出URL"""
        logout_url = self.config.get('logout_url')
        if not logout_url:
            return None
        
        params = {}
        if return_url:
            params['post_logout_redirect_uri'] = return_url
        
        if 'client_id' in self.config:
            params['client_id'] = self.config['client_id']
        
        if params:
            logout_url += f"?{urlencode(params)}"
        
        return logout_url


class SAMLSSOProvider(BaseSSOProvider):
    """SAML SSO提供者"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        try:
            from onelogin.saml2.auth import OneLogin_Saml2_Auth
            from onelogin.saml2.settings import OneLogin_Saml2_Settings
            self.saml_auth_class = OneLogin_Saml2_Auth
            self.saml_settings_class = OneLogin_Saml2_Settings
        except ImportError:
            raise SSOError("python3-saml library is required for SAML SSO")
    
    def get_authorization_url(self, state: str = None) -> str:
        """生成SAML授权URL"""
        # SAML通常需要POST请求，这里返回一个特殊标识
        # 实际的重定向会在视图中处理
        return "saml_redirect_required"
    
    def handle_callback(self, request_args: Dict[str, Any]) -> Dict[str, Any]:
        """处理SAML回调"""
        # SAML回调处理需要完整的请求对象
        # 这里只是示例，实际实现需要在视图中处理
        raise NotImplementedError("SAML callback handling requires full request object")
    
    def _get_saml_settings(self) -> Dict[str, Any]:
        """获取SAML设置"""
        return {
            "sp": {
                "entityId": self.config['sp_entity_id'],
                "assertionConsumerService": {
                    "url": self.config['sp_acs_url'],
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
                },
                "singleLogoutService": {
                    "url": self.config['sp_sls_url'],
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
                },
                "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
                "x509cert": "",
                "privateKey": ""
            },
            "idp": {
                "entityId": self.config['idp_entity_id'],
                "singleSignOnService": {
                    "url": self.config['idp_sso_url'],
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
                },
                "singleLogoutService": {
                    "url": self.config['idp_sls_url'],
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
                },
                "x509cert": self.config['idp_x509_cert']
            }
        }


class SSOService:
    """SSO服务管理器"""

    def __init__(self):
        self.providers = {}
        self._initialized = False

    def _ensure_initialized(self):
        """确保服务已初始化"""
        if not self._initialized:
            self._initialize_providers()
            self._initialized = True

    def _initialize_providers(self):
        """初始化SSO提供者"""
        try:
            from flask import current_app
            if not current_app.config.get('SSO_ENABLED'):
                logger.info("SSO未启用")
                return
        except RuntimeError:
            # 应用上下文不可用，延迟初始化
            logger.debug("应用上下文不可用，延迟SSO初始化")
            return
        
        try:
            provider_type = str(
                current_app.config.get('SSO_PROVIDER', 'oauth2')
            ).strip().lower()

            if provider_type in ('oauth2', 'oidc'):
                # 检查是否是Authing提供者
                oauth2_vendor = str(
                    current_app.config.get('OAUTH2_VENDOR')
                    or os.getenv('OAUTH2_VENDOR', '')
                ).strip().lower()
                auth_url = current_app.config.get('OAUTH2_AUTHORIZATION_URL', '')
                authing_host = (
                    current_app.config.get('AUTHING_APP_HOST')
                    or os.getenv('AUTHING_APP_HOST', '')
                )
                if (
                    oauth2_vendor == 'authing'
                    or bool(authing_host)
                    or 'authing' in auth_url.lower()
                ):
                    self._setup_authing_provider()
                else:
                    self._setup_oauth2_provider()
            elif provider_type == 'authing':
                self._setup_authing_provider()
            elif provider_type == 'saml':
                self._setup_saml_provider()
            else:
                logger.warning(f"不支持的SSO提供者类型: {provider_type}")
        except Exception as e:
            logger.error(f"SSO提供者初始化失败: {e}")

    def _setup_oauth2_provider(self):
        """设置OAuth2提供者"""
        from flask import current_app

        config = {
            'client_id': current_app.config.get('OAUTH2_CLIENT_ID', ''),
            'client_secret': current_app.config.get('OAUTH2_CLIENT_SECRET', ''),
            'authorization_url': current_app.config.get('OAUTH2_AUTHORIZATION_URL', ''),
            'token_url': current_app.config.get('OAUTH2_TOKEN_URL', ''),
            'userinfo_url': current_app.config.get('OAUTH2_USERINFO_URL', ''),
            'scope': current_app.config.get('OAUTH2_SCOPE', 'openid profile email'),
            'redirect_uri': current_app.config.get('OAUTH2_REDIRECT_URI', '')
        }
        
        # 验证必需的配置
        required_fields = ['client_id', 'client_secret', 'authorization_url', 'token_url', 'userinfo_url']
        missing_fields = [field for field in required_fields if not config.get(field)]
        
        if missing_fields:
            logger.error(f"OAuth2配置缺少必需字段: {missing_fields}")
            return
        
        self.providers['oauth2'] = OAuth2SSOProvider(config)
        logger.info("OAuth2 SSO提供者已初始化")

    def _setup_authing_provider(self):
        """设置Authing提供者"""
        from flask import current_app
        from .authing_provider import AuthingOAuth2Provider

        config = {
            'client_id': current_app.config.get('OAUTH2_CLIENT_ID', ''),
            'client_secret': current_app.config.get('OAUTH2_CLIENT_SECRET', ''),
            'authorization_url': current_app.config.get('OAUTH2_AUTHORIZATION_URL', ''),
            'token_url': current_app.config.get('OAUTH2_TOKEN_URL', ''),
            'userinfo_url': current_app.config.get('OAUTH2_USERINFO_URL', ''),
            'logout_url': current_app.config.get('OAUTH2_LOGOUT_URL', ''),
            'scope': current_app.config.get('OAUTH2_SCOPE', 'openid profile email phone'),
            'redirect_uri': current_app.config.get('OAUTH2_REDIRECT_URI', ''),
            'app_host': (
                current_app.config.get('AUTHING_APP_HOST')
                or os.getenv('AUTHING_APP_HOST', '')
            )
        }

        # 验证必需的配置
        required_fields = ['client_id', 'client_secret', 'authorization_url', 'token_url', 'userinfo_url']
        missing_fields = [field for field in required_fields if not config.get(field)]

        if missing_fields:
            logger.error(f"Authing配置缺少必需字段: {missing_fields}")
            raise SSOError(f"Authing配置不完整，缺少: {', '.join(missing_fields)}")

        self.providers['authing'] = AuthingOAuth2Provider(config)
        self.providers['oauth2'] = self.providers['authing']  # 兼容性别名
        logger.info("Authing SSO提供者已初始化")
    
    def _setup_saml_provider(self):
        """设置SAML提供者"""
        from flask import current_app

        config = {
            'sp_entity_id': current_app.config.get('SAML_SP_ENTITY_ID', ''),
            'sp_acs_url': current_app.config.get('SAML_SP_ACS_URL', ''),
            'sp_sls_url': current_app.config.get('SAML_SP_SLS_URL', ''),
            'idp_entity_id': current_app.config.get('SAML_IDP_ENTITY_ID', ''),
            'idp_sso_url': current_app.config.get('SAML_IDP_SSO_URL', ''),
            'idp_sls_url': current_app.config.get('SAML_IDP_SLS_URL', ''),
            'idp_x509_cert': current_app.config.get('SAML_IDP_X509_CERT', '')
        }
        
        # 验证必需的配置
        required_fields = ['idp_entity_id', 'idp_sso_url', 'idp_x509_cert']
        missing_fields = [field for field in required_fields if not config.get(field)]
        
        if missing_fields:
            logger.error(f"SAML配置缺少必需字段: {missing_fields}")
            return
        
        try:
            self.providers['saml'] = SAMLSSOProvider(config)
            logger.info("SAML SSO提供者已初始化")
        except SSOError as e:
            logger.error(f"SAML SSO提供者初始化失败: {e}")
    
    def is_enabled(self) -> bool:
        """检查SSO是否启用"""
        self._ensure_initialized()
        try:
            from flask import current_app
            return current_app.config.get('SSO_ENABLED', False) and bool(self.providers)
        except RuntimeError:
            return False

    def get_provider(self, provider_name: str = None) -> Optional[BaseSSOProvider]:
        """获取SSO提供者"""
        self._ensure_initialized()
        try:
            from flask import current_app
            if not provider_name:
                provider_name = current_app.config.get('SSO_PROVIDER', 'oauth2')
        except RuntimeError:
            provider_name = provider_name or 'oauth2'

        return self.providers.get(provider_name)

    def get_authorization_url(self, provider_name: str = None) -> str:
        """获取授权URL"""
        provider = self.get_provider(provider_name)
        if not provider:
            raise SSOError(f"SSO provider not found: {provider_name}")

        return provider.get_authorization_url()

    def handle_callback(self, request_args: Dict[str, Any], provider_name: str = None) -> Dict[str, Any]:
        """处理SSO回调"""
        provider = self.get_provider(provider_name)
        if not provider:
            raise SSOError(f"SSO provider not found: {provider_name}")

        return provider.handle_callback(request_args)

    def map_user_attributes(self, user_info: Dict[str, Any]) -> Dict[str, Any]:
        """映射用户属性"""
        try:
            from flask import current_app
            mapping = current_app.config.get('SSO_USER_MAPPING', {})
        except RuntimeError:
            # 默认映射
            mapping = {
                'username': 'preferred_username',
                'email': 'email',
                'first_name': 'given_name',
                'last_name': 'family_name',
                'display_name': 'name'
            }

        mapped_user = {}
        
        for local_attr, remote_attr in mapping.items():
            if remote_attr in user_info:
                mapped_user[local_attr] = user_info[remote_attr]
        
        # 确保有用户名
        if 'username' not in mapped_user:
            mapped_user['username'] = (
                user_info.get('preferred_username') or
                user_info.get('email') or
                user_info.get('sub') or
                f"sso_user_{uuid.uuid4().hex[:8]}"
            )
        
        logger.info(f"用户属性映射完成: {mapped_user.get('username')}")
        return mapped_user


# 全局SSO服务实例（延迟初始化）
sso_service = None


def get_sso_service() -> SSOService:
    """获取SSO服务实例（延迟初始化）"""
    global sso_service
    if sso_service is None:
        sso_service = SSOService()
    return sso_service
