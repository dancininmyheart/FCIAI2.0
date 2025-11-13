#!/usr/bin/env python3
"""
MinerU API接口实现
用于PDF文档的OCR识别和内容提取
"""

import os
import time
import requests
import logging
import zipfile
import platform
import subprocess
import mimetypes
from pathlib import Path
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from PIL import Image

# 修复logger_config_ocr导入问题
try:
    from .logger_config_ocr import setup_logger
    logger = setup_logger('MinerUAPI')
except (ImportError, ModuleNotFoundError):
    # 如果无法导入自定义日志配置，则使用默认日志配置
    logger = logging.getLogger('MinerUAPI')
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

try:
    import zlib
    compression = zipfile.ZIP_DEFLATED
except:
    compression = zipfile.ZIP_STORED

# 添加项目根目录到Python路径，确保可以导入logger_config_ocr
current_dir = Path(__file__).parent
project_root = current_dir.parent.parent
import sys
sys.path.insert(0, str(project_root))

# 尝试导入日志配置
try:
    from .logger_config_ocr import setup_logger
    logger = setup_logger("mineru_api")
except ImportError:
    # 如果无法导入自定义日志配置，则使用默认配置
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger(__name__)

class MinerUAPI:
    """MinerU API接口类"""
    
    def __init__(self):
        self.token = os.getenv('MINERU_API_KEY')
        if not self.token:
            raise ValueError("MINERU_API_KEY环境变量未设置")
        
        # 记录token信息用于调试（只显示部分）
        logger.info(f"MinerU API Token loaded, length: {len(self.token)}")
        logger.info(f"MinerU API Token prefix: {self.token[:50]}...")
        
        # 验证token格式
        if not self.token.startswith('eyJ'):
            logger.warning("Token格式可能不正确，应该以'eyJ'开头")
        
        self.session = requests.Session()
        # 根据官方文档设置请求头
        self.session.headers.update({
            'Authorization': f'Bearer {self.token}',
            'User-Agent': 'FCIAI2.0/1.0',
            'Content-Type': 'application/json'
        })
        
        # 配置代理和SSL设置
        self.session.proxies = {
            'http': None,
            'https': None
        }
        
        # 禁用SSL验证（仅用于测试）
        self.session.verify = False
        
        # 禁用SSL警告
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        logger.info("MinerU API客户端初始化完成")
    
    def process_pdf(self, file_path, enable_ocr=True):
        """处理本地PDF文件"""
        # 1. 上传文件
        logger.info(f"开始上传PDF文件: {file_path}")
        pdf_url = self.upload_file(file_path)
        if not pdf_url:
            logger.error("文件上传失败")
            return None
        
        logger.info(f"文件上传成功，URL: {pdf_url}")
        
        # 2. 创建MinerU任务
        logger.info("📄 创建解析任务...")
        task_url = 'https://mineru.net/api/v4/extract/task'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.token}'
        }
        data = {
            'url': pdf_url,
            'is_ocr': enable_ocr,
            'enable_formula': True,
            'enable_table': True,
            'language': 'auto'
        }
        
        try:
            logger.info("发送创建任务请求...")
            logger.info(f"请求头信息: Authorization: Bearer {self.token[:10]}***")
            logger.info(f"请求数据: {data}")
            logger.info(f"OCR功能状态: {'启用' if enable_ocr else '禁用'}")
            
            # 使用官方文档中的认证方式和请求格式
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.token}'
            }
            
            response = self.session.post(
                task_url,
                headers=headers,
                json=data,
                timeout=(30, 60)
            )
            
            logger.info(f"响应状态码: {response.status_code}")
            logger.info(f"响应头: {dict(response.headers)}")
            
            try:
                result = response.json()
                logger.info(f"响应内容: {result}")
            except Exception as e:
                logger.error(f"响应解析失败: {e}")
                logger.error(f"响应内容: {response.text}")
                return None

            # 检查API响应的格式和内容
            if not isinstance(result, dict):
                logger.error(f" API响应格式错误: {result}")
                return None

            if 'code' not in result:
                logger.error(f" API响应缺少'code'字段: {result}")
                # 检查是否是认证错误的特殊情况
                if 'msgCode' in result and result.get('msgCode') == 'A0202':
                    logger.error(" 用户认证失败，请检查MINERU_API_KEY是否正确配置")
                    logger.error("请确认以下几点:")
                    logger.error("1. MINERU_API_KEY在.env文件中是否正确设置")
                    logger.error("2. API密钥是否已过期")
                    logger.error("3. 是否在MinerU平台正确配置了API访问权限")
                    logger.error("4. 尝试访问 https://mineru.net/apiManage/docs 检查API密钥状态")
                return None

            if result['code'] != 0:
                error_msg = result.get('msg', '未知错误')
                msg_code = result.get('msgCode', '未知错误代码')
                trace_id = result.get('traceId', '未知traceId')
                logger.error(f" 创建任务失败: {error_msg}, 错误代码: {msg_code}, Trace ID: {trace_id}")
                return None

            if 'data' not in result:
                logger.error(f" API响应缺少'data'字段: {result}")
                return None

            if 'task_id' not in result['data']:
                logger.error(f" API响应缺少task_id字段: {result}")
                return None

            task_id = result['data']['task_id']
            logger.info(f"  任务ID: {task_id}")

            # 3. 等待处理完成
            logger.info(" 等待处理...")
            return self._wait_for_task_completion(task_id, headers)
        except Exception as e:
            logger.error(f" 创建任务时出错: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            return None
    
    def process_pdf_with_url(self, pdf_url, enable_ocr=True):
        """通过URL处理PDF文件"""
        # 1. 验证URL
        if not pdf_url:
            logger.error("PDF URL不能为空")
            return None
        
        logger.info(f"开始处理PDF URL: {pdf_url}")
        
        # 2. 创建MinerU任务
        logger.info(" 创建解析任务...")
        task_url = 'https://mineru.net/api/v4/extract/task'
        data = {
            'url': pdf_url,
            'is_ocr': enable_ocr,
            'enable_formula': True,
            'enable_table': True,
            'language': 'auto'
        }
        
        try:
            logger.info("发送创建任务请求...")
            logger.info(f"请求头信息: Authorization: Bearer {self.token[:10]}***")
            logger.info(f"请求数据: {data}")
            logger.info(f"OCR功能状态: {'启用' if enable_ocr else '禁用'}")
            
            # 使用官方文档中的认证方式和请求格式
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.token}'
            }
            
            response = self.session.post(
                task_url,
                headers=headers,
                json=data,
                timeout=(30, 60)
            )
            
            logger.info(f"响应状态码: {response.status_code}")
            logger.info(f"响应头: {dict(response.headers)}")
            
            try:
                result = response.json()
                logger.info(f"响应内容: {result}")
            except Exception as e:
                logger.error(f"响应解析失败: {e}")
                logger.error(f"响应内容: {response.text}")
                return None

            # 检查API响应的格式和内容
            if not isinstance(result, dict):
                logger.error(f" API响应格式错误: {result}")
                return None

            if 'code' not in result:
                logger.error(f" API响应缺少'code'字段: {result}")
                # 检查是否是认证错误的特殊情况
                if 'msgCode' in result and result.get('msgCode') == 'A0202':
                    logger.error(" 用户认证失败，请检查MINERU_API_KEY是否正确配置")
                    logger.error("请确认以下几点:")
                    logger.error("1. MINERU_API_KEY在.env文件中是否正确设置")
                    logger.error("2. API密钥是否已过期")
                    logger.error("3. 是否在MinerU平台正确配置了API访问权限")
                    logger.error("4. 尝试访问 https://mineru.net/apiManage/docs 检查API密钥状态")
                return None

            if result['code'] != 0:
                error_msg = result.get('msg', '未知错误')
                msg_code = result.get('msgCode', '未知错误代码')
                trace_id = result.get('traceId', '未知traceId')
                logger.error(f" 创建任务失败: {error_msg}, 错误代码: {msg_code}, Trace ID: {trace_id}")
                return None

            if 'data' not in result:
                logger.error(f" API响应缺少'data'字段: {result}")
                return None

            if 'task_id' not in result['data']:
                logger.error(f" API响应缺少task_id字段: {result}")
                return None

            task_id = result['data']['task_id']
            logger.info(f"  任务ID: {task_id}")

            # 3. 等待处理完成
            logger.info(" 等待处理...")
            return self._wait_for_task_completion(task_id, headers)
        except Exception as e:
            logger.error(f" 创建任务时出错: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            return None
    
    def _wait_for_task_completion(self, task_id, headers):
        """等待任务完成"""
        task_url = f'https://mineru.net/api/v4/extract/task/{task_id}'
        max_attempts = 60  # 最多尝试60次，每次间隔5秒，总共300秒(5分钟)
        attempt = 0
        
        while attempt < max_attempts:
            try:
                attempt += 1
                logger.info(f"检查任务状态 (尝试 {attempt}/{max_attempts})")
                status_response = self.session.get(
                    task_url, 
                    headers=headers,
                    timeout=(30, 60)
                )
                status_data = status_response.json()
                logger.info(f"任务状态响应: {status_data}")

                # 检查API响应的格式和内容
                if not isinstance(status_data, dict):
                    logger.error(f" 任务状态响应格式错误: {status_data}")
                    return None

                if 'data' not in status_data:
                    logger.error(f" 任务状态响应缺少'data'字段: {status_data}")
                    return None

                if not isinstance(status_data['data'], dict):
                    logger.error(f" 任务状态响应data字段格式错误: {status_data}")
                    return None

                if 'state' not in status_data['data']:
                    logger.error(f" 任务状态响应缺少'state'字段: {status_data}")
                    return None

                state = status_data['data']['state']
                logger.info(f"当前任务状态: {state}")
                
                if state == 'done':
                    if 'full_zip_url' not in status_data['data']:
                        logger.error("任务完成但缺少下载URL")
                        return None
                    zip_url = status_data['data']['full_zip_url']
                    logger.info(f"  处理完成！")
                    logger.info(f" 下载地址: {zip_url}")
                    return status_data
                    
                elif state == 'failed':
                    err_msg = status_data['data'].get('err_msg', '未知错误')
                    logger.error(f" 处理失败: {err_msg}")
                    return None
                    
                elif state == 'running':
                    progress = status_data['data'].get('extract_progress', {})
                    extracted = progress.get('extracted_pages', 0)
                    total = progress.get('total_pages', 0)
                    logger.info(f" 正在处理... {extracted}/{total} 页")
                    
                else:
                    logger.info(f" 状态: {state}")
                    
                # 等待5秒后再次检查
                time.sleep(5)
                
            except Exception as e:
                logger.error(f" 检查任务状态时出错: {e}")
                import traceback
                logger.error(f"错误详情: {traceback.format_exc()}")
                # 继续尝试而不是直接返回
                
        logger.error("任务等待超时")
        return None
    
    def upload_file(self, file_path):
        """上传本地文件到临时存储"""
        logger.info(f"正在上传文件: {os.path.basename(file_path)}")
        logger.info(f"文件大小: {os.path.getsize(file_path)} 字节")
        
        # 验证文件是否存在且可读
        if not os.path.exists(file_path):
            logger.error(f"文件不存在: {file_path}")
            return None
            
        if not os.path.isfile(file_path):
            logger.error(f"路径不是文件: {file_path}")
            return None
            
        # 检查文件是否为空
        if os.path.getsize(file_path) == 0:
            logger.error(f"文件为空: {file_path}")
            return None
        
        # 尝试多个上传服务，gofile作为首选
        upload_services = [
            {
                'name': 'gofile',
                'method': self._upload_to_gofile
            },
            {
                'name': 'tmpfiles.org',
                'url': 'https://tmpfiles.org/api/v1/upload',
                'method': self._upload_to_tmpfiles
            },
            {
                'name': 'file.io',
                'url': 'https://file.io',
                'method': self._upload_to_fileio
            }
        ]
        
        for service in upload_services:
            try:
                logger.info(f"尝试上传到 {service['name']}")
                result = service['method'](file_path)
                if result:
                    logger.info(f"  上传到 {service['name']} 成功: {result}")
                    return result
                else:
                    logger.warning(f"上传到 {service['name']} 失败")
            except Exception as e:
                logger.error(f" 上传到 {service['name']} 异常: {e}")
                continue
        
        logger.error("所有上传服务都失败了")
        return None
    
    def _upload_to_gofile(self, file_path):
        """上传到gofile"""
        try:
            # 1. 获取服务器列表
            logger.info("正在获取gofile服务器列表...")
            server_response = self.session.get("https://api.gofile.io/servers", timeout=30)
            if server_response.status_code != 200:
                logger.error(f" 获取服务器列表失败，状态码: {server_response.status_code}")
                return None
                
            server_data = server_response.json()
            if server_data.get("status") != "ok":
                logger.error(f" 服务器响应状态不正确: {server_data}")
                return None
                
            # 选择第一个服务器
            server = server_data["data"]["servers"][0]["name"]
            logger.info(f"使用服务器: {server}")
            
            # 2. 上传文件
            filename = os.path.basename(file_path)
            # 获取文件MIME类型
            mime_type, _ = mimetypes.guess_type(file_path)
            if mime_type is None:
                mime_type = 'application/octet-stream'
            
            with open(file_path, 'rb') as f:
                files = {'file': (filename, f, mime_type)}
                upload_response = self.session.post(
                    f'https://{server}.gofile.io/uploadFile',
                    files=files,
                    timeout=60
                )
                
            logger.info(f"上传响应状态: {upload_response.status_code}")
            
            if upload_response.status_code == 200:
                upload_data = upload_response.json()
                logger.info(f"上传响应: {upload_data}")
                if upload_data.get("status") == "ok":
                    # 根据API响应构造直链
                    file_id = upload_data["data"]["id"]
                    direct_url = f"https://store1.gofile.io/download/{file_id}/{filename}"
                    logger.info(f"  上传成功: {direct_url}")
                    return direct_url
                else:
                    logger.error(f" 上传失败: {upload_data}")
            else:
                logger.error(f" 上传请求失败，状态码: {upload_response.status_code}")
                
        except Exception as e:
            logger.error(f" 上传到gofile时出错: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
        
        return None
    
    def _upload_to_tmpfiles(self, file_path):
        """上传到tmpfiles.org"""
        with open(file_path, 'rb') as f:
            filename = os.path.basename(file_path)
            files = {'file': (filename, f, 'application/pdf')}
            
            response = self.session.post(
                'https://tmpfiles.org/api/v1/upload',
                files=files,
                timeout=(30, 60)
            )
            
            if response.status_code == 200:
                result = response.json()
                if 'data' in result and 'url' in result['data']:
                    url = result['data']['url']
                    direct_url = url.replace('tmpfiles.org/', 'tmpfiles.org/dl/')
                    return direct_url
            return None
    
    def _upload_to_fileio(self, file_path):
        """上传到file.io"""
        with open(file_path, 'rb') as f:
            files = {'file': f}
            
            response = self.session.post(
                'https://file.io',
                files=files,
                timeout=(30, 60)
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success') and 'link' in result:
                    return result['link']
            return None
    
    def download_result(self, zip_url, task_id):
        """下载结果文件"""
        save_path = f"mineru_result_{task_id}.zip"
        
        try:
            response = self.session.get(
                zip_url, 
                stream=True,
                timeout=(30, 300)
            )
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:  # 过滤掉keep-alive chunks
                        f.write(chunk)
            logger.info(f"  结果已保存到: {save_path}")
        except Exception as e:
            logger.error(f" 下载失败: {e}")
    
    def validate_token(self):
        """
        验证API密钥是否有效
        返回True表示有效，False表示无效
        """
        logger.info("开始验证MinerU API密钥有效性...")
        
        # 使用官方文档中的方式验证
        url = 'https://mineru.net/api/v4/extract/tasks'
        headers = {
            'Authorization': f'Bearer {self.token}',
            'User-Agent': 'FCIAI2.0/1.0'
        }
        
        try:
            response = self.session.get(url, headers=headers, timeout=30)
            logger.info(f"Token验证响应状态码: {response.status_code}")
            
            if response.status_code in [200, 201, 202, 204]:
                logger.info("API密钥验证成功")
                return True
            elif response.status_code == 401:
                logger.error("API密钥验证失败：认证错误")
                logger.error(f"响应内容: {response.text}")
                return False
            else:
                logger.warning(f"API密钥验证返回意外状态码: {response.status_code}")
                logger.warning(f"响应内容: {response.text}")
                # 对于其他状态码，我们不能确定密钥无效，所以返回True
                return True
        except Exception as e:
            logger.error(f"验证API密钥时出错: {e}")
            # 出错时我们不能确定密钥是否有效，所以返回True
            return True
    
    def test_auth(self):
        """测试认证"""
        logger.info("开始测试MinerU API认证...")
        url = 'https://mineru.net/api/v4/extract/tasks'
        
        # 使用官方文档中的认证方式
        headers = {
            'Authorization': f'Bearer {self.token}',
            'User-Agent': 'FCIAI2.0/1.0'
        }
        
        try:
            response = self.session.get(url, headers=headers, timeout=30)
            logger.info(f"认证测试响应状态码: {response.status_code}")
            if response.status_code in [200, 201, 202, 204]:
                logger.info("认证测试成功")
                return True
            else:
                logger.warning(f"认证测试失败: {response.status_code}")
                logger.warning(f"响应内容: {response.text}")
                return False
        except Exception as e:
            logger.error(f"认证测试异常: {e}")
            return False

# 导入日志系统
try:
    from .logger_config_ocr import get_logger
    # 获取日志记录器
    logger = get_logger("ocr_api")
except (ImportError, ModuleNotFoundError):
    # 如果无法导入自定义日志配置，则使用默认日志配置
    import logging
    logger = logging.getLogger("ocr_api")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

class OCRProcessor:
    def __init__(self, token, pdf_folder=None):
        self.token = token
        self.pdf_folder = pdf_folder
        self.session = self._create_session()
        self.headers = {
            'Authorization': f'Bearer {token}'
        }
    
    def _create_session(self):
        """创建带重试机制的会话"""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504, 521, 522, 524],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
    
    def convert_emf_to_png(self, emf_path, png_path):
        """
        将EMF文件转换为PNG格式
        支持Windows和Linux系统
        """
        system = platform.system().lower()
        
        if system == 'windows':
            # Windows平台使用原有方法
            try:
                # 使用PIL尝试打开EMF文件
                image = Image.open(emf_path)
                # 保存为PNG格式
                image.save(png_path, 'PNG')
                logger.info(f"  EMF文件已转换为PNG: {png_path}")
                return True
            except Exception as e:
                logger.error(f" EMF转换PNG失败: {e}")
                return False
        else:
            # Linux/Mac平台使用替代方案
            # 尝试使用Inkscape
            if self._convert_emf_to_png_inkscape(emf_path, png_path):
                return True
            # 尝试使用LibreOffice
            elif self._convert_emf_to_png_libreoffice(emf_path, png_path):
                return True
            else:
                logger.error(f" 在{system}系统上无法转换EMF文件: {emf_path}")
                return False
    
    def _convert_emf_to_png_inkscape(self, emf_path, png_path):
        """
        使用Inkscape转换EMF到PNG
        需要安装: sudo apt-get install inkscape
        """
        try:
            cmd = [
                'inkscape',
                emf_path,
                '--export-type=png',
                f'--export-filename={png_path}'
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            logger.info(f"  使用Inkscape将EMF文件转换为PNG: {png_path}")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning(f" 使用Inkscape转换EMF失败: {e}")
            return False
    
    def _convert_emf_to_png_libreoffice(self, emf_path, png_path):
        """
        使用LibreOffice转换EMF到PNG
        需要安装: sudo apt-get install libreoffice
        """
        try:
            # 使用libreoffice将EMF转换为PNG
            cmd = [
                'libreoffice',
                '--headless',
                '--convert-to', 'png',
                '--outdir', os.path.dirname(png_path),
                emf_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            # LibreOffice会自动命名输出文件，我们需要重命名为目标文件名
            base_name = os.path.splitext(os.path.basename(emf_path))[0]
            auto_generated_path = os.path.join(os.path.dirname(png_path), f"{base_name}.png")
            if os.path.exists(auto_generated_path):
                os.rename(auto_generated_path, png_path)
                logger.info(f"  使用LibreOffice将EMF文件转换为PNG: {png_path}")
                return True
            return False
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning(f" 使用LibreOffice转换EMF失败: {e}")
            return False
    
    def convert_emf_to_pdf(self, emf_path, pdf_path):
        """
        将EMF文件转换为PDF格式
        """
        try:
            # 先转换为PNG，再转换为PDF
            image = Image.open(emf_path)
            # 转换为RGB模式（如果需要）
            if image.mode in ('RGBA', 'LA', 'P'):
                # 创建白色背景
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                background.paste(image, mask=image.split()[-1] if image.mode in ('RGBA', 'LA') else None)
                image = background
            
            # 保存为PDF
            image.save(pdf_path, 'PDF', resolution=100.0)
            logger.info(f"  EMF文件已转换为PDF: {pdf_path}")
            return True
        except Exception as e:
            logger.error(f" EMF转换PDF失败: {e}")
            return False
    
    def upload_file(self, file_path):
        """上传本地文件到临时存储"""
        logger.info(f" 正在上传文件: {os.path.basename(file_path)}")
        
        # 使用 gofile 作为首选上传服务
        try:
            logger.info("尝试上传到gofile...")
            # 1. 获取服务器列表
            server_response = self.session.get("https://api.gofile.io/servers", timeout=30)
            if server_response.status_code != 200:
                logger.error(f" 获取服务器列表失败，状态码: {server_response.status_code}")
                return None
                
            server_data = server_response.json()
            if server_data.get("status") != "ok":
                logger.error(f" 服务器响应状态不正确: {server_data}")
                return None
                
            # 选择第一个服务器
            server = server_data["data"]["servers"][0]["name"]
            logger.info(f"使用服务器: {server}")
            
            # 2. 上传文件
            filename = os.path.basename(file_path)
            # 获取文件MIME类型
            mime_type, _ = mimetypes.guess_type(file_path)
            if mime_type is None:
                mime_type = 'application/octet-stream'
            
            with open(file_path, 'rb') as f:
                files = {'file': (filename, f, mime_type)}
                upload_response = self.session.post(
                    f'https://{server}.gofile.io/uploadFile',
                    files=files,
                    timeout=60
                )
                
            logger.info(f"上传响应状态: {upload_response.status_code}")
            
            if upload_response.status_code == 200:
                upload_data = upload_response.json()
                logger.info(f"上传响应: {upload_data}")
                if upload_data.get("status") == "ok":
                    # 根据API响应构造直链
                    file_id = upload_data["data"]["id"]
                    direct_url = f"https://store1.gofile.io/download/{file_id}/{filename}"
                    logger.info(f"  上传成功: {direct_url}")
                    return direct_url
                else:
                    logger.error(f" 上传失败: {upload_data}")
            else:
                logger.error(f" 上传请求失败，状态码: {upload_response.status_code}")
                
        except Exception as e:
            logger.error(f" 上传到gofile时出错: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
        
        return None
    
    def process_pdf(self, file_path):
        """处理本地PDF文件"""
        # 1. 上传文件
        pdf_url = self.upload_file(file_path)
        if not pdf_url:
            return None
        
        # 2. 创建MinerU任务
        logger.info(" 创建解析任务...")
        task_url = 'https://mineru.net/api/v4/extract/task'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.token}'
        }
        data = {
            'url': pdf_url,
            'is_ocr': True,
            'enable_formula': True,
            'enable_table': True,
            'language': 'auto'
        }
        
        try:
            response = self.session.post(
                task_url,
                headers=headers,
                json=data,
                timeout=(30, 60)
            )
            result = response.json()

            # 检查API响应的格式和内容
            if not isinstance(result, dict):
                logger.error(f" API响应格式错误: {result}")
                return None

            if 'code' not in result:
                logger.error(f" API响应缺少'code'字段: {result}")
                return None

            if result['code'] != 0:
                error_msg = result.get('msg', '未知错误')
                logger.error(f" 创建任务失败: {error_msg}")
                return None

            if 'data' not in result:
                logger.error(f" API响应缺少'data'字段: {result}")
                return None

            if 'task_id' not in result['data']:
                logger.error(f" API响应缺少task_id字段: {result}")
                return None

            task_id = result['data']['task_id']
            logger.info(f"  任务ID: {task_id}")

            # 3. 等待处理完成
            logger.info(" 等待处理...")
            return self._wait_for_task_completion(task_id, headers)
        except Exception as e:
            logger.error(f" 创建任务时出错: {e}")
            return None
    
    def _wait_for_task_completion(self, task_id, headers):
        """等待任务完成"""
        task_url = f'https://mineru.net/api/v4/extract/task/{task_id}'
        while True:
            try:
                time.sleep(5)
                status_response = self.session.get(
                    task_url, 
                    headers=headers,
                    timeout=(30, 60)
                )
                status_data = status_response.json()

                # 检查API响应的格式和内容
                if not isinstance(status_data, dict):
                    logger.error(f" 任务状态响应格式错误: {status_data}")
                    return None

                if 'data' not in status_data:
                    logger.error(f" 任务状态响应缺少'data'字段: {status_data}")
                    return None

                if not isinstance(status_data['data'], dict):
                    logger.error(f" 任务状态响应data字段格式错误: {status_data}")
                    return None

                if 'state' not in status_data['data']:
                    logger.error(f" 任务状态响应缺少'state'字段: {status_data}")
                    return None

                state = status_data['data']['state']

                if state == 'done':
                    if 'full_zip_url' not in status_data['data']:
                        logger.error(f" 任务完成但缺少下载URL: {status_data}")
                        return None

                    zip_url = status_data['data']['full_zip_url']
                    logger.info(f"  处理完成！")
                    logger.info(f" 下载地址: {zip_url}")

                    # 下载结果
                    self.download_result(zip_url, task_id)
                    return status_data

                elif state == 'failed':
                    err_msg = status_data['data'].get('err_msg', '未知错误')
                    logger.error(f" 处理失败: {err_msg}")
                    return None
                    
                elif state == 'running':
                    progress = status_data['data'].get('extract_progress', {})
                    extracted = progress.get('extracted_pages', 0)
                    total = progress.get('total_pages', 0)
                    logger.info(f" 正在处理... {extracted}/{total} 页")
                
                else:
                    logger.info(f" 状态: {state}")
            except Exception as e:
                logger.error(f" 检查任务状态时出错: {e}")
    
    def download_result(self, zip_url, task_id):
        """下载结果文件"""
        save_path = f"mineru_result_{task_id}.zip"
        
        try:
            response = self.session.get(
                zip_url, 
                stream=True,
                timeout=(30, 300)
            )
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:  # 过滤掉keep-alive chunks
                        f.write(chunk)
            logger.info(f"  结果已保存到: {save_path}")
            return save_path
        except Exception as e:
            logger.error(f" 下载失败: {e}")
            return None

    def batch_process_pdfs(self, file_paths, data_ids=None):
        """批量处理PDF文件"""
        # 检查文件是否存在
        valid_files = []
        valid_data_ids = []
        
        for i, file_path in enumerate(file_paths):
            if os.path.exists(file_path):
                valid_files.append(file_path)
                if data_ids and i < len(data_ids):
                    valid_data_ids.append(data_ids[i])
                else:
                    # 如果没有提供data_id，则使用文件名作为data_id
                    valid_data_ids.append(os.path.basename(file_path))
            else:
                logger.error(f" 文件不存在: {file_path}")
        
        if not valid_files:
            logger.error("没有有效的文件可以处理")
            return None
            
        # 准备文件信息
        files_info = []
        file_names = []
        for i, file_path in enumerate(valid_files):
            file_name = os.path.basename(file_path)
            file_names.append(file_name)
            files_info.append({
                "name": file_name,
                "is_ocr": True,
                "data_id": valid_data_ids[i]
            })
        
        # 发送批量处理请求
        logger.info(" 申请批量处理...")
        batch_url = 'https://mineru.net/api/v4/file-urls/batch'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.token}'
        }
        
        data = {
            "enable_formula": True,
            "language": "auto",
            "enable_table": True,
            "files": files_info
        }
        
        try:
            response = self.session.post(
                batch_url, 
                headers=headers, 
                json=data,
                timeout=(30, 60)
            )
            if response.status_code == 200:
                result = response.json()
                logger.info(f'  批量请求响应: {result}')

                # 检查API响应的格式和内容
                if not isinstance(result, dict):
                    logger.error(f" 批量请求响应格式错误: {result}")
                    return None

                if 'code' not in result:
                    logger.error(f" 批量请求响应缺少'code'字段: {result}")
                    return None

                if result["code"] == 0:
                    if 'data' not in result:
                        logger.error(f" 批量请求响应缺少'data'字段: {result}")
                        return None

                    if 'batch_id' not in result["data"]:
                        logger.error(f" 批量请求响应缺少batch_id字段: {result}")
                        return None

                    if 'file_urls' not in result["data"]:
                        logger.error(f" 批量请求响应缺少file_urls字段: {result}")
                        return None

                    batch_id = result["data"]["batch_id"]
                    urls = result["data"]["file_urls"]
                    logger.info(f' 批量ID: {batch_id}')
                    logger.info(f' 上传链接: {urls}')

                    # 上传文件到返回的URL
                    for i, url in enumerate(urls):
                        file_path = valid_files[i]
                        logger.info(f" 正在上传: {file_path}")
                        try:
                            with open(file_path, 'rb') as f:
                                res_upload = self.session.put(
                                    url, 
                                    data=f,
                                    timeout=(30, 300)
                                )
                                if res_upload.status_code == 200:
                                    logger.info(f"  {file_path} 上传成功")
                                else:
                                    logger.error(f" {file_path} 上传失败, 状态码: {res_upload.status_code}")
                        except Exception as upload_err:
                            logger.error(f" {file_path} 上传过程中出错: {upload_err}")
                        
                        # 在文件上传之间添加延迟，避免服务器压力过大
                        time.sleep(1)
                    
                    logger.info(f"  批量上传完成，批次ID: {batch_id}")
                    
                    # 等待处理完成并下载结果
                    self.wait_and_download_batch_results(batch_id)
                    return batch_id
                else:
                    logger.error(f' 申请上传URL失败: {result["msg"]}')
            else:
                logger.error(f' 请求失败，状态码: {response.status_code}')
                logger.error(f'响应内容: {response.text}')
        except Exception as err:
            logger.error(f" 批量处理出错: {err}")
            
        return None