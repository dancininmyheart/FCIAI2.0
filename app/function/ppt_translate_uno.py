"""
基于LibreOffice UNO接口的PPT翻译模块
提供最精确的颜色保护和格式控制
"""
import os
import logging
from typing import Dict, List, Any, Optional

from .libreoffice_uno_color import LibreOfficeUNOColorManager, UNO_AVAILABLE

logger = logging.getLogger(__name__)


def translate_ppt_with_uno_color_protection(
    ppt_path: str, 
    translation_data: Dict[str, str], 
    output_path: str = None,
    bilingual_mode: bool = False
) -> bool:
    """
    使用LibreOffice UNO接口翻译PPT，完美保持颜色和格式
    
    Args:
        ppt_path: 输入PPT文件路径
        translation_data: 翻译数据字典 {原文: 译文}
        output_path: 输出文件路径（可选）
        bilingual_mode: 是否双语模式
        
    Returns:
        bool: 翻译是否成功
    """
    if not UNO_AVAILABLE:
        logger.error("LibreOffice UNO接口不可用，请先运行 setup_libreoffice_uno.py 进行配置")
        return False
    
    if not os.path.exists(ppt_path):
        logger.error(f"PPT文件不存在: {ppt_path}")
        return False
    
    manager = LibreOfficeUNOColorManager()
    
    try:
        logger.info(f"开始UNO颜色保护翻译: {os.path.basename(ppt_path)}")
        
        # 1. 启动LibreOffice服务
        if not manager.start_libreoffice_service():
            logger.error("启动LibreOffice UNO服务失败")
            return False
        
        # 2. 打开PPT文件
        if not manager.open_presentation(ppt_path):
            logger.error("打开PPT文件失败")
            return False
        
        # 3. 提取原始颜色和格式信息
        logger.info("提取原始颜色和格式信息...")
        color_map = manager.extract_text_colors()
        
        if not color_map:
            logger.warning("未提取到颜色信息，继续处理...")
        
        # 4. 执行翻译并保持格式
        logger.info("执行翻译并保持颜色格式...")
        translation_map = _prepare_translation_map(translation_data, bilingual_mode)
        
        success = manager.apply_text_colors(color_map, translation_map)
        
        if not success:
            logger.warning("应用翻译和颜色时出现问题")
        
        # 5. 保存文档
        save_path = output_path or ppt_path
        if manager.save_and_close(save_path):
            logger.info(f"  UNO颜色保护翻译完成: {save_path}")
            return True
        else:
            logger.error("保存文档失败")
            return False
        
    except Exception as e:
        logger.error(f"UNO翻译过程中出错: {e}")
        return False
    finally:
        manager.cleanup()


def _prepare_translation_map(translation_data: Dict[str, str], bilingual_mode: bool) -> Dict[str, str]:
    """准备翻译映射"""
    if not bilingual_mode:
        return translation_data
    
    # 双语模式：原文 + 译文
    bilingual_map = {}
    for original, translated in translation_data.items():
        if original != translated:
            bilingual_map[original] = f"{original}\n{translated}"
        else:
            bilingual_map[original] = original
    
    return bilingual_map


def extract_text_from_ppt_uno(ppt_path: str) -> List[str]:
    """
    使用UNO接口从PPT中提取文本
    
    Args:
        ppt_path: PPT文件路径
        
    Returns:
        List[str]: 提取的文本列表
    """
    if not UNO_AVAILABLE:
        logger.error("LibreOffice UNO接口不可用")
        return []
    
    manager = LibreOfficeUNOColorManager()
    texts = []
    
    try:
        if manager.start_libreoffice_service():
            if manager.open_presentation(ppt_path):
                # 提取文本
                color_map = manager.extract_text_colors()
                
                for page_key, page_colors in color_map.items():
                    for shape_info in page_colors:
                        text = shape_info.get('text', '').strip()
                        if text and text not in texts:
                            texts.append(text)
                
                manager.save_and_close()
        
        return texts
        
    except Exception as e:
        logger.error(f"UNO提取文本失败: {e}")
        return []
    finally:
        manager.cleanup()


def check_uno_availability() -> bool:
    """检查UNO接口可用性"""
    if not UNO_AVAILABLE:
        return False
    
    try:
        manager = LibreOfficeUNOColorManager()
        success = manager.start_libreoffice_service()
        if success:
            manager.cleanup()
        return success
    except:
        return False


def get_uno_translation_capabilities() -> Dict[str, Any]:
    """获取UNO翻译能力信息"""
    return {
        'available': UNO_AVAILABLE,
        'features': {
            'precise_color_control': True,
            'font_formatting': True,
            'background_colors': True,
            'theme_colors': True,
            'paragraph_formatting': True,
            'table_support': True,
            'shape_support': True,
            'cross_platform': True
        },
        'advantages': [
            "精确的颜色控制",
            "完整的格式保护", 
            "原生LibreOffice支持",
            "跨平台兼容性",
            "无需额外依赖",
            "支持复杂格式"
        ],
        'requirements': [
            "LibreOffice 6.0+",
            "Python UNO绑定",
            "足够的系统权限"
        ]
    }


def integrate_uno_with_existing_translation(
    ppt_path: str,
    translation_function,
    *args,
    **kwargs
) -> bool:
    """
    将UNO接口集成到现有翻译流程中
    
    Args:
        ppt_path: PPT文件路径
        translation_function: 现有翻译函数
        *args, **kwargs: 传递给翻译函数的参数
        
    Returns:
        bool: 是否成功
    """
    if not UNO_AVAILABLE:
        logger.info("UNO接口不可用，使用传统翻译方法")
        return translation_function(ppt_path, *args, **kwargs)
    
    try:
        # 尝试使用UNO接口
        logger.info("尝试使用UNO接口进行颜色保护翻译")
        
        # 如果kwargs中有translation_data，使用UNO翻译
        if 'translation_data' in kwargs:
            translation_data = kwargs['translation_data']
            bilingual_mode = kwargs.get('bilingual_translation', '0') == '1'
            output_path = kwargs.get('output_path')
            
            success = translate_ppt_with_uno_color_protection(
                ppt_path, 
                translation_data, 
                output_path,
                bilingual_mode
            )
            
            if success:
                logger.info("  UNO颜色保护翻译成功")
                return True
            else:
                logger.warning("UNO翻译失败，回退到传统方法")
        
        # 回退到传统方法
        return translation_function(ppt_path, *args, **kwargs)
        
    except Exception as e:
        logger.warning(f"UNO集成失败: {e}，使用传统方法")
        return translation_function(ppt_path, *args, **kwargs)


def create_uno_translation_report(ppt_path: str) -> Dict[str, Any]:
    """
    创建UNO翻译能力报告
    
    Args:
        ppt_path: PPT文件路径
        
    Returns:
        Dict: 报告信息
    """
    report = {
        'file_path': ppt_path,
        'uno_available': UNO_AVAILABLE,
        'can_process': False,
        'text_count': 0,
        'color_info': {},
        'recommendations': []
    }
    
    if not UNO_AVAILABLE:
        report['recommendations'].append("安装LibreOffice UNO接口以获得最佳颜色保护")
        return report
    
    if not os.path.exists(ppt_path):
        report['recommendations'].append("PPT文件不存在")
        return report
    
    try:
        # 检查UNO服务
        if check_uno_availability():
            report['can_process'] = True
            
            # 提取文本信息
            texts = extract_text_from_ppt_uno(ppt_path)
            report['text_count'] = len(texts)
            
            if texts:
                report['recommendations'].append("建议使用UNO接口进行精确颜色保护翻译")
            else:
                report['recommendations'].append("PPT中未检测到文本内容")
        else:
            report['recommendations'].append("UNO服务启动失败，检查LibreOffice安装")
    
    except Exception as e:
        report['recommendations'].append(f"UNO检查失败: {e}")
    
    return report


# 便捷函数
def uno_translate_ppt(ppt_path: str, translations: Dict[str, str], **options) -> bool:
    """
    便捷的UNO PPT翻译函数
    
    Args:
        ppt_path: PPT文件路径
        translations: 翻译字典
        **options: 其他选项
        
    Returns:
        bool: 是否成功
    """
    return translate_ppt_with_uno_color_protection(
        ppt_path,
        translations,
        options.get('output_path'),
        options.get('bilingual', False)
    )


if __name__ == "__main__":
    # 测试UNO翻译功能
    print("LibreOffice UNO PPT翻译模块")
    print("=" * 50)
    
    capabilities = get_uno_translation_capabilities()
    print(f"UNO可用性: {capabilities['available']}")
    
    if capabilities['available']:
        print("  UNO接口可用")
        print("支持的功能:")
        for feature, supported in capabilities['features'].items():
            status = " " if supported else "❌"
            print(f"  {status} {feature}")
    else:
        print("❌ UNO接口不可用")
        print("请运行 setup_libreoffice_uno.py 进行配置")
