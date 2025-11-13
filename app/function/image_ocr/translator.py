import os
import json
import time
import requests
from typing import Dict, List, Optional, Union
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 导入日志系统
from logger_config_ocr import get_logger

# 获取日志记录器
logger = get_logger("translator")


class QwenTranslator:
    """通义千问翻译器"""
    
    def __init__(self, api_key: str = None, target_language: str = "英文"):
        """
        初始化翻译器
        
        Args:
            api_key: API密钥，如果为None则从环境变量获取
            target_language: 目标语言，默认为英文
        """
        self.api_key = api_key or os.getenv("QWEN_API_KEY")
        if not self.api_key:
            raise ValueError("未找到API密钥，请设置环境变量QWEN_API_KEY或传入api_key参数")
        
        self.target_language = target_language
        self.base_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        self.session = self._create_session()
        
        logger.info(f"  翻译器初始化完成，目标语言: {target_language}")
    
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
    
    def translate_text(self, text: str, source_language: str = "中文") -> Optional[str]:
        """
        翻译单个文本
        
        Args:
            text: 待翻译的文本
            source_language: 源语言，默认为中文
            
        Returns:
            翻译后的文本，失败返回None
        """
        if not text or not text.strip():
            return ""
        
        # 构建翻译提示词
        prompt = self._build_translation_prompt(text, source_language, self.target_language)
        
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            "model": "qwen3-235b-a22b-instruct-2507",  # 使用qwen-turbo模型，更快更便宜
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            },
            "parameters": {
                "max_tokens": 16000,  # Increased from 1000 to 16000 to handle longer texts
                "temperature": 0.1,  # 较低的温度确保翻译准确性
                "top_p": 0.8
            }
        }
        
        try:
            logger.info(f"🔄 正在翻译文本: {text[:50]}...")
            
            response = self.session.post(
                self.base_url,
                headers=headers,
                json=data,
                timeout=(30, 60)
            )
            
            if response.status_code == 200:
                result = response.json()
                
                if 'output' in result and 'text' in result['output']:
                    translated_text = result['output']['text'].strip()
                    logger.info(f"  翻译成功: {translated_text[:50]}...")
                    return translated_text
                else:
                    logger.error(f"❌ API响应格式错误: {result}")
                    return None
            else:
                logger.error(f"❌ API请求失败，状态码: {response.status_code}")
                logger.error(f"响应内容: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"❌ 翻译请求异常: {str(e)}")
            return None
    
    def _build_translation_prompt(self, text: str, source_lang: str, target_lang: str) -> str:
        """构建翻译提示词"""
        prompt = f"""请将以下{source_lang}文本翻译成{target_lang}，要求：
1. 保持原文的意思和语气
2. 翻译要自然流畅
3. 如果是专业术语，请保持准确性
4. 只返回翻译结果，不要包含其他解释

原文：
{text}

翻译："""
        return prompt
    
    def translate_batch_texts(self, texts: List[str], source_language: str = "中文") -> List[Optional[str]]:
        """
        批量翻译文本
        
        Args:
            texts: 待翻译的文本列表
            source_language: 源语言
            
        Returns:
            翻译结果列表，与输入列表一一对应
        """
        results = []
        total = len(texts)
        
        logger.info(f" 开始批量翻译，共 {total} 条文本")
        
        for i, text in enumerate(texts, 1):
            logger.info(f" 翻译进度: {i}/{total}")
            
            translated = self.translate_text(text, source_language)
            results.append(translated)
            
            # 避免API频率限制
            if i < total:
                time.sleep(0.5)
        
        success_count = sum(1 for r in results if r is not None)
        logger.info(f" 批量翻译完成，成功: {success_count}/{total}")
        
        return results
    
    def translate_image_mapping(self, mapping_file_path: str, source_language: str = "中文") -> bool:
        """
        翻译image_mapping.json文件中的所有文本
        
        Args:
            mapping_file_path: image_mapping.json文件路径
            source_language: 源语言
            
        Returns:
            是否翻译成功
        """
        try:
            # 读取映射文件
            with open(mapping_file_path, 'r', encoding='utf-8') as f:
                mapping_data = json.load(f)
            
            logger.info(f" 开始翻译映射文件: {mapping_file_path}")
            
            total_texts = 0
            translated_count = 0
            
            # 遍历所有幻灯片
            for slide_key, slide_data in mapping_data.items():
                if 'images' not in slide_data:
                    continue
                
                # 遍历该页的所有图片
                for image_info in slide_data['images']:
                    if 'all_text' not in image_info or not image_info['all_text']:
                        continue
                    
                    # 翻译该图片的所有文本
                    translated_texts = {}
                    
                    for text_key, text_value in image_info['all_text'].items():
                        if text_value and text_value.strip():
                            total_texts += 1
                            
                            translated = self.translate_text(text_value, source_language)
                            if translated:
                                translated_texts[text_key] = translated
                                translated_count += 1
                            else:
                                # 翻译失败时保留原文
                                translated_texts[text_key] = text_value
                                logger.warning(f" 翻译失败，保留原文: {text_value[:30]}...")
                    
                    # 将翻译结果添加到映射数据中
                    if translated_texts:
                        image_info['translated_text'] = translated_texts
            
            # 保存更新后的映射文件
            with open(mapping_file_path, 'w', encoding='utf-8') as f:
                json.dump(mapping_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f" 翻译完成并保存到: {mapping_file_path}")
            logger.info(f" 翻译统计: {translated_count}/{total_texts} 条文本翻译成功")
            
            return True
            
        except Exception as e:
            logger.error(f" 翻译映射文件时出错: {str(e)}")
            return False
    
    def set_target_language(self, language: str):
        """设置目标语言"""
        self.target_language = language
        logger.info(f" 目标语言已更改为: {language}")


class TranslationManager:
    """翻译管理器"""
    
    @staticmethod
    def translate_ocr_results(temp_dir: str, target_language: str = "英文", source_language: str = "中文") -> bool:
        """
        翻译OCR识别结果
        
        Args:
            temp_dir: 临时目录路径
            target_language: 目标语言
            source_language: 源语言
            
        Returns:
            是否翻译成功
        """
        mapping_file = os.path.join(temp_dir, "image_mapping.json")
        
        if not os.path.exists(mapping_file):
            logger.error(f" 映射文件不存在: {mapping_file}")
            return False
        
        try:
            # 初始化翻译器
            translator = QwenTranslator(target_language=target_language)
            
            # 执行翻译
            success = translator.translate_image_mapping(mapping_file, source_language)
            
            if success:
                logger.info(" OCR结果翻译完成！")
            else:
                logger.error(" OCR结果翻译失败！")
            
            return success
            
        except Exception as e:
            logger.error(f" 翻译管理器执行失败: {str(e)}")
            return False
    
    @staticmethod
    def get_translation_summary(mapping_file_path: str) -> Dict:
        """
        获取翻译结果摘要
        
        Args:
            mapping_file_path: 映射文件路径
            
        Returns:
            翻译摘要信息
        """
        try:
            with open(mapping_file_path, 'r', encoding='utf-8') as f:
                mapping_data = json.load(f)
            
            total_images = 0
            images_with_text = 0
            images_with_translation = 0
            total_text_count = 0
            total_translation_count = 0
            
            for slide_data in mapping_data.values():
                if 'images' not in slide_data:
                    continue
                
                for image_info in slide_data['images']:
                    total_images += 1
                    
                    if 'all_text' in image_info and image_info['all_text']:
                        images_with_text += 1
                        total_text_count += len(image_info['all_text'])
                    
                    if 'translated_text' in image_info and image_info['translated_text']:
                        images_with_translation += 1
                        total_translation_count += len(image_info['translated_text'])
            
            return {
                'total_images': total_images,
                'images_with_text': images_with_text,
                'images_with_translation': images_with_translation,
                'total_text_count': total_text_count,
                'total_translation_count': total_translation_count,
                'translation_success_rate': total_translation_count / max(total_text_count, 1) * 100
            }
            
        except Exception as e:
            logger.error(f" 获取翻译摘要时出错: {str(e)}")
            return {}


# 使用示例
if __name__ == "__main__":
    # 测试翻译功能
    translator = QwenTranslator(target_language="英文")
    
    # 测试单个文本翻译
    test_text = "这是一个测试文本，用于验证翻译功能是否正常工作。"
    result = translator.translate_text(test_text)
    print(f"原文: {test_text}")
    print(f"译文: {result}")
    
    # 测试批量翻译
    test_texts = [
        "你好，世界！",
        "人工智能正在改变我们的生活。",
        "这个图片包含重要的技术信息。"
    ]
    results = translator.translate_batch_texts(test_texts)
    for i, (original, translated) in enumerate(zip(test_texts, results)):
        print(f"{i+1}. 原文: {original}")
        print(f"   译文: {translated}")
        print()
