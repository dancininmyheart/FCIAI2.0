from typing import List, Dict
import json
import logging
import os

import requests

from app.function.local_qwen_async import get_field_async, logger, parse_formatted_text_async
from app.utils.translation_utils import clean_translation_text, build_map
from app.utils.lazy_http_client import http_client

# 配置日志记录器
logger = logging.getLogger(__name__)


def _configured_api_url() -> str:
    """Resolve the optional legacy DeepSeek proxy without a private default."""
    api_url = os.getenv('DEEPSEEK_TRANSLATION_API_URL', '').strip()
    if not api_url:
        raise RuntimeError(
            'DeepSeek translation proxy is disabled: set '
            'DEEPSEEK_TRANSLATION_API_URL to enable it'
        )
    return api_url

async def Translate_texts(field, text, stop_words, custom_translations, source_language, target_language):
    """
    调用DeepSeek翻译API进行文本翻译

    Args:
        field: 文本领域
        text: 待翻译文本
        stop_words: 停止词列表
        custom_translations: 自定义翻译字典
        source_language: 源语言代码
        target_language: 目标语言代码

    Returns:
        翻译结果
    """
    # DeepSeek API接口URL
    print("调用deepseek接口翻译")
    api_url = _configured_api_url()
    
    # 准备请求数据
    stop_words_str = ", ".join(f'"{word}"' for word in stop_words)
    custom_translations_str = ", ".join(f'"{k}": "{v}"' for k, v in custom_translations.items())

    # 构建请求体
    request_data = {
        "_streaming": False,
        "is_app_uid": False,
        "field": field,
        "text": text,
        "stop_words_str": stop_words_str,
        "custom_translations_str": custom_translations_str,
        "source_language": source_language,
        "target_language": target_language
    }
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Python-API-Client/1.0'
    }
    
    # 设置重试参数
    max_retries = 3
    retry_delay = 5  # 重试延迟时间（秒）
    
    # 重试循环
    for attempt in range(max_retries + 1):
        try:
            # 使用全局HTTP客户端发送POST请求
            response = requests.post(api_url, json=request_data, headers=headers, timeout=100)
            response.raise_for_status()

            result = response.json()

            # 处理响应
            logger.info(result)
            result = result["data"]["translated_json"]
            return str(result)
            
        except Exception as e:
            logger.error(f"DeepSeek翻译API调用失败 (尝试 {attempt + 1}/{max_retries + 1}): {str(e)}")
            if attempt < max_retries:
                # 等待一段时间后重试
                import time
                time.sleep(retry_delay)
            else:
                # 所有重试都失败了
                raise Exception(f"DeepSeek翻译API调用失败，已重试{max_retries}次: {str(e)}")
async def translate_deepseek_async(text: str, field: str = None, stop_words: List[str] = None,
                       custom_translations: Dict[str, str] = None,
                       source_language: str = "en", target_language: str = "zh"):
    """
    异步翻译功能主函数

    Args:
        text: 待翻译文本
        field: 文本领域，如果为None则自动检测
        stop_words: 停止词列表
        custom_translations: 自定义翻译字典
        source_language: 源语言代码
        target_language: 目标语言代码

    Returns:
        翻译映射字典（原文->译文）
    """
    try:
        # 设置默认值
        stop_words = stop_words or []
        custom_translations = custom_translations or {}

        # 如果没有领域信息，先获取领域
        if not field:
            field = await get_field_async(text)
            logger.info(f"检测到文本领域: {field}")

        # 翻译文本
        translation_result = await Translate_texts(
            field, text, stop_words, custom_translations, source_language, target_language
        )
        # 清理特殊字符
        text_clean = clean_translation_text(translation_result)

        # 解析结果
        parsed_result = await parse_formatted_text_async(text_clean)

        # 构建映射并返回
        return build_map(parsed_result)

    except Exception as e:
        logger.error(f"翻译过程中出错: {str(e)}")
        # 如果出错，返回一个只包含原文的映射
        lines = text.strip().split('\n')
        result = {line: f"[翻译错误: {str(e)}]" for line in lines if line.strip()}
        return result
