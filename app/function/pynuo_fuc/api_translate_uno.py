# 请先安装 OpenAI SDK: `pip3 install openai`
'''
api_translate_uno.py
支持段落层级的翻译API模块
'''
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import json
import re
import requests  # 新增：用于调用后端API
from logger_config import get_logger
from openai import OpenAI
import unicodedata
import ast
from typing import List, Dict

# 获取日志记录器
logger = get_logger("pyuno")

QWEN_API_KEY = os.getenv("QWEN_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

def translate(text: str,
              field: str="", 
              stop_words: List[str]=[],
              custom_translations: Dict[str, str]={},
              source_language: str="English", 
              target_language: str="Chinese",
              model:str="qwen"):
    # 将stop_words和custom_translations转换为字符串
    logger.info(f"translate_api_uno开始工作，执行将{source_language}翻译为{target_language}的任务")
    stop_words_str = ", ".join(f'"{word}"' for word in stop_words)
    custom_translations_str = ", ".join(f'"{k}": "{v}"' for k, v in custom_translations.items())
    if model == "qwen":
        logger.info("model参数设置为qwen,使用qwen2.5-72b-instruct模型")
        client = OpenAI(api_key=QWEN_API_KEY, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        used_model = "qwen3-235b-a22b-instruct-2507"
        response = client.chat.completions.create(
            model = used_model,
            messages=[
                {"role": "system", "content": f"""您是翻译{field}领域文本的专家。接下来，您将获得一系列{source_language}文本（包括短语、句子和单词），他们是隶属于同一个PPT的同一页面下的文本框段落的所有文本。
                                                  请将每一段文本翻译成专业的{target_language}中文。
                                                  1. 上传的将是一个格式化文本，结构如下：
                                                    第1页内容：

                                                    【文本框1-段落1】
                                                    【文本框1-段落1内的原始文本】

                                                    【文本框1-段落2】
                                                    【文本框1-段落2内的原始文本】

                                                    【文本框2-段落1】
                                                    【文本框2-段落1内的原始文本】
                                                     
                                                    每一个文本元素都是该PPT页面内一个文本框的一个段落的完整内容，请**保持整体性**，即便出现换行符等特殊符号，也务必完整翻译全文,同时保留这些换行符。
                                                  2. 原文中存在形式为[block]的分隔符，该符的作用是区分不同字体格式的文本，请不要对[block]符进行翻译。但是在翻译后的内容中你仍然需要在最后处理时要插入与原文相同数量的[block]符,且插入的位置应该在与原文相同词义的位置，以此作为后续格式处理的标记。
                                                     你需要保证翻译后的内容中，[block]符的个数与原文相同，这也就代表着译前译后拥有相同数量的文本片段，这些文段有不同的字体格式，但一一对应。
                                                  3. 不要输出任何不可见字符、控制字符、特殊符号
                                                  4. 如果原文出现了中文甚至全文段都是中文，就将中文写在source_language中，且target_language中仍然保留。
                                                  5. 输出格式应严格保持输入顺序，一段对应一段，使用如下 JSON 格式输出：
                                                  [
                                                      {{
                                                          \"box_index\": 1,
                                                          \"paragraph_index\": 1,
                                                          \"source_language\": \"【文本框1-段落1的原始文本】\",
                                                          \"target_language\": \"【文本框1-段落1的翻译】\"
                                                      }},
                                                      {{
                                                          \"box_index\": 1,
                                                          \"paragraph_index\": 2,
                                                          \"source_language\": \"【文本框1-段落2的原始文本】\",
                                                          \"target_language\": \"【文本框1-段落2的翻译】\"
                                                      }},
                                                      {{
                                                          \"box_index\": 2,
                                                          \"paragraph_index\": 1,
                                                          \"source_language\": \"【文本框2-段落1的原始文本】\",
                                                          \"target_language\": \"【文本框2-段落1的翻译】\"
                                                      }}
                                                  ]
                                                  **重要：请严格遵守以下翻译规则**：
                                                  1. **格式要求**：
                                                      - 对每个文本框段落，输出一个 JSON 对象，格式如下：
                                                      {{
                                                          \"box_index\": 文本框序号,
                                                          \"paragraph_index\": 段落序号,
                                                          \"source_language\": \"原语言文本\",
                                                          \"target_language\": \"译文\"
                                                      }}
                                                      - 按文本框段落顺序在 **同一个 JSON 数组** 内输出
                                                      - **不要输出额外信息、注释或多余文本**。
                                                      - box_index 和 paragraph_index 必须与输入中的【文本框X-段落Y】序号完全对应
                                                  2. **自定义翻译**：
                                                     如果遇到以下词汇，在保持语义通顺的前提下使用提供的翻译做参考：
                                                      {custom_translations_str}
                                                  3. **停翻词处理**：
                                                     以下或单词短语**保留原样，不翻译**：
                                                      {stop_words_str}
                                                  现在，请按照上述规则翻译文本"""},
                {"role": "user", "content": text}
            ],
            stream=False,
            max_tokens = 32768
        )
        return response.choices[0].message.content
    
    elif model == "deepseek":
        logger.info("model参数设置为deepseek,使用后端translate_ppt_page接口")
        return call_backend_translate_ppt_page(text, "deepseek", field, stop_words_str, custom_translations_str, source_language, target_language)
    
    elif model == "gpt4o":
        logger.info("model参数设置为gpt4o,使用后端translate_ppt_page接口")
        return call_backend_translate_ppt_page(text, "gpt4o", field, stop_words_str, custom_translations_str, source_language, target_language)
    
    else:
        raise ValueError(f"不支持的模型: {model}")

def call_backend_translate_ppt_page(text, model, field, stop_words_str, custom_translations_str, source_language, target_language, timeout=120):
    """
    调用后端的translate_ppt_page接口
    
    Args:
        text: 要翻译的文本
        model: 模型类型 ("deepseek" 或 "gpt4o")
        timeout: 超时时间（秒）
        
    Returns:
        str: 大模型的原始response（直接返回data）
    """
    # API基础地址和端点配置（使用api_test.py中的配置）
    base_url = "http://117.50.216.15/agent_server/app/run/"
    
    # 使用api_test.py中的端点ID
    endpoints = {
        "gpt4o": "dd69b399afaf46a18efe751e0f21f05f",
        "deepseek": "d145ae592efa4240867c3b1f99c7a5d7"
    }
    
    if model not in endpoints:
        raise ValueError(f"不支持的后端模型: {model}")
    
    endpoint_id = endpoints[model]
    url = f"{base_url}{endpoint_id}"
    
    # 构建请求载荷
    payload = {
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
    
    try:
        logger.info(f"正在调用后端API: {url}")
        logger.debug(f"请求载荷: {json.dumps(payload, ensure_ascii=False, indent=2)}")
        
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        result = response.json()
        logger.debug(f"后端API原始响应: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        # 检查响应状态
        if result.get("code") == 200:
            data = result.get("data", "")
            logger.info(f"后端API调用成功，处理返回数据")
            
            # 🔧 修复：正确处理后端返回的数据结构
            if isinstance(data, dict):
                # 如果data是字典且包含translated_json字段，提取该字段
                if 'translated_json' in data:
                    translated_json = data['translated_json']
                    logger.info(f"提取translated_json字段")
                    
                    # 如果translated_json是字符串，直接返回
                    if isinstance(translated_json, str):
                        logger.info(f"translated_json是字符串，直接返回")
                        return translated_json
                    
                    # 如果translated_json是列表或其他结构，转换为JSON字符串
                    else:
                        json_result = json.dumps(translated_json, ensure_ascii=False)
                        logger.info(f"translated_json转换为JSON字符串，长度: {len(json_result)} 字符")
                        return json_result
                
                # 如果data是字典且包含output字段，提取output字段
                elif 'output' in data:
                    output_data = data['output']
                    
                    # 如果output也是字典且包含translated_json
                    if isinstance(output_data, dict) and 'translated_json' in output_data:
                        translated_json = output_data['translated_json']
                        if isinstance(translated_json, str):
                            return translated_json
                        else:
                            return json.dumps(translated_json, ensure_ascii=False)
                    
                    # 否则直接处理output
                    json_result = json.dumps(output_data, ensure_ascii=False)
                    logger.info(f"提取output字段并转换为JSON字符串，长度: {len(json_result)} 字符")
                    return json_result
                
                # 如果都没有特殊字段，直接转换整个data
                else:
                    json_result = json.dumps(data, ensure_ascii=False)
                    logger.info(f"直接转换data为JSON字符串，长度: {len(json_result)} 字符")
                    return json_result
            
            # 如果data已经是字符串，直接返回
            elif isinstance(data, str):
                logger.info(f"data已经是字符串，直接返回")
                return data
            
            # 如果data是列表，转换为JSON字符串
            elif isinstance(data, list):
                json_result = json.dumps(data, ensure_ascii=False)
                logger.info(f"data是列表，转换为JSON字符串，长度: {len(json_result)} 字符")
                return json_result
            
            # 其他情况，尝试转换为JSON字符串
            else:
                try:
                    json_result = json.dumps(data, ensure_ascii=False)
                    logger.info(f"data转换为JSON字符串，长度: {len(json_result)} 字符")
                    return json_result
                except Exception as e:
                    logger.error(f"无法将data转换为JSON字符串: {e}")
                    raise ValueError(f"后端返回的数据格式无法处理: {type(data)}")
        else:
            error_msg = result.get('msg', '未知错误')
            logger.error(f"后端API调用失败: 状态码 {result.get('code')}, 错误信息: {error_msg}")
            raise ValueError(f"后端API调用失败: {error_msg}")
    
    except requests.exceptions.Timeout:
        logger.error(f"后端API调用超时 (超过 {timeout} 秒)")
        raise ValueError(f"后端API调用超时，请稍后重试")
    
    except requests.exceptions.ConnectionError as e:
        logger.error(f"后端API连接错误: {e}")
        raise ValueError("无法连接到后端API服务器，请检查网络连接")
    
    except requests.exceptions.RequestException as e:
        logger.error(f"后端API请求异常: {e}")
        raise ValueError(f"后端API请求失败: {str(e)}")
    
    except json.JSONDecodeError as e:
        logger.error(f"后端API响应不是有效的JSON格式: {e}")
        raise ValueError("后端API返回的响应格式无效")
    
    except Exception as e:
        logger.error(f"调用后端API时发生未知错误: {e}", exc_info=True)
        raise ValueError(f"调用后端API时发生错误: {str(e)}")

def clean_translation_text(text: str) -> str:
    """
    清理翻译文本中的不可见字符和特殊控制字符
    """
    if not text:
        return text

    # 移除常见控制字符
    text = re.sub(r'[\x00-\x1F\x7F]', '', text)
    # 移除零宽字符、不可见空格等
    invisible_chars = [
        '\u200b',  # 零宽空格
        '\u200c',  # 零宽非连接符
        '\u200d',  # 零宽连接符
        '\u200e',  # 从左到右标记
        '\u200f',  # 从右到左标记
        '\u202a',  # 从左到右嵌入
        '\u202b',  # 从右到左嵌入
        '\u202c',  # 嵌入结束
        '\u202d',  # 从左到右覆盖
        '\u202e',  # 从右到左覆盖
        '\ufeff',  # BOM
    ]
    for ch in invisible_chars:
        text = text.replace(ch, '')

    # 还可以用unicodedata过滤所有类别为"Cf"的字符
    text = ''.join(c for c in text if unicodedata.category(c) != 'Cf')

    return text.strip()

def parse_formatted_text_async(text: str):
    """
    异步解析格式化文本（JSON）

    Args:
        text: 格式化文本

    Returns:
        解析结果
    """
    logger.debug(f"原始待解析文本: {repr(text)}")
    cleaned_text = clean_translation_text(text)
    logger.debug(f"清理后待解析文本: {repr(cleaned_text)}")
    
    # 先尝试直接用json解析
    try:
        return json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        logger.warning(f"初次解析 JSON 失败，尝试 ast.literal_eval: {e}")
        try:
            result = ast.literal_eval(cleaned_text)
            logger.info("使用 ast.literal_eval 成功解析")
            return result
        except Exception as e2:
            logger.warning(f"ast.literal_eval 解析失败，尝试正则提取: {e2}")
            # 尝试正则提取JSON主体
            json_block = extract_json_block(cleaned_text)
            try:
                return json.loads(json_block)
            except Exception as e3:
                logger.warning(f"正则提取后仍失败，尝试大模型修复: {e3}")
                # 调用大模型修复
                fixed_text = clean_translation_text(re_parse_formatted_text_async(json_block))
                logger.debug(f"修复后待解析文本: {repr(fixed_text)}")
                return json.loads(fixed_text)

def re_parse_formatted_text_async(text: str):
    """
    同步重新解析格式化文本，修复可能的格式错误
    Args:
        text: 格式可能错误的文本
    Returns:
        修复后的文本
    """
    try:
        client = OpenAI(api_key=QWEN_API_KEY, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        response = client.chat.completions.create(
            model="qwen3-235b-a22b-instruct-2507",
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
        logger.error(f"修复JSON格式失败，返回原文: {str(e)}")
        return text

def separate_translate_text(text_translate):
    """
    解析翻译后的JSON文本，提取所有target_language字段，并按文本框段落索引组织
    """
    logger.debug(f"开始解析翻译结果，输入类型: {type(text_translate)}")
    logger.debug(f"输入内容前100字符: {str(text_translate)[:100]}...")
    
    # 对json文本进行简单的字符过滤
    text_clean = clean_translation_text(text_translate)
    logger.debug(f"清理后文本类型: {type(text_clean)}")
    logger.debug(f"清理后内容前100字符: {str(text_clean)[:100]}...")
    
    # 解析JSON
    try:
        data = parse_formatted_text_async(text_clean)
        logger.debug(f"JSON解析成功，解析结果类型: {type(data)}")
        if isinstance(data, list):
            logger.debug(f"解析结果是列表，长度: {len(data)}")
            if len(data) > 0:
                logger.debug(f"第一个元素类型: {type(data[0])}")
                logger.debug(f"第一个元素: {data[0]}")
        elif isinstance(data, dict):
            logger.debug(f"解析结果是字典，键: {list(data.keys())}")
        elif isinstance(data, str):
            logger.debug(f"解析结果仍然是字符串，长度: {len(data)}")
            logger.debug(f"字符串内容前100字符: {data[:100]}...")
            # 如果还是字符串，尝试再次解析
            try:
                data = json.loads(data)
                logger.debug(f"二次JSON解析成功，结果类型: {type(data)}")
            except Exception as e2:
                logger.error(f"二次JSON解析失败: {e2}")
        else:
            logger.debug(f"解析结果是其他类型: {type(data)}, 值: {data}")
    except Exception as e:
        logger.error(f"JSON解析失败: {e}")
        raise ValueError(f"翻译结果不是合法JSON: {e}\n{text_translate}")
    
    # 确保data是列表
    if not isinstance(data, list):
        logger.error(f"期望解析结果为列表，但得到: {type(data)}")
        raise ValueError(f"翻译结果解析后不是列表格式，而是: {type(data)}")
    
    # 处理新的JSON格式：带box_index和paragraph_index的数组
    box_paragraph_translations = {}
    
    for i, item in enumerate(data):
        logger.debug(f"处理第 {i} 个元素，类型: {type(item)}")
        
        if not isinstance(item, dict):
            logger.error(f"数组元素 {i} 不是字典类型，而是: {type(item)}, 值: {item}")
            continue
            
        box_index = item.get("box_index")
        paragraph_index = item.get("paragraph_index")
        target_language = item.get("target_language", "")
        
        logger.debug(f"元素 {i}: box_index={box_index}, paragraph_index={paragraph_index}")
        
        if box_index is not None and paragraph_index is not None:
            # 创建复合键：box_index_paragraph_index
            key = f"{box_index}_{paragraph_index}"
            
            # 将翻译文本按[block]分割成片段
            fragments = [seg.strip() for seg in target_language.split('[block]') if seg.strip()]
            box_paragraph_translations[key] = fragments
            
            logger.debug(f"解析文本框 {box_index} 段落 {paragraph_index}: {len(fragments)} 个片段")
    
    logger.info(f"解析到 {len(box_paragraph_translations)} 个文本框段落的翻译结果")
    return box_paragraph_translations


def validate_page_indices(text_boxes_data):
    """
    验证页面索引的正确性，检测可能的页面索引重新映射bug
    """
    logger = get_logger("pyuno")
    page_indices = set(bp['page_index'] for bp in text_boxes_data)
    page_indices_sorted = sorted(page_indices)
    
    logger.info(f"检测到的页面索引: {page_indices_sorted}")
    
    # 检查是否是连续的 0,1,2... 序列（可能是重新映射bug的特征）
    if len(page_indices_sorted) > 1 and page_indices_sorted == list(range(len(page_indices_sorted))):
        logger.warning("⚠️  检测到连续的页面索引序列 (0,1,2,...)，这可能表明存在页面索引重新映射bug！")
        logger.warning("⚠️  如果用户选择的不是连续页面，请检查 ppt_data_utils.py 中的 extract_texts_for_translation 函数")
    else:
        logger.info("✅ 页面索引看起来正确（不是简单的重新映射序列）")
    
    return page_indices


def validate_page_indices(text_boxes_data):
    """
    验证页面索引的正确性，检测可能的页面索引重新映射bug
    """
    logger = get_logger("pyuno")
    page_indices = set(bp['page_index'] for bp in text_boxes_data)
    page_indices_sorted = sorted(page_indices)
    
    logger.info(f"检测到的页面索引: {page_indices_sorted}")
    
    # 检查是否是连续的 0,1,2... 序列（可能是重新映射bug的特征）
    if len(page_indices_sorted) > 1 and page_indices_sorted == list(range(len(page_indices_sorted))):
        logger.warning("⚠️  检测到连续的页面索引序列 (0,1,2,...)，这可能表明存在页面索引重新映射bug！")
        logger.warning("⚠️  如果用户选择的不是连续页面，请检查 ppt_data_utils.py 中的 extract_texts_for_translation 函数")
    else:
        logger.info("✅ 页面索引看起来正确（不是简单的重新映射序列）")
    
    return page_indices


def format_page_text_for_translation(text_boxes_data, page_index):
    """
    格式化指定页面的文本用于翻译API调用（支持段落层级）
    ✅ 修复版本：增强页面索引验证和日志
    
    Args:
        text_boxes_data: 文本框段落数据列表
        page_index: 要处理的页面索引（PPT中的真实页面索引）
        
    Returns:
        str: 格式化后的页面文本内容
    """
    # 过滤出指定页面的文本框段落数据
    page_box_paragraphs = [box_para for box_para in text_boxes_data if box_para['page_index'] == page_index]
    
    if not page_box_paragraphs:
        logger.warning(f"⚠️  页面索引 {page_index} 没有找到对应的文本框段落数据")
        return ""
    
    # ✅ 更清晰的页面标识，明确显示这是PPT中的真实页面索引
    formatted_text = f"第{page_index + 1}页内容（PPT原始页面索引：{page_index}）：\n\n"
    
    # 按文本框和段落组织数据
    box_paragraphs_dict = {}
    for box_para in page_box_paragraphs:
        box_index = box_para['box_index']
        paragraph_index = box_para['paragraph_index']
        
        if box_index not in box_paragraphs_dict:
            box_paragraphs_dict[box_index] = {}
        
        box_paragraphs_dict[box_index][paragraph_index] = box_para
    
    # 按文本框索引排序输出
    for box_index in sorted(box_paragraphs_dict.keys()):
        paragraphs_dict = box_paragraphs_dict[box_index]
        
        # 按段落索引排序输出
        for paragraph_index in sorted(paragraphs_dict.keys()):
            box_para = paragraphs_dict[paragraph_index]
            
            # 使用1-based索引显示
            formatted_text += f"【文本框{box_index + 1}-段落{paragraph_index + 1}】\n"
            formatted_text += f"{box_para['combined_text']}\n\n"
    
    logger.debug(f"PPT第 {page_index + 1} 页（原始索引{page_index}）格式化了 {len(page_box_paragraphs)} 个文本框段落")
    return formatted_text.strip()

def translate_pages_by_page(text_boxes_data, progress_callback, source_language, target_language, model,stop_words_list,custom_translations):
    """
    按页翻译文本内容，每页调用一次翻译API（支持段落层级）
    ✅ 修复版本：正确处理页面索引和进度回调
    
    Args:
        text_boxes_data: 文本框段落数据列表
        progress_callback: 进度回调函数
        source_language: 源语言
        target_language: 目标语言
        model: 使用的翻译模型
        
    Returns:
        dict: 翻译结果，格式为 {page_index: translated_content}
    """
    logger.info(f"开始按页翻译（段落层级），共 {len(text_boxes_data)} 个文本框段落")
    
    # ✅ 新增：验证页面索引的正确性
    page_indices = validate_page_indices(text_boxes_data)
    page_indices_sorted = sorted(page_indices)
    total_pages = len(page_indices_sorted)
    
    logger.info(f"需要翻译的页面索引: {page_indices_sorted}")
    logger.info(f"总共需要翻译 {total_pages} 页")
    
    # ✅ 增强：显示每页的详细统计，验证页面索引正确性
    logger.info("=" * 50)
    logger.info("各页面文本框段落分布验证:")
    for page_index in page_indices_sorted:
        page_box_paragraphs = [bp for bp in text_boxes_data if bp['page_index'] == page_index]
        logger.info(f"PPT第 {page_index + 1} 页（原始索引{page_index}）: {len(page_box_paragraphs)} 个文本框段落")
        
        # 显示详细的文本框段落分布
        box_para_dist = {}
        for bp in page_box_paragraphs:
            box_idx = bp['box_index']
            if box_idx not in box_para_dist:
                box_para_dist[box_idx] = 0
            box_para_dist[box_idx] += 1
        
        for box_idx in sorted(box_para_dist.keys()):
            logger.info(f"    文本框 {box_idx + 1}: {box_para_dist[box_idx]} 个段落")
    logger.info("=" * 50)
    
    translation_results = {}
    
    # 初始化进度回调
    if progress_callback:
        progress_callback(0, total_pages)
    
    # ✅ 修复：使用枚举来获取正确的进度序号，同时保持真实的页面索引
    for current_page_number, page_index in enumerate(page_indices_sorted, 1):
        logger.info("=" * 60)
        logger.info(f"正在处理第 {current_page_number}/{total_pages} 页")
        logger.info(f"对应PPT第 {page_index + 1} 页（原始页面索引：{page_index}）")
        logger.info("=" * 60)
        
        # ✅ 修复：使用正确的当前页面数进行进度回调
        if progress_callback:
            progress_callback(current_page_number - 1, total_pages)
        
        # 生成该页的格式化文本
        page_content = format_page_text_for_translation(text_boxes_data, page_index)
        
        if not page_content:
            logger.warning(f"PPT第 {page_index + 1} 页（原始索引{page_index}）没有文本内容，跳过")
            continue
        
        logger.info(f"PPT第 {page_index + 1} 页格式化完成:")
        logger.info(f"  格式化文本长度: {len(page_content)} 字符")
        logger.info("-" * 40)
        # logger.info(page_content)  # 可以取消注释查看详细内容
        logger.info("-" * 40)
        
        try:
            # 调用翻译API
            logger.info(f"正在调用翻译API翻译PPT第 {page_index + 1} 页...")
            translated_result = translate(page_content, 
                                          model=model,
                                          stop_words=stop_words_list,
                                          custom_translations=custom_translations,
                                          source_language=source_language,
                                          target_language=target_language)          
            logger.info(f"PPT第 {page_index + 1} 页翻译完成")
            
            logger.info("翻译结果:")
            logger.info(f"  翻译结果长度: {len(translated_result)} 字符")
            logger.info("-" * 40)
            logger.info(translated_result)  # 可以取消注释查看详细内容
            logger.info("-" * 40)
            
            # 解析翻译结果
            translated_fragments = separate_translate_text(translated_result)
            
            # 存储翻译结果 - 使用真实的页面索引作为键
            page_box_paragraphs = [bp for bp in text_boxes_data if bp['page_index'] == page_index]
            
            translation_results[page_index] = {  # ✅ 使用真实的页面索引作为键
                'original_content': page_content,
                'translated_json': translated_result,
                'translated_fragments': translated_fragments,
                'box_paragraph_count': len(page_box_paragraphs),
                'box_count': len(set(bp['box_index'] for bp in page_box_paragraphs)),
                'ppt_page_number': page_index + 1,  # PPT中的显示页码
                'processing_sequence': current_page_number,  # 处理序号
                'original_page_index': page_index  # 原始页面索引
            }
            
            logger.info(f"PPT第 {page_index + 1} 页翻译完成，得到 {len(translated_fragments)} 个文本框段落的翻译")
            
            # 显示翻译结果的键值对应关系
            logger.info("翻译结果键值映射:")
            for key, fragments in translated_fragments.items():
                logger.info(f"    {key}: {len(fragments)} 个片段")
            
        except Exception as e:
            logger.error(f"翻译PPT第 {page_index + 1} 页时出错: {e}", exc_info=True)
            # 如果翻译失败，记录错误信息
            page_box_paragraphs = [bp for bp in text_boxes_data if bp['page_index'] == page_index]
            translation_results[page_index] = {
                'original_content': page_content,
                'error': str(e),
                'translated_fragments': {},
                'box_paragraph_count': len(page_box_paragraphs),
                'box_count': len(set(bp['box_index'] for bp in page_box_paragraphs)),
                'ppt_page_number': page_index + 1,
                'processing_sequence': current_page_number,
                'original_page_index': page_index
            }
    
    # 完成进度回调
    if progress_callback:
        progress_callback(total_pages, total_pages)
    
    logger.info("=" * 60)
    logger.info(f"按页翻译完成，共处理 {len(translation_results)} 页")
    logger.info("=" * 60)
    
    # 显示统计信息
    successful_pages = len([r for r in translation_results.values() if 'error' not in r])
    failed_pages = len([r for r in translation_results.values() if 'error' in r])
    total_box_paragraphs_translated = sum(len(r.get('translated_fragments', {})) for r in translation_results.values())
    total_boxes_translated = sum(r.get('box_count', 0) for r in translation_results.values())
    
    logger.info("翻译统计:")
    logger.info(f"  - 成功翻译页数: {successful_pages}")
    logger.info(f"  - 翻译失败页数: {failed_pages}")
    logger.info(f"  - 总翻译文本框数: {total_boxes_translated}")
    logger.info(f"  - 总翻译文本框段落数: {total_box_paragraphs_translated}")
    
    # ✅ 增强：显示详细的页面处理信息，验证页面索引映射正确性
    logger.info("详细页面处理验证:")
    for page_index, result in translation_results.items():
        ppt_page_num = result.get('ppt_page_number', page_index + 1)
        processing_seq = result.get('processing_sequence', '?')
        original_idx = result.get('original_page_index', page_index)
        status = "成功" if 'error' not in result else f"失败({result.get('error', 'unknown')[:50]}...)"
        logger.info(f"  处理序号 {processing_seq}: PPT第{ppt_page_num}页（原始索引{original_idx}）- {status}")
    
    return translation_results

def extract_json_block(text):
    """
    尝试提取最外层的[]或{}包裹的内容
    """
    import re
    match = re.search(r'(\[.*\]|\{.*\})', text, re.DOTALL)
    if match:
        return match.group(1)
    return text  # 如果没找到，返回原文

def validate_translation_result(translation_results, text_boxes_data):
    """
    验证翻译结果的完整性和正确性
    
    Args:
        translation_results: 翻译结果
        text_boxes_data: 原始文本框段落数据
        
    Returns:
        dict: 验证结果统计
    """
    logger = get_logger("pyuno")
    logger.info("开始验证翻译结果...")
    
    validation_stats = {
        'total_expected_box_paragraphs': len(text_boxes_data),
        'total_translated_box_paragraphs': 0,
        'missing_translations': [],
        'extra_translations': [],
        'fragment_count_mismatches': [],
        'pages_processed': len(translation_results)
    }
    
    try:
        # 创建预期的文本框段落映射
        expected_box_paragraphs = {}
        for box_para in text_boxes_data:
            page_idx = box_para['page_index']
            box_idx = box_para['box_index']
            para_idx = box_para['paragraph_index']
            key = f"{box_idx + 1}_{para_idx + 1}"  # 转为1-based
            
            if page_idx not in expected_box_paragraphs:
                expected_box_paragraphs[page_idx] = {}
            
            expected_box_paragraphs[page_idx][key] = {
                'expected_fragments': len(box_para['texts']),
                'box_para_data': box_para
            }
        
        # 验证每页的翻译结果
        for page_idx, translation_result in translation_results.items():
            if 'error' in translation_result:
                logger.warning(f"第 {page_idx + 1} 页翻译失败，跳过验证")
                continue
            
            translated_fragments = translation_result.get('translated_fragments', {})
            expected_for_page = expected_box_paragraphs.get(page_idx, {})
            
            # 检查缺失的翻译
            for expected_key in expected_for_page:
                if expected_key not in translated_fragments:
                    validation_stats['missing_translations'].append(f"页面{page_idx + 1}-{expected_key}")
                else:
                    # 检查片段数量是否匹配
                    expected_count = expected_for_page[expected_key]['expected_fragments']
                    actual_count = len(translated_fragments[expected_key])
                    
                    if expected_count != actual_count:
                        validation_stats['fragment_count_mismatches'].append({
                            'location': f"页面{page_idx + 1}-{expected_key}",
                            'expected': expected_count,
                            'actual': actual_count
                        })
                    
                    validation_stats['total_translated_box_paragraphs'] += 1
            
            # 检查多余的翻译
            for actual_key in translated_fragments:
                if actual_key not in expected_for_page:
                    validation_stats['extra_translations'].append(f"页面{page_idx + 1}-{actual_key}")
        
        # 计算验证统计
        validation_stats['translation_coverage'] = (
            validation_stats['total_translated_box_paragraphs'] / 
            validation_stats['total_expected_box_paragraphs'] * 100
            if validation_stats['total_expected_box_paragraphs'] > 0 else 0
        )
        
        # 记录验证结果
        logger.info("翻译结果验证完成:")
        logger.info(f"  - 预期文本框段落数: {validation_stats['total_expected_box_paragraphs']}")
        logger.info(f"  - 实际翻译文本框段落数: {validation_stats['total_translated_box_paragraphs']}")
        logger.info(f"  - 翻译覆盖率: {validation_stats['translation_coverage']:.2f}%")
        logger.info(f"  - 缺失翻译数: {len(validation_stats['missing_translations'])}")
        logger.info(f"  - 多余翻译数: {len(validation_stats['extra_translations'])}")
        logger.info(f"  - 片段数量不匹配数: {len(validation_stats['fragment_count_mismatches'])}")
        
        # 如果有问题，记录详细信息
        if validation_stats['missing_translations']:
            logger.warning(f"缺失的翻译: {validation_stats['missing_translations']}")
        
        if validation_stats['extra_translations']:
            logger.warning(f"多余的翻译: {validation_stats['extra_translations']}")
        
        if validation_stats['fragment_count_mismatches']:
            logger.warning("片段数量不匹配的情况:")
            for mismatch in validation_stats['fragment_count_mismatches']:
                logger.warning(f"  {mismatch['location']}: 预期 {mismatch['expected']}, 实际 {mismatch['actual']}")
        
        return validation_stats
        
    except Exception as e:
        logger.error(f"验证翻译结果时出错: {e}", exc_info=True)
        return validation_stats

if __name__ == "__main__":
    # 测试代码
    print("=" * 60)
    print("api_translate_uno 模块测试（段落层级支持）")
    print("=" * 60)
    
    logger = get_logger("pyuno.test")
    logger.info("api_translate_uno 模块加载成功")
    
    # 创建模拟的文本框段落数据进行测试
    mock_text_boxes_data = [
        {
            'page_index': 0,
            'box_index': 0,
            'box_id': 'textbox_0',
            'paragraph_index': 0,
            'paragraph_id': 'para_0_0',
            'texts': ['Hello', 'world'],
            'combined_text': 'Hello[block]world'
        },
        {
            'page_index': 0,
            'box_index': 0,
            'box_id': 'textbox_0',
            'paragraph_index': 1,
            'paragraph_id': 'para_0_1',
            'texts': ['This is', 'a test'],
            'combined_text': 'This is[block]a test'
        }
    ]
    
    try:
        # 测试格式化函数
        formatted_text = format_page_text_for_translation(mock_text_boxes_data, 0)
        logger.info("格式化测试成功:")
        logger.info(formatted_text)
        
        # 测试翻译结果解析（模拟）
        mock_translation_result = '''[
            {
                "box_index": 1,
                "paragraph_index": 1,
                "source_language": "Hello[block]world",
                "target_language": "你好[block]世界"
            },
            {
                "box_index": 1,
                "paragraph_index": 2,
                "source_language": "This is[block]a test",
                "target_language": "这是[block]一个测试"
            }
        ]'''
        
        translated_fragments = separate_translate_text(mock_translation_result)
        logger.info("翻译结果解析测试成功:")
        for key, fragments in translated_fragments.items():
            logger.info(f"  {key}: {fragments}")
        
        # 测试后端API调用（如果有网络连接）
        try:
            test_text = """第1页内容：

【文本框1-段落1】
Hello[block]world

【文本框1-段落2】
This is[block]a test"""
            
            logger.info("测试后端API调用 (deepseek):")
            result = call_backend_translate_ppt_page(test_text, "deepseek")
            logger.info(f"后端API测试成功，返回data: {result}")
            
        except Exception as e:
            logger.warning(f"后端API测试失败（可能是网络问题）: {e}")
        
    except Exception as e:
        logger.error(f"测试失败: {e}", exc_info=True)
    
    print("=" * 60)
