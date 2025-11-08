#!/usr/bin/env python3
"""
上传文件到阿里云OSS并返回访问URL
"""

import os
import sys
import argparse
import datetime
import alibabacloud_oss_v2 as oss
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


def upload_file_and_get_url(file_path, object_key=None, bucket=None, region=None, generate_presigned=False, force_download=False, expires_in=3600):
    """
    上传文件到OSS并返回访问URL
    
    Args:
        file_path (str): 本地文件路径
        object_key (str): OSS对象键名，如果未提供则使用文件名
        bucket (str): 存储桶名称，如果未提供则从环境变量获取
        region (str): 区域，如果未提供则从环境变量获取
        generate_presigned (bool): 是否生成预签名URL
        force_download (bool): 是否强制下载
        expires_in (int): 预签名URL过期时间（秒）
    
    Returns:
        str: 文件的访问URL
    """
    # 获取配置信息
    access_key_id = os.environ.get('OSS_ACCESS_KEY_ID')
    access_key_secret = os.environ.get('OSS_ACCESS_KEY_SECRET')
    bucket = bucket or os.environ.get('OSS_BUCKET', 'fciai')
    region = region or os.environ.get('OSS_REGION', 'cn-beijing')
    
    # 检查必要配置
    if not access_key_id or not access_key_secret:
        raise ValueError("请在.env文件中设置OSS_ACCESS_KEY_ID和OSS_ACCESS_KEY_SECRET")
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")
    
    # 如果没有提供object_key，则使用文件名
    if not object_key:
        object_key = os.path.basename(file_path)
    
    try:
        # 创建凭证提供者
        credentials_provider = oss.credentials.StaticCredentialsProvider(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret
        )
        
        # 加载SDK的默认配置，并设置凭证提供者
        cfg = oss.config.load_default()
        cfg.credentials_provider = credentials_provider
        cfg.region = region
        
        # 创建OSS客户端
        client = oss.Client(cfg)
        
        print(f"开始上传文件: {file_path}")
        print(f"目标存储桶: {bucket}")
        print(f"目标对象名: {object_key}")
        print(f"区域: {region}")
        
        # 上传文件
        result = client.put_object_from_file(
            oss.PutObjectRequest(
                bucket=bucket,
                key=object_key
            ),
            file_path
        )
        
        # 生成URL
        if generate_presigned:
            # 使用SDK的presign功能生成预签名URL
            if force_download:
                # 强制下载，设置Content-Disposition头
                filename = os.path.basename(object_key)
                import urllib.parse
                encoded_filename = urllib.parse.quote(filename)
                req = oss.GetObjectRequest(
                    bucket=bucket,
                    key=object_key,
                    response_content_disposition=f"attachment; filename*=utf-8''{encoded_filename}"
                )
            else:
                req = oss.GetObjectRequest(
                    bucket=bucket,
                    key=object_key
                )
            
            # 转换过期秒数为timedelta
            expires = datetime.timedelta(seconds=expires_in)
            presigned = client.presign(req, expires=expires)
            url = presigned.url
            print(f"生成预签名URL，有效期: {expires_in} 秒")
            if force_download:
                print("强制下载模式: 是")
        else:
            # 生成公共访问URL
            url = f"https://{bucket}.{region}.aliyuncs.com/{object_key.lstrip('/')}"
        
        print("\n上传结果:")
        print(f'状态码: {result.status_code}')
        print(f'请求ID: {result.request_id}')
        print(f'ETag: {result.etag}')
        print(f'文件URL: {url}')
        
        return url
        
    except oss.exceptions.ServiceError as e:
        print(f"\nOSS服务错误:")
        print(f"错误代码: {e.error_code}")
        print(f"错误消息: {e.message}")
        print(f"请求ID: {e.request_id}")
        raise
    except Exception as e:
        print(f"上传过程中出现错误: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description="上传文件到阿里云OSS并返回访问URL",
        epilog="""
使用说明:
1. 确保已在.env文件中配置OSS_ACCESS_KEY_ID和OSS_ACCESS_KEY_SECRET
2. 确保指定的存储桶已在阿里云OSS控制台中创建
3. 确保AccessKey具有对存储桶的读写权限

使用示例:
1. 上传文件并返回公共URL:
   python upload_file_and_get_url.py test.txt
   
2. 上传文件到指定bucket和region:
   python upload_file_and_get_url.py test.txt --bucket fci --region cn-beijing
   
3. 上传文件并返回预签名URL:
   python upload_file_and_get_url.py test.txt --presigned --bucket fci --region cn-beijing
   
4. 上传文件并返回强制下载的预签名URL:
   python upload_file_and_get_url.py test.txt --presigned --download --bucket fci --region cn-beijing
   
5. 上传文件并返回有效期为2小时的预签名URL:
   python upload_file_and_get_url.py test.txt --presigned --expires 7200 --bucket fci --region cn-beijing
        """
    )
    
    parser.add_argument('file_path', help='要上传的本地文件路径')
    parser.add_argument('--key', help='OSS对象键名（可选，默认使用文件名）')
    parser.add_argument('--bucket', help='存储桶名称（可选，默认从环境变量获取）')
    parser.add_argument('--region', help='区域（可选，默认从环境变量获取）')
    parser.add_argument('--presigned', action='store_true', help='生成预签名URL')
    parser.add_argument('--download', action='store_true', help='强制浏览器下载文件而不是预览')
    parser.add_argument('--expires', type=int, default=3600, help='预签名URL过期时间（秒），默认3600秒')
    
    args = parser.parse_args()
    
    try:
        url = upload_file_and_get_url(
            file_path=args.file_path,
            object_key=args.key,
            bucket=args.bucket,
            region=args.region,
            generate_presigned=args.presigned,
            force_download=args.download,
            expires_in=args.expires
        )
        print(f"\n文件上传成功!")
        if args.presigned:
            mode = "强制下载URL" if args.download else "临时访问URL"
            print(f"{mode} (有效期{args.expires}秒): {url}")
        else:
            print(f"公共访问URL: {url}")
        return url
    except Exception as e:
        print(f"上传失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()