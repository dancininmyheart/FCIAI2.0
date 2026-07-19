#!/usr/bin/env python3
"""
文档生成器模块
用于创建双语Word文档，包含原文和译文的对照显示
"""

import os
import logging
from typing import List, Dict, Tuple
from docx import Document
from docx.shared import RGBColor, Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.shared import qn
from docx.enum.style import WD_STYLE_TYPE
from bs4 import BeautifulSoup

from app.translation.providers import default_provider_registry
from app.translation.service import DocumentTranslationService, current_translation_memory, current_translation_settings
from app.translation.types import ProviderError, ProviderRequest, TranslationProvider
from app.translation.units import PdfTextBlock, build_pdf_units

logger = logging.getLogger(__name__)


class BilingualDocumentGenerator:
    """
    双语文档生成器
    支持创建包含原文和译文对照的Word文档
    """
    
    def __init__(self):
        """初始化文档生成器"""
        self.document = Document()
        self._setup_styles()
    
    def _setup_styles(self):
        """设置文档样式"""
        # 设置默认字体
        style = self.document.styles['Normal']
        font = style.font
        font.name = '宋体'
        font._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
        font.size = Pt(12)
        
        # 设置标题样式
        title_style = self.document.styles['Heading 1']
        title_font = title_style.font
        title_font.name = '黑体'
        title_font._element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')
        title_font.size = Pt(16)
        title_font.bold = True
        
        # 设置二级标题样式
        heading2_style = self.document.styles['Heading 2']
        heading2_font = heading2_style.font
        heading2_font.name = '黑体'
        heading2_font._element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')
        heading2_font.size = Pt(14)
        
    def add_heading(self, text: str, level: int = 1) -> None:
        """
        添加标题
        
        Args:
            text: 标题文本
            level: 标题级别 (1-6)
        """
        try:
            # 清理Markdown符号
            cleaned_text = self._strip_inline_markdown(text.strip())
            heading = self.document.add_heading(cleaned_text, level=level)
            # 设置中文字体
            for run in heading.runs:
                run.font.name = '黑体'
                run._element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')
            logger.info(f"添加标题: {cleaned_text}")
        except Exception as e:
            logger.error(f"添加标题失败: {e}")
            # 降级处理
            self.add_original_text(text)
    
    def add_original_text(self, text: str) -> None:
        """
        添加原文段落
        
        Args:
            text: 原文文本
        """
        if not text.strip():
            self.document.add_paragraph()
            return
            
        try:
            # 检测是否是HTML表格
            if '<table' in text and '</table>' in text:
                # 使用BeautifulSoup解析HTML表格
                soup = BeautifulSoup(text, 'html.parser')
                table = soup.find('table')
                
                if table:
                    # 获取表格的行和列
                    rows = table.find_all('tr')
                    max_cols = 0
                    cell_contents = []
                    
                    # 提取所有单元格内容
                    for row in rows:
                        cells = row.find_all(['td', 'th'])
                        max_cols = max(max_cols, len(cells))
                        row_contents = []
                        for cell in cells:
                            # 清理单元格文本
                            cell_text = self._strip_inline_markdown(cell.get_text().strip())
                            row_contents.append(cell_text)
                        cell_contents.append(row_contents)
                    
                    # 创建原文表格
                    word_table = self.document.add_table(rows=len(rows), cols=max_cols)
                    word_table.style = 'Table Grid'
                    
                    # 填充原文表格内容
                    for i, row_content in enumerate(cell_contents):
                        for j, cell_text in enumerate(row_content):
                            cell = word_table.cell(i, j)
                            cell.text = cell_text
                            # 设置单元格格式
                            paragraphs = cell.paragraphs
                            if paragraphs:
                                for paragraph in paragraphs:
                                    for run in paragraph.runs:
                                        run.font.color.rgb = RGBColor(0, 0, 0)
                    
                    # 添加一个空行分隔
                    self.document.add_paragraph()
                    return
                else:
                    # 如果表格解析失败，降级为普通文本
                    self.document.add_paragraph(text.strip())
                    return
                
            # 清理Markdown符号
            cleaned_text = self._strip_inline_markdown(text.strip())
            paragraph = self.document.add_paragraph()
            run = paragraph.add_run(cleaned_text)
            # 原文使用黑色字体
            run.font.color.rgb = RGBColor(0, 0, 0)
            logger.info(f"添加原文: {cleaned_text[:50]}...")
        except Exception as e:
            logger.error(f"添加原文失败: {e}")
            self.document.add_paragraph(text.strip())
    
    def add_translated_text(self, text: str) -> None:
        """
        添加译文段落
        
        Args:
            text: 译文文本
        """
        if not text.strip():
            return
            
        try:
            # 清理Markdown符号
            cleaned_text = self._strip_inline_markdown(text.strip())
            paragraph = self.document.add_paragraph()
            run = paragraph.add_run(cleaned_text)
            # 译文使用灰色字体以便区分，统一不使用斜体，保证风格一致
            run.font.color.rgb = RGBColor(96, 96, 96)
            run.italic = False
            
            # 设置段落格式
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
            paragraph.paragraph_format.space_before = Pt(6)
            paragraph.paragraph_format.space_after = Pt(12)
            
            logger.info(f"添加译文: {cleaned_text[:50]}...")
        except Exception as e:
            logger.error(f"添加译文失败: {e}")
            paragraph = self.document.add_paragraph()
            run = paragraph.add_run(text.strip())
            run.font.color.rgb = RGBColor(128, 128, 128)
    
    def add_bilingual_pair(self, original: str, translated: str) -> None:
        """
        添加原文和译文对
        
        Args:
            original: 原文
            translated: 译文
        """
        self.add_original_text(original)
        if translated and not translated.startswith('[翻译错误:') and translated.strip():
            self.add_translated_text(translated)
        self.document.add_paragraph()  # 添加空行分隔
    
    def add_list_item(self, text: str, numbered: bool = False) -> None:
        """
        添加列表项
        
        Args:
            text: 列表项文本
            numbered: 是否为有序列表
        """
        try:
            # 清理Markdown符号
            cleaned_text = self._strip_inline_markdown(text.strip())
            if numbered:
                self.document.add_paragraph(cleaned_text, style='ListNumber')
            else:
                self.document.add_paragraph(cleaned_text, style='ListBullet')
        except Exception as e:
            logger.warning(f"添加列表项失败，使用普通段落: {e}")
            self.add_original_text(text)
    
    def add_bilingual_table(
        self,
        html_table: str,
        source_language: str = "en",
        target_language: str = "zh",
        custom_translations: Dict[str, str] = None,
        provider_model: str = "qwen",
        provider: TranslationProvider | None = None,
    ) -> None:
        """
        将HTML表格转换为双语Word表格并添加到文档
        会创建两个表格：原文表格和译文表格

        Args:
            html_table: HTML格式的表格字符串
            source_language: 源语言代码
            target_language: 目标语言代码
            custom_translations: 自定义翻译字典
        """
        try:
            soup = BeautifulSoup(html_table, 'html.parser')
            table = soup.find('table')
            
            if table:
                # 获取所有行
                rows = table.find_all('tr')
                if rows:
                    # 计算最大列数和提取单元格内容
                    max_cols = 0
                    cell_contents = []  # 原文内容
                    translated_contents = []  # 译文内容
                    translation_cache = {}  # 翻译缓存
                    
                    for row in rows:
                        cells = row.find_all(['td', 'th'])
                        max_cols = max(max_cols, len(cells))
                        row_contents = []
                        row_translations = []
                        
                        for cell in cells:
                            # 清理单元格文本
                            cell_text = self._strip_inline_markdown(cell.get_text().strip())
                            row_contents.append(cell_text)
                            
                            # 获取翻译
                            if cell_text in translation_cache:
                                translated_text = translation_cache[cell_text]
                            else:
                                translated_text = _sync_translate_single_text(
                                    cell_text,
                                     source_language=source_language,
                                     target_language=target_language,
                                     custom_translations=custom_translations,
                                     provider_model=provider_model,
                                     provider=provider,
                                 )
                                translation_cache[cell_text] = translated_text
                            
                            row_translations.append(translated_text if translated_text else cell_text)
                        
                        cell_contents.append(row_contents)
                        translated_contents.append(row_translations)
                    
                    # 创建并填充原文表格
                    word_table = self.document.add_table(rows=len(rows), cols=max_cols)
                    word_table.style = 'Table Grid'
                    
                    for i, row_content in enumerate(cell_contents):
                        for j, cell_text in enumerate(row_content):
                            cell = word_table.cell(i, j)
                            cell.text = cell_text
                            # 设置单元格格式
                            for paragraph in cell.paragraphs:
                                for run in paragraph.runs:
                                    run.font.color.rgb = RGBColor(0, 0, 0)
                    
                    # 添加一个空行分隔
                    self.document.add_paragraph()
                    
                    # 创建并填充译文表格
                    trans_table = self.document.add_table(rows=len(rows), cols=max_cols)
                    trans_table.style = 'Table Grid'
                    
                    for i, row_translations in enumerate(translated_contents):
                        for j, trans_text in enumerate(row_translations):
                            cell = trans_table.cell(i, j)
                            cell.text = trans_text
                            # 设置单元格格式
                            for paragraph in cell.paragraphs:
                                for run in paragraph.runs:
                                    run.font.color.rgb = RGBColor(96, 96, 96)
                    
                    logger.info(f"成功添加双语HTML表格，行数: {len(rows)}, 列数: {max_cols}")
                    return
            
            # 如果没有找到表格，降级处理为普通文本
            logger.warning("未在HTML中找到有效表格，作为普通文本处理")
            self.add_original_text(html_table)
        except Exception as e:
            logger.error(f"添加HTML表格失败: {e}")
            # 降级处理，将HTML作为普通文本添加
            self.add_original_text(html_table)

    def add_image(self, image_path: str, width_inches: float = 6.0) -> None:
        """
        添加图片到文档
        
        Args:
            image_path: 图片路径
            width_inches: 图片宽度（英寸）
        """
        try:
            if os.path.exists(image_path):
                from docx.shared import Inches
                self.document.add_picture(image_path, width=Inches(width_inches))
                logger.info(f"添加图片: {image_path}")
            else:
                logger.warning(f"图片文件不存在: {image_path}")
        except Exception as e:
            logger.error(f"添加图片失败: {e}")
    
    def save(self, file_path: str) -> bool:
        """
        保存文档
        
        Args:
            file_path: 保存路径
            
        Returns:
            bool: 是否保存成功
        """
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # 保存文档
            self.document.save(file_path)
            logger.info(f"文档保存成功: {file_path}")
            return True
        except Exception as e:
            logger.error(f"保存文档失败: {e}")
            return False

    @staticmethod
    def _strip_inline_markdown(text: str) -> str:
        """
        移除常见的 Markdown 行内语法，避免原样进入 Word：
        - 粗体/斜体: **text**, __text__, *text*, _text_
        - 行内代码: `code`
        - 链接: [text](url) -> text
        - 图片标记: ![alt](path) -> alt
        - 引用残留的转义符号
        """
        try:
            import re
            original_text = text or ""
            s = original_text
            
            # 图片: ![alt](path) -> alt
            s = re.sub(r"!\[([^\]]*)\]\([^\)]*\)", r"\1", s)
            # 链接: [text](url) -> text
            s = re.sub(r"\[([^\]]+)\]\([^\)]*\)", r"\1", s)
            # 粗体/斜体包裹: **text** 或 __text__ 或 *text* 或 _text_
            s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
            s = re.sub(r"__([^_]+)__", r"\1", s)
            s = re.sub(r"\*([^*]+)\*", r"\1", s)
            s = re.sub(r"_([^_]+)_", r"\1", s)
            # 行内代码: `code`
            s = re.sub(r"`([^`]+)`", r"\1", s)
            # 数学: $...$ / \( ... \) / \[ ... \] -> 去除包裹符，只保留内部内容
            s = re.sub(r"\$\s*([^$]+?)\s*\$", r"\1", s)
            s = re.sub(r"\\\(\s*([^)]*?)\s*\\\)", r"\1", s)
            s = re.sub(r"\\\[\s*([^]]*?)\s*\\\]", r"\1", s)
            # 常见 LaTeX 语法清理: ^{...} / _{...} 去掉标记，保留内容
            s = re.sub(r"\^\s*\{\s*([^}]*)\s*\}", r"\1", s)
            s = re.sub(r"_\s*\{\s*([^}]*)\s*\}", r"\1", s)
            # 特定数学符号替换: 改进对 \prime、\cdot、\mathsf 等命令的处理
            # 处理带空格的命令，如 { \prime } 和 { \cdot }
            s = re.sub(r"\\prime\s*", "′", s)  # 将 \prime 替换为 Unicode 撇号
            s = re.sub(r"\{\s*\\prime\s*\}", "′", s)  # 将 { \prime } 替换为 Unicode 撇号
            s = re.sub(r"\\cdot\s*", "·", s)   # 将 \cdot 替换为 Unicode 中点
            s = re.sub(r"\{\s*\\cdot\s*\}", "·", s)   # 将 { \cdot } 替换为 Unicode 中点
            s = re.sub(r"\\times\s*", "×", s)  # 将 \times 替换为 Unicode 乘号
            s = re.sub(r"\\leq\s*", "≤", s)    # 将 \leq 替换为 Unicode 小于等于号
            s = re.sub(r"\\geq\s*", "≥", s)    # 将 \geq 替换为 Unicode 大于等于号
            s = re.sub(r"\\mathsf\s*\{?\s*([^}]*)\s*\}?", r"\1", s)  # 处理 \mathsf{L} 等格式
            s = re.sub(r"\\mathrm\s*\{?\s*([^}]*)\s*\}?", r"\1", s)  # 处理 \mathrm{R} 等格式
            # 处理更复杂的带空格花括号情况
            s = re.sub(r"\{\s*′\s*\}", "′", s)   # 将 { ′ } 替换为 ′
            s = re.sub(r"\{\s*·\s*\}", "·", s)   # 将 { · } 替换为 ·
            # 处理单独的 ^ 和 _ 符号
            s = re.sub(r"\^\s*", "", s)  # 去除单独的 ^ 符号
            s = re.sub(r"_\s*", "", s)   # 去除单独的 _ 符号
            # 特别处理百分号前的反斜杠，如30 \%
            s = re.sub(r"\\%", "%", s)
            # 处理商标符号 @ -> ®
            s = s.replace('@', '®')
            # 去除多余的反斜杠和花括号空格
            s = s.replace("\\{", "{").replace("\\}", "}").replace("\\ ", " ")
            # 规范连字符与空格: 避免 ' - ' 残留空格
            s = re.sub(r"\s*-\s*", "-", s)
            # 折叠多空格
            s = re.sub(r"\s+", " ", s).strip()
            # 剩余的转义反斜杠
            s = s.replace("\\*", "*").replace("\\_", "_").replace("\\#", "#").replace("\\`", "`")
            
            # 记录文本清理操作
            if s != original_text:
                logger.debug(f"文本清理完成: '{original_text[:30]}...' -> '{s[:30]}...'")
            
            return s
        except Exception as e:
            logger.error(f"文本清理过程中出错: {e}")
            return text or ""


def create_bilingual_word_document(
    content_lines: List[str], 
    translation_dict: Dict[str, str],
    output_path: str
) -> bool:
    """
    创建双语Word文档
    
    Args:
        content_lines: 原始内容行列表
        translation_dict: 翻译字典 {原文: 译文}
        output_path: 输出文件路径
        
    Returns:
        bool: 是否创建成功
    """
    try:
        generator = BilingualDocumentGenerator()
        
        i = 0
        while i < len(content_lines):
            line = content_lines[i].strip()
            
            if not line:
                generator.document.add_paragraph()
                i += 1
                continue
            
            # 处理标题 (# 开头)
            if line.startswith('#'):
                # 计算标题级别
                level = 1
                for char in line:
                    if char == '#':
                        level += 1
                    else:
                        break
                level = min(level, 6)  # 最多支持6级标题
                
                # 提取标题文本
                title_text = line.lstrip('# ').strip()
                generator.add_heading(title_text, level)
                
                # 检查下一行是否为译文
                if i + 1 < len(content_lines):
                    next_line = content_lines[i + 1].strip()
                    if next_line.startswith('【译文】'):
                        translated_text = next_line[5:].strip()  # 去掉"【译文】"前缀
                        generator.add_translated_text(translated_text)
                        i += 2  # 跳过标题和译文行
                        continue
                
                i += 1
                continue
            
            # 处理无序列表 (* 或 - 开头)
            if line.startswith('* ') or line.startswith('- '):
                list_text = line[2:].strip()
                generator.add_list_item(list_text, numbered=False)
                
                # 检查下一行是否为译文
                if i + 1 < len(content_lines):
                    next_line = content_lines[i + 1].strip()
                    if next_line.startswith('【译文】'):
                        translated_text = next_line[5:].strip()
                        generator.add_translated_text(translated_text)
                        i += 2  # 跳过列表项和译文行
                        continue
                
                i += 1
                continue
            
            # 处理有序列表 (数字. 开头)
            if line.startswith(tuple(f"{n}. " for n in range(1, 100))):  # 支持1-99的编号
                dot_index = line.find('. ')
                if dot_index > 0:
                    list_text = line[dot_index + 2:].strip()
                    generator.add_list_item(list_text, numbered=True)
                    
                    # 检查下一行是否为译文
                    if i + 1 < len(content_lines):
                        next_line = content_lines[i + 1].strip()
                        if next_line.startswith('【译文】'):
                            translated_text = next_line[5:].strip()
                            generator.add_translated_text(translated_text)
                            i += 2  # 跳过列表项和译文行
                            continue
                    
                    i += 1
                    continue
            
            # 处理译文标记行
            if line.startswith('【译文】'):
                # 这种情况理论上不应该出现，因为我们会在添加原文时处理对应的译文
                translated_text = line[5:].strip()
                generator.add_translated_text(translated_text)
                i += 1
                continue
            
            # 处理普通段落
            original_text = line
            translated_text = ""
            
            # 尝试查找翻译
            if original_text in translation_dict:
                translated_text = translation_dict[original_text]
            else:
                # 使用我们之前实现的模糊匹配逻辑
                for key, value in translation_dict.items():
                    if (original_text.strip() in key.strip() or 
                        key.strip() in original_text.strip()):
                        translated_text = value
                        break
            
            generator.add_bilingual_pair(original_text, translated_text)
            i += 1
        
        # 保存文档
        return generator.save(output_path)
        
    except Exception as e:
        logger.error(f"创建双语Word文档失败: {e}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")
        return False


def process_markdown_to_bilingual_doc(
    markdown_content: str,
    translation_dict: Dict[str, str],
    output_path: str
) -> bool:
    """
    将Markdown内容处理为双语Word文档
    
    Args:
        markdown_content: Markdown格式的内容
        translation_dict: 翻译字典 {原文: 译文}
        output_path: 输出文件路径
        
    Returns:
        bool: 是否处理成功
    """
    try:
        # 按行分割内容
        content_lines = markdown_content.split('\n')
        
        # 创建双语文档
        success = create_bilingual_word_document(content_lines, translation_dict, output_path)
        
        if success:
            logger.info(f"成功创建双语Word文档: {output_path}")
        else:
            logger.error("创建双语Word文档失败")
            
        return success
        
    except Exception as e:
        logger.error(f"处理Markdown到双语文档失败: {e}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")
        return False


def _sync_translate_single_text(text: str,
                                source_language: str = "en",
                                target_language: str = "zh",
                                custom_translations: Dict[str, str] = None,
                                provider_model: str = "qwen",
                                provider: TranslationProvider | None = None) -> str:
    """
    使用指定 provider 对单条文本进行同步翻译，返回纯文本译文。

    若翻译不可用或失败，返回空字符串以便调用方降级处理。
    """
    if not text or not text.strip():
        return ""
    try:
        selected = provider or default_provider_registry().resolve(provider_model)
        result = selected.translate(
            ProviderRequest.create(
                text=text.strip(),
                field="general",
                custom_translations=custom_translations,
                source_language=source_language,
                target_language=target_language,
                output_format="plain",
            ),
        )
        return result.text.strip()
    except ProviderError as error:
        logger.warning("PDF text translation failed provider=%s code=%s", error.provider, error.code)
        return ""


def translate_markdown_to_bilingual_doc(
    markdown_content: str,
    output_path: str,
    source_language: str = "en",
    target_language: str = "zh",
    image_base_dir: str | None = None,
    custom_translations: Dict[str, str] = None,
    image_ocr_results: list[dict] | None = None,
    provider_model: str = "qwen",
    provider: TranslationProvider | None = None,
) -> bool:
    """
    将Markdown内容按"标题/段落 → 逐条翻译 → 立即写入Word(原文在前，译文在后)"的方式生成双语Word文档。

    - 标题(`#`级别)写入为对应Heading，然后紧跟译文段落
    - 无序/有序列表项写入列表项，然后紧跟译文段落
    - 普通段落使用 add_bilingual_pair，原文后紧跟译文
    - 空行保持
    
    参数:
        markdown_content: Markdown内容
        output_path: 输出Word文档路径
        source_language: 源语言
        target_language: 目标语言
        image_base_dir: 图片基础目录
        custom_translations: 自定义翻译字典
        image_ocr_results: 图片OCR识别结果列表，每个元素包含：
            - success: bool - OCR是否成功
            - image_path: str - 图片路径
            - ocr_text_combined: str - OCR识别的文本
            - translation_text_combined: str - 翻译后的文本

    若翻译不可用或失败，依然写入原文，译文留空。
    """
    try:
        # 创建图片路径到OCR结果的映射
        ocr_results_map = {}
        if image_ocr_results:
            import os as _os
            for result in image_ocr_results:
                if result.get('success'):
                    img_path = result.get('image_path', '')
                    if img_path:
                        # 使用规范化路径作为key
                        normalized_path = _os.path.normpath(img_path)
                        ocr_results_map[normalized_path] = result
            if ocr_results_map:
                logger.info(f"📊 已加载 {len(ocr_results_map)} 个图片的OCR结果到映射字典")
                logger.info("OCR结果映射中的路径:")
                for idx, (path, result) in enumerate(list(ocr_results_map.items())[:3], 1):
                    logger.info(f"  {idx}. {path}")
                    logger.info(f"     OCR文本长度: {len(result.get('ocr_text_combined', ''))}")
                    logger.info(f"     翻译文本长度: {len(result.get('translation_text_combined', ''))}")
                if len(ocr_results_map) > 3:
                    logger.info(f"  ... 还有 {len(ocr_results_map) - 3} 个图片")
            else:
                logger.warning("⚠️ OCR结果映射字典为空 - 未添加任何图片")
        else:
            logger.info("ℹ️ image_ocr_results参数为None或空列表，跳过OCR结果映射")
        
        generator = BilingualDocumentGenerator()
        if not markdown_content:
            return generator.save(output_path)

        lines = markdown_content.split('\n')

        # 简单的中文检测(用于跳过已是中文的文本)
        def is_mostly_chinese(s: str) -> bool:
            if not s:
                return False
            total = len(s)
            if total == 0:
                return False
            import re
            cjk = len(re.findall(r"[\u4e00-\u9fff]", s))
            return (cjk / total) > 0.5

        # 解析 markdown 为块：标题、列表项、图片、普通段落(合并连续行)
        blocks: list[dict] = []
        i = 0
        while i < len(lines):
            raw_line = lines[i]
            line = (raw_line or "").rstrip('\r')

            # 跳过带有固定译文标记的行
            if line.strip().startswith('【译文】'):
                i += 1
                continue

            # 图片行(只处理整行图片语法): ![alt](path)
            stripped = line.lstrip()
            if stripped.startswith('![') and '](' in stripped and stripped.endswith(')'):
                try:
                    alt_end = stripped.find('](')
                    path = stripped[alt_end+2:-1].strip()
                    blocks.append({'type': 'image', 'path': path, 'alt': stripped[2:alt_end]})
                    i += 1
                    continue
                except Exception:
                    pass

            # 标题
            if stripped.startswith('#'):
                level = 0
                for ch in stripped:
                    if ch == '#':
                        level += 1
                    else:
                        break
                level = max(1, min(level, 6))
                title_text = stripped[level:].strip()
                blocks.append({'type': 'heading', 'level': level, 'text': title_text})
                i += 1
                continue

            # 列表项
            if stripped.startswith('* ') or stripped.startswith('- '):
                item_text = stripped[2:].strip()
                blocks.append({'type': 'ul_item', 'text': item_text})
                i += 1
                continue

            dot_index = stripped.find('. ')
            if dot_index > 0 and stripped[:dot_index].isdigit():
                item_text = stripped[dot_index+2:].strip()
                blocks.append({'type': 'ol_item', 'text': item_text})
                i += 1
                continue

            # 空行 -> 作为段落分隔
            if not line.strip():
                blocks.append({'type': 'blank'})
                i += 1
                continue

            # 合并连续的非空普通文本行为一个段落
            paragraph_lines = [line.strip()]
            j = i + 1
            while j < len(lines):
                nxt = (lines[j] or "").rstrip('\r')
                nxt_stripped = nxt.lstrip()
                if not nxt.strip():
                    break
                if nxt_stripped.startswith('#') or nxt_stripped.startswith('![') or \
                   nxt_stripped.startswith('* ') or nxt_stripped.startswith('- '):
                    break
                di = nxt_stripped.find('. ')
                if di > 0 and nxt_stripped[:di].isdigit():
                    break
                if nxt_stripped.startswith('【译文】'):
                    break
                paragraph_lines.append(nxt.strip())
                j += 1
            merged = ' '.join(paragraph_lines).strip()
            if merged:
                blocks.append({'type': 'paragraph', 'text': merged})
            i = j if j > i else (i + 1)

        selected_provider = provider or default_provider_registry().resolve(provider_model)
        unit_blocks: list[PdfTextBlock] = []
        title_context = ""
        for block_index, block in enumerate(blocks):
            block_type = block.get('type')
            block_text = str(block.get('text', '')).strip()
            if block_type == 'heading':
                title_context = block_text
            if block_type not in ('blank', 'image') and block_text and '<table' not in block_text:
                unit_blocks.append(PdfTextBlock(block_index, block_text, title_context))
        units = build_pdf_units(
            tuple(unit_blocks),
            source_language,
            target_language,
            glossary=custom_translations,
        )
        translated_blocks: dict[int, str] = {}
        if units:
            service = DocumentTranslationService(
                selected_provider,
                provider_model,
                current_translation_settings(),
                current_translation_memory(),
            )
            translated = service.translate(units)
            translated_blocks = {
                int(result.stable_id.rsplit('b', 1)[1]): result.translated_text
                for result in translated.results
            }

        for block_index, blk in enumerate(blocks):
            btype = blk.get('type')
            if btype == 'blank':
                generator.document.add_paragraph()
                continue

            if btype == 'image':
                path = blk.get('path') or ''
                if path:
                    # 如果是相对路径，则基于 image_base_dir 解析
                    final_path = path
                    if image_base_dir and not (path.startswith('http://') or path.startswith('https://') or 
                                               path.startswith('/') or (len(path) > 1 and path[1] == ':')):
                        import os as _os
                        final_path = _os.path.join(image_base_dir, path)
                    
                    # 尝试插入图片
                    image_inserted = False
                    try:
                        logger.info(f"尝试插入图片: {final_path}")
                        if _os.path.exists(final_path):
                            generator.document.add_picture(final_path, width=Inches(6.0))
                            image_inserted = True
                            logger.info(f"  成功插入图片: {final_path}")
                        else:
                            logger.warning(f"⚠️ 图片文件不存在: {final_path}")
                    except Exception as img_error:
                        logger.error(f"❌ 插入图片失败: {final_path}, 错误: {img_error}")
                    
                    # 检查是否有OCR结果并添加到文档
                    if ocr_results_map and image_inserted:
                        normalized_path = _os.path.normpath(final_path)
                        logger.info(f"🔍 查找图片OCR结果...")
                        logger.info(f"   原始路径: {final_path}")
                        logger.info(f"   规范化路径: {normalized_path}")
                        logger.info(f"   映射中有 {len(ocr_results_map)} 个图片")
                        ocr_result = ocr_results_map.get(normalized_path)
                        
                        if ocr_result:
                            logger.info(f"  找到OCR结果！")
                            ocr_text = ocr_result.get('ocr_text_combined', '').strip()
                            translation_text = ocr_result.get('translation_text_combined', '').strip()
                            logger.info(f"   OCR文本: {len(ocr_text)} 字符")
                            logger.info(f"   翻译文本: {len(translation_text)} 字符")
                            
                            if ocr_text or translation_text:
                                # 添加OCR结果的标题
                                generator.document.add_paragraph(
                                    f"【图片文字识别】",
                                    style='Heading 3'
                                )
                                
                                # 添加OCR原文
                                if ocr_text:
                                    ocr_para = generator.document.add_paragraph()
                                    ocr_run = ocr_para.add_run(f"原文: {ocr_text}")
                                    ocr_run.font.size = Pt(10)
                                    ocr_run.font.color.rgb = RGBColor(70, 70, 70)
                                    logger.info(f"    已添加OCR原文到Word ({len(ocr_text)} 字符)")
                                
                                # 添加翻译文本
                                if translation_text:
                                    trans_para = generator.document.add_paragraph()
                                    trans_run = trans_para.add_run(f"译文: {translation_text}")
                                    trans_run.font.size = Pt(10)
                                    trans_run.font.color.rgb = RGBColor(0, 102, 204)
                                    logger.info(f"    已添加OCR译文到Word ({len(translation_text)} 字符)")
                                
                                # 添加分隔线
                                generator.document.add_paragraph("─" * 50)
                                logger.info(f"    OCR结果已完整添加到Word文档")
                            else:
                                logger.warning(f"  ⚠️ OCR文本和翻译都为空")
                        else:
                            logger.warning(f"❌ 未找到匹配的OCR结果")
                            logger.warning(f"   图片文件名: {_os.path.basename(final_path)}")
                            logger.warning(f"   规范化路径: {normalized_path}")
                            if ocr_results_map:
                                logger.warning(f"   映射中的路径示例（前3个）:")
                                for idx, map_path in enumerate(list(ocr_results_map.keys())[:3], 1):
                                    logger.warning(f"     {idx}. {map_path}")
                    elif not image_inserted:
                        logger.warning(f"⚠️ 图片未成功插入，跳过OCR结果处理")
                    elif not ocr_results_map:
                        logger.info(f"ℹ️ 没有OCR结果映射，跳过OCR文本添加")
                continue

            text = blk.get('text', '').strip()
            if not text:
                continue

            # 仅在英翻中场景下跳过已是中文的原文，避免重复译文
            # 当目标语言是中文时，检测原文是否主要是中文，如果是则跳过翻译
            # 注意：不要跳过中文内容，即使是英翻中场景，因为可能用户需要中英对照
            # 注释掉跳过逻辑，确保所有内容都能被翻译并添加到文档中
            # if target_language.lower().startswith('zh') and is_mostly_chinese(text):
            #     generator.add_original_text(text)
            #     continue

            if btype == 'heading':
                level = int(blk.get('level', 1))
                generator.add_heading(text, level)

                # 检查文本语言特性
                is_chinese_content = is_mostly_chinese(text)
                is_target_english = target_language.lower().startswith('en')
                is_target_chinese = target_language.lower().startswith('zh')

                # 检查是否是英文内容（简单检测：包含较多拉丁字母）
                def is_mostly_english(s: str) -> bool:
                    if not s:
                        return False
                    total = len(s)
                    if total == 0:
                        return False
                    import re
                    latin = len(re.findall(r"[a-zA-Z]", s))
                    return (latin / total) > 0.5

                is_english_content = is_mostly_english(text)

                # 根据翻译方向和内容语言决定是否跳过翻译
                should_skip_translation = False
                if is_target_chinese and is_chinese_content:
                    # 英翻中场景，原文已经是中文，跳过翻译
                    should_skip_translation = True
                    logger.info(f"跳过已是中文的标题: {text[:30]}...")
                elif is_target_english and is_english_content:
                    # 中翻英场景，原文已经是英文，跳过翻译
                    should_skip_translation = True
                    logger.info(f"跳过已是英文的标题: {text[:30]}...")

                translated = translated_blocks.get(block_index, "")

                if translated and not should_skip_translation:
                    generator.add_translated_text(translated)
                generator.document.add_paragraph()
                continue

            if btype == 'ul_item':
                generator.add_list_item(text, numbered=False)
                translated = translated_blocks.get(block_index, "")
                if translated:
                    generator.add_translated_text(translated)
                generator.document.add_paragraph()
                continue

            if btype == 'ol_item':
                generator.add_list_item(text, numbered=True)
                translated = translated_blocks.get(block_index, "")
                if translated:
                    generator.add_translated_text(translated)
                generator.document.add_paragraph()
                continue

            # 检测是否是HTML表格
            if '<table' in text and '</table>' in text:
                # 添加双语表格（原文表格和译文表格）
                generator.add_bilingual_table(
                    text,
                    source_language=source_language,
                    target_language=target_language,
                    custom_translations=custom_translations,
                    provider_model=provider_model,
                    provider=provider,
                )
                continue

            # 普通段落
            translated = translated_blocks.get(block_index, "")

            # 检查文本语言特性
            is_chinese_content = is_mostly_chinese(text)
            is_target_english = target_language.lower().startswith('en')
            is_target_chinese = target_language.lower().startswith('zh')

            # 检查是否是英文内容（简单检测：包含较多拉丁字母）
            def is_mostly_english(s: str) -> bool:
                if not s:
                    return False
                total = len(s)
                if total == 0:
                    return False
                import re
                latin = len(re.findall(r"[a-zA-Z]", s))
                return (latin / total) > 0.5

            is_english_content = is_mostly_english(text)

            # 根据翻译方向和内容语言决定是否跳过翻译
            should_skip_translation = False
            if is_target_chinese and is_chinese_content:
                # 英翻中场景，原文已经是中文，跳过翻译
                should_skip_translation = True
                logger.info(f"跳过已是中文的文本: {text[:30]}...")
            elif is_target_english and is_english_content:
                # 中翻英场景，原文已经是英文，跳过翻译
                should_skip_translation = True
                logger.info(f"跳过已是英文的文本: {text[:30]}...")

            if translated and not should_skip_translation:
                # 根据内容和目标语言选择合适的文档格式
                if is_chinese_content and is_target_english:
                    # 中文内容翻译为英文，确保原文在上，译文在下
                    generator.add_original_text(text)  # 添加中文原文
                    generator.add_translated_text(translated)  # 添加英文译文
                elif is_english_content and is_target_chinese:
                    # 英文内容翻译为中文，使用标准双语对格式
                    generator.add_bilingual_pair(text, translated)
                else:
                    # 其他情况，使用标准双语对格式
                    generator.add_bilingual_pair(text, translated)
            else:
                # 跳过翻译或翻译失败，只添加原文
                generator.add_original_text(text)
        return generator.save(output_path)
    except Exception as e:
        logger.error(f"translate_markdown_to_bilingual_doc处理失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
