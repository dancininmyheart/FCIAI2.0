from pathlib import Path
import re

text = Path('original_main.py').read_text(encoding='utf-16')

# 1. Update timestamp formats
text = text.replace("datetime.now().strftime('%Y%m%d_%H%M%S')", "datetime.now().strftime('%Y%m%d_%H%M%S_%f')")

# 2. Update zip filename naming
text = text.replace('zip_filename = f"mineru_result_{task_id}.zip"', 'zip_filename = f"{timestamp}_mineru_result_{task_id}.zip"')

# 3. Replace download_translated_pdf function
pattern_download = r"@main.route\('/download_translated_pdf/<filename>'\)\r?\n@login_required\r?\ndef download_translated_pdf\(filename\):\r?\n(?:    .*(?:\r?\n))+?    except Exception as e:\r?\n        logger.error\(f\"下载文件时出错: {e}\"\)\r?\n        import traceback\r?\n        logger.error\(f\"错误详情: {traceback.format_exc\(\)}\"\)\r?\n        return jsonify\({'success': False, 'error': f'下载文件时出错: {str\(e\)}'}\), 500\r?\n"
new_download = """@main.route('/download_translated_pdf/<filename>')
@login_required
def download_translated_pdf(filename):
    \"\"\"下载翻译后的PDF文件（实际上是Word文档）\"\"\"
    try:
        if not filename:
            logger.error(\"下载请求缺少文件名\")
            return jsonify({'success': False, 'error': '文件名无效'}), 400

        logger.info(f\"用户 {current_user.username} 请求下载文件: {filename}\")

        from werkzeug.utils import secure_filename
        filename = secure_filename(filename)
        logger.info(f\"安全文件名: {filename}\")

        project_root = (os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        upload_folder = current_app.config['UPLOAD_FOLDER']
        if not os.path.isabs(upload_folder):
            upload_folder = os.path.join(project_root, upload_folder)

        pdf_output_dir = os.path.join(upload_folder, 'pdf_outputs')
        file_path = os.path.join(pdf_output_dir, filename)

        logger.info(f\"项目根目录: {project_root}\")
        logger.info(f\"上传文件夹配置: {current_app.config['UPLOAD_FOLDER']}\")
        logger.info(f\"实际上传文件夹路径: {upload_folder}\")
        logger.info(f\"PDF输出目录: {pdf_output_dir}\")
        logger.info(f\"期望的文件路径: {file_path}\")
        logger.info(f\"文件绝对路径: {os.path.abspath(file_path)}\")

        if not os.path.exists(pdf_output_dir):
            logger.error(f\"PDF输出目录不存在: {pdf_output_dir}\")
            os.makedirs(pdf_output_dir, exist_ok=True)
            logger.info(f\"已创建PDF输出目录: {pdf_output_dir}\")

        if not os.path.isfile(file_path):
            logger.error(f\"请求的文件不存在或已被清理: {file_path}\")
            logger.error(f\"文件绝对路径: {os.path.abspath(file_path)}\")
            if os.path.exists(pdf_output_dir):
                files_in_dir = os.listdir(pdf_output_dir)
                logger.info(f\"当前目录文件列表: {files_in_dir}\")
            return jsonify({'success': False, 'error': '文件不存在或已被清理'}), 404

        if not filename.endswith('.docx'):
            logger.warning(f\"请求的文件扩展名不正确: {filename}\")
            if not filename.endswith('.docx'):
                filename += '.docx'

        logger.info(f\"准备返回文件给用户: {file_path}\")
        logger.info(f\"文件大小: {os.path.getsize(file_path)} 字节\")
        logger.info(f\"文件绝对路径: {os.path.abspath(file_path)}\")

        absolute_file_path = os.path.abspath(file_path)
        if os.path.exists(absolute_file_path):
            logger.info(f\"使用绝对路径发送文件: {absolute_file_path}\")
            return send_file(absolute_file_path, as_attachment=True, download_name=filename)
        else:
            logger.error(f\"绝对路径文件也不存在: {absolute_file_path}\")
            return jsonify({'success': False, 'error': '文件不存在或已被清理'}), 404

    except Exception as e:
        logger.error(f\"下载文件时出错: {e}\")
        import traceback
        logger.error(f\"错误详情: {traceback.format_exc()}\")
        return jsonify({'success': False, 'error': f'下载文件时出错: {str(e)}'}), 500
"""
text = re.sub(pattern_download, new_download, text, count=1, flags=re.DOTALL)

old_exists_line = "            file_exists = os.path.exists(os.path.join(record.file_path, record.stored_filename))"
new_trans_block = """            # 检查文件是否仍然存在
            stored_filename = getattr(record, 'stored_filename', None)
            if not stored_filename:
                logger.warning(f\"[Translation History] 记录缺少 stored_filename: id={record.id}\")
                upload_time = datetime_to_isoformat(record.upload_time)
                history_records.append({
                    'id': record.id,
                    'filename': record.filename,
                    'stored_filename': None,
                    'file_size': record.file_size,
                    'upload_time': upload_time,
                    'status': record.status,
                    'file_exists': False
                })
                continue

            file_path = os.path.join(record.file_path, stored_filename)
            file_exists = os.path.exists(file_path)"""
text = text.replace(old_exists_line, new_trans_block, 1)

new_pdf_block = """            # 检查文件是否仍然存在
            stored_filename = getattr(record, 'stored_filename', None)
            if not stored_filename:
                logger.warning(f\"[PDF History] 记录缺少 stored_filename: id={record.id}\")
                upload_time = datetime_to_isoformat(record.upload_time)
                history_records.append({
                    'id': record.id,
                    'filename': record.filename,
                    'stored_filename': None,
                    'file_size': record.file_size,
                    'upload_time': upload_time,
                    'status': record.status,
                    'file_exists': False
                })
                continue

            file_path = os.path.join(record.file_path, stored_filename)
            file_exists = os.path.exists(file_path)"""
text = text.replace(old_exists_line, new_pdf_block, 1)

text = text.replace("potential_file_path = os.path.join(pdf_output_dir, record.stored_filename)", "potential_file_path = os.path.join(pdf_output_dir, stored_filename)")
text = text.replace("'stored_filename': getattr(record, 'stored_filename', None)", "'stored_filename': stored_filename")

Path('app/views/main.py').write_text(text, encoding='utf-8')
