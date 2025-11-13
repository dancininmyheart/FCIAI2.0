"""
LibreOffice UNO接口颜色保护模块
使用LibreOffice的Universal Network Objects接口来精确控制PPT文本颜色
提供比python-pptx更强大的颜色处理能力
"""
import os
import sys
import time
import logging
import subprocess
import tempfile
import shutil
from typing import Dict, List, Any, Optional, Tuple
import platform

logger = logging.getLogger(__name__)

# UNO相关导入
try:
    import uno
    from com.sun.star.beans import PropertyValue
    from com.sun.star.connection import NoConnectException
    from com.sun.star.lang import DisposedException
    UNO_AVAILABLE = True
except ImportError:
    UNO_AVAILABLE = False
    logger.warning("LibreOffice UNO接口不可用，请安装LibreOffice Python SDK")


class LibreOfficeUNOColorManager:
    """LibreOffice UNO颜色管理器"""
    
    def __init__(self):
        self.soffice_process = None
        self.desktop = None
        self.document = None
        self.port = 2002
        self.context = None
        
    def start_libreoffice_service(self) -> bool:
        """启动LibreOffice服务"""
        if not UNO_AVAILABLE:
            logger.error("UNO接口不可用")
            return False
        
        try:
            # 查找LibreOffice可执行文件
            soffice_path = self._find_libreoffice_executable()
            if not soffice_path:
                logger.error("未找到LibreOffice可执行文件")
                return False
            
            # 启动LibreOffice服务
            cmd = [
                soffice_path,
                "--headless",
                "--invisible",
                "--nocrashreport",
                "--nodefault",
                "--nolockcheck",
                "--nologo",
                "--norestore",
                f"--accept=socket,host=localhost,port={self.port};urp;StarOffice.ServiceManager"
            ]
            
            logger.info(f"启动LibreOffice服务: {' '.join(cmd)}")
            self.soffice_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # 等待服务启动
            logger.info("等待LibreOffice服务启动...")
            time.sleep(5)  # 增加等待时间

            # 连接到LibreOffice
            return self._connect_to_libreoffice()
            
        except Exception as e:
            logger.error(f"启动LibreOffice服务失败: {e}")
            return False
    
    def _find_libreoffice_executable(self) -> Optional[str]:
        """查找LibreOffice可执行文件"""
        system = platform.system()
        
        if system == "Windows":
            possible_paths = [
                r"C:\Program Files\LibreOffice\program\soffice.exe",
                r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                r"C:\LibreOffice\program\soffice.exe"
            ]
        elif system == "Linux":
            possible_paths = [
                "/usr/bin/libreoffice",
                "/usr/local/bin/libreoffice",
                "/opt/libreoffice/program/soffice",
                "/snap/bin/libreoffice"
            ]
        elif system == "Darwin":  # macOS
            possible_paths = [
                "/Applications/LibreOffice.app/Contents/MacOS/soffice",
                "/usr/local/bin/libreoffice"
            ]
        else:
            possible_paths = []
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        # 尝试在PATH中查找
        try:
            result = subprocess.run(
                ["which", "libreoffice"] if system != "Windows" else ["where", "soffice.exe"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
        except:
            pass
        
        return None
    
    def _connect_to_libreoffice(self) -> bool:
        """连接到LibreOffice服务"""
        try:
            # 检查进程是否还在运行
            if self.soffice_process and self.soffice_process.poll() is not None:
                logger.error("LibreOffice进程已退出")
                return False

            # 创建UNO连接
            local_context = uno.getComponentContext()
            resolver = local_context.ServiceManager.createInstanceWithContext(
                "com.sun.star.bridge.UnoUrlResolver", local_context
            )

            # 连接到LibreOffice
            connection_string = f"uno:socket,host=localhost,port={self.port};urp;StarOffice.ComponentContext"
            logger.info(f"尝试连接: {connection_string}")

            # 重试连接
            for attempt in range(15):  # 增加重试次数
                try:
                    logger.info(f"连接尝试 {attempt + 1}/15...")
                    self.context = resolver.resolve(connection_string)
                    self.desktop = self.context.ServiceManager.createInstanceWithContext(
                        "com.sun.star.frame.Desktop", self.context
                    )
                    logger.info("  成功连接到LibreOffice UNO服务")
                    return True
                except NoConnectException as e:
                    if attempt < 14:
                        logger.debug(f"连接失败，等待重试... ({e})")
                        time.sleep(2)  # 增加等待时间
                        continue
                    else:
                        logger.error(f"连接超时: {e}")
                        raise
                except Exception as e:
                    logger.error(f"连接异常: {e}")
                    if attempt < 14:
                        time.sleep(2)
                        continue
                    else:
                        raise

            return False

        except Exception as e:
            logger.error(f"连接LibreOffice失败: {e}")
            # 尝试重启服务
            if hasattr(e, '__class__') and 'Binary URP bridge disposed' in str(e):
                logger.info("检测到URP桥接问题，尝试重启服务...")
                self._restart_service()
            return False

    def _restart_service(self) -> bool:
        """重启LibreOffice服务"""
        try:
            logger.info("重启LibreOffice服务...")

            # 清理现有连接
            self.cleanup()

            # 等待一段时间
            time.sleep(3)

            # 重新启动服务
            return self.start_libreoffice_service()

        except Exception as e:
            logger.error(f"重启服务失败: {e}")
            return False
    
    def open_presentation(self, ppt_path: str) -> bool:
        """打开PPT文件"""
        try:
            if not self.desktop:
                logger.error("LibreOffice服务未连接")
                return False
            
            # 转换文件路径为URL格式
            file_url = uno.systemPathToFileUrl(os.path.abspath(ppt_path))
            
            # 设置打开参数
            properties = (
                PropertyValue("Hidden", 0, True, 0),
                PropertyValue("ReadOnly", 0, False, 0),
            )
            
            # 打开文档
            self.document = self.desktop.loadComponentFromURL(
                file_url, "_blank", 0, properties
            )
            
            if self.document:
                logger.info(f"成功打开PPT文件: {ppt_path}")
                return True
            else:
                logger.error("打开PPT文件失败")
                return False
                
        except Exception as e:
            logger.error(f"打开PPT文件时出错: {e}")
            return False
    
    def extract_text_colors(self) -> Dict[str, Any]:
        """提取PPT中所有文本的颜色信息"""
        if not self.document:
            logger.error("文档未打开")
            return {}
        
        try:
            color_map = {}
            
            # 获取所有幻灯片
            draw_pages = self.document.getDrawPages()
            
            for page_idx in range(draw_pages.getCount()):
                page = draw_pages.getByIndex(page_idx)
                page_colors = []
                
                # 遍历页面中的所有形状
                for shape_idx in range(page.getCount()):
                    shape = page.getByIndex(shape_idx)
                    
                    # 检查是否为文本形状
                    if hasattr(shape, 'getString') and shape.getString():
                        shape_colors = self._extract_shape_text_colors(shape, page_idx, shape_idx)
                        if shape_colors:
                            page_colors.append(shape_colors)
                
                if page_colors:
                    color_map[f"page_{page_idx}"] = page_colors
            
            logger.info(f"提取了 {len(color_map)} 页的颜色信息")
            return color_map
            
        except Exception as e:
            logger.error(f"提取颜色信息失败: {e}")
            return {}
    
    def _extract_shape_text_colors(self, shape, page_idx: int, shape_idx: int) -> Optional[Dict[str, Any]]:
        """提取形状中文本的颜色信息"""
        try:
            shape_info = {
                'page_index': page_idx,
                'shape_index': shape_idx,
                'text': shape.getString(),
                'paragraphs': []
            }
            
            # 获取文本范围
            text_range = shape.createTextCursor()
            text_range.gotoStart(False)
            text_range.gotoEnd(True)
            
            # 遍历段落
            paragraph_enum = shape.createEnumeration()
            para_idx = 0
            
            while paragraph_enum.hasMoreElements():
                paragraph = paragraph_enum.nextElement()
                para_info = {
                    'paragraph_index': para_idx,
                    'text': paragraph.getString(),
                    'portions': []
                }
                
                # 遍历文本片段
                portion_enum = paragraph.createEnumeration()
                portion_idx = 0
                
                while portion_enum.hasMoreElements():
                    portion = portion_enum.nextElement()
                    
                    # 提取颜色信息
                    color_info = self._extract_portion_colors(portion)
                    portion_info = {
                        'portion_index': portion_idx,
                        'text': portion.getString(),
                        'colors': color_info
                    }
                    
                    para_info['portions'].append(portion_info)
                    portion_idx += 1
                
                shape_info['paragraphs'].append(para_info)
                para_idx += 1
            
            return shape_info
            
        except Exception as e:
            logger.debug(f"提取形状颜色失败: {e}")
            return None
    
    def _extract_portion_colors(self, portion) -> Dict[str, Any]:
        """提取文本片段的颜色信息"""
        colors = {}
        
        try:
            # 字体颜色
            if hasattr(portion, 'CharColor'):
                colors['font_color'] = portion.CharColor
            
            # 背景色/高亮色
            if hasattr(portion, 'CharBackColor'):
                colors['background_color'] = portion.CharBackColor
            
            # 字体属性
            if hasattr(portion, 'CharFontName'):
                colors['font_name'] = portion.CharFontName
            if hasattr(portion, 'CharHeight'):
                colors['font_size'] = portion.CharHeight
            if hasattr(portion, 'CharWeight'):
                colors['font_weight'] = portion.CharWeight
            if hasattr(portion, 'CharPosture'):
                colors['font_italic'] = portion.CharPosture
            if hasattr(portion, 'CharUnderline'):
                colors['font_underline'] = portion.CharUnderline
                
        except Exception as e:
            logger.debug(f"提取片段颜色失败: {e}")
        
        return colors
    
    def apply_text_colors(self, color_map: Dict[str, Any], translation_map: Dict[str, str]) -> bool:
        """应用颜色信息到翻译后的文本"""
        if not self.document or not color_map:
            return False
        
        try:
            # 获取所有幻灯片
            draw_pages = self.document.getDrawPages()
            
            for page_key, page_colors in color_map.items():
                page_idx = int(page_key.split('_')[1])
                
                if page_idx >= draw_pages.getCount():
                    continue
                
                page = draw_pages.getByIndex(page_idx)
                
                for shape_info in page_colors:
                    shape_idx = shape_info['shape_index']
                    
                    if shape_idx >= page.getCount():
                        continue
                    
                    shape = page.getByIndex(shape_idx)
                    
                    # 应用翻译和颜色
                    self._apply_shape_translation_and_colors(shape, shape_info, translation_map)
            
            logger.info("颜色应用完成")
            return True
            
        except Exception as e:
            logger.error(f"应用颜色失败: {e}")
            return False
    
    def _apply_shape_translation_and_colors(self, shape, shape_info: Dict[str, Any], translation_map: Dict[str, str]):
        """应用形状的翻译和颜色"""
        try:
            original_text = shape_info['text']
            
            # 查找翻译
            translated_text = translation_map.get(original_text, original_text)
            
            if translated_text != original_text:
                # 设置翻译文本
                shape.setString(translated_text)
                
                # 应用原始颜色格式
                self._apply_colors_to_shape(shape, shape_info)
                
                logger.debug(f"应用翻译和颜色: '{original_text[:30]}...' -> '{translated_text[:30]}...'")
            
        except Exception as e:
            logger.debug(f"应用形状翻译和颜色失败: {e}")
    
    def _apply_colors_to_shape(self, shape, shape_info: Dict[str, Any]):
        """应用颜色到形状"""
        try:
            # 获取文本光标
            cursor = shape.createTextCursor()
            cursor.gotoStart(False)
            cursor.gotoEnd(True)
            
            # 应用第一个段落第一个片段的格式作为整体格式
            if shape_info['paragraphs'] and shape_info['paragraphs'][0]['portions']:
                first_portion = shape_info['paragraphs'][0]['portions'][0]
                colors = first_portion['colors']
                
                # 应用字体颜色
                if 'font_color' in colors:
                    cursor.CharColor = colors['font_color']
                
                # 应用背景色
                if 'background_color' in colors:
                    cursor.CharBackColor = colors['background_color']
                
                # 应用字体属性
                if 'font_name' in colors:
                    cursor.CharFontName = colors['font_name']
                if 'font_size' in colors:
                    cursor.CharHeight = colors['font_size']
                if 'font_weight' in colors:
                    cursor.CharWeight = colors['font_weight']
                if 'font_italic' in colors:
                    cursor.CharPosture = colors['font_italic']
                if 'font_underline' in colors:
                    cursor.CharUnderline = colors['font_underline']
                
                logger.debug("应用颜色格式成功")
            
        except Exception as e:
            logger.debug(f"应用颜色到形状失败: {e}")
    
    def save_and_close(self, output_path: str = None) -> bool:
        """保存并关闭文档"""
        try:
            if self.document:
                if output_path:
                    # 保存到指定路径
                    file_url = uno.systemPathToFileUrl(os.path.abspath(output_path))
                    self.document.storeAsURL(file_url, ())
                else:
                    # 保存到原路径
                    self.document.store()
                
                # 关闭文档
                self.document.close(True)
                self.document = None
                
                logger.info("文档保存并关闭成功")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"保存文档失败: {e}")
            return False
    
    def cleanup(self):
        """清理资源"""
        try:
            # 关闭文档
            if self.document:
                try:
                    self.document.close(True)
                except:
                    pass
                self.document = None

            # 清理桌面对象
            if self.desktop:
                try:
                    # 尝试退出LibreOffice
                    self.desktop.terminate()
                except:
                    pass
                self.desktop = None

            # 清理上下文
            if self.context:
                self.context = None

            # 终止进程
            if self.soffice_process:
                try:
                    # 首先尝试正常终止
                    self.soffice_process.terminate()
                    try:
                        self.soffice_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        # 如果正常终止失败，强制杀死进程
                        logger.warning("正常终止超时，强制杀死LibreOffice进程")
                        self.soffice_process.kill()
                        self.soffice_process.wait(timeout=3)
                except Exception as e:
                    logger.debug(f"终止进程时出错: {e}")
                finally:
                    self.soffice_process = None

            logger.info("LibreOffice UNO资源清理完成")

        except Exception as e:
            logger.debug(f"清理资源时出错: {e}")


def translate_ppt_with_uno_color_preservation(ppt_path: str, translation_map: Dict[str, str], output_path: str = None) -> bool:
    """
    使用LibreOffice UNO接口翻译PPT并保持颜色一致
    
    Args:
        ppt_path: 输入PPT文件路径
        translation_map: 翻译映射字典 {原文: 译文}
        output_path: 输出PPT文件路径（可选）
        
    Returns:
        bool: 处理是否成功
    """
    if not UNO_AVAILABLE:
        logger.error("LibreOffice UNO接口不可用")
        return False
    
    manager = LibreOfficeUNOColorManager()
    
    try:
        # 启动LibreOffice服务
        if not manager.start_libreoffice_service():
            return False
        
        # 打开PPT文件
        if not manager.open_presentation(ppt_path):
            return False
        
        # 提取颜色信息
        logger.info("提取原始颜色信息...")
        color_map = manager.extract_text_colors()
        
        if not color_map:
            logger.warning("未提取到颜色信息")
            return False
        
        # 应用翻译和颜色
        logger.info("应用翻译并保持颜色...")
        success = manager.apply_text_colors(color_map, translation_map)
        
        if success:
            # 保存文档
            save_path = output_path or ppt_path
            if manager.save_and_close(save_path):
                logger.info(f"  UNO颜色保护翻译完成: {save_path}")
                return True
        
        return False
        
    except Exception as e:
        logger.error(f"UNO颜色保护翻译失败: {e}")
        return False
    finally:
        manager.cleanup()


def test_uno_color_preservation():
    """测试UNO颜色保护功能"""
    if not UNO_AVAILABLE:
        print("❌ LibreOffice UNO接口不可用，请安装LibreOffice Python SDK")
        return False
    
    print("🔧 测试LibreOffice UNO颜色保护功能...")
    
    # 这里可以添加测试代码
    manager = LibreOfficeUNOColorManager()
    
    try:
        if manager.start_libreoffice_service():
            print("  LibreOffice UNO服务启动成功")
            return True
        else:
            print("❌ LibreOffice UNO服务启动失败")
            return False
    finally:
        manager.cleanup()


if __name__ == "__main__":
    test_uno_color_preservation()
