"""
Authing身份云SSO提供者
专门针对Authing API优化的SSO实现
"""
import logging
import os
import requests
from typing import Dict, Any, Optional
from urllib.parse import urlencode, parse_qs, urlparse
import secrets
import time
from flask import current_app, session

from .sso_service import BaseSSOProvider, SSOError

logger = logging.getLogger(__name__)


class AuthingOAuth2Provider(BaseSSOProvider):
    """Authing身份云OAuth2提供者"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.app_id = config.get('client_id')
        self.app_secret = config.get('client_secret')
        # The identity tenant is deployment-specific. Requiring configuration
        # keeps organisation hostnames out of the distributable demo.
        self.app_host = (
            config.get('app_host') or os.getenv('AUTHING_APP_HOST', '')
        ).strip().rstrip('/')
        
        # Authing特定的端点
        self.auth_url = self._configured_endpoint(config, 'authorization_url', '/oidc/auth')
        self.token_url = self._configured_endpoint(config, 'token_url', '/oidc/token')
        self.userinfo_url = self._configured_endpoint(config, 'userinfo_url', '/oidc/me')
        self.logout_url = self._configured_endpoint(config, 'logout_url', '/oidc/session/end')
        
        # Authing支持的scope
        self.scope = config.get('scope', 'openid profile email phone')
        self.redirect_uri = config.get('redirect_uri')
        
        logger.info(f"Authing OAuth2提供者已初始化 - App ID: {self.app_id}")
    
    def _configured_endpoint(
        self,
        config: Dict[str, Any],
        key: str,
        path: str,
    ) -> str:
        """Return an explicit endpoint or derive one from the configured tenant."""
        explicit_url = (config.get(key) or '').strip()
        if explicit_url:
            return explicit_url
        if self.app_host:
            return f"{self.app_host}{path}"
        return ''

    @staticmethod
    def _require_endpoint(endpoint: str, setting_name: str) -> str:
        """Fail closed before an HTTP request when SSO is not configured."""
        if not endpoint:
            raise SSOError(
                f"Authing SSO is not configured: set {setting_name} "
                "or AUTHING_APP_HOST"
            )
        return endpoint

    def get_authorization_url(self) -> str:
        """获取Authing授权URL"""
        auth_endpoint = self._require_endpoint(
            self.auth_url,
            'OAUTH2_AUTHORIZATION_URL',
        )
        try:
            # 生成state参数防止CSRF攻击
            state = secrets.token_urlsafe(32)
            session['oauth_state'] = state
            
            # 构建授权参数
            params = {
                'client_id': self.app_id,
                'response_type': 'code',
                'scope': self.scope,
                'redirect_uri': self.redirect_uri,
                'state': state,
                'prompt': 'login'  # 强制用户重新认证
            }
            
            auth_url = f"{auth_endpoint}?{urlencode(params)}"
            logger.info(f"生成Authing授权URL: {auth_url}")
            
            return auth_url
            
        except Exception as e:
            logger.error(f"生成Authing授权URL失败: {e}")
            raise SSOError(f"生成授权URL失败: {str(e)}")
    
    def handle_callback(self, request_args: Dict[str, Any]) -> Dict[str, Any]:
        """处理Authing回调"""
        try:
            # 检查错误
            if 'error' in request_args:
                error_desc = request_args.get('error_description', request_args['error'])
                logger.error(f"Authing授权错误: {error_desc}")
                raise SSOError(f"授权失败: {error_desc}")
            
            # 验证state参数
            received_state = request_args.get('state')
            stored_state = session.pop('oauth_state', None)

            # 在开发环境中，如果是本地回调URL，可以放宽state验证
            from flask import current_app
            is_development = current_app.config.get('ENV') == 'development'
            is_local_callback = 'localhost' in current_app.config.get('OAUTH2_REDIRECT_URI', '')

            if not received_state or received_state != stored_state:
                if is_development and is_local_callback:
                    logger.warning("开发环境中State参数验证失败，但继续处理")
                    logger.warning(f"接收到的state: {received_state}")
                    logger.warning(f"存储的state: {stored_state}")
                else:
                    logger.error("State参数验证失败")
                    raise SSOError("状态验证失败，可能存在安全风险")
            
            # 获取授权码
            auth_code = request_args.get('code')
            if not auth_code:
                logger.error("未收到授权码")
                raise SSOError("未收到授权码")
            
            logger.info(f"收到Authing授权码: {auth_code[:10]}...")
            
            # 用授权码换取访问令牌
            token_data = self._exchange_code_for_token(auth_code)
            
            # 获取用户信息
            user_info = self._get_user_info(token_data['access_token'])
            
            return {
                'provider': 'authing',
                'token_data': token_data,
                'user_info': user_info
            }
            
        except SSOError:
            raise
        except Exception as e:
            logger.error(f"处理Authing回调失败: {e}")
            raise SSOError(f"回调处理失败: {str(e)}")
    
    def _exchange_code_for_token(self, auth_code: str) -> Dict[str, Any]:
        """用授权码换取访问令牌"""
        token_endpoint = self._require_endpoint(
            self.token_url,
            'OAUTH2_TOKEN_URL',
        )
        try:
            # 构建令牌请求
            token_data = {
                'client_id': self.app_id,
                'client_secret': self.app_secret,
                'code': auth_code,
                'grant_type': 'authorization_code',
                'redirect_uri': self.redirect_uri
            }
            
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json'
            }
            
            logger.info(f"向Authing请求访问令牌: {self.token_url}")
            
            # 发送令牌请求
            response = requests.post(
                token_endpoint,
                data=token_data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Authing令牌请求失败: {response.status_code} - {response.text}")
                raise SSOError(f"获取访问令牌失败: HTTP {response.status_code}")
            
            token_response = response.json()
            
            # 检查响应中的错误
            if 'error' in token_response:
                error_desc = token_response.get('error_description', token_response['error'])
                logger.error(f"Authing令牌响应错误: {error_desc}")
                raise SSOError(f"令牌获取失败: {error_desc}")
            
            # 验证必需的令牌字段
            required_fields = ['access_token', 'token_type']
            for field in required_fields:
                if field not in token_response:
                    logger.error(f"令牌响应缺少字段: {field}")
                    raise SSOError(f"令牌响应格式错误")
            
            logger.info("成功获取Authing访问令牌")
            return token_response
            
        except requests.RequestException as e:
            logger.error(f"Authing令牌请求网络错误: {e}")
            raise SSOError(f"网络请求失败: {str(e)}")
        except Exception as e:
            logger.error(f"Authing令牌交换失败: {e}")
            raise SSOError(f"令牌交换失败: {str(e)}")
    
    def _get_user_info(self, access_token: str) -> Dict[str, Any]:
        """获取Authing用户信息"""
        userinfo_endpoint = self._require_endpoint(
            self.userinfo_url,
            'OAUTH2_USERINFO_URL',
        )
        try:
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            }
            
            logger.info(f"向Authing请求用户信息: {self.userinfo_url}")
            
            # 发送用户信息请求
            response = requests.get(
                userinfo_endpoint,
                headers=headers,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Authing用户信息请求失败: {response.status_code} - {response.text}")
                raise SSOError(f"获取用户信息失败: HTTP {response.status_code}")
            
            user_info = response.json()
            
            # 检查响应中的错误
            if 'error' in user_info:
                error_desc = user_info.get('error_description', user_info['error'])
                logger.error(f"Authing用户信息响应错误: {error_desc}")
                raise SSOError(f"用户信息获取失败: {error_desc}")
            
            # 验证必需的用户字段
            if 'sub' not in user_info:
                logger.error("用户信息响应缺少sub字段")
                raise SSOError("用户信息格式错误")
            
            logger.info(f"成功获取Authing用户信息: {user_info.get('username', user_info.get('sub'))}")
            return user_info
            
        except requests.RequestException as e:
            logger.error(f"Authing用户信息请求网络错误: {e}")
            raise SSOError(f"网络请求失败: {str(e)}")
        except Exception as e:
            logger.error(f"Authing用户信息获取失败: {e}")
            raise SSOError(f"用户信息获取失败: {str(e)}")
    
    def get_logout_url(self, return_url: str = None) -> Optional[str]:
        """获取Authing登出URL"""
        try:
            if not self.logout_url:
                return None
            
            params = {}
            if return_url:
                params['post_logout_redirect_uri'] = return_url
            
            if params:
                logout_url = f"{self.logout_url}?{urlencode(params)}"
            else:
                logout_url = self.logout_url
            
            logger.info(f"生成Authing登出URL: {logout_url}")
            return logout_url
            
        except Exception as e:
            logger.error(f"生成Authing登出URL失败: {e}")
            return None
    
    def validate_token(self, access_token: str) -> bool:
        """验证Authing访问令牌"""
        try:
            # 通过获取用户信息来验证令牌
            self._get_user_info(access_token)
            return True
        except Exception as e:
            logger.warning(f"Authing令牌验证失败: {e}")
            return False
    
    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """刷新Authing访问令牌"""
        token_endpoint = self._require_endpoint(
            self.token_url,
            'OAUTH2_TOKEN_URL',
        )
        try:
            token_data = {
                'client_id': self.app_id,
                'client_secret': self.app_secret,
                'refresh_token': refresh_token,
                'grant_type': 'refresh_token'
            }
            
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json'
            }
            
            response = requests.post(
                token_endpoint,
                data=token_data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Authing令牌刷新失败: {response.status_code}")
                raise SSOError(f"令牌刷新失败: HTTP {response.status_code}")
            
            token_response = response.json()
            
            if 'error' in token_response:
                error_desc = token_response.get('error_description', token_response['error'])
                raise SSOError(f"令牌刷新失败: {error_desc}")
            
            logger.info("成功刷新Authing访问令牌")
            return token_response
            
        except Exception as e:
            logger.error(f"Authing令牌刷新失败: {e}")
            raise SSOError(f"令牌刷新失败: {str(e)}")
    
    def get_provider_info(self) -> Dict[str, Any]:
        """获取Authing提供者信息"""
        return {
            'name': 'Authing身份云',
            'type': 'oauth2',
            'app_id': self.app_id,
            'app_host': self.app_host,
            'scope': self.scope,
            'endpoints': {
                'authorization': self.auth_url,
                'token': self.token_url,
                'userinfo': self.userinfo_url,
                'logout': self.logout_url
            }
        }
