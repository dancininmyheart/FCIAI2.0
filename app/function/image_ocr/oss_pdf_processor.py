#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于阿里云OSS的PDF处理器
将本地PDF文件上传到OSS并生成直链，然后传递给MinerU进行处理
"""

import os
import datetime
import logging
import urllib.parse
import alibabacloud_oss_v2 as oss
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 配置日志
logger = logging.getLogger(__name__)


class OSSPDFProcessor:
    """基于OSS的PDF处理器"""
    
    def __init__(self, bucket=None, region=None):
        """初始化OSS PDF处理器"""
        # 获取配置信息
        self.access_key_id = os.environ.get('OSS_ACCESS_KEY_ID')
        self.access_key_secret = os.environ.get('OSS_ACCESS_KEY_SECRET')
        self.bucket = bucket or os.environ.get('OSS_BUCKET', 'fciai')
        self.region = region or os.environ.get('OSS_REGION', 'cn-beijing')
        
        # 检查必要配置
        if not self.access_key_id or not self.access_key_secret:
            raise ValueError("请在.env文件中设置OSS_ACCESS_KEY_ID和OSS_ACCESS_KEY_SECRET")
        
        # 初始化OSS客户端
        self._initialize_oss_client()
    
    def _initialize_oss_client(self):
        """初始化OSS客户端"""
        try:
            # 创建凭证提供者
            credentials_provider = oss.credentials.StaticCredentialsProvider(
                access_key_id=self.access_key_id,
                access_key_secret=self.access_key_secret
            )
            
            # 加载SDK的默认配置，并设置凭证提供者
            cfg = oss.config.load_default()
            cfg.credentials_provider = credentials_provider
            cfg.region = self.region  # 确保使用初始化时确定的region
            
            # 创建OSS客户端
            self.client = oss.Client(cfg)
            logger.info("OSS客户端初始化成功")
        except Exception as e:
            logger.error(f"OSS客户端初始化失败: {e}")
            raise
    
    def upload_pdf_and_get_url(self, file_path, object_key=None, expires_in=3600):
        """
        上传PDF文件到OSS并生成直链
        
        Args:
            file_path (str): 本地PDF文件路径
            object_key (str): OSS对象键名，如果未提供则使用文件名
            expires_in (int): 预签名URL过期时间（秒），默认1小时
            
        Returns:
            str: 文件的直链URL
        """
        # 检查文件是否存在
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        # 验证是否为PDF文件
        if not file_path.lower().endswith('.pdf'):
            raise ValueError("文件必须是PDF格式")
        
        # 如果没有提供object_key，则使用文件名
        if not object_key:
            object_key = os.path.basename(file_path)
        
        try:
            logger.info(f"开始上传PDF文件: {file_path}")
            logger.info(f"目标存储桶: {self.bucket}")
            logger.info(f"目标对象名: {object_key}")
            logger.info(f"区域: {self.region}")
            
            # 上传文件到OSS
            result = self.client.put_object_from_file(
                oss.PutObjectRequest(
                    bucket=self.bucket,
                    key=object_key
                ),
                file_path
            )
            
            # 生成预签名URL（强制下载）
            filename = os.path.basename(object_key)
            encoded_filename = urllib.parse.quote(filename)
            req = oss.GetObjectRequest(
                bucket=self.bucket,
                key=object_key,
                response_content_disposition=f"attachment; filename*=utf-8''{encoded_filename}"
            )
            
            # 转换过期秒数为timedelta
            expires = datetime.timedelta(seconds=expires_in)
            presigned = self.client.presign(req, expires=expires)
            
            logger.info(f"PDF文件上传成功")
            logger.info(f'状态码: {result.status_code}')
            logger.info(f'请求ID: {result.request_id}')
            logger.info(f'ETag: {result.etag}')
            logger.info(f'直链URL: {presigned.url}')
            
            return presigned.url
            
        except oss.exceptions.ServiceError as e:
            logger.error(f"OSS服务错误:")
            logger.error(f"错误代码: {e.error_code}")
            logger.error(f"错误消息: {e.message}")
            logger.error(f"请求ID: {e.request_id}")
            raise
        except Exception as e:
            logger.error(f"上传过程中出现错误: {e}")
            raise
    
    def process_pdf_with_mineru(self, file_path, mineru_api, bucket=None, region=None, object_key=None, expires_in=3600, enable_ocr=True):
        """
        使用OSS直链处理PDF文件
        
        Args:
            file_path (str): 本地PDF文件路径
            mineru_api (MinerUAPI): MinerU API实例
            bucket (str): OSS存储桶名称
            region (str): OSS区域
            object_key (str): OSS对象键名，如果未提供则使用文件名
            expires_in (int): 预签名URL过期时间（秒），默认1小时
            enable_ocr (bool): 是否启用OCR功能，默认True
            
        Returns:
            dict: MinerU处理结果
        """
        try:
            # 如果提供了bucket或region参数，则使用它们
            original_bucket = self.bucket
            original_region = self.region
            
            if bucket:
                self.bucket = bucket
            if region:
                self.region = region
                
            # 上传PDF文件到OSS并获取直链
            pdf_url = self.upload_pdf_and_get_url(file_path, object_key, expires_in)
            
            # 恢复原始的bucket和region设置
            self.bucket = original_bucket
            self.region = original_region
            
            # 使用MinerU处理PDF
            logger.info(f"使用MinerU处理PDF，URL: {pdf_url}, OCR: {enable_ocr}")
            result = mineru_api.process_pdf_with_url(pdf_url, enable_ocr=enable_ocr)
            
            return result
            
        except Exception as e:
            logger.error(f"使用OSS直链处理PDF时出错: {e}")
            raise


# 使用示例
if __name__ == "__main__":
    # 创建测试PDF文件
    test_content = "%PDF-1.4\n%äüöß\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/MediaBox [0 0 612 792]\n/Resources <<>>\n>>\nendobj\nxref\n0 4\n0000000000 65535 f \n0000000015 00000 n \n0000000060 00000 n \n0000000111 00000 n \ntrailer\n<<\n/Size 4\n/Root 1 0 R\n>>\nstartxref\n190\n%%EOF"
    
    with open("test.pdf", "w", encoding="utf-8") as f:
        f.write(test_content)
    
    try:
        # 初始化OSS PDF处理器，使用默认存储桶和区域
        processor = OSSPDFProcessor(bucket="fciai", region="cn-beijing")
        
        # 上传PDF并获取直链
        url = processor.upload_pdf_and_get_url("test.pdf")
        print(f"PDF直链URL: {url}")
        
    except Exception as e:
        print(f"操作失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 清理测试文件
        if os.path.exists("test.pdf"):
            os.remove("test.pdf")
            print("已清理测试文件")