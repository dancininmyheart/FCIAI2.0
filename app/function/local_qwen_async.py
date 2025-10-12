"""
异步Qwen API接口
支持并发处理和高效的API调用
"""
import json
import random
import logging
import re
import os
import asyncio
from typing import Dict, Any, List, Optional, Union, Callable
import time
import socket
import httpx
from urllib.parse import urlparse

from dotenv import load_dotenv
from openai import OpenAI
from functools import lru_cache

# 导入工具函数
from ..utils.translation_utils import (
    build_map,
    clean_translation_text
)

# from ..utils.async_http_client import AsyncHttpClient
try:
    from ..utils.network_diagnostics import diagnose_network_issue, quick_connectivity_check
except ImportError:
    # 如果导入失败，创建简单的替代函数
    async def diagnose_network_issue(api_url: str) -> str:
        return f"网络诊断工具不可用，无法诊断 {api_url}"

    def quick_connectivity_check(host: str, port: int = 443) -> bool:
        return True

load_dotenv()
# 配置日志记录器
logger = logging.getLogger(__name__)

# 模型配置
MODEL_NAME = "qwen3-235b-a22b-instruct-2507"
API_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
API_KEY = os.environ.get("QWEN_API_KEY")

# 备用API配置
BACKUP_API_URLS = [
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
    # 可以添加其他备用端点
]

# 连接配置
CONNECTION_TIMEOUT = 30  # 连接超时时间（秒）
READ_TIMEOUT = 60       # 读取超时时间（秒）
MAX_RETRIES = 3         # 最大重试次数
RETRY_DELAY = 2         # 重试延迟（秒）

def check_network_connectivity(url: str, timeout: int = 10) -> bool:
    """
    检查网络连接性

    Args:
        url: 要检查的URL
        timeout: 超时时间

    Returns:
        是否可以连接
    """
    try:
        parsed_url = urlparse(url)
        host = parsed_url.hostname
        port = parsed_url.port or (443 if parsed_url.scheme == 'https' else 80)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()

        return result == 0
    except Exception as e:
        logger.warning(f"网络连接检查失败: {str(e)}")
        return False

# 创建OpenAI客户端实例
@lru_cache(maxsize=1)
def get_openai_client():
    """
    获取OpenAI客户端实例（使用缓存以避免重复创建）

    Returns:
        OpenAI客户端实例
    """
    # 检查API密钥
    if not API_KEY or API_KEY == "sk-placeholder":
        logger.error("DASHSCOPE_API_KEY 未设置或无效")
        raise ValueError("API密钥未配置")

    # 检查网络连接
    if not check_network_connectivity(API_BASE_URL):
        logger.warning(f"无法连接到主API端点: {API_BASE_URL}")
        # 尝试备用端点
        for backup_url in BACKUP_API_URLS[1:]:  # 跳过第一个（主端点）
            if check_network_connectivity(backup_url):
                logger.info(f"使用备用API端点: {backup_url}")
                api_url = backup_url
                break
        else:
            logger.error("所有API端点都无法连接")
            # 仍然创建客户端，但会在实际调用时失败
            api_url = API_BASE_URL
    else:
        api_url = API_BASE_URL

    return OpenAI(
        api_key=API_KEY,
        base_url=api_url,
        timeout=httpx.Timeout(
            connect=CONNECTION_TIMEOUT,
            read=READ_TIMEOUT,
            write=CONNECTION_TIMEOUT,
            pool=CONNECTION_TIMEOUT
        ),
        max_retries=MAX_RETRIES,
    )

async def retry_with_backoff(func, max_retries: int = MAX_RETRIES, delay: float = RETRY_DELAY):
    """
    带退避的重试机制

    Args:
        func: 要重试的函数
        max_retries: 最大重试次数
        delay: 初始延迟时间

    Returns:
        函数执行结果
    """
    last_exception = None
    network_diagnosed = False

    for attempt in range(max_retries + 1):
        try:
            return await func() if asyncio.iscoroutinefunction(func) else func()
        except Exception as e:
            last_exception = e

            # 检查是否是网络连接错误
            is_network_error = any(error_type in str(e) for error_type in [
                "getaddrinfo failed", "Connection error", "ConnectError",
                "timeout", "TimeoutError", "ConnectionError"
            ])

            if is_network_error:
                logger.warning(f"网络连接失败 (尝试 {attempt + 1}/{max_retries + 1}): {str(e)}")

                # 在第一次网络错误时进行诊断
                if not network_diagnosed:
                    network_diagnosed = True
                    try:
                        logger.info("正在进行网络诊断...")
                        diagnosis_report = await diagnose_network_issue(API_BASE_URL)
                        logger.info(f"网络诊断结果:\n{diagnosis_report}")
                    except Exception as diag_e:
                        logger.warning(f"网络诊断失败: {str(diag_e)}")
            else:
                logger.warning(f"API调用失败 (尝试 {attempt + 1}/{max_retries + 1}): {str(e)}")

            if attempt < max_retries:
                wait_time = delay * (2 ** attempt)  # 指数退避
                logger.info(f"等待 {wait_time:.1f} 秒后重试...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"重试次数已达上限，最后一次错误: {str(last_exception)}")
                break

    # 如果所有重试都失败，抛出最后一个异常
    raise last_exception

# 创建为字段分析的异步函数
async def get_field_async(text: str) -> str:
    """
    异步获取PPT可能属于的领域

    Args:
        text: PPT文本内容

    Returns:
        领域分析结果
    """
    # 在异步函数中使用同步客户端，使用线程池执行
    loop = asyncio.get_event_loop()

    def _get_field():
        try:
            client = get_openai_client()
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": """你是一个专业的文档分析专家。请根据给定的文本内容，判断这个PPT可能属于哪个专业领域。

请从以下领域中选择最合适的一个：
- 医学
- 工程技术
- 商业管理
- 教育培训
- 科学研究
- 法律
- 金融
- 艺术设计
- 信息技术
- 其他

请只返回领域名称，不要添加任何解释。"""},
                    {"role": "user", "content": f"请分析以下文本内容属于哪个领域：\n\n{text[:1000]}"}  # 限制文本长度
                ],
                temperature=0.1,
                max_tokens=100  # Increased from 50 to 100 to allow for slightly longer responses
            )
            result = response.choices[0].message.content.strip()
            logger.info(f"成功获取领域信息: {result}")
            return result
        except Exception as e:
            logger.error(f"获取领域信息失败: {str(e)}")
            raise

    try:
        # 使用重试机制执行API调用
        async def _async_get_field():
            return await loop.run_in_executor(None, _get_field)

        result = await retry_with_backoff(_async_get_field)
        return result
    except Exception as e:
        # 如果所有重试都失败，返回默认值
        logger.error(f"无法获取领域信息，使用默认值: {str(e)}")
        return "其他"  # 返回默认领域

# 创建翻译文本的异步函数
async def translate_by_fields_async(field, text, stop_words, custom_translations, source_language, target_language, vocabulary_prompt=None):
    """
    异步调用Qwen API翻译文本
    
    Args:
        field: 文本领域
        text: 待翻译文本
        stop_words: 停止词列表
        custom_translations: 自定义翻译字典
        source_language: 源语言
        target_language: 目标语言
        vocabulary_prompt: 词汇表提示词

    Returns:
        翻译结果
    """
    # 将stop_words和custom_translations转换为字符串
    stop_words_str = ", ".join(f'"{word}"' for word in stop_words) if stop_words else ""
    custom_translations_str = ", ".join(f'"{k}": "{v}"' for k, v in custom_translations.items()) if custom_translations else ""

    # 如果没有提供vocabulary_prompt，则从custom_translations构建
    if not vocabulary_prompt and custom_translations:
        vocabulary_prompt = "专业词汇表（请在翻译中优先使用以下术语的对应翻译）:\n" + "\n".join(f'"{k}": "{v}"' for k, v in custom_translations.items())

    # 在异步函数中使用同步客户端，使用线程池执行
    loop = asyncio.get_event_loop()

    def _translate():
        try:
            client = get_openai_client()
            
            # 构建系统提示词
            system_content = f"""您是翻译{field}领域文本的专家。接下来，您将获得一系列{source_language}文本（包括短语、句子和单词）。
请将每一段文本翻译成专业的{target_language}。

### **格式要求**：
1. 请严格按照如下JSON格式输出，不要添加任何额外解释或文本：
      [
          {{
              "source_language": "原语言文本",
              "target_language": "译文"
          }},
          {{
              "source_language": "原语言文本",
              "target_language": "译文"
          }}
      ]
      
2. **自定义翻译**：
   如果遇到以下词汇，在保持语义通顺的前提下使用提供的翻译做参考：
       {custom_translations_str}

3. **数字处理**：
    - 如果输入是 **单独的数字**，请保持原样，如：
      {{
          "source_language": "1",
          "target_language": "1"
      }}

4. **翻译风格**：
    - 请保持翻译的专业性，并符合 {field} 领域的语言习惯。
    """
            
            # 如果有词汇表提示词，则添加到系统提示中
            if vocabulary_prompt:
                system_content += f"\n2. 自定义翻译：\n如果遇到以下词汇，在保持语义通顺的前提下使用提供的翻译做参考：\n{vocabulary_prompt}\n\n"
                
            system_content += "现在，请按照上述规则翻译文本"

            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": text}
                ],
                temperature=0.7,
                max_tokens=16000,  # Increased from 8000 to 16000 to handle longer paragraphs
                timeout=600
            )
            result = response.choices[0].message.content
            logger.info(f"翻译成功，返回结果长度: {len(result)}")
            return result
        except Exception as e:
            logger.error(f"翻译文本失败: {str(e)}")
            raise

    try:
        # 使用重试机制执行API调用
        async def _async_translate():
            return await loop.run_in_executor(None, _translate)

        result = await retry_with_backoff(_async_translate)
        return result
    except Exception as e:
        logger.error(f"翻译失败: {str(e)}")
        raise

# 解析格式化文本的函数
async def parse_formatted_text_async(text: str):
    """
    异步解析格式化文本（JSON）

    Args:
        text: 格式化文本

    Returns:
        解析结果
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"初次解析 JSON 失败，尝试修复格式: {e}")
        fixed_text = await re_parse_formatted_text_async(text)
        return json.loads(fixed_text)

def re_parse_formatted_text_async(text: str):
    """
    同步重新解析格式化文本，修复可能的格式错误
    Args:
        text: 格式可能错误的文本
    Returns:
        修复后的文本
    """
    # 在异步函数中使用同步客户端，使用线程池执行
    loop = asyncio.get_event_loop()

    def _re_parse():
        try:
            client = get_openai_client()
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": """
                     你是一个 JSON 解析和修复专家。你的任务是修复一段 **可能存在格式错误的 JSON**，并输出一个 **严格符合 JSON 标准** 的 **格式正确的 JSON**。

### **规则要求：**
1. **确保 JSON 格式正确**：修复任何可能的语法错误，如缺少引号、逗号、括号不匹配等。
2. **保持原始结构和数据**：除非必要，尽量不修改原始数据内容，仅修复格式问题。
3. **正确处理数据类型**：
   - **字符串** 应该使用 **双引号 `"`** 包裹，而不是单引号 `'`。
   - **数字** 应保持原始数值，不要转换为字符串。
   - **布尔值**（`true` / `false`）和 **null** 必须符合 JSON 规范，不要误修改。
4. **不输出额外文本**：
   - **仅输出修复后的 JSON**，不要添加解释、注释或额外的说明文本。
   """},
                    {"role": "user", "content": text}
                ],
                temperature=0.3,
                max_tokens=16000  # Increased from 8000 to 16000 to handle larger JSON responses
            )
            result = response.choices[0].message.content
            logger.info(f"JSON修复成功")
            return result
        except Exception as e:
            logger.error(f"修复JSON格式失败: {str(e)}")
            raise

    try:
        # 直接在同步函数中执行API调用
        result = _re_parse()
        return result
    except Exception as e:
        logger.error(f"JSON修复失败: {str(e)}")
        raise

# build_map函数已移动到 utils/translation_utils.py

# 主要翻译函数
async def translate_async(text: str, field: str = None, stop_words: List[str] = None,
                       custom_translations: Dict[str, str] = None,
                       source_language: str = "en", target_language: str = "zh",
                       clean_markdown: bool = True, vocabulary_prompt: str = None):
    """
    异步翻译功能主函数

    Args:
        text: 待翻译文本
        field: 文本领域，如果为None则自动检测
        stop_words: 停止词列表
        custom_translations: 自定义翻译字典
        source_language: 源语言代码
        target_language: 目标语言代码
        clean_markdown: 是否清理Markdown符号（PDF翻译需要，PPT翻译不需要）
        vocabulary_prompt: 词汇表提示词

    Returns:
        翻译映射字典（原文->译文）
    """
    try:
        # 设置默认值
        stop_words = stop_words or []
        custom_translations = custom_translations or {}

        # 根据参数决定是否清理Markdown符号
        if clean_markdown:
            # 清理待翻译文本，确保发送到翻译API的文本不包含Markdown符号
            from app.function.pdf_translation_utils import PDFTranslationUtils
            cleaned_text = PDFTranslationUtils._strip_inline_markdown(text)
            logger.debug(f"原文本: {text[:100]}...")
            logger.debug(f"清理后文本: {cleaned_text[:100]}...")
        else:
            cleaned_text = text

        # 如果没有领域信息，先获取领域
        if not field:
            field = await get_field_async(cleaned_text)
            logger.info(f"检测到文本领域: {field}")

        # 翻译文本
        translation_result = await translate_by_fields_async(
            field, cleaned_text, stop_words, custom_translations, source_language, target_language, vocabulary_prompt
        )
        logger.info(f"翻译API返回结果类型: {type(translation_result)}")
        logger.info(f"翻译API返回结果长度: {len(translation_result) if hasattr(translation_result, '__len__') else 'N/A'}")
        if isinstance(translation_result, str):
            logger.info(f"翻译API返回结果前200字符: {translation_result[:200]}")

        # 清理特殊字符
        text_clean = clean_translation_text(translation_result)
        logger.info(f"清理后文本类型: {type(text_clean)}")
        logger.info(f"清理后文本长度: {len(text_clean) if hasattr(text_clean, '__len__') else 'N/A'}")
        if isinstance(text_clean, str):
            logger.info(f"清理后文本前200字符: {text_clean[:200]}")

        # 解析结果
        parsed_result = await parse_formatted_text_async(text_clean)
        logger.info(f"解析后结果类型: {type(parsed_result)}")
        logger.info(f"解析后结果长度: {len(parsed_result) if hasattr(parsed_result, '__len__') else 'N/A'}")
        if isinstance(parsed_result, (list, dict)) and len(parsed_result) > 0:
            if isinstance(parsed_result, list) and len(parsed_result) > 0:
                logger.info(f"解析后结果第一个元素: {parsed_result[0]}")
            elif isinstance(parsed_result, dict):
                logger.info(f"解析后结果键示例: {list(parsed_result.keys())[:3]}")

        # 构建映射并返回
        result = build_map(parsed_result)
        logger.info(f"构建映射后的结果类型: {type(result)}")
        logger.info(f"构建映射后的结果长度: {len(result)}")
        logger.info(f"构建映射后的结果键示例: {list(result.keys())[:3] if len(result) > 0 else '空'}")
        return result

    except Exception as e:
        logger.error(f"翻译过程中出错: {str(e)}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")
        # 如果出错，返回一个只包含原文的映射
        lines = text.strip().split('\n')
        result = {line: f"[翻译错误: {str(e)}]" for line in lines if line.strip()}
        return result

# 批量翻译函数
async def batch_translate_async(texts: List[str], field: str = None,
                             stop_words: List[str] = None,
                             custom_translations: Dict[str, str] = None,
                             source_language: str = "en", target_language: str = "zh",
                             concurrency: int = 3):
    """
    批量异步翻译

    Args:
        texts: 待翻译文本列表
        field: 文本领域
        stop_words: 停止词列表
        custom_translations: 自定义翻译字典
        source_language: 源语言代码
        target_language: 目标语言代码
        concurrency: 并发翻译数量

    Returns:
        翻译结果列表
    """
    # 使用信号量限制并发
    semaphore = asyncio.Semaphore(concurrency)

    async def _translate_with_limit(text):
        async with semaphore:
            return await translate_async(
                text, field, stop_words, custom_translations,
                source_language, target_language
            )

    # 创建任务
    tasks = [_translate_with_limit(text) for text in texts]

    # 并发执行
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 处理结果
    processed_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"批量翻译中第 {i+1} 个文本失败: {str(result)}")
            processed_results.append({texts[i]: f"[翻译错误: {str(result)}]"})
        else:
            processed_results.append(result)

    return processed_results

# client=get_openai_client()
# print(client.api_key)
# completion = client.chat.completions.create(
#     model=MODEL_NAME, # 模型列表：https://help.aliyun.com/zh/model-studio/getting-started/models
#     messages=[
#         {'role': 'system', 'content': 'You are a helpful assistant.'},
#         {'role': 'user', 'content': '你是谁？'}
#         ]
# )
# print(completion.choices[0].message.content)