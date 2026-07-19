"""
阿里云翻译API（同步版本）
使用新的阿里云API进行文本翻译
"""
import json
import logging
import random
from http import HTTPStatus
from dashscope import Generation

from app.translation.qwen_config import qwen_model_name

# 导入工具函数
from ..utils.translation_utils import (
    build_map,
    parse_formatted_text,
    re_parse_formatted_text,
    clean_translation_text
)

# 配置
from config import api_key

model = qwen_model_name()
logging.basicConfig(level=logging.INFO, format='%(message)s', encoding='utf-8')
logger = logging.getLogger(__name__)


def get_field(text: str) -> str:
    """
    获取文本领域分析结果

    Args:
        text: 待分析的文本

    Returns:
        领域分析结果字符串
    """
    messages = [
        {'role': 'system', 'content': """
        你是一个多语言专家。我将给你一系列PPT中的文本。我需要你帮我判断这个PPT可能的领域。给我一到三个可能的领域。
        请用简洁的词汇回答，例如：医学、技术、商务、教育、科学等。
        """},
        {'role': 'user', 'content': text}
    ]

    try:
        response = Generation.call(
            model=model,
            messages=messages,
            api_key=api_key,
            seed=random.randint(1, 10000),
            result_format='message',
            enable_thinking=False,
        )

        if response.status_code == HTTPStatus.OK:
            return response.output.choices[0]['message']['content']
        else:
            logger.error(f'领域分析请求失败: {response.status_code}, {response.message}')
            return "通用"  # 默认返回通用领域
    except Exception as e:
        logger.error(f'领域分析异常: {str(e)}')
        return "通用"

def translate_by_fields(field: str, text: str, stop_words: list, custom_translations: dict,
                       source_language: str, target_language: str) -> str:
    """
    按领域翻译文本

    Args:
        field: 文本领域
        text: 待翻译文本
        stop_words: 停止词列表
        custom_translations: 自定义翻译字典
        source_language: 源语言
        target_language: 目标语言

    Returns:
        翻译结果JSON字符串
    """
    stop_words_str = ", ".join(f'"{word}"' for word in stop_words)
    custom_translations_str = ", ".join(f'"{k}": "{v}"' for k, v in custom_translations.items())

    messages = [
        {'role': 'system', 'content': f"""您是{field}领域的专家。
接下来，您将获得一系列{source_language}文本（包括短语、句子和单词）。
以下词汇或短语**保留原样，不翻译**：
{stop_words_str}
请将每一段{source_language}文本翻译成专业的{target_language}。

**重要：请严格遵守以下翻译规则**：
1. **格式要求**：
    - 对每条待翻译文本，输出一个 JSON 对象，格式如下：
      {{
          "source_language": "原语言文本",
          "target_language": "译文"
      }}
    - 若有多条待翻译文本，请按顺序在 **同一个 JSON 数组** 内输出，例如：
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
    - **不要输出额外信息、注释或多余文本**。

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

现在，请按照上述规则翻译文本
"""},
        {'role': 'user', 'content': text}
    ]

    try:
        response = Generation.call(
            model=model,
            messages=messages,
            api_key=api_key,
            seed=random.randint(1, 10000),
            result_format='message',
            enable_thinking=False,
        )

        if response.status_code == HTTPStatus.OK:
            return response.output.choices[0]['message']['content']
        else:
            logger.error(f'翻译请求失败: {response.status_code}, {response.message}')
            return f'[{{"source_language": "{text[:100]}...", "target_language": "[翻译失败]"}}]'
    except Exception as e:
        logger.error(f'翻译异常: {str(e)}')
        return f'[{{"source_language": "{text[:100]}...", "target_language": "[翻译异常: {str(e)}]"}}]'


def translate_qwen(text: str, field: str, stop_words: list, custom_translations: dict,
                  source_language: str, target_language: str) -> dict:
    """
    使用阿里云API翻译文本

    Args:
        text: 待翻译文本
        field: 文本领域
        stop_words: 停止词列表
        custom_translations: 自定义翻译字典
        source_language: 源语言
        target_language: 目标语言

    Returns:
        翻译映射字典 {原文: 译文}
    """
    try:
        # 调用翻译API
        raw_output = translate_by_fields(field, text, stop_words, custom_translations,
                                       source_language, target_language)

        # 清理特殊字符
        cleaned_text = clean_translation_text(raw_output)

        # 解析JSON结果
        parsed_result = parse_formatted_text(cleaned_text)

        # 构建映射字典
        return build_map(parsed_result)

    except Exception as e:
        logger.error(f'翻译处理失败: {str(e)}')
        return {text: f"[翻译失败: {str(e)}]"}



