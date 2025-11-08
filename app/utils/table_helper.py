
def add_html_table_to_doc(document, html_table: str) -> bool:
    """
    将HTML表格转换为Word表格并添加到文档

    Args:
        document: docx文档对象
        html_table: HTML格式的表格字符串

    Returns:
        bool: 是否成功添加表格
    """
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_table, 'html.parser')
        table = soup.find('table')

        if table:
            # 获取所有行
            rows = table.find_all('tr')
            if rows:
                # 计算最大列数
                max_cols = 0
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    max_cols = max(max_cols, len(cells))

                # 创建Word表格
                word_table = document.add_table(rows=len(rows), cols=max_cols)
                word_table.style = 'Table Grid'

                # 填充表格内容
                for i, row in enumerate(rows):
                    cells = row.find_all(['td', 'th'])
                    for j, cell in enumerate(cells):
                        # 清理单元格文本
                        cell_text = cell.get_text().strip()
                        word_table.cell(i, j).text = cell_text

                logger = logging.getLogger(__name__)
                logger.info(f"成功添加HTML表格，行数: {len(rows)}, 列数: {max_cols}")
                return True

        # 如果没有找到表格，返回失败
        logger = logging.getLogger(__name__)
        logger.warning("未在HTML中找到有效表格")
        return False
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"添加HTML表格失败: {e}")
        return False
