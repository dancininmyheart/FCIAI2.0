import os
import json
import mimetypes
import tempfile
import zipfile
from datetime import datetime
from urllib.parse import quote  # 用于在生成 URL 时编码中文
from flask import Blueprint, request, jsonify, current_app, send_file, after_this_request
from flask_login import login_required

ingredient = Blueprint('ingredient', __name__)

# 缓存JSON数据
_cached_registration_data = None
_cached_filing_data = None
_cached_combined_data = None
_cache_registration_file_path = None
_cache_filing_file_path = None
_ALLOWED_INGREDIENT_EXTENSIONS = {'.json', '.xlsx', '.xls', '.csv', '.zip', '.rar', '.7z'}
_UPLOAD_STREAM_CHUNK_SIZE = 16 * 1024 * 1024  # 16MB chunks keep memory steady on large uploads

def load_registration_data():
    """加载保健食品注册数据"""
    global _cached_registration_data, _cache_registration_file_path
    json_file_path = os.path.join(current_app.root_path, 'Ingredient_Search', '保健食品注册.json')
    json_file_path = os.path.abspath(json_file_path)
    if _cached_registration_data and _cache_registration_file_path == json_file_path:
        return _cached_registration_data
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            _cached_registration_data = json.load(f)
            _cache_registration_file_path = json_file_path
            return _cached_registration_data
    except Exception as e:
        current_app.logger.error(f"加载注册JSON文件失败: {e}")
        return {}

def load_filing_data():
    """加载保健食品备案数据"""
    global _cached_filing_data, _cache_filing_file_path
    json_file_path = os.path.join(current_app.root_path, 'Ingredient_Search', '保健食品备案.json')
    json_file_path = os.path.abspath(json_file_path)
    if _cached_filing_data and _cache_filing_file_path == json_file_path:
        return _cached_filing_data
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            _cached_filing_data = json.load(f)
            _cache_filing_file_path = json_file_path
            return _cached_filing_data
    except Exception as e:
        current_app.logger.error(f"加载备案JSON文件失败: {e}")
        return {}

def load_both_ingredient_data():
    """加载保健食品注册和备案数据并合并"""
    global _cached_combined_data
    if _cached_combined_data:
        return _cached_combined_data

    registration_data = load_registration_data()
    filing_data = load_filing_data()

    combined_data = {}
    for product_name, product_info in registration_data.items():
        combined_data[product_name] = {**product_info, 'data_source': '注册'}
    for product_name, product_info in filing_data.items():
        if product_name in combined_data:
            product_name = f"{product_name}(备案)"
        combined_data[product_name] = {**product_info, 'data_source': '备案'}

    _cached_combined_data = combined_data
    return combined_data

def _normalize_rel_url_path(p: str) -> str:
    """用于生成URL：把 \→/，去掉 ./ 前缀，不做安全判断（仅用于URL展示）"""
    if not p:
        return p
    p = p.replace('\\', '/')
    while p.startswith('./'):
        p = p[2:]
    return p

def get_image_url(image_path):
    """将本地图片路径转换为可访问的URL（供前端展示）"""
    if not image_path or image_path == '无截图路径':
        return None
    if not os.path.isabs(image_path):
        # 统一为 URL 友好的相对路径，并对中文做编码
        rel_url_path = _normalize_rel_url_path(image_path)
        return f"/ingredient/image/{quote(rel_url_path)}"
    return None

@ingredient.route('/api/ingredient/search', methods=['GET'])
@login_required
def search_ingredient():
    """搜索保健食品成分API"""
    try:
        keyword = request.args.get('keyword', '').strip()
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 12))
        data_source = request.args.get('data_source', 'all')

        if not keyword:
            return jsonify({'success': False, 'message': '请输入搜索关键词'}), 400

        if data_source == 'registration':
            data = {k: {**v, 'data_source': '注册'} for k, v in load_registration_data().items()}
        elif data_source == 'filing':
            data = {k: {**v, 'data_source': '备案'} for k, v in load_filing_data().items()}
        else:
            data = load_both_ingredient_data()

        if not data:
            return jsonify({'success': False, 'message': '数据加载失败'}), 500

        matched_products = []
        for product_name, product_info in data.items():
            ingredients = product_info.get('ingredient', '') or ''
            data_source_label = product_info.get('data_source', '未知')
            if keyword.lower() in ingredients.lower() or keyword.lower() in product_name.lower():
                if ingredients:
                    parts = [ing.strip() for ing in ingredients.split(',')]
                    main_ingredients = parts[:3]
                    main_ingredients_str = "、".join(main_ingredients) + ("等" if len(parts) > 3 else "")
                else:
                    main_ingredients_str = "无成分信息"

                image_path = product_info.get('path', '无截图路径')
                image_url = get_image_url(image_path) if image_path != '无截图路径' else None

                matched_products.append({
                    '产品名称': product_name,
                    '主要成分': main_ingredients_str,
                    '完整成分': ingredients,
                    '截图路径': image_path,
                    '图片URL': image_url,
                    '数据源': data_source_label,
                    'detail_url': product_info.get('detail_url', '')
                })

        total = len(matched_products)
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        paginated_products = matched_products[start_index:end_index]

        return jsonify({
            'success': True,
            'data': paginated_products,
            'pagination': {
                'current_page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': (total + per_page - 1) // per_page
            }
        })
    except Exception as e:
        current_app.logger.error(f"搜索出错: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'搜索出错: {str(e)}'}), 500

def _resolve_safe_path(rel_path: str, base_dir: str) -> str:
    """
    将传入的相对路径规范化为 base_dir 下的绝对路径，并做安全校验。
    兼容反斜杠与 './' 前缀；禁止越权访问（..、绝对路径）。
    """
    rel_path = (rel_path or '').replace('\\', '/')
    while rel_path.startswith('./'):
        rel_path = rel_path[2:]

    rel_path_norm = os.path.normpath(rel_path)

    if os.path.isabs(rel_path_norm) or rel_path_norm.startswith('..'):
        raise ValueError('非法路径')

    full_path = os.path.abspath(os.path.join(base_dir, rel_path_norm))

    base_dir_abs = os.path.abspath(base_dir)
    if not (full_path == base_dir_abs or full_path.startswith(base_dir_abs + os.sep)):
        raise ValueError('非法路径')

    return full_path


def _get_storage_dir() -> str:
    """成分搜索数据文件存储目录"""
    return os.path.join(current_app.root_path, 'Ingredient_Search')

def _save_upload_stream(file_storage, destination_path: str, chunk_size: int = _UPLOAD_STREAM_CHUNK_SIZE) -> int:
    """
    将上传文件流以固定块写入目标路径，避免一次性占用大量内存。

    Args:
        file_storage: Flask FileStorage 对象
        destination_path: 目标文件完整路径
        chunk_size: 单次写盘块大小，默认16MB

    Returns:
        写入的总字节数
    """
    stream = getattr(file_storage, 'stream', None)
    if stream is None:
        raise ValueError('上传数据流不存在')

    if hasattr(stream, 'seek'):
        try:
            stream.seek(0)
        except (OSError, ValueError):
            # 某些流不可回退，忽略即可
            pass

    total_written = 0
    with open(destination_path, 'wb') as dest_fp:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            dest_fp.write(chunk)
            total_written += len(chunk)

    return total_written


def _compute_directory_size(path: str) -> int:
    """计算目录大小"""
    total = 0
    for root, _, files in os.walk(path):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            try:
                total += os.path.getsize(file_path)
            except OSError:
                continue
    return total


def _build_file_info(entry: os.DirEntry, stat_res=None) -> dict:
    """构造统一的文件信息响应"""
    if stat_res is None:
        stat_res = entry.stat()
    rel_path = entry.name
    full_path = getattr(entry, 'path', None) or os.path.join(_get_storage_dir(), rel_path)
    is_directory = entry.is_dir()
    if is_directory:
        size_value = _compute_directory_size(full_path)
    else:
        size_value = stat_res.st_size

    return {
        'name': entry.name,
        'size': size_value,
        'modified_at': datetime.fromtimestamp(stat_res.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
        'relative_path': rel_path,
        'download_url': f"/ingredient/api/ingredient/download?path={quote(rel_path)}&download=1",
        'is_directory': is_directory
    }

@ingredient.route('/image/<path:image_path>')
@login_required
def serve_ingredient_image(image_path):
    """提供成分图片访问（支持子目录与中文文件名）"""
    try:
        base_dir = os.path.join(current_app.root_path, 'Ingredient_Search')
        full_image_path = _resolve_safe_path(image_path, base_dir)

        if not os.path.exists(full_image_path) or not os.path.isfile(full_image_path):
            return jsonify({'error': '图片不存在'}), 404

        return send_file(full_image_path)
    except ValueError:
        return jsonify({'error': '非法路径'}), 400
    except Exception as e:
        current_app.logger.error(f"提供图片出错: {e}", exc_info=True)
        return jsonify({'error': '无法提供图片'}), 500

# —— 下载接口（两种写法都支持）——

@ingredient.route('/api/ingredient/download', methods=['GET'])
@login_required
def download_ingredient_file_qs():
    """下载/预览（QueryString版）：/api/ingredient/download?path=..."""
    try:
        raw = request.args.get('path', '')
        return _download_impl(raw)
    except Exception as e:
        current_app.logger.error(f"下载文件出错: {e}", exc_info=True)
        return jsonify({'error': f'无法下载文件: {str(e)}'}), 500

@ingredient.route('/api/ingredient/download/<path:image_path>', methods=['GET'])
@login_required
def download_ingredient_file(image_path):
    """下载/预览（路径段版，保留兼容）"""
    try:
        return _download_impl(image_path)
    except Exception as e:
        current_app.logger.error(f"下载文件出错: {e}", exc_info=True)
        return jsonify({'error': f'无法下载文件: {str(e)}'}), 500

def _download_impl(rel_path: str):
    """核心下载逻辑：统一安全解析与返回"""
    print(rel_path)
    base_dir = os.path.join(current_app.root_path, 'Ingredient_Search')
    print(base_dir)
    # 统一分隔符 + 去掉 ./ 前缀
    rel_path = (rel_path or '').replace('\\', '/')
    while rel_path.startswith('./'):
        rel_path = rel_path[2:]

    full_path = _resolve_safe_path(rel_path, base_dir)
    print(full_path)
    if not os.path.exists(full_path):
        return jsonify({'error': '文件不存在'}), 404

    if os.path.isdir(full_path):
        return _send_directory_as_zip(full_path)

    if not os.path.isfile(full_path):
        return jsonify({'error': '不支持的路径类型'}), 400

    filename = os.path.basename(full_path)
    guessed_mime, _ = mimetypes.guess_type(full_path)
    download_flag = request.args.get('download', '1') != '0'

    return send_file(
        full_path,
        as_attachment=download_flag,
        download_name=filename,
        mimetype=guessed_mime
    )


def _send_directory_as_zip(directory_path: str):
    """将目录压缩为临时ZIP并返回下载响应"""
    base_name = os.path.basename(directory_path.rstrip(os.sep)) or 'archive'
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    tmp_file_path = tmp_file.name
    tmp_file.close()

    with zipfile.ZipFile(tmp_file_path, 'w', zipfile.ZIP_DEFLATED) as zip_buffer:
        for root, dirs, files in os.walk(directory_path):
            relative_dir = os.path.relpath(root, directory_path)
            if relative_dir == '.':
                arc_root = base_name
            else:
                arc_root = os.path.join(base_name, relative_dir)

            arc_root_posix = arc_root.replace('\\', '/')

            if not files and not dirs:
                zip_buffer.writestr(f"{arc_root_posix}/", '')

            for file_name in files:
                abs_path = os.path.join(root, file_name)
                arcname = f"{arc_root_posix}/{file_name}"
                zip_buffer.write(abs_path, arcname)

    @after_this_request
    def cleanup(response):
        try:
            os.remove(tmp_file_path)
        except OSError:
            pass
        return response

    return send_file(
        tmp_file_path,
        as_attachment=True,
        download_name=f"{base_name}.zip",
        mimetype='application/zip'
    )


@ingredient.route('/api/ingredient/upload-file', methods=['POST'])
@login_required
def upload_ingredient_file():
    """上传用于成分搜索的数据文件"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': '未找到上传文件'}), 400

        file = request.files['file']
        original_name = (file.filename or '').strip()
        if not original_name:
            return jsonify({'success': False, 'message': '文件名不能为空'}), 400

        safe_name = os.path.basename(original_name.replace('\\', '/'))
        if not safe_name or safe_name in {'.', '..'}:
            return jsonify({'success': False, 'message': '非法的文件名'}), 400

        _, ext = os.path.splitext(safe_name)
        ext = ext.lower()
        if ext not in _ALLOWED_INGREDIENT_EXTENSIONS:
            allowed_list = ', '.join(sorted(_ALLOWED_INGREDIENT_EXTENSIONS))
            return jsonify({'success': False, 'message': f'文件类型不被支持，仅允许: {allowed_list}'}), 400

        storage_dir = _get_storage_dir()
        os.makedirs(storage_dir, exist_ok=True)

        target_path = os.path.join(storage_dir, safe_name)
        backup_name = None
        if os.path.exists(target_path):
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            backup_name = f"{safe_name}.{timestamp}.bak"
            os.replace(target_path, os.path.join(storage_dir, backup_name))

        temp_target_path = f"{target_path}.uploading"
        if os.path.exists(temp_target_path):
            os.remove(temp_target_path)

        try:
            bytes_written = _save_upload_stream(file, temp_target_path)
            os.replace(temp_target_path, target_path)
            current_app.logger.info(
                "成分文件上传完成: %s, 大小: %d 字节", safe_name, bytes_written
            )
        except Exception:
            # 清理临时文件并尝试恢复备份
            if os.path.exists(temp_target_path):
                try:
                    os.remove(temp_target_path)
                except OSError:
                    pass

            if backup_name:
                backup_path = os.path.join(storage_dir, backup_name)
                if os.path.exists(backup_path):
                    try:
                        os.replace(backup_path, target_path)
                    except OSError:
                        current_app.logger.warning(
                            "恢复备份文件失败: %s -> %s", backup_path, target_path, exc_info=True
                        )
            raise

        _refresh_cached_data()

        stat_res = os.stat(target_path)
        file_info = {
            'name': safe_name,
            'size': stat_res.st_size,
            'modified_at': datetime.fromtimestamp(stat_res.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            'relative_path': safe_name,
            'download_url': f"/ingredient/api/ingredient/download?path={quote(safe_name)}&download=1",
            'backup': backup_name,
            'is_directory': False
        }

        return jsonify({'success': True, 'message': '文件上传成功', 'data': file_info})

    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.error('上传成分数据文件失败: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': f'文件上传失败: {exc}'}), 500


def _refresh_cached_data():
    """刷新内存缓存，确保最新文件立即生效"""
    global _cached_registration_data, _cached_filing_data, _cached_combined_data
    global _cache_registration_file_path, _cache_filing_file_path
    _cached_registration_data = None
    _cached_filing_data = None
    _cached_combined_data = None
    _cache_registration_file_path = None
    _cache_filing_file_path = None


@ingredient.route('/api/ingredient/files', methods=['GET'])
@login_required
def list_ingredient_files():
    """列出当前成分搜索目录下的数据文件"""
    try:
        storage_dir = _get_storage_dir()
        if not os.path.exists(storage_dir):
            return jsonify({'success': True, 'data': []})

        file_items = []
        with os.scandir(storage_dir) as it:
            for entry in it:
                stat_res = entry.stat()
                info = _build_file_info(entry, stat_res)
                info['_modified_ts'] = stat_res.st_mtime
                file_items.append(info)

        file_items.sort(key=lambda x: x['_modified_ts'], reverse=True)
        for item in file_items:
            item.pop('_modified_ts', None)

        return jsonify({'success': True, 'data': file_items})
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.error('读取成分数据文件列表失败: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': f'获取文件列表失败: {exc}'}), 500
