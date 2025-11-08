#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阿里云OSS服务模块
提供文件上传、下载、删除等操作接口
"""

import os
import uuid
import logging
import datetime
import urllib.parse
from typing import Optional, Dict, Any
import alibabacloud_oss_v2 as oss
from app.config import Config

# 配置日志
try:
    from app.utils.logger import setup_logger
    logger = setup_logger('OSSService')
except ImportError:
    logger = logging.getLogger('OSSService')
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class OSSServiceError(Exception):
    """OSS服务异常类"""
    pass


class OSSService:
    """阿里云OSS服务类"""
    
    def __init__(self, bucket=None, region=None):
        """初始化OSS服务"""
        self.config = Config.get_oss_config()
        # 允许覆盖默认配置
        if bucket:
            self.config['bucket'] = bucket
        if region:
            self.config['region'] = region
            
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """初始化OSS客户端"""
        if not Config.is_oss_configured():
            raise OSSServiceError("OSS未正确配置，请检查环境变量")
        
        try:
            # 创建凭证提供者
            credentials_provider = oss.credentials.StaticCredentialsProvider(
                access_key_id=self.config['access_key_id'],
                access_key_secret=self.config['access_key_secret']
            )
            
            # 加载SDK的默认配置，并设置凭证提供者
            cfg = oss.config.load_default()
            cfg.credentials_provider = credentials_provider
            cfg.region = self.config['region']
            
            # 创建OSS客户端
            self.client = oss.Client(cfg)
            logger.info("OSS客户端初始化成功")
        except Exception as e:
            logger.error(f"OSS客户端初始化失败: {e}")
            raise OSSServiceError(f"OSS客户端初始化失败: {e}")
    
    def upload_file(self, file_path: str, object_key: Optional[str] = None, 
                   prefix: str = "uploads/") -> Dict[str, Any]:
        """
        上传文件到OSS
        
        Args:
            file_path (str): 本地文件路径
            object_key (str, optional): OSS对象键名
            prefix (str): 对象键前缀
            
        Returns:
            dict: 上传结果信息
        """
        if not os.path.exists(file_path):
            raise OSSServiceError(f"文件不存在: {file_path}")
        
        # 确定对象键名
        if not object_key:
            filename = os.path.basename(file_path)
            object_key = prefix.rstrip('/') + '/' + filename
        
        try:
            logger.info(f"开始上传文件: {file_path} -> {object_key}")
            
            # 执行上传
            result = self.client.put_object_from_file(
                oss.PutObjectRequest(
                    bucket=self.config['bucket'],
                    key=object_key
                ),
                file_path
            )
            
            # 构造访问URL
            url = self._generate_url(object_key)
            
            upload_info = {
                'status_code': result.status_code,
                'request_id': result.request_id,
                'etag': result.etag,
                'object_key': object_key,
                'url': url,
                'bucket': self.config['bucket']
            }
            
            logger.info(f"文件上传成功: {object_key}")
            return upload_info
            
        except oss.exceptions.ServiceError as e:
            logger.error(f"OSS服务错误: {e.error_code} - {e.message}")
            raise OSSServiceError(f"OSS服务错误: {e.error_code} - {e.message}")
        except Exception as e:
            logger.error(f"文件上传失败: {e}")
            raise OSSServiceError(f"文件上传失败: {e}")
    
    def upload_file_with_unique_name(self, file_path: str, 
                                   prefix: str = "uploads/") -> Dict[str, Any]:
        """
        上传文件到OSS并生成唯一文件名
        
        Args:
            file_path (str): 本地文件路径
            prefix (str): 对象键前缀
            
        Returns:
            dict: 上传结果信息
        """
        filename = os.path.basename(file_path)
        name, ext = os.path.splitext(filename)
        unique_name = f"{name}_{uuid.uuid4().hex[:8]}{ext}"
        object_key = prefix.rstrip('/') + '/' + unique_name
        
        return self.upload_file(file_path, object_key)
    
    def _generate_url(self, object_key: str) -> str:
        """
        生成文件访问URL
        
        Args:
            object_key (str): OSS对象键名
            
        Returns:
            str: 文件访问URL
        """
        return f"https://{self.config['bucket']}.{self.config['region']}.aliyuncs.com/{object_key.lstrip('/')}"
    
    def get_file_url(self, object_key: str) -> str:
        """
        获取文件访问URL
        
        Args:
            object_key (str): OSS对象键名
            
        Returns:
            str: 文件访问URL
        """
        return self._generate_url(object_key)
    
    def generate_presigned_url(self, object_key: str, expires_in: int = 3600, 
                              method: str = 'GET', force_download: bool = False) -> str:
        """
        生成预签名URL（临时访问链接）
        
        Args:
            object_key (str): OSS对象键名
            expires_in (int): 过期时间（秒），默认3600秒（1小时）
            method (str): HTTP方法，支持GET/PUT/HEAD，默认GET
            force_download (bool): 是否强制下载，默认False
            
        Returns:
            str: 预签名URL
        """
        try:
            # 使用SDK的presign功能生成预签名URL
            if method.upper() == 'GET':
                if force_download:
                    # 强制下载，设置Content-Disposition头
                    filename = os.path.basename(object_key)
                    encoded_filename = urllib.parse.quote(filename)
                    req = oss.GetObjectRequest(
                        bucket=self.config['bucket'],
                        key=object_key,
                        response_content_disposition=f"attachment; filename*=utf-8''{encoded_filename}"
                    )
                else:
                    req = oss.GetObjectRequest(
                        bucket=self.config['bucket'],
                        key=object_key
                    )
                
                # 转换过期秒数为timedelta
                expires = datetime.timedelta(seconds=expires_in)
                presigned = self.client.presign(req, expires=expires)
                
            elif method.upper() == 'PUT':
                req = oss.PutObjectRequest(
                    bucket=self.config['bucket'],
                    key=object_key
                )
                expires = datetime.timedelta(seconds=expires_in)
                presigned = self.client.presign(req, expires=expires)
                
            elif method.upper() == 'HEAD':
                req = oss.HeadObjectRequest(
                    bucket=self.config['bucket'],
                    key=object_key
                )
                expires = datetime.timedelta(seconds=expires_in)
                presigned = self.client.presign(req, expires=expires)
            
            logger.info(f"生成预签名URL成功: {object_key} ({method})")
            return presigned.url
            
        except Exception as e:
            logger.error(f"生成预签名URL失败: {e}")
            # 回退到手动构造URL（无签名）
            base_url = self._generate_url(object_key)
            logger.warning(f"回退到基础URL: {base_url}")
            return base_url
    
    def delete_file(self, object_key: str) -> bool:
        """
        删除OSS中的文件
        
        Args:
            object_key (str): OSS对象键名
            
        Returns:
            bool: 删除是否成功
        """
        try:
            result = self.client.delete_object(
                oss.DeleteObjectRequest(
                    bucket=self.config['bucket'],
                    key=object_key
                )
            )
            
            if result.status_code == 204:
                logger.info(f"文件删除成功: {object_key}")
                return True
            else:
                logger.warning(f"文件删除可能失败: {object_key}, 状态码: {result.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"文件删除失败: {e}")
            raise OSSServiceError(f"文件删除失败: {e}")
    
    def file_exists(self, object_key: str) -> bool:
        """
        检查文件是否存在
        
        Args:
            object_key (str): OSS对象键名
            
        Returns:
            bool: 文件是否存在
        """
        try:
            self.client.head_object(
                oss.HeadObjectRequest(
                    bucket=self.config['bucket'],
                    key=object_key
                )
            )
            return True
        except oss.exceptions.ServiceError as e:
            if e.error_code == "NoSuchKey":
                return False
            else:
                raise OSSServiceError(f"检查文件存在性时出错: {e}")
        except Exception as e:
            logger.error(f"检查文件存在性时出错: {e}")
            raise OSSServiceError(f"检查文件存在性时出错: {e}")


# 全局单例实例
_oss_service_instance = None


def get_oss_service(bucket=None, region=None) -> OSSService:
    """
    获取OSS服务单例实例
    
    Returns:
        OSSService: OSS服务实例
    """
    global _oss_service_instance
    if _oss_service_instance is None or bucket is not None or region is not None:
        _oss_service_instance = OSSService(bucket, region)
    return _oss_service_instance


def upload_file_to_oss(file_path: str, object_key: Optional[str] = None,
                      prefix: str = "uploads/", bucket=None, region=None) -> Dict[str, Any]:
    """
    上传文件到OSS的便捷函数
    
    Args:
        file_path (str): 本地文件路径
        object_key (str, optional): OSS对象键名
        prefix (str): 对象键前缀
        bucket (str, optional): 存储桶名称
        region (str, optional): 区域
        
    Returns:
        dict: 上传结果信息
    """
    service = get_oss_service(bucket, region)
    return service.upload_file(file_path, object_key, prefix)


def upload_file_with_unique_name_to_oss(file_path: str,
                                      prefix: str = "uploads/", bucket=None, region=None) -> Dict[str, Any]:
    """
    上传文件到OSS并生成唯一文件名的便捷函数
    
    Args:
        file_path (str): 本地文件路径
        prefix (str): 对象键前缀
        bucket (str, optional): 存储桶名称
        region (str, optional): 区域
        
    Returns:
        dict: 上传结果信息
    """
    service = get_oss_service(bucket, region)
    return service.upload_file_with_unique_name(file_path, prefix)


def generate_presigned_url(object_key: str, expires_in: int = 3600, 
                          method: str = 'GET', force_download: bool = False,
                          bucket=None, region=None) -> str:
    """
    生成预签名URL的便捷函数
    
    Args:
        object_key (str): OSS对象键名
        expires_in (int): 过期时间（秒），默认3600秒（1小时）
        method (str): HTTP方法，支持GET/PUT/HEAD，默认GET
        force_download (bool): 是否强制下载，默认False
        bucket (str, optional): 存储桶名称
        region (str, optional): 区域
        
    Returns:
        str: 预签名URL
    """
    service = get_oss_service(bucket, region)
    return service.generate_presigned_url(object_key, expires_in, method, force_download)


# 使用示例
if __name__ == "__main__":
    # 创建测试文件
    test_content = "这是一个测试文件内容"
    with open("test_upload.txt", "w", encoding="utf-8") as f:
        f.write(test_content)
    
    try:
        # 上传文件到指定的bucket和region
        result = upload_file_to_oss("test_upload.txt", bucket="fciai", region="cn-beijing")
        print("上传结果:")
        for key, value in result.items():
            print(f"  {key}: {value}")
        
        # 生成预签名URL（临时下载链接）
        presigned_url = generate_presigned_url(result['object_key'], 3600, bucket="fciai", region="cn-beijing")
        print(f"\n临时下载链接: {presigned_url}")
        
        # 生成强制下载链接
        download_url = generate_presigned_url(
            result['object_key'], 3600, force_download=True, bucket="fciai", region="cn-beijing")
        print(f"\n强制下载链接: {download_url}")
        
        # 上传文件并生成唯一名称
        result2 = upload_file_with_unique_name_to_oss("test_upload.txt", bucket="fciai", region="cn-beijing")
        print("\n唯一名称上传结果:")
        for key, value in result2.items():
            print(f"  {key}: {value}")
        
        # 为唯一名称文件生成预签名URL
        presigned_url2 = generate_presigned_url(result2['object_key'], 3600, bucket="fciai", region="cn-beijing")
        print(f"\n唯一文件临时下载链接: {presigned_url2}")
        
    except Exception as e:
        print(f"操作失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 清理测试文件
        if os.path.exists("test_upload.txt"):
            os.remove("test_upload.txt")
            print("\n已清理测试文件")