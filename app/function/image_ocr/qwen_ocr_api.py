import requests
import json
import base64
import os
import subprocess
import sys
import platform
import re
import ast
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from PIL import Image

# 检查是否可以导入处理EMF的库
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("⚠️  警告: 缺少PIL库")

# 检查是否安装了必要的工具（根据操作系统类型）
def check_tools():
    """检查系统上必要的工具"""
    tools = ['convert', 'inkscape', 'libreoffice']
    available_tools = []
    
    for tool in tools:
        try:
            result = subprocess.run(['which', tool], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                available_tools.append(tool)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    
    return available_tools

class QwenOCRProcessor:
    def __init__(self, api_key):
        """
        初始化OCR处理器
        :param api_key: 你的通义千问API密钥
        """
        self.api_key = api_key
        self.model = "qwen-vl-ocr"  # 使用OCR专用模型
        self.api_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
        
        # 创建一个带有重试机制的会话
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def encode_image_to_base64(self, image_path):
        """
        将图片文件编码为base64字符串
        :param image_path: 图片文件路径
        :return: base64编码的字符串
        """
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    
    def ocr_image(self, image_path):
        """
        对指定图片进行OCR识别并返回结果
        
        Args:
            image_path (str): 图片文件路径
            
        Returns:
            dict: 包含识别文字的JSON结果
        """
        # 检查文件是否存在
        if not os.path.exists(image_path):
            return {
                "error": f"文件不存在: {image_path}"
            }
        
        try:
            # 将图片编码为base64
            image_base64 = self.encode_image_to_base64(image_path)
            
            # 构造请求头
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            # 构造请求参数
            payload = {
                "model": self.model,
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "image": f"data:image/jpeg;base64,{image_base64}"
                                },
                                {
                                    "text": "请识别图片中的所有文字内容，以纯文本格式输出。"
                                }
                            ]
                        }
                    ]
                },
                "parameters": {
                    "max_tokens": 2000,
                    "temperature": 0.1
                }
            }
            
            # 发送请求到通义千问API
            response = self.session.post(
                self.api_url, 
                headers=headers, 
                data=json.dumps(payload),
                timeout=60
            )
            
            # 处理API响应
            if response.status_code == 200:
                result = response.json()
                # 提取识别的文字内容
                text_content = result.get("output", {}).get("choices", [{}])[0].get("message", {}).get("content", "")
                
                # 清理文本内容，提取实际文本
                cleaned_text = self.clean_text_content(text_content)
                
                # 清理后的文本为空或为"0"，则不生成all_text字段
                if (not cleaned_text or 
                    (isinstance(cleaned_text, str) and (cleaned_text.strip() == "" or cleaned_text.strip() == "0"))):
                    return {
                        "image_path": image_path,
                        "all_text": {},
                        "status": "success"
                    }
                
                # 根据API返回的内容决定如何组织文本
                text_dict = self.organize_text_content(cleaned_text)
                
                return {
                    "image_path": image_path,
                    "all_text": text_dict,
                    "status": "success"
                }
            else:
                return {
                    "image_path": image_path,
                    "error": f"API请求失败: {response.status_code} - {response.text}",
                    "status": "failed"
                }
                
        except Exception as e:
            return {
                "image_path": image_path,
                "error": f"处理过程中发生错误: {str(e)}",
                "status": "failed"
            }
    
    def clean_text_content(self, text_content):
        """
        清理OCR识别的文本内容，提取实际文本
        :param text_content: 原始文本内容
        :return: 清理后的文本内容
        """
        # 如果是列表，先转换为字符串
        if isinstance(text_content, list):
            # 如果列表为空
            if not text_content:
                return ""
            # 如果列表只有一个元素且是字符串
            elif len(text_content) == 1 and isinstance(text_content[0], str):
                text_content = text_content[0]
            # 如果列表有多个元素，转换为字符串表示
            else:
                text_content = str(text_content)
        
        # 如果不是字符串，直接转换为字符串
        if not isinstance(text_content, str):
            return str(text_content)
            
        # 处理空列表情况
        if text_content.strip() == '[]':
            return ""
            
        # 尝试解析字符串形式的列表/字典
        try:
            # 尝试使用ast.literal_eval安全地解析字符串
            parsed_content = ast.literal_eval(text_content)
            # 如果解析成功且是列表
            if isinstance(parsed_content, list):
                if not parsed_content:
                    return ""
                elif len(parsed_content) == 1 and isinstance(parsed_content[0], dict):
                    # 处理 [{'text': '...'}] 格式
                    if 'text' in parsed_content[0]:
                        extracted_text = parsed_content[0]['text']
                        # 处理转义字符
                        if isinstance(extracted_text, str):
                            extracted_text = extracted_text.replace('\\n', '\n')
                        return extracted_text
                elif len(parsed_content) == 1:
                    # 处理 ['...'] 格式
                    return str(parsed_content[0]) if not isinstance(parsed_content[0], str) else parsed_content[0]
            # 如果解析成功且是字典
            elif isinstance(parsed_content, dict):
                if 'text' in parsed_content:
                    extracted_text = parsed_content['text']
                    # 处理转义字符
                    if isinstance(extracted_text, str):
                        extracted_text = extracted_text.replace('\\n', '\n')
                    return extracted_text
        except (ValueError, SyntaxError):
            # 如果解析失败，继续使用正则表达式处理
            pass
            
        # 处理嵌套格式：[{'text': "..."}] (字符串形式)
        nested_match = re.search(r"\[\s*{.*['\"]text['\"]\s*:\s*['\"]((?:[^'\\]|\\.)*)['\"].*}\s*\]", text_content)
        if nested_match:
            extracted_text = nested_match.group(1)
            # 处理转义字符
            extracted_text = extracted_text.replace('\\n', '\n').replace('\\', '')  # 移除多余的反斜杠
            return extracted_text
            
        # 处理嵌套格式：[{"text": "..."}] (字符串形式)
        nested_match_double = re.search(r'\[\s*{.*[\'\"]text[\'\"]\s*:\s*\"((?:[^\"\\]|\\.)*)\".*}\s*\]', text_content)
        if nested_match_double:
            extracted_text = nested_match_double.group(1)
            # 处理转义字符
            extracted_text = extracted_text.replace('\\n', '\n').replace('\\', '')  # 移除多余的反斜杠
            return extracted_text
            
        # 匹配 {'text': '...'} 或 {"text": "..."} 格式
        # 处理单引号格式
        match_single = re.search(r"{'text':\s*'((?:[^'\\]|\\.)*)'}", text_content)
        if match_single:
            # 处理转义字符
            extracted_text = match_single.group(1)
            # 将 \\n 转换为真正的换行符
            extracted_text = extracted_text.replace('\\n', '\n')
            return extracted_text
            
        # 处理双引号格式
        match_double = re.search(r'{"text":\s*"((?:[^"\\]|\\.)*)"}', text_content)
        if match_double:
            # 处理转义字符
            extracted_text = match_double.group(1)
            # 将 \\n 转换为真正的换行符
            extracted_text = extracted_text.replace('\\n', '\n')
            return extracted_text
            
        # 如果没有匹配到特定格式，返回原始内容（但去除首尾空白）
        return text_content.strip()
    
    def organize_text_content(self, text_content):
        """
        根据文本内容组织all_text字段
        :param text_content: 清理后的文本内容
        :return: 组织好的文本字典
        """
        text_dict = {}
        
        def is_valid_text(text):
            """检查文本是否有效（不为空且不为"0"）"""
            if not text:
                return False
            text_str = str(text).strip()
            return text_str != "" and text_str != "0"
        
        # 如果text_content是一个列表
        if isinstance(text_content, list):
            if not text_content:
                # 空列表
                return {}
            elif len(text_content) == 1:
                # 只有一个元素，如果有效则作为text1
                text = str(text_content[0]) if not isinstance(text_content[0], str) else text_content[0]
                if is_valid_text(text):
                    text_dict["text1"] = text
            else:
                # 多个元素，每个有效元素一个text字段
                text_counter = 1
                for item in text_content:
                    text = item if isinstance(item, str) else str(item)
                    if is_valid_text(text):
                        text_dict[f"text{text_counter}"] = text
                        text_counter += 1
        # 如果text_content是一个字符串
        elif isinstance(text_content, str):
            # 检查是否是JSON数组格式的内容
            if text_content.startswith('[') and text_content.endswith(']'):
                try:
                    # 尝试解析为JSON数组
                    text_list = json.loads(text_content)
                    text_counter = 1
                    # 为每个有效元素创建一个text字段
                    for item in text_list:
                        text = item if isinstance(item, str) else str(item)
                        if is_valid_text(text):
                            text_dict[f"text{text_counter}"] = text
                            text_counter += 1
                except:
                    # 如果解析失败且文本有效，将整个内容作为text1
                    if is_valid_text(text_content):
                        text_dict["text1"] = text_content
            else:
                # 如果文本有效，将其作为text1
                if is_valid_text(text_content):
                    text_dict["text1"] = text_content
        else:
            # 其他情况，如果转换为字符串后有效，将其作为text1
            text = str(text_content)
            if is_valid_text(text):
                text_dict["text1"] = text
            
        return text_dict

def convert_emf_to_png(emf_path):
    """
    将EMF文件转换为PNG格式（跨平台）
    :param emf_path: EMF文件路径
    :return: PNG文件路径或None（如果转换失败）
    """
    try:
        # 构造PNG文件路径
        png_path = emf_path.replace('.emf', '.png').replace('.EMF', '.png')
        
        # Linux/Mac系统转换方法
        return convert_emf_to_png_linux(emf_path, png_path)
            
    except Exception as e:
        print(f"⚠️  EMF转换PNG失败 ({emf_path}): {e}")
        return None

def convert_emf_to_png_linux(emf_path, png_path):
    """
    在Linux/Mac系统上将EMF文件转换为PNG格式
    :param emf_path: EMF文件路径
    :param png_path: PNG文件路径
    :return: PNG文件路径或None（如果转换失败）
    """
    try:
        # 方法1: 使用ImageMagick的convert工具
        try:
            result = subprocess.run([
                'convert', 
                emf_path, 
                '-density', '300', 
                '-trim', 
                '+repage', 
                png_path
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0 and os.path.exists(png_path):
                print(f"✅ 使用ImageMagick成功转换 {os.path.basename(emf_path)}")
                return png_path
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # 方法2: 使用Inkscape
        try:
            result = subprocess.run([
                'inkscape', 
                emf_path, 
                '--export-type=png', 
                '--export-filename=' + png_path,
                '--export-dpi=300'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0 and os.path.exists(png_path):
                print(f"✅ 使用Inkscape成功转换 {os.path.basename(emf_path)}")
                return png_path
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # 方法3: 使用LibreOffice
        try:
            # 先将EMF转换为PDF，再转换为PNG
            pdf_path = emf_path.replace('.emf', '.pdf').replace('.EMF', '.pdf')
            result1 = subprocess.run([
                'libreoffice', 
                '--headless', 
                '--convert-to', 'pdf', 
                emf_path,
                '--outdir', os.path.dirname(emf_path)
            ], capture_output=True, text=True, timeout=30)
            
            if result1.returncode == 0 and os.path.exists(pdf_path):
                result2 = subprocess.run([
                    'convert', 
                    pdf_path, 
                    '-density', '300', 
                    '-trim', 
                    '+repage', 
                    png_path
                ], capture_output=True, text=True, timeout=30)
                
                # 清理临时PDF文件
                if os.path.exists(pdf_path):
                    os.remove(pdf_path)
                
                if result2.returncode == 0 and os.path.exists(png_path):
                    print(f"✅ 使用LibreOffice成功转换 {os.path.basename(emf_path)}")
                    return png_path
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # 清理可能创建的临时文件
            pdf_path = emf_path.replace('.emf', '.pdf').replace('.EMF', '.pdf')
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
            pass
        
        # 方法4: 尝试使用PIL (如果安装了支持EMF的插件)
        if PIL_AVAILABLE:
            try:
                with Image.open(emf_path) as img:
                    img.save(png_path, 'PNG')
                print(f"✅ 使用PIL成功转换 {os.path.basename(emf_path)}")
                return png_path
            except Exception:
                pass
        
        print(f"❌ 所有方法都失败，无法转换EMF文件: {os.path.basename(emf_path)}")
        return None
        
    except Exception as e:
        print(f"⚠️  EMF转换PNG失败 ({emf_path}): {e}")
        return None

def process_folder_with_mapping(folder_path, json_path, api_key):
    """
    批量处理文件夹中的图片，并将OCR结果更新到JSON文件中
    
    Args:
        folder_path (str): 包含图片文件的文件夹路径
        json_path (str): JSON映射文件路径
        api_key (str): 通义千问API密钥
    """
    # 检查文件夹和JSON文件是否存在
    if not os.path.exists(folder_path):
        print(f"❌ 文件夹不存在: {folder_path}")
        return
    
    if not os.path.exists(json_path):
        print(f"❌ JSON文件不存在: {json_path}")
        return
    
    # 读取JSON映射文件
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            mapping_data = json.load(f)
        print(f"✅ 成功读取JSON映射文件")
    except Exception as e:
        print(f"❌ 读取JSON文件失败: {e}")
        return
    
    # 初始化OCR处理器
    processor = QwenOCRProcessor(api_key)
    
    # 检查系统上的可用工具
    available_tools = check_tools()
    
    if available_tools:
        print(f"✅ 检测到可用工具: {', '.join(available_tools)}")
    else:
        print("⚠️  未检测到可用的EMF转换工具，将跳过EMF文件处理")
        print("💡 建议安装以下工具之一:")
        print("   sudo apt-get install imagemagick inkscape libreoffice")
    
    # 收集所有需要处理的图片文件
    image_files = {}
    temp_files = []  # 记录临时创建的文件，以便后续删除
    
    for file_name in os.listdir(folder_path):
        file_path = os.path.join(folder_path, file_name)
        # 处理支持的图片格式
        if file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
            image_files[file_name] = file_path
        # 特殊处理EMF文件
        elif file_name.lower().endswith('.emf'):
            if not available_tools:
                print(f"❌ 无法处理EMF文件 (缺少工具): {file_name}，跳过处理")
                continue
                
            print(f"🔄 检测到EMF文件: {file_name}，正在尝试转换为PNG...")
            png_path = convert_emf_to_png(file_path)
            if png_path and os.path.exists(png_path):
                png_file_name = os.path.basename(png_path)
                image_files[png_file_name] = png_path
                temp_files.append(png_path)  # 记录临时文件
                print(f"✅ 已将 {file_name} 转换为 {png_file_name}")
            else:
                print(f"❌ 无法处理EMF文件: {file_name}，跳过处理")
    
    print(f"📁 找到 {len(image_files)} 个可处理的图片文件")
    
    # 处理每个图片文件
    ocr_results = {}
    for file_name, file_path in image_files.items():
        print(f"🔍 正在处理: {file_name}")
        result = processor.ocr_image(file_path)
        ocr_results[file_name] = result
        if result["status"] == "success":
            print(f"✅ {file_name} 处理成功")
        else:
            print(f"❌ {file_name} 处理失败: {result.get('error', 'Unknown error')}")
    
    # 将OCR结果更新到JSON映射数据中
    updated_count = 0
    for slide_key, slide_data in mapping_data.items():
        if 'images' in slide_data:
            for image_info in slide_data['images']:
                filename = image_info.get('filename')
                if filename and filename in ocr_results:
                    ocr_result = ocr_results[filename]
                    if ocr_result["status"] == "success":
                        # 只有当all_text不为空时才添加到image_info中
                        if ocr_result["all_text"] and any(ocr_result["all_text"].values()):
                            image_info['all_text'] = ocr_result["all_text"]
                            updated_count += 1
                            print(f"📝 已更新 {filename} 的OCR结果")
                        else:
                            # 如果没有识别到文本，确保移除可能已存在的all_text字段
                            if 'all_text' in image_info:
                                del image_info['all_text']
                            print(f"⚠️ {filename} 没有识别到文本，跳过更新")
                    else:
                        print(f"⚠️ {filename} OCR处理失败，跳过更新")
    
    # 将更新后的数据写回JSON文件
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(mapping_data, f, ensure_ascii=False, indent=2)
        print(f"✅ 成功更新JSON文件，共更新了 {updated_count} 个图片的OCR结果")
    except Exception as e:
        print(f"❌ 写入JSON文件失败: {e}")
        return
    
    # 删除临时创建的PNG文件
    for temp_file in temp_files:
        try:
            os.remove(temp_file)
            print(f"🗑️ 已删除临时文件: {os.path.basename(temp_file)}")
        except Exception as e:
            print(f"⚠️ 删除临时文件失败 {os.path.basename(temp_file)}: {e}")
    
    # 输出处理报告
    success_count = sum(1 for result in ocr_results.values() if result["status"] == "success")
    failed_count = len(ocr_results) - success_count
    print(f"\n📊 处理报告:")
    print(f"   成功处理: {success_count}")
    print(f"   处理失败: {failed_count}")
    print(f"   更新到JSON: {updated_count}")
    if temp_files:
        print(f"   临时文件: {len(temp_files)} 个已清理")

# 使用示例
if __name__ == "__main__":
    # 替换为你的实际API Key
    API_KEY = "sk-"
    
    # 设置文件夹路径和JSON文件路径
    folder_path = "/home/a937911378/AIGC/ppt_ocr_8vu7ritd"  # 替换为你的图片文件夹路径
    json_path = "/home/a937911378/AIGC/ppt_ocr_8vu7ritd/image_mapping.json"  # 替换为你的JSON文件路径
    
    # 执行批量处理
    process_folder_with_mapping(folder_path, json_path, API_KEY)
