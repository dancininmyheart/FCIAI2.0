import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import json
from datetime import datetime
from logger_config import get_logger, log_execution_time

def extract_texts_for_translation(ppt_data):
    """
    从PPT数据中提取所有需要翻译的文本片段，按文本框和段落分组
      修复版本：正确使用原始页面索引
    Args:
        ppt_data: PPT数据结构（包含段落层级）
    Returns:
        tuple: (text_boxes_data, fragment_mapping)
            - text_boxes_data: 按文本框和段落分组的文本数据
            - fragment_mapping: 片段ID到索引的映射
    """
    logger = get_logger("pyuno.subprocess")
    logger.info("开始提取文本片段用于翻译（按文本框和段落分组，修复页面索引bug）...")
    
    text_boxes_data = []  # 存储每个文本框段落的文本信息
    fragment_mapping = {}  # fragment_id -> (box_index, paragraph_index, fragment_index)
    
    try:
        pages = ppt_data.get('pages', [])
        global_box_paragraph_index = 0  # 全局文本框段落计数器
        
        #   修复：直接遍历页面数据，不使用enumerate
        for page_data in pages:
            #   关键修复：从页面数据中获取真实的页面索引
            original_page_index = page_data.get('page_index')
            
            if original_page_index is None:
                logger.error(f"页面数据缺少page_index字段: {page_data.keys()}")
                continue
                
            logger.debug(f"处理PPT第 {original_page_index + 1} 页的文本框（原始页面索引：{original_page_index}）")
            text_boxes = page_data.get('text_boxes', [])
            
            for box_index, text_box in enumerate(text_boxes):
                paragraphs = text_box.get('paragraphs', [])
                box_id = text_box.get('box_id', f'textbox_{box_index}')
                
                logger.debug(f"PPT第{original_page_index + 1}页 文本框 {box_id} 包含 {len(paragraphs)} 个段落")
                
                # 处理每个段落
                for paragraph_index, paragraph in enumerate(paragraphs):
                    fragments = paragraph.get('text_fragments', [])
                    paragraph_id = paragraph.get('paragraph_id', f'para_{box_index}_{paragraph_index}')
                    
                    paragraph_texts = []
                    paragraph_fragments_info = []
                    
                    # 处理段落中的每个文本片段
                    for frag_index, fragment in enumerate(fragments):
                        text = fragment.get('text', '').strip()
                        fragment_id = fragment.get('fragment_id', '')
                        
                        if text:  # 只处理非空文本
                            paragraph_texts.append(text)
                            paragraph_fragments_info.append({
                                'fragment_id': fragment_id,
                                'text': text,
                                'original_index': frag_index
                            })
                            
                            # 映射：fragment_id -> (global_box_paragraph_index, fragment_index_in_paragraph)
                            fragment_mapping[fragment_id] = (global_box_paragraph_index, len(paragraph_texts) - 1)
                            
                            logger.debug(f"提取PPT第{original_page_index + 1}页段落 {paragraph_id} 片段 {frag_index}: {fragment_id} -> '{text[:20]}...'")
                    
                    # 如果段落有内容，则添加到数据中
                    if paragraph_texts:
                        text_boxes_data.append({
                            'page_index': original_page_index,  #   使用真实的原始页面索引
                            'box_index': box_index,
                            'box_id': box_id,
                            'paragraph_index': paragraph_index,
                            'paragraph_id': paragraph_id,
                            'texts': paragraph_texts,
                            'fragments_info': paragraph_fragments_info,
                            'combined_text': '[block]'.join(paragraph_texts),
                            'global_index': global_box_paragraph_index  # 全局索引，用于翻译结果映射
                        })
                        global_box_paragraph_index += 1
        
        logger.info(f"总共提取了 {len(text_boxes_data)} 个有内容的文本框段落")
        total_fragments = sum(len(box_para['texts']) for box_para in text_boxes_data)
        logger.info(f"总共提取了 {total_fragments} 个文本片段")
        
        #   新增：显示真实的页面索引分布，用于验证修复效果
        page_distribution = {}
        for box_para in text_boxes_data:
            page_idx = box_para['page_index']
            if page_idx not in page_distribution:
                page_distribution[page_idx] = 0
            page_distribution[page_idx] += 1
        
        logger.info("=" * 60)
        logger.info("页面索引验证（应显示用户选择的原始页面）:")
        for page_idx in sorted(page_distribution.keys()):
            logger.info(f"  PPT第 {page_idx + 1} 页（原始索引{page_idx}）: {page_distribution[page_idx]} 个文本框段落")
        logger.info("=" * 60)
        
        # 显示详细的提取统计
        logger.info("提取统计详情:")
        for i, box_para in enumerate(text_boxes_data):
            logger.info(f"  {i+1}. PPT第{box_para['page_index']+1}页 - {box_para['box_id']} - {box_para['paragraph_id']}: {len(box_para['texts'])} 个片段")
        
        return text_boxes_data, fragment_mapping
        
    except Exception as e:
        logger.error(f"提取文本片段时出错: {e}", exc_info=True)
        raise

def call_translation_api(text_fragments, source_language='en', target_language='zh'):
    """
    调用翻译API翻译文本片段（保持向后兼容）
    Args:
        text_fragments: 文本片段列表
        source_language: 源语言
        target_language: 目标语言
    Returns:
        list: 翻译后的文本片段列表
    """
    logger = get_logger("pyuno.subprocess")
    logger.info(f"开始调用翻译API，源语言: {source_language} -> 目标语言: {target_language}")
    
    try:
        from api_translate_uno import translate, separate_translate_text
        text_full = "[block]".join(text_fragments)
        logger.debug(f"合并后的待翻译文本长度: {len(text_full)} 字符")
        
        logger.info("正在调用翻译API...")
        translation_start_time = datetime.now()
        translated_result = translate(text_full)
        log_execution_time(logger, "翻译API调用", translation_start_time)
        
        logger.info("正在解析翻译结果...")
        translated_fragments = separate_translate_text(translated_result)
        
        logger.info(f"翻译完成，原文 {len(text_fragments)} 个片段，译文 {len(translated_fragments)} 个片段")
        
        # 长度匹配检查和调整
        if len(translated_fragments) != len(text_fragments):
            logger.warning(f"翻译结果数量不匹配: 原文 {len(text_fragments)} 个，译文 {len(translated_fragments)} 个")
            if len(translated_fragments) < len(text_fragments):
                missing_count = len(text_fragments) - len(translated_fragments)
                translated_fragments.extend([""] * missing_count)
                logger.warning(f"补充了 {missing_count} 个空翻译")
            else:
                translated_fragments = translated_fragments[:len(text_fragments)]
                logger.warning(f"截取了前 {len(text_fragments)} 个翻译结果")
        
        return translated_fragments
        
    except ImportError as e:
        logger.error(f"无法导入翻译模块: {e}")
        raise
    except Exception as e:
        logger.error(f"调用翻译API时出错: {e}", exc_info=True)
        raise

def map_translation_results_back(ppt_data, translation_results, text_boxes_data):
    """
    将翻译结果映射回原PPT数据结构（支持段落层级）
    Args:
        ppt_data: 原始PPT数据
        translation_results: 翻译结果，格式为 {page_index: {box_paragraph_key: fragments}}
        text_boxes_data: 文本框段落数据列表
    Returns:
        dict: 更新后的PPT数据，包含翻译后的文本
    """
    logger = get_logger("pyuno.subprocess")
    logger.info("开始将翻译结果映射回原PPT数据结构（段落层级）...")
    
    try:
        # 深拷贝原始数据
        translated_ppt_data = json.loads(json.dumps(ppt_data))
        pages = translated_ppt_data.get('pages', [])
        updated_fragments = 0
        
        # 创建文本框段落数据的快速查找字典
        box_para_lookup = {}
        for box_para in text_boxes_data:
            page_idx = box_para['page_index']
            box_idx = box_para['box_index']
            para_idx = box_para['paragraph_index']
            key = f"{page_idx}_{box_idx}_{para_idx}"
            box_para_lookup[key] = box_para
        
        logger.info(f"创建了 {len(box_para_lookup)} 个文本框段落的查找映射")
        
        # 遍历页面进行翻译结果映射
        for page_data in pages:
            page_index = page_data['page_index']
            text_boxes = page_data.get('text_boxes', [])
            page_translation = translation_results.get(page_index, {})
            
            if 'error' in page_translation:
                logger.warning(f"第 {page_index + 1} 页翻译失败，使用原文")
                continue
            
            box_paragraph_translations = page_translation.get('translated_fragments', {})
            logger.info(f"第 {page_index + 1} 页有 {len(box_paragraph_translations)} 个文本框段落的翻译结果")
            
            # 遍历每个文本框
            for text_box in text_boxes:
                box_index = text_box.get('box_index', 0)
                paragraphs = text_box.get('paragraphs', [])
                
                # 遍历每个段落
                for paragraph in paragraphs:
                    paragraph_index = paragraph.get('paragraph_index', 0)
                    fragments = paragraph.get('text_fragments', [])
                    
                    # 构造查找键：基于1的索引（API返回格式）
                    box_para_key = f"{box_index + 1}_{paragraph_index + 1}"  # 转换为1-based索引
                    
                    if box_para_key in box_paragraph_translations:
                        translated_fragments = box_paragraph_translations[box_para_key]
                        logger.debug(f"文本框 {box_index + 1} 段落 {paragraph_index + 1} 有 {len(translated_fragments)} 个翻译片段")
                        
                        # 更新每个文本片段
                        for i, fragment in enumerate(fragments):
                            if i < len(translated_fragments):
                                original_text = fragment.get('text', '')
                                translated_text = translated_fragments[i]
                                fragment['translated_text'] = translated_text
                                fragment['original_text'] = original_text  # 保留原文
                                updated_fragments += 1
                                logger.debug(f"更新文本框 {box_index + 1} 段落 {paragraph_index + 1} 片段 {i}: '{original_text[:20]}...' -> '{translated_text[:20]}...'")
                            else:
                                logger.warning(f"文本框 {box_index + 1} 段落 {paragraph_index + 1} 片段 {i} 没有对应的翻译")
                    else:
                        logger.warning(f"文本框 {box_index + 1} 段落 {paragraph_index + 1} (键: {box_para_key}) 没有找到翻译结果")
        
        logger.info(f"成功更新了 {updated_fragments} 个文本片段的翻译")
        
        # 添加翻译元数据
        translated_ppt_data['translation_metadata'] = {
            'total_pages_translated': len(translation_results),
            'successful_pages': len([r for r in translation_results.values() if 'error' not in r]),
            'failed_pages': len([r for r in translation_results.values() if 'error' in r]),
            'total_fragments_updated': updated_fragments,
            'total_box_paragraphs_processed': len(text_boxes_data),
            'translation_timestamp': datetime.now().isoformat(),
            'structure_version': 'with_paragraphs'
        }
        
        return translated_ppt_data
        
    except Exception as e:
        logger.error(f"映射翻译结果时出错: {e}", exc_info=True)
        raise

def save_translated_ppt_data(translated_ppt_data, output_path=None):
    """
    保存翻译后的PPT数据
    Args:
        translated_ppt_data: 翻译后的PPT数据
        output_path: 输出文件路径，如果为None则自动生成
    Returns:
        str: 保存的文件路径
    """
    logger = get_logger("pyuno.subprocess")
    
    try:
        if output_path is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            temp_dir = os.path.join(current_dir, "temp")
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
            import uuid
            output_filename = f"translated_ppt_{uuid.uuid4().hex[:8]}.json"
            output_path = os.path.join(temp_dir, output_filename)
        
        # 确保输出目录存在
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(translated_ppt_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"翻译后的PPT数据已保存到: {output_path}")
        
        # 显示保存文件的统计信息
        file_size = os.path.getsize(output_path)
        logger.info(f"保存文件大小: {file_size / 1024:.2f} KB")
        
        return output_path
        
    except Exception as e:
        logger.error(f"保存翻译后的PPT数据时出错: {e}", exc_info=True)
        raise

def get_paragraph_statistics(text_boxes_data):
    """
    获取段落级别的统计信息
    Args:
        text_boxes_data: 文本框段落数据列表
    Returns:
        dict: 统计信息
    """
    logger = get_logger("pyuno.subprocess")
    
    try:
        stats = {
            'total_box_paragraphs': len(text_boxes_data),
            'pages': {},
            'boxes': {},
            'fragments_per_paragraph': []
        }
        
        for box_para in text_boxes_data:
            page_idx = box_para['page_index']
            box_idx = box_para['box_index']
            fragment_count = len(box_para['texts'])
            
            # 页面统计
            if page_idx not in stats['pages']:
                stats['pages'][page_idx] = {'box_paragraphs': 0, 'fragments': 0}
            stats['pages'][page_idx]['box_paragraphs'] += 1
            stats['pages'][page_idx]['fragments'] += fragment_count
            
            # 文本框统计
            box_key = f"{page_idx}_{box_idx}"
            if box_key not in stats['boxes']:
                stats['boxes'][box_key] = {'paragraphs': 0, 'fragments': 0}
            stats['boxes'][box_key]['paragraphs'] += 1
            stats['boxes'][box_key]['fragments'] += fragment_count
            
            # 每段落片段数统计
            stats['fragments_per_paragraph'].append(fragment_count)
        
        # 计算平均值
        total_fragments = sum(stats['fragments_per_paragraph'])
        stats['total_fragments'] = total_fragments
        stats['avg_fragments_per_paragraph'] = total_fragments / len(text_boxes_data) if text_boxes_data else 0
        
        logger.info(f"段落统计: {stats['total_box_paragraphs']} 个段落，{stats['total_fragments']} 个片段")
        logger.info(f"平均每段落 {stats['avg_fragments_per_paragraph']:.2f} 个片段")
        
        return stats
        
    except Exception as e:
        logger.error(f"获取段落统计信息时出错: {e}", exc_info=True)
        return {}

# 向后兼容的函数（如果有其他代码还在使用旧接口）
def extract_texts_for_translation_legacy(ppt_data):
    """
    向后兼容的文本提取函数（不支持段落层级）
    """
    logger = get_logger("pyuno.subprocess")
    logger.warning("使用了向后兼容的文本提取函数，建议升级到新的段落层级版本")
    
    # 这里可以实现一个简化版本，将段落合并为文本框级别
    # 但建议直接使用新版本
    return extract_texts_for_translation(ppt_data)

if __name__ == "__main__":
    # 测试代码
    print("=" * 60)
    print("ppt_data_utils 模块测试")
    print("=" * 60)
    
    # 这里可以添加一些基本的测试代码
    logger = get_logger("pyuno.test")
    logger.info("ppt_data_utils 模块加载成功")
    
    # 创建一个模拟的PPT数据进行测试
    mock_ppt_data = {
        'pages': [
            {
                'page_index': 0,
                'text_boxes': [
                    {
                        'box_index': 0,
                        'box_id': 'textbox_0',
                        'paragraphs': [
                            {
                                'paragraph_index': 0,
                                'paragraph_id': 'para_0_0',
                                'text_fragments': [
                                    {'fragment_id': 'frag_0_0_0', 'text': 'Hello'},
                                    {'fragment_id': 'frag_0_0_1', 'text': ' world'}
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    }
    
    try:
        text_boxes_data, fragment_mapping = extract_texts_for_translation(mock_ppt_data)
        logger.info(f"测试成功：提取了 {len(text_boxes_data)} 个文本框段落")
        for box_para in text_boxes_data:
            logger.info(f"  {box_para['paragraph_id']}: {box_para['combined_text']}")
    except Exception as e:
        logger.error(f"测试失败: {e}")
    
    print("=" * 60)
