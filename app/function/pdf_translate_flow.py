# 添加详细的OCR结果日志
for i, result in enumerate(image_ocr_results):
    logger.info(f"[PDF OCR] 图片 {i+1}:")
    logger.info(f"  - 路径: {result.get('image_path', '未知')}")
    logger.info(f"  - OCR成功: {result.get('success', False)}")
    logger.info(f"  - OCR文本长度: {len(result.get('ocr_text_combined', ''))}")
    logger.info(f"  - 翻译文本长度: {len(result.get('translation_text_combined', ''))}")
    logger.info(f"  - OCR文本内容: {result.get('ocr_text_combined', '')[:100]}...")
    logger.info(f"  - 翻译文本内容: {result.get('translation_text_combined', '')[:100]}...")
# 将OCR结果添加到文档内容中
if image_ocr_results:
    logger.info(f"[PDF OCR] 开始将OCR结果添加到文档内容中")
    ocr_section = "\n\n# 图片OCR识别结果\n\n"
    for i, result in enumerate(image_ocr_results):
        if result.get("success") and result.get("ocr_text_combined"):
            image_path = result.get("image_path", "未知图片")
            ocr_text = result.get("ocr_text_combined", "").strip()
            translation_text = result.get("translation_text_combined", "").strip()
            
            # 只有当OCR文本不为空且不为0时才显示结果
            if ocr_text and ocr_text != "0":
                ocr_section += f"## 图片 {i+1}: {os.path.basename(image_path)}\n\n"
                ocr_section += f"**OCR识别结果:**\n\n{ocr_text}\n\n"
                # 只有当翻译文本不为空且不为0时才显示翻译结果
                if translation_text and translation_text != "0" and translation_text != ocr_text:
                    ocr_section += f"**翻译结果:**\n\n{translation_text}\n\n"
            ocr_section += "---\n\n"
    
    # 在文档末尾添加OCR结果
    document_content += ocr_section
    logger.info(f"[PDF OCR] OCR结果已添加到文档内容中，新增内容长度: {len(ocr_section)} 字符")
else:
    logger.info("[PDF OCR] 没有OCR结果需要添加到文档中")