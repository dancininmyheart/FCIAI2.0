#!/usr/bin/env python3
"""
生成阿里云OSS预签名URL的脚本
"""

import os
import sys
import argparse
from app.services.oss_service import generate_presigned_url, OSSServiceError
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


def main():
    parser = argparse.ArgumentParser(
        description="生成阿里云OSS预签名URL",
        epilog="""
使用示例:
1. 为已存在的文件生成临时下载链接:
   python generate_presigned_url.py test_file.txt
   
2. 生成有效期为2小时的链接:
   python generate_presigned_url.py test_file.txt --expires 7200
   
3. 指定bucket和region:
   python generate_presigned_url.py test_file.txt --bucket fci --region cn-beijing
   
4. 生成强制下载链接:
   python generate_presigned_url.py test_file.txt --download --bucket fci --region cn-beijing
   
5. 生成PUT方法的上传链接:
   python generate_presigned_url.py test_file.txt --method PUT
        """
    )
    
    parser.add_argument('object_key', help='OSS对象键名')
    parser.add_argument('--expires', type=int, default=3600, help='过期时间（秒），默认3600秒（1小时）')
    parser.add_argument('--method', choices=['GET', 'PUT', 'HEAD'], default='GET', help='HTTP方法，默认GET')
    parser.add_argument('--download', action='store_true', help='强制浏览器下载文件而不是预览')
    parser.add_argument('--bucket', help='存储桶名称（可选，默认从环境变量获取）')
    parser.add_argument('--region', help='区域（可选，默认从环境变量获取）')
    
    args = parser.parse_args()
    
    try:
        print(f"正在为对象生成预签名URL: {args.object_key}")
        print(f"HTTP方法: {args.method}")
        print(f"有效期: {args.expires} 秒")
        if args.download:
            print("强制下载模式: 是")
        if args.bucket:
            print(f"存储桶: {args.bucket}")
        if args.region:
            print(f"区域: {args.region}")
        
        # 生成预签名URL
        presigned_url = generate_presigned_url(
            object_key=args.object_key,
            expires_in=args.expires,
            method=args.method,
            force_download=args.download,
            bucket=args.bucket,
            region=args.region
        )
        
        print(f"\n预签名URL生成成功!")
        print(f"URL: {presigned_url}")
        
        return presigned_url
        
    except OSSServiceError as e:
        print(f"OSS服务错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"生成预签名URL时出错: {e}")
        import traceback
        print(f"详细错误信息: {traceback.format_exc()}")
        sys.exit(1)


# 直接使用示例
def example_usage():
    """直接使用函数的示例"""
    print("=== 预签名URL生成示例 ===")
    
    try:
        # 生成临时下载的预签名URL
        url = generate_presigned_url('test_file.txt', 3600, bucket='fciai', region='cn-beijing')  # 1小时有效期
        print(f"生成的预签名URL: {url}")
        
        # 生成强制下载的预签名URL
        url = generate_presigned_url('test_file.txt', 3600, force_download=True, bucket='fciai', region='cn-beijing')
        print(f"生成的强制下载URL: {url}")
        
        # 生成24小时有效期的预签名URL
        url = generate_presigned_url('test_file.txt', 86400, bucket='fciai', region='cn-beijing')  # 24小时有效期
        print(f"生成的24小时有效期URL: {url}")
        
        # 生成上传用的预签名URL（PUT请求）
        url = generate_presigned_url('new_upload.txt', 3600, 'PUT', bucket='fciai', region='cn-beijing')
        print(f"生成的上传URL: {url}")
        
    except Exception as e:
        print(f"示例执行失败: {e}")


if __name__ == "__main__":
    # 如果没有参数，则运行示例
    if len(sys.argv) == 1:
        example_usage()
    else:
        main()