#!/usr/bin/env python3
"""
一键上传并拿到可直接下载的 URL
用法：
python upload_and_link.py local_file.txt  [--bucket fci] [--region cn-beijing] [--expire 3600]
"""
import argparse
import datetime
import pathlib
import sys
import os
from dotenv import load_dotenv
import alibabacloud_oss_v2 as oss

# 加载环境变量
load_dotenv()


def upload_and_link(local_path: str, bucket: str, region: str, expire_seconds: int):
    # 检查文件是否存在
    if not os.path.exists(local_path):
        raise FileNotFoundError(f"文件不存在: {local_path}")
    
    # 获取访问凭证
    access_key_id = os.environ.get('OSS_ACCESS_KEY_ID')
    access_key_secret = os.environ.get('OSS_ACCESS_KEY_SECRET')
    
    if not access_key_id or not access_key_secret:
        raise ValueError("请在.env文件中设置OSS_ACCESS_KEY_ID和OSS_ACCESS_KEY_SECRET")
    
    # 配置OSS客户端
    cfg = oss.config.load_default()
    cfg.region = region
    cfg.credentials_provider = oss.credentials.StaticCredentialsProvider(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret
    )
    client = oss.Client(cfg)

    key = pathlib.Path(local_path).name           # 对象名=本地文件名
    # 1. 上传（私有 ACL）
    print(f"正在上传 {local_path} → oss://{bucket}/{key}")
    with open(local_path, "rb") as f:
        client.put_object(oss.PutObjectRequest(bucket=bucket, key=key, body=f))

    # 2. 生成预签名 URL（强制下载，保留原名）
    filename = pathlib.Path(key).name
    # 对文件名进行URL编码以支持中文
    import urllib.parse
    encoded_filename = urllib.parse.quote(filename)
    req = oss.GetObjectRequest(
        bucket=bucket,
        key=key,
        response_content_disposition=f"attachment; filename*=utf-8''{encoded_filename}"
    )
    url = client.presign(req, expires=datetime.timedelta(seconds=expire_seconds))
    print("上传完成！直链（有效期 {} s）：".format(expire_seconds))
    print(url.url)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="一键上传文件到阿里云OSS并生成可直接下载的链接",
        epilog="""
使用示例:
1. 上传文件并生成默认配置的下载链接:
   python upload_and_link.py test_file.txt
   
2. 指定bucket、region和过期时间:
   python upload_and_link.py test_file.txt --bucket fci --region cn-beijing --expire 7200
        """
    )
    parser.add_argument("file", help="本地文件路径")
    parser.add_argument("--bucket", default="fciai", help="目标 bucket")
    parser.add_argument("--region", default="cn-beijing", help="地域")
    parser.add_argument("--expire", type=int, default=3600, help="链接有效期（秒）")
    args = parser.parse_args()

    try:
        upload_and_link(args.file, args.bucket, args.region, args.expire)
    except Exception as e:
        print(f"操作失败: {e}")
        sys.exit(1)