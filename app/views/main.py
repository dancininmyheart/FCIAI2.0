import time
import json

import pytz


from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, send_from_directory, \
    jsonify, session, send_file, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy.exc import SQLAlchemyError

from config import data_file
# from ..Ingredient_Search.Flask_app import search, download_files
from ..function.adjust_text_size import set_textbox_autofit
from ..function.ppt_translate import process_presentation, process_presentation_add_annotations
from config import base_model_file
from ..models import User, UploadRecord, Translation, StopWord
from ..services.sso_service import get_sso_service
from .. import db
import os
import uuid
import re

from ..utils.task_queue import translation_queue as old_translation_queue
from ..function.ppt_translate_async import process_presentation as process_presentation_async
from ..function.ppt_translate_async import process_presentation_add_annotations as process_presentation_add_annotations_async
from ..utils.enhanced_task_queue import EnhancedTranslationQueue, TranslationTask, translation_queue
from ..utils.thread_pool_executor import thread_pool, TaskType
import openpyxl
from io import BytesIO
import logging
import threading
from datetime import datetime
from app.utils.timezone_helper import format_datetime, datetime_to_isoformat

# from ..utils.Tokenization import Tokenizer
# from ...train import train_model
# sys.stdout.reconfigure(encoding='utf-8')
main = Blueprint('main', __name__)

# 配置日志记录器
logger = logging.getLogger(__name__)

# 使用增强的任务队列替换旧队列
# translation_queue = TranslationQueue()

# 简单任务状态存储（用于公开API）
simple_task_status = {}
simple_task_files = {}


@main.route('/')
@login_required
def index():
    return render_template('main/index.html', user=current_user)


@main.route('/dashboard')
@login_required
def dashboard():
    return redirect(url_for('main.index'))


@main.route('/index')
@login_required
def index_page():
    return render_template('main/index.html', user=current_user)


@main.route('/page1')
@login_required
def page1():
    return render_template('main/page1.html', user=current_user)


@main.route('/page2')
@login_required
def page2():
    return render_template('main/page2.html', user=current_user)


# 允许的文件扩展名和大小限制
ALLOWED_EXTENSIONS = {'ppt', 'pptx'}
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_unique_filename(filename):
    """生成唯一的文件名"""
    ext = filename.rsplit('.', 1)[1].lower()
    return f"{uuid.uuid4().hex}.{ext}"

def custom_filename(name):
    # 移除危险的路径字符，仅保留基本合法字符 + 中文
    name = re.sub(r'[\\/:"*?<>|]+', '_', name)  # 替换非法字符
    return name
@main.route('/upload', methods=['POST'])
@login_required
def upload_file():
    try:
        # 验证用户是否登录
        if not current_user.is_authenticated:
            return jsonify({'code': 403, 'msg': '用户未登录'}), 403

        # 获取表单数据
        user_language = request.form.get('source_language', 'English')
        target_language = request.form.get('target_language', 'Chinese')
        bilingual_translation = request.form.get('bilingual_translation', 'paragraph_up')
        select_page = request.form.getlist('select_page')
        model = request.form.get('model', 'qwen')
        enable_text_splitting = request.form.get('enable_text_splitting', 'False')  # 字符串: "False" 或 "True_spliting"
        enable_uno_conversion = request.form.get('enable_uno_conversion', 'True').lower() == 'true'
        
        # 获取选中的词汇表ID
        selected_vocabulary = request.form.get('selected_vocabulary', '')
        vocabulary_ids = []
        if selected_vocabulary:
            try:
                vocabulary_ids = [int(x.strip()) for x in selected_vocabulary.split(',') if x.strip()]
                logger.info(f"接收到词汇表ID: {vocabulary_ids}")
            except ValueError as e:
                logger.error(f"词汇表ID解析失败: {selected_vocabulary}, 错误: {str(e)}")
                vocabulary_ids = []
        
        # 记录接收到的参数
        logger.info(f"接收到的翻译参数:")
        logger.info(f"  - 源语言: {user_language}")
        logger.info(f"  - 目标语言: {target_language}")
        logger.info(f"  - 双语翻译: {bilingual_translation}")
        logger.info(f"  - 模型: {model}")
        logger.info(f"  - 文本分割: {enable_text_splitting}")
        logger.info(f"  - UNO转换: {enable_uno_conversion}")
        logger.info(f"  - 选择页面: {select_page}")
        logger.info(f"  - 词汇表数量: {len(vocabulary_ids)}")

        # 转换select_page为整数列表
        if select_page and select_page[0]:
            try:
                select_page = [int(x) for x in select_page[0].split(',')]
                logger.info(f"  用户选择的页面: {select_page}")
            except Exception as e:
                logger.error(f"  页面选择参数解析失败: {select_page}, 错误: {str(e)}")
                select_page = []
        else:
            logger.info(f"  没有选择页面，将翻译所有页面")
            select_page = []

        # 构建自定义翻译词典
        custom_translations = {}
        if vocabulary_ids:
            try:
                # 查询词汇表数据（包含权限检查）
                translations = Translation.query.filter(
                    Translation.id.in_(vocabulary_ids),
                    db.or_(
                        db.and_(Translation.user_id == current_user.id, Translation.is_public == False),
                        Translation.is_public == True
                    )
                ).all()
                
                logger.info(f"从数据库查询到 {len(translations)} 个词汇条目")
                
                # 根据翻译方向构建词典
                for trans in translations:
                    source_text = None
                    target_text = None
                    
                    # 根据语言方向映射源文本和目标文本
                    if user_language == 'English' and target_language == 'Chinese':
                        source_text = trans.english
                        target_text = trans.chinese
                    elif user_language == 'Chinese' and target_language == 'English':
                        source_text = trans.chinese
                        target_text = trans.english
                    elif user_language == 'English' and target_language == 'Dutch':
                        source_text = trans.english
                        target_text = trans.dutch
                    elif user_language == 'Dutch' and target_language == 'English':
                        source_text = trans.dutch
                        target_text = trans.english
                    elif user_language == 'Chinese' and target_language == 'Dutch':
                        source_text = trans.chinese
                        target_text = trans.dutch
                    elif user_language == 'Dutch' and target_language == 'Chinese':
                        source_text = trans.dutch
                        target_text = trans.chinese
                    
                    # 添加到词典（确保源文本和目标文本都存在且不为空）
                    if source_text and target_text and source_text.strip() and target_text.strip():
                        custom_translations[source_text.strip()] = target_text.strip()
                
                logger.info(f"构建自定义词典完成，包含 {len(custom_translations)} 个词汇对")
                logger.info(f"词典示例: {dict(list(custom_translations.items())[:3])}..." if custom_translations else "词典为空")
                
            except Exception as e:
                logger.error(f"构建自定义词典失败: {str(e)}")
                custom_translations = {}

        # 其他参数处理
        stop_words_input = request.form.get('stop_words', '')
        stop_words = [word.strip() for word in stop_words_input.split('\n') if word.strip()]

        custom_translations_input = request.form.get('custom_translations', '')
        # 合并用户输入的翻译和词汇表翻译
        for line in custom_translations_input.split('\n'):
            line = line.strip()
            if not line:
                continue
            parts = line.split('->')
            if len(parts) == 2:
                eng, chi = parts[0].strip(), parts[1].strip()
                custom_translations[eng] = chi

        # 获取上传的文件
        file = request.files.get('file')


        if not file:
            return jsonify({'code': 400, 'msg': '请选择文件上传'}), 400

        # 检查文件名和类型
        if not file.filename or not allowed_file(file.filename):
            return jsonify({'code': 400, 'msg': '不支持的文件类型'}), 400

        # 检查文件大小
        file.seek(0, 2)  # 移动到文件末尾
        file_size = file.tell()  # 获取文件大小
        file.seek(0)  # 重置文件指针

        if file_size > MAX_FILE_SIZE:
            return jsonify({'code': 400, 'msg': f'文件大小超过限制 ({MAX_FILE_SIZE/1024/1024}MB)'}), 400

        # 创建用户上传目录
        upload_folder = current_app.config['UPLOAD_FOLDER']
        user_upload_dir = os.path.join(upload_folder, f"user_{current_user.id}")
        os.makedirs(user_upload_dir, exist_ok=True)

        # 生成安全的文件名
        original_filename = custom_filename(file.filename)
        
        # 创建语言名称到语言代码的映射
        language_map = {
            'English': 'en',
            'Chinese': 'zh',
            'Dutch': 'nl'
        }
        
        # 获取源语言和目标语言的代码
        source_lang_code = language_map.get(user_language, user_language)
        target_lang_code = language_map.get(target_language, target_language)
        
        # 生成新的文件名格式：源语言_目标语言_源文件名.pptx
        name_without_ext, ext = os.path.splitext(original_filename)
        new_filename = f"{source_lang_code}_{target_lang_code}_{name_without_ext}{ext}"
        
        stored_filename = get_unique_filename(new_filename)
        file_path = os.path.join(user_upload_dir, stored_filename)

        try:
            # 保存PPT文件
            file.save(file_path)


            # 创建上传记录，使用新的文件名
            record = UploadRecord(
                user_id=current_user.id,
                filename=new_filename,  # 使用新的文件名格式
                stored_filename=stored_filename,
                file_path=user_upload_dir,
                file_size=file_size,
                status='pending'
            )

            db.session.add(record)
            db.session.commit()

            # 添加翻译任务到队列
            priority = 0  # 默认优先级
            
            # 记录传递给任务队列的参数
            logger.info(f"传递给任务队列的参数:")
            logger.info(f"  - 文件路径: {file_path}")
            logger.info(f"  - 模型: {model}")
            logger.info(f"  - 文本分割: {enable_text_splitting}")
            logger.info(f"  - UNO转换: {enable_uno_conversion}")
            logger.info(f"  - 自定义词典条目数: {len(custom_translations)}")
            
            queue_position = translation_queue.add_task(
                user_id=current_user.id,
                user_name=current_user.username,
                file_path=file_path,
                select_page=select_page,
                source_language=user_language,
                target_language=target_language,
                bilingual_translation=bilingual_translation,
                priority=priority,
                model=model,
                enable_text_splitting=enable_text_splitting,
                enable_uno_conversion=enable_uno_conversion,
                custom_translations=custom_translations  # 传递自定义词典
            )

            return jsonify({
                'code': 200,
                'msg': '文件上传成功，已加入翻译队列',
                'queue_position': queue_position,
                'record_id': record.id
            })

        except Exception as e:
            # 清理已上传的文件
            if os.path.exists(file_path):
                os.remove(file_path)

            # 回滚数据库事务
            db.session.rollback()

            logger.error(f"文件上传失败: {str(e)}")
            return jsonify({'code': 500, 'msg': f'文件上传失败: {str(e)}'}), 500

    except Exception as e:
        logger.error(f"处理上传请求失败: {str(e)}")
        return jsonify({'code': 500, 'msg': f'处理上传请求失败: {str(e)}'}), 500


def process_queue(app, stop_words_list, custom_translations,source_language, target_language,bilingual_translation):
    """
    处理翻译队列的函数

    注意：此函数已被 EnhancedTranslationQueue 类的 _processor_loop 方法取代，
    不再被主动调用。保留此函数仅用于兼容旧代码。
    新的任务处理逻辑在 app/utils/enhanced_task_queue.py 中实现。
    """
    while True:
        task = translation_queue.start_next_task()
        if not task:
            time.sleep(1)  # 如果没有任务，等待1秒
            continue

        # 创建应用上下文
        with app.app_context():
            # try:
                    # 执行翻译
                    process_presentation(
                        task['file_path'], stop_words_list, custom_translations,
                        task['select_page'], source_language, target_language, bilingual_translation,
                        model=task.get('model', 'qwen'),
                        enable_text_splitting=task.get('enable_text_splitting', 'False')
                    )
    
                    set_textbox_autofit(task['file_path'])
    
                    translation_queue.complete_current_task(success=True)
    
                    # 更新数据库记录状态
                    record = UploadRecord.query.filter_by(
                        user_id=task['user_id'],
                        file_path=os.path.dirname(task['file_path']),
                        stored_filename=os.path.basename(task['file_path'])
                    ).first()
    
                    if record:
                        record.status = 'completed'
                        db.session.commit()
    
                # except Exception as e:
                #     print(f"Translation error: {str(e)}")
                #     translation_queue.complete_current_task(success=False, error=str(e))
    
                    # 更新数据库记录状态
                    if 'record' in locals() and record:
                        record.status = 'failed'
                        try:
                            db.session.commit()
                        except:
                            db.session.rollback()
            # finally:
            #     # 确保会话被正确清理
            #     db.session.remove()


@main.route('/task_status')
@login_required
def get_task_status():
    """获取当前用户的任务状态"""
    status = translation_queue.get_task_status_by_user(current_user.id)
    if status:
        # 转换日志格式以便前端显示
        if 'recent_logs' in status:
            formatted_logs = []
            for log in status['recent_logs']:
                formatted_logs.append({
                    'timestamp': datetime_to_isoformat(log['timestamp']) if log['timestamp'] else '',
                    'message': log['message'],
                    'level': log['level']
                })
            status['recent_logs'] = formatted_logs

        # 使用ISO格式化时间戳
        for key in ['created_at', 'started_at', 'completed_at']:
            if key in status and status[key]:
                status[key] = datetime_to_isoformat(status[key])

        return jsonify(status)
    return jsonify({'status': 'no_task'})


@main.route('/queue_status')
@login_required
def get_queue_status():
    """获取翻译队列状态信息"""
    try:
        # 获取队列统计信息
        queue_stats = translation_queue.get_queue_stats()

        # 添加详细的任务信息
        active_tasks = queue_stats.get('processing', 0)  # 修正键名
        waiting_tasks = queue_stats.get('waiting', 0)
        max_concurrent = queue_stats.get('max_concurrent', 10)

        detailed_stats = {
            'max_concurrent_tasks': max_concurrent,
            'active_tasks': active_tasks,
            'waiting_tasks': waiting_tasks,
            'total_tasks': queue_stats.get('total', 0),
            'completed_tasks': queue_stats.get('completed', 0),
            'failed_tasks': queue_stats.get('failed', 0),
            'available_slots': max(0, max_concurrent - active_tasks),
            'queue_full': (active_tasks + waiting_tasks) >= max_concurrent,
            'system_status': 'normal' if (active_tasks + waiting_tasks) < max_concurrent else 'busy'
        }

        # 如果是管理员，提供更多详细信息
        if current_user.is_administrator():
            detailed_stats['admin_info'] = {
                'processor_running': translation_queue.running,
                'task_timeout': translation_queue.task_timeout,
                'retry_times': translation_queue.retry_times
            }

        return jsonify(detailed_stats)

    except Exception as e:
        logger.error(f"获取队列状态失败: {str(e)}")
        return jsonify({
            'error': '获取队列状态失败',
            'max_concurrent_tasks': 10,
            'active_tasks': 0,
            'waiting_tasks': 0,
            'total_tasks': 0,
            'available_slots': 10,
            'queue_full': False,
            'system_status': 'unknown'
        }), 500


@main.route('/history')
@login_required
def get_history():
    try:
        # 只返回状态为 completed 的记录
        records = UploadRecord.query.filter_by(user_id=current_user.id, status='completed') \
            .order_by(UploadRecord.upload_time.desc()).all()

        history_records = []
        for record in records:
            # 检查文件是否仍然存在
            file_exists = os.path.exists(os.path.join(record.file_path, record.stored_filename))

            # 使用ISO格式返回时间，让前端正确处理时区
            upload_time = datetime_to_isoformat(record.upload_time)
            
            # 直接使用数据库中存储的文件名
            history_records.append({
                'id': record.id,
                'filename': record.filename,  # 使用数据库中存储的文件名
                'file_size': record.file_size,
                'upload_time': upload_time,
                'status': record.status,
                'file_exists': file_exists
            })

        return jsonify(history_records)

    except Exception as e:
        print(f"History error: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': '获取历史记录失败'
        }), 500

        try:
            # 删除物理文件
            file_path = os.path.join(record.file_path, record.stored_filename)
            if os.path.exists(file_path):
                os.remove(file_path)

            # 删除数据库记录
            db.session.delete(record)
            db.session.commit()

            return jsonify({'message': '文件删除成功'})

        except Exception as e:
            db.session.rollback()
            print(f"Delete error: {str(e)}")
            return jsonify({'error': f'删除失败: {str(e)}'}), 500

    except Exception as e:
        print(f"Delete error: {str(e)}")
        return jsonify({'error': f'删除失败: {str(e)}'}), 500


@main.route('/translate')
@login_required
def translate():
    return render_template('main/translate.html', user=current_user)

@main.route('/pdf_translate')
@login_required
def pdf_translate():
    """PDF翻译页面"""
    return render_template('main/pdf_translate.html')


@main.route('/batch_process')
@login_required
def batch_process():
    return render_template('main/batch_process.html', user=current_user)


@main.route('/settings')
@login_required
def settings():
    return render_template('main/settings.html', user=current_user)

@main.route('/pdf_translation')
@login_required
def pdf_translation():
    return render_template('main/pdf_translation.html', user=current_user)

@main.route('/dictionary')
@login_required
def dictionary():
    return render_template('main/dictionary.html', user=current_user)


@main.route('/file_search')
@login_required
def file_search():
    return render_template('main/file_search.html', user=current_user)


@main.route('/account_settings')
@login_required
def account_settings():
    return render_template('main/account_settings.html', user=current_user)


@main.route('/registration_approval')
@login_required
def registration_approval():
    if not current_user.is_administrator():
        flash('没有权限访问此页面')
        return redirect(url_for('main.index'))
    return render_template('main/registration_approval.html')


# @main.route('/sso_management')
# @login_required
# def sso_management():
#     """SSO管理页面"""
#     if not current_user.is_administrator():
#         flash('没有权限访问此页面')
#         return redirect(url_for('main.index'))
#     return render_template('main/sso_management.html')


@main.route('/api/registrations')
@login_required
def get_registrations():
    if not current_user.is_administrator():
        return jsonify({'error': '没有权限访问'}), 403

    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', 'all')
    per_page = 10

    query = User.query
    if status != 'all':
        query = query.filter_by(status=status)

    pagination = query.order_by(User.register_time.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        'registrations': [{ 
            'id': user.id,
            'username': user.username,
            'status': user.status,
            'register_time': datetime_to_isoformat(user.register_time) if user.register_time else None,
            'approve_user': user.approve_user.username if user.approve_user else None,
            'approve_time': datetime_to_isoformat(user.approve_time) if user.approve_time else None
        } for user in pagination.items],
        'total_pages': pagination.pages,
        'current_page': page,
        'total': pagination.total
    })


@main.route('/api/users')
@login_required
def get_users():
    if not current_user.is_administrator():
        return jsonify({'error': '没有权限访问'}), 403

    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', 'all')
    per_page = 10

    query = User.query.filter(User.status.in_(['approved', 'disabled']))
    if status != 'all':
        query = query.filter_by(status=status)

    pagination = query.order_by(User.register_time.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        'users': [{ 
            'id': user.id,
            'username': user.username,
            'status': user.status,
            'register_time': datetime_to_isoformat(user.register_time) if user.register_time else None,
        } for user in pagination.items],
        'total_pages': pagination.pages,
        'current_page': page,
        'total': pagination.total
    })


@main.route('/api/registrations/<int:id>/approve', methods=['POST'])
@login_required
def approve_registration(id):
    if not current_user.is_administrator():
        return jsonify({'error': '没有权限进行此操作'}), 403

    user = User.query.get_or_404(id)
    if user.status != 'pending':
        return jsonify({'error': '该用户已被审批'}), 400

    try:
        user.status = 'approved'
        user.approve_time = datetime.now(pytz.timezone('Asia/Shanghai'))
        user.approve_user_id = current_user.id
        db.session.commit()
        return jsonify({'message': '审批成功'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@main.route('/api/registrations/<int:id>/reject', methods=['POST'])
@login_required
def reject_registration(id):
    if not current_user.is_administrator():
        return jsonify({'error': '没有权限进行此操作'}), 403

    user = User.query.get_or_404(id)
    if user.status != 'pending':
        return jsonify({'error': '该用户已被审批'}), 400

    try:
        user.status = 'rejected'
        user.approve_time = datetime.now(pytz.timezone('Asia/Shanghai'))
        user.approve_user_id = current_user.id
        db.session.commit()
        return jsonify({'message': '已拒绝申请'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@main.route('/api/users/<int:id>/disable', methods=['POST'])
@login_required
def disable_user(id):
    if not current_user.is_administrator():
        return jsonify({'error': '没有权限进行此操作'}), 403

    user = User.query.get_or_404(id)
    if user.status != 'approved':
        return jsonify({'error': '该用户无法被禁用'}), 400

    try:
        user.status = 'disabled'
        db.session.commit()
        return jsonify({'message': '用户已禁用'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@main.route('/api/users/<int:id>/enable', methods=['POST'])
@login_required
def enable_user(id):
    if not current_user.is_administrator():
        return jsonify({'error': '没有权限进行此操作'}), 403

    user = User.query.get_or_404(id)
    if user.status != 'disabled':
        return jsonify({'error': '该用户无法被启用'}), 400

    try:
        user.status = 'approved'
        db.session.commit()
        return jsonify({'message': '用户已启用'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# 词库管理API路由
@main.route('/api/translations', methods=['GET'])
@login_required
def get_translations():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)  # 添加per_page参数支持
    search = request.args.get('search', '')
    # Add filter for public/private translations
    visibility = request.args.get('visibility', 'private')  # private, public, all

    if visibility == 'private':
        # 只查询当前用户的私有翻译数据
        query = Translation.query.filter(
            Translation.user_id == current_user.id,
            Translation.is_public == False
        )
    elif visibility == 'public':
        # 只查询公共的翻译数据
        query = Translation.query.filter_by(is_public=True)
    else:  # all 或其他值，默认为all
        # 查询当前用户的所有私有数据和所有公共数据
        query = Translation.query.filter(
            db.or_(
                db.and_(Translation.user_id == current_user.id, Translation.is_public == False),
                Translation.is_public == True
            )
        )

    if search:
        query = query.filter(
            db.or_(
                Translation.english.ilike(f'%{search}%'),
                Translation.chinese.ilike(f'%{search}%'),
                Translation.dutch.ilike(f'%{search}%'),
                Translation.category.ilike(f'%{search}%')
            )
        )

    pagination = query.order_by(Translation.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    translations_data = []
    for item in pagination.items:
        translation_dict = {
            'id': item.id,
            'english': item.english,
            'chinese': item.chinese,
            'dutch': item.dutch,
            'category': item.category,
            'created_at': datetime_to_isoformat(item.created_at),
            'is_public': item.is_public,
            'user_id': item.user_id
        }
        # Add user info for display
        if item.user:
            translation_dict['user'] = {
                'id': item.user.id,
                'username': item.user.username
            }
        translations_data.append(translation_dict)

    return jsonify({
        'translations': translations_data,
        'total_pages': pagination.pages,
        'current_page': page,
        'total_items': pagination.total
    })


@main.route('/api/translations/categories', methods=['GET'])
@login_required
def get_translation_categories():
    """获取所有已存在的分类列表（去重，按字母排序）"""
    try:
        from app.models.translation import Translation as TranslationModel
        categories_set = set()
        # 仅提取有值的分类
        for row in db.session.query(TranslationModel.category).filter(TranslationModel.category.isnot(None)).all():
            value = row[0]
            if not value:
                continue
            # 支持分号分隔的多分类
            for part in value.split(';'):
                name = part.strip()
                if name:
                    categories_set.add(name)
        categories = sorted(categories_set, key=lambda x: x.lower())
        return jsonify({'categories': categories})
    except Exception as e:
        logger.error(f"获取分类失败: {e}")
        return jsonify({'categories': []}), 200

@main.route('/api/translations', methods=['POST'])
@login_required
def add_translation():
    data = request.get_json()
    english = data.get('english')
    chinese = data.get('chinese')
    dutch = data.get('dutch')
    category = data.get('category')  # Single category field
    is_public = data.get('is_public', False)

    if not english or not chinese:
        return jsonify({'error': '英文和中文翻译都是必填的'}), 400

    # Build query based on whether it's a public or private translation
    if is_public and current_user.is_administrator():
        # For public translations, check against all public translations
        existing = Translation.query.filter_by(
            english=english,
            is_public=True
        ).first()
    else:
        # For private translations, check only against current user's translations
        is_public = False  # Ensure non-admin users can't add public translations
        existing = Translation.query.filter_by(
            user_id=current_user.id,
            english=english
        ).first()

    if existing:
        return jsonify({'error': '该英文翻译已存在于词库中'}), 400

    try:
        translation = Translation(
            english=english,
            chinese=chinese,
            dutch=dutch,
            category=category,
            is_public=is_public,
            user_id=current_user.id  # Always set user_id, even for public translations
        )
        db.session.add(translation)
        db.session.commit()

        return jsonify({
            'message': '添加成功',
            'translation': {
                'id': translation.id,
                'english': translation.english,
                'chinese': translation.chinese,
                'dutch': translation.dutch,
                'category': translation.category,
                'is_public': translation.is_public,
                'created_at': datetime_to_isoformat(translation.created_at)
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@main.route('/api/translations/<int:id>', methods=['DELETE'])
@login_required
def delete_translation(id):
    translation = Translation.query.get_or_404(id)

    # 验证所有权 - users can only delete their own private translations
    # admins can delete public translations
    if translation.is_public:
        if not current_user.is_administrator():
            return jsonify({'error': '无权删除公共词库'}), 403
    else:
        if translation.user_id != current_user.id:
            return jsonify({'error': '无权删除此翻译'}), 403

    try:
        db.session.delete(translation)
        db.session.commit()
        return jsonify({'message': '删除成功'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@main.route('/api/translations/<int:id>', methods=['PUT'])
@login_required
def update_translation(id):
    translation = Translation.query.get_or_404(id)

    # 验证所有权 - users can only edit their own private translations
    # admins can edit public translations
    if translation.is_public:
        if not current_user.is_administrator():
            return jsonify({'error': '无权修改公共词库'}), 403
    else:
        if translation.user_id != current_user.id:
            return jsonify({'error': '无权修改此翻译'}), 403

    data = request.get_json()
    english = data.get('english')
    chinese = data.get('chinese')
    is_public = data.get('is_public', translation.is_public)  # Keep existing value if not provided

    # Only admins can change the public status
    if 'is_public' in data and data['is_public'] != translation.is_public:
        if not current_user.is_administrator():
            return jsonify({'error': '无权修改词条的公共状态'}), 403

    if not english or not chinese:
        return jsonify({'error': '英文和中文翻译都是必填的'}), 400

    # 检查是否与其他翻译重复
    if translation.is_public or is_public:
        # For public translations, check against all public translations
        existing = Translation.query.filter(
            Translation.is_public == True,
            Translation.english == english,
            Translation.id != id
        ).first()
    else:
        # For private translations, check only against current user's translations
        existing = Translation.query.filter(
            Translation.user_id == current_user.id,
            Translation.english == english,
            Translation.id != id
        ).first()

    if existing:
        return jsonify({'error': '该英文翻译已存在于词库中'}), 400

    try:
        translation.english = english
        translation.chinese = chinese
        translation.dutch = data.get('dutch')
        translation.category = data.get('category')
        
        # Only admins can change public status
        if current_user.is_administrator() and 'is_public' in data:
            translation.is_public = is_public
            
        db.session.commit()

        return jsonify({
            'message': '更新成功',
            'translation': {
                'id': translation.id,
                'english': translation.english,
                'chinese': translation.chinese,
                'dutch': translation.dutch,
                'category': translation.category,
                'is_public': translation.is_public,
                'created_at': datetime_to_isoformat(translation.created_at)
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

        db.session.commit()

        return jsonify({
            'message': '更新成功',
            'translation': {
                'id': translation.id,
                'english': translation.english,
                'chinese': translation.chinese,
                'dutch': translation.dutch,
                'class1': translation.class1,
                'class2': translation.class2,
                'is_public': translation.is_public,
                'created_at': datetime_to_isoformat(translation.created_at)
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@main.route('/api/translations/stats', methods=['GET'])
@login_required
def get_translation_stats():
    """获取当前用户的词库统计信息"""
    try:
        total_count = Translation.query.filter_by(user_id=current_user.id).count()
        return jsonify({
            'total_translations': total_count
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@main.route('/api/train', methods=['POST'])
@login_required
def train_model():
    """使用当前用户的词库数据进行训练"""
    try:

        # Tokenizer()
        # # TODO: 实现模型训练逻辑，只使用当前用户的数据
        # train_model()
        translations = Translation.query.all()
        return jsonify({
            'message': '训练完成',
            'data_count': len(translations)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@main.route('/ingredient')
@login_required
def ingredient():
    return render_template('main/ingredient.html')


@main.route('/ingredient/upload')
@login_required
def ingredient_upload_page():
    if not current_user.is_administrator():
        abort(403)
    return render_template('main/ingredient_upload.html')


# 加载JSON数据
def load_data(json_path):
    with open(json_path, 'r', encoding='UTF-8') as file:
        return json.load(file)


def extract_ingredient(s, ingredient):
    """提取匹配的成分"""
    ingredients = re.sub(r'(\(|\（)', ',', s)
    ingredients = re.sub(r'(\)|\）)', '', ingredients)
    ingredients = re.split(r'[、,，]', ingredients)
    ingredients = [ing.replace(' ', "") for ing in ingredients]
    # 去掉类似于"又名"、"以"、"记"等词
    cleaned_ingredient_list = [re.sub(r'(又名|以|记)', '', ing) for ing in ingredients]

    for i in cleaned_ingredient_list:
        if ingredient in i:
            return i
    return None


def clean_food_name(food_name):
    """清理食品名称"""
    return re.sub(r'备案入.*', '', food_name)


@main.route('/search', methods=['POST'])
@login_required
def search_ingredient():
    # print(request.form['query'])
    # 临时返回空结果，直到实现完整的搜索功能
    return jsonify([])


@main.route('/ingredient/download', methods=['POST'])
@login_required
def download_ingredient_file():
    # print(request.form['file_path'])
    # 临时返回错误，直到实现完整的下载功能
    return jsonify({'error': '功能暂未实现'}), 500


# 允许的PDF文件扩展名
PDF_ALLOWED_EXTENSIONS = {'pdf'}


def allowed_pdf_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in PDF_ALLOWED_EXTENSIONS


@main.route('/pdf/<filename>')
@login_required
def get_pdf(filename):
    try:
        # 获取上传文件夹路径
        upload_folder = current_app.config['UPLOAD_FOLDER']
        logger.info(f"PDF请求: {filename}, 上传文件夹: {upload_folder}")
        
        if not os.path.exists(upload_folder):
            logger.error(f"上传文件夹不存在: {upload_folder}")
            return jsonify({'error': '上传文件夹不存在'}), 404

        # 构建用户PDF目录路径
        user_pdf_dir = os.path.join(upload_folder, f"{current_user.username}_pdfs")
        logger.info(f"尝试从目录提供PDF: {user_pdf_dir}")

        if not os.path.exists(user_pdf_dir):
            # 尝试创建目录
            try:
                os.makedirs(user_pdf_dir, exist_ok=True)
                logger.info(f"创建了PDF目录: {user_pdf_dir}")
            except Exception as e:
                logger.error(f"无法创建PDF目录: {user_pdf_dir}, 错误: {str(e)}")
                return jsonify({'error': f'无法创建PDF目录: {str(e)}'}), 500
                
        # 构建完整的文件路径
        file_path = os.path.join(user_pdf_dir, filename)
        file_path = os.path.abspath(file_path)  # 转换为绝对路径
        logger.info(f"完整的PDF文件路径: {file_path}")

        if not os.path.exists(file_path):
            logger.error(f"PDF文件不存在: {file_path}")
            
            # 检查是否存在于其他可能的位置
            alt_paths = [
                os.path.join(upload_folder, filename),  # 直接在上传文件夹中
                os.path.join(upload_folder, 'pdf', filename),  # 在pdf子文件夹中
                os.path.join(current_app.root_path, 'static', 'uploads', filename)  # 在静态文件夹中
            ]
            
            for alt_path in alt_paths:
                if os.path.exists(alt_path):
                    logger.info(f"在替代位置找到PDF文件: {alt_path}")
                    file_path = alt_path
                    break
            else:
                return jsonify({'error': '文件不存在'}), 404

        # 检查文件权限
        try:
            # 尝试打开文件进行读取测试
            with open(file_path, 'rb') as f:
                f.read(1)  # 只读取1字节进行测试
            logger.info(f"文件权限检查通过: {file_path}")
        except PermissionError:
            logger.error(f"无法读取PDF文件(权限错误): {file_path}")
            # 尝试修改文件权限
            try:
                import stat
                os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
                logger.info(f"已修改文件权限: {file_path}")
            except Exception as e:
                logger.error(f"无法修改文件权限: {str(e)}")
                return jsonify({'error': f'文件无法访问(权限错误): {str(e)}'}), 403
        except Exception as e:
            logger.error(f"文件读取测试失败: {str(e)}")
            return jsonify({'error': f'文件无法访问: {str(e)}'}), 403

        logger.info(f"准备提供PDF文件: {file_path}")
        try:
            # 使用安全的方式提供文件
            response = send_file(
                file_path,
                mimetype='application/pdf',
                as_attachment=False,
                download_name=filename
            )
            # 添加必要的安全头部
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            
            # 添加内容安全策略头部
            response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; object-src 'self'"
            
            # 添加X-Content-Type-Options头部，防止MIME类型嗅探
            response.headers['X-Content-Type-Options'] = 'nosniff'
            
            # 强制使用HTTPS
            if request.is_secure:
                response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
            
            logger.info(f"PDF文件已成功提供: {file_path}")
            return response

        except Exception as e:
            logger.error(f"提供PDF文件时出错: {str(e)}")
            raise

    except Exception as e:
        logger.error(f"PDF提供错误: {str(e)}")
        return jsonify({'error': f'获取文件失败: {str(e)}'}), 500



@main.route('/save_annotations', methods=['POST'])
@login_required
def save_annotations():
    try:
        data = request.get_json()
        annotations = data.get('annotations', [])

        # 创建注释存储目录
        annotations_dir = os.path.join(
            current_app.config['UPLOAD_FOLDER'],
            f"{current_user.username}_annotations"
        )

        if not os.path.exists(annotations_dir):
            os.makedirs(annotations_dir)

        # 保存注释到JSON文件
        filename = f"annotations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        file_path = os.path.join(annotations_dir, filename)

        # 添加时间戳和用户信息
        annotation_data = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'user': current_user.username,
            'annotations': annotations
        }

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(annotation_data, f, ensure_ascii=False, indent=2)

        return jsonify({'message': '注释保存成功'})

    except Exception as e:
        print(f"Save annotations error: {str(e)}")
        return jsonify({'error': f'保存失败: {str(e)}'}), 500


@main.route('/get_annotations/<filename>')
@login_required
def get_annotations(filename):
    try:
        annotations_dir = os.path.join(
            current_app.config['UPLOAD_FOLDER'],
            f"{current_user.username}_annotations"
        )

        file_path = os.path.join(annotations_dir, filename)

        if not os.path.exists(file_path):
            return jsonify({'error': '注释文件不存在'}), 404

        with open(file_path, 'r', encoding='utf-8') as f:
            annotations = json.load(f)

        return jsonify(annotations)

    except Exception as e:
        print(f"Get annotations error: {str(e)}")
        return jsonify({'error': f'获取注释失败: {str(e)}'}), 500


@main.route('/get_annotation_files')
@login_required
def get_annotation_files():
    try:
        # 获取用户注释文件目录
        annotations_dir = os.path.join(
            current_app.config['UPLOAD_FOLDER'],
            f"{current_user.username}_annotations"
        )

        if not os.path.exists(annotations_dir):
            return jsonify([])

        # 获取目录中的所有JSON文件
        files = []
        for filename in os.listdir(annotations_dir):
            if filename.endswith('.json'):
                file_path = os.path.join(annotations_dir, filename)
                files.append({
                    'filename': filename,
                    'created_time': datetime.fromtimestamp(os.path.getctime(file_path)).strftime('%Y-%m-%d %H:%M:%S')
                })

        # 按创建时间降序排序
        files.sort(key=lambda x: x['created_time'], reverse=True)
        return jsonify(files)

    except Exception as e:
        print(f"Error getting annotation files: {str(e)}")
        return jsonify({'error': str(e)}), 500


@main.route('/api/users/sso')
@login_required
def get_sso_users():
    """获取SSO用户列表"""
    if not current_user.is_administrator():
        return jsonify({'error': '权限不足'}), 403

    try:
        # 查询所有SSO用户
        sso_users = User.query.filter(User.sso_provider.isnot(None)).all()

        users_data = []
        for user in sso_users:
            # 格式化时间
            last_login = format_datetime(user.last_login)
            register_time = format_datetime(user.register_time)

            users_data.append({
                'id': user.id,
                'username': user.username,
                'email': user.email or '',
                'display_name': user.get_display_name(),
                'first_name': user.first_name or '',
                'last_name': user.last_name or '',
                'sso_provider': user.sso_provider,
                'sso_subject': user.sso_subject or '',
                'status': user.status,
                'role': user.role.name if user.role else 'unknown',
                'last_login': last_login,
                'register_time': register_time
            })

        return jsonify(users_data)

    except Exception as e:
        logger.error(f"获取SSO用户列表失败: {e}")
        return jsonify({'error': f'获取用户列表失败: {str(e)}'}), 500


@main.route('/get_queue_status')
def get_detailed_queue_status():
    """获取详细的翻译队列状态（旧版API）"""
    username = session.get('username', '')
    if not username:
        return jsonify({'code': 403, 'msg': '用户未登录'}), 403

    try:
        # 获取队列状态和统计信息
        status_info = translation_queue.get_queue_status()
        user_tasks = translation_queue.get_user_tasks(username)

        # 轮询用户任务以获取当前状态
        user_task_details = []
        for task in user_tasks:
            task_detail = {
                'task_id': task.task_id,
                'file_name': os.path.basename(task.file_path),
                'status': task.status,
                'progress': task.progress,
                'result': task.result,
                'error': task.error,
                'created_at': task.created_at.isoformat(),
                'started_at': task.started_at.isoformat() if task.started_at else None,
                'completed_at': task.completed_at.isoformat() if task.completed_at else None
            }
            user_task_details.append(task_detail)

        return jsonify({
            'code': 200,
            'queue_status': status_info,
            'user_tasks': user_task_details
        })
    except Exception as e:
        logger.error(f"获取队列状态失败: {str(e)}")
        return jsonify({'code': 500, 'msg': f'获取队列状态失败: {str(e)}'}), 500


@main.route('/cancel_task/<task_id>')
def cancel_task(task_id):
    """取消翻译任务"""
    username = session.get('username', '')
    if not username:
        return jsonify({'code': 403, 'msg': '用户未登录'}), 403

    try:
        # 尝试取消任务
        result = translation_queue.cancel_task(task_id, username)
        if result:
            return jsonify({'code': 200, 'msg': '任务已取消'})
        else:
            return jsonify({'code': 400, 'msg': '取消任务失败，任务可能不存在或已经开始处理'}), 400
    except Exception as e:
        logger.error(f"取消任务失败: {str(e)}")
        return jsonify({'code': 500, 'msg': f'取消任务失败: {str(e)}'}), 500


@main.route('/logs')
@login_required
def logs():
    """日志管理页面"""
    # 检查管理员权限
    if not current_user.is_administrator():
        flash('没有权限访问此页面', 'error')
        return redirect(url_for('main.index'))
    return render_template('main/logs.html')


@main.route('/switch_language', methods=['POST'])
def switch_language():
    """处理语言切换请求"""
    try:
        data = request.get_json()
        language = data.get('language', 'zh')
        
        # 验证语言代码
        if language not in ['zh', 'en']:
            return jsonify({
                'success': False,
                'message': 'Invalid language code'
            }), 400
        
        # 在session中保存语言设置
        session['language'] = language
        
        return jsonify({
            'success': True,
            'message': 'Language switched successfully',
            'language': language
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

# ==================== 公开API端点（不需要认证） ====================
# 用于简单前端（html文件夹）的API端点

@main.route('/start_translation', methods=['POST'])
def start_translation():
    """启动PPT翻译任务（公开API，不需要认证）"""
    try:
        # 检查是否有文件
        if 'file' not in request.files:
            return jsonify({'error': '没有文件'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': '没有选择文件'}), 400

        if not allowed_file(file.filename):
            return jsonify({'error': '不支持的文件格式'}), 400

        # 生成唯一的任务ID
        task_id = str(uuid.uuid4())

        # 创建临时上传目录
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        temp_upload_dir = os.path.join(upload_folder, 'temp')
        os.makedirs(temp_upload_dir, exist_ok=True)

        # 保存上传的文件
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{timestamp}_{task_id}_{filename}"
        file_path = os.path.join(temp_upload_dir, unique_filename)
        file.save(file_path)

        logger.info(f"公开API文件已保存: {file_path}")

        # 初始化任务状态
        simple_task_status[task_id] = {
            'status': 'processing',
            'progress': 0,
            'current_slide': 0,
            'total_slides': 0,
            'file_path': file_path,
            'original_filename': filename,
            'created_at': datetime.now(),
            'error': None
        }

        # 启动异步翻译任务
        translation_thread = threading.Thread(
            target=execute_simple_translation_task,
            args=(task_id, file_path, filename)
        )
        translation_thread.daemon = True
        translation_thread.start()

        logger.info(f"公开API翻译任务已启动: {task_id}")

        # 立即返回任务ID
        return jsonify({
            'task_id': task_id,
            'status': 'started',
            'message': '翻译任务已启动'
        })

    except Exception as e:
        logger.error(f"启动公开API翻译任务失败: {str(e)}")
        return jsonify({'error': f'启动翻译任务失败: {str(e)}'}), 500


def execute_simple_translation_task(task_id, file_path, filename):
    """执行简单翻译任务（在后台线程中运行）"""
    try:
        logger.info(f"开始执行公开API翻译任务: {task_id}")

        # 进度回调函数
        def progress_callback(current, total):
            if task_id in simple_task_status:
                progress = int((current / total) * 100) if total > 0 else 0
                simple_task_status[task_id].update({
                    'progress': progress,
                    'current_slide': current,
                    'total_slides': total
                })
                logger.info(f"公开API任务 {task_id} 进度: {current}/{total} ({progress}%)")

        # 翻译参数（使用默认值）
        stop_words_list = []
        custom_translations = {}
        select_page = []  # 处理所有页面
        source_language = "en"
        target_language = "zh"
        bilingual_translation = "1"  # 双语模式
        enable_uno_conversion = True  # 默认启用UNO转换

        # 执行翻译
        result = process_presentation(
            file_path,
            stop_words_list,
            custom_translations,
            select_page,
            source_language,
            target_language,
            bilingual_translation,
            progress_callback,
            enable_uno_conversion=enable_uno_conversion
        )

        if result:
            # 翻译成功
            simple_task_status[task_id].update({
                'status': 'completed',
                'progress': 100,
                'completed_at': datetime.now()
            })
            # 保存翻译后的文件路径
            simple_task_files[task_id] = file_path
            logger.info(f"公开API翻译任务完成: {task_id}")
        else:
            # 翻译失败
            simple_task_status[task_id].update({
                'status': 'failed',
                'error': '翻译处理失败'
            })
            logger.error(f"公开API翻译任务失败: {task_id}")

    except Exception as e:
        # 翻译异常
        error_msg = str(e)
        logger.error(f"公开API翻译任务异常: {task_id}, 错误: {error_msg}")
        simple_task_status[task_id].update({
            'status': 'failed',
            'error': error_msg
        })


@main.route('/task_status/<task_id>')
def get_simple_task_status(task_id):
    """获取特定任务状态（公开API，不需要认证）"""
    try:
        if task_id not in simple_task_status:
            return jsonify({'status': 'not_found', 'error': '任务不存在'}), 404

        task = simple_task_status[task_id]

        # 返回任务状态
        response = {
            'status': task['status'],
            'progress': task['progress'],
            'current_slide': task['current_slide'],
            'total_slides': task['total_slides']
        }

        if task['error']:
            response['error'] = task['error']

        return jsonify(response)

    except Exception as e:
        logger.error(f"获取公开API任务状态失败: {str(e)}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


@main.route('/download/<task_id>')
def download_simple_translated_file(task_id):
    """下载翻译后的文件（公开API，不需要认证）"""
    try:
        if task_id not in simple_task_status:
            return jsonify({'error': '任务不存在'}), 404

        task = simple_task_status[task_id]

        if task['status'] != 'completed':
            return jsonify({'error': '任务尚未完成'}), 400

        if task_id not in simple_task_files:
            return jsonify({'error': '翻译文件不存在'}), 404

        file_path = simple_task_files[task_id]

        if not os.path.exists(file_path):
            return jsonify({'error': '文件不存在'}), 404

        return send_file(
            file_path,
            as_attachment=True,
            download_name=f"translated_{task['original_filename']}",
            mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation'
        )

    except Exception as e:
        logger.error(f"下载公开API文件失败: {str(e)}")
        return jsonify({'error': f'下载失败: {str(e)}'}), 500


@main.route('/ppt_translate', methods=['POST'])
def ppt_translate_simple():
    """PPT翻译（公开API，兼容原有接口，不需要认证）"""
    try:
        # 检查是否有文件
        if 'file' not in request.files:
            return jsonify({'error': '没有文件'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': '没有选择文件'}), 400

        if not allowed_file(file.filename):
            return jsonify({'error': '不支持的文件格式'}), 400

        # 创建临时上传目录
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        temp_upload_dir = os.path.join(upload_folder, 'temp')
        os.makedirs(temp_upload_dir, exist_ok=True)

        # 保存上传的文件
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{timestamp}_{filename}"
        file_path = os.path.join(temp_upload_dir, unique_filename)
        file.save(file_path)

        logger.info(f"同步API文件已保存: {file_path}")

        # 翻译参数（使用默认值）
        stop_words_list = []
        custom_translations = {}
        select_page = []  # 处理所有页面
        source_language = "en"
        target_language = "zh"
        bilingual_translation = "1"  # 双语模式
        enable_uno_conversion = True  # 默认启用UNO转换

        # 执行同步翻译
        result = process_presentation(
            file_path,
            stop_words_list,
            custom_translations,
            select_page,
            source_language,
            target_language,
            bilingual_translation,
            enable_uno_conversion=enable_uno_conversion
        )

        if result:
            logger.info(f"同步API翻译完成: {file_path}")
            # 返回翻译后的文件
            return send_file(
                file_path,
                as_attachment=True,
                download_name=f"translated_{filename}",
                mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation'
            )
        else:
            return jsonify({'error': '翻译处理失败'}), 500

    except Exception as e:
        logger.error(f"同步API翻译失败: {str(e)}")
        return jsonify({'error': f'翻译失败: {str(e)}'}), 500


@main.route('/db_stats')
@login_required
def db_stats():
    """数据库状态页面"""
    if not current_user.is_administrator():
        flash('您没有权限访问此页面')
        return redirect(url_for('main.index'))
    
    # 获取数据库统计信息
    db_stats = get_db_stats()
    
    # 获取线程池统计信息
    thread_pool_stats = thread_pool.get_stats()
    
    # 获取任务队列统计信息
    queue_stats = translation_queue.get_queue_stats()
    
    return render_template('main/db_stats.html', 
                          user=current_user,
                          db_stats=db_stats,
                          thread_pool_stats=thread_pool_stats,
                          queue_stats=queue_stats)


@main.route('/db_stats_data')
@login_required
def get_db_stats_data():
    """获取数据库统计数据的API，用于AJAX刷新"""
    if not current_user.is_administrator():
        return jsonify({'error': '没有权限访问此API'}), 403
    
    # 获取数据库统计信息
    db_stats = get_db_stats()
    
    return jsonify(db_stats)


@main.route('/recycle_connections', methods=['POST'])
@login_required
def recycle_connections():
    """回收空闲数据库连接"""
    if not current_user.is_administrator():
        return jsonify({'success': False, 'message': '没有权限执行此操作'}), 403
    
    try:
        # 调用翻译队列中的回收连接方法
        result = translation_queue.recycle_idle_connections()
        
        # 记录操作日志
        logger.info(f"管理员 {current_user.username} 手动回收了数据库空闲连接")
        
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"回收数据库连接失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'回收连接失败: {str(e)}',
            'error': str(e)
        }), 500


def get_db_stats():
    """获取数据库连接池统计信息"""
    try:
        engine = db.engine
        
        # 基本信息
        stats = {
            'engine_name': engine.name,
            'driver_name': engine.driver,
            'url': str(engine.url).replace('://*:*@', '://***:***@'),  # 隐藏敏感信息
            'pool_size': engine.pool.size(),
            'current_size': engine.pool.size(),
            'checked_in': engine.pool.checkedin(),
            'checked_out': engine.pool.checkedout(),
            'overflow': engine.pool.overflow(),
            'max_overflow': engine.pool._max_overflow
        }
        
        # 获取连接池配置
        try:
            stats['pool_config'] = {
                'size': engine.pool.size(),
                'max_overflow': engine.pool._max_overflow,
                'timeout': engine.pool._timeout,
                'recycle': engine.pool._recycle,
                'pre_ping': engine.pool._pre_ping
            }
        except:
            stats['pool_config'] = None
        
        # 获取已签出连接的详细信息
        checked_out_details = []
        try:
            mutex = engine.pool._mutex
            checked_out = {}
            
            if hasattr(mutex, '_semlock') and hasattr(engine.pool, '_checked_out'):
                # SQLAlchemy 1.3+ 
                checked_out = engine.pool._checked_out
            elif hasattr(engine.pool, '_checked_out'):
                # 早期版本
                checked_out = engine.pool._checked_out
            
            for conn, (ref, traceback, timestamp) in checked_out.items():
                conn_id = str(conn)
                checkout_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                duration = time.time() - timestamp
                duration_str = f"{duration:.2f}秒"
                
                if duration > 3600:
                    hours = int(duration / 3600)
                    minutes = int((duration % 3600) / 60)
                    duration_str = f"{hours}小时{minutes}分钟"
                elif duration > 60:
                    minutes = int(duration / 60)
                    seconds = int(duration % 60)
                    duration_str = f"{minutes}分钟{seconds}秒"
                
                checked_out_details.append({
                    'connection_id': conn_id,
                    'checkout_time': checkout_time,
                    'duration': duration_str,
                    'stack_trace': '\n'.join(traceback) if traceback else '无堆栈信息'
                })
            
            stats['checked_out_details'] = checked_out_details
        except Exception as e:
            stats['checked_out_details'] = []
            logger.warning(f"获取已签出连接详情失败: {str(e)}")
        
        return stats
    
    except Exception as e:
        logger.error(f"获取数据库统计信息失败: {str(e)}")
        return {'error': f'获取数据库统计信息失败: {str(e)}'}


@main.route('/system_status', methods=['GET'])
@login_required
def system_status():
    """获取系统状态信息"""
    if not current_user.is_administrator():
        return jsonify({'error': '没有权限访问此API'}), 403
    
    try:
        # 获取线程池状态
        thread_pool_stats = thread_pool.get_stats()
        thread_pool_health = thread_pool.get_health_status()
        
        # 获取任务队列状态
        queue_stats = translation_queue.get_queue_stats()
        
        # 获取数据库连接状态
        db_stats = get_db_stats()
        
        # 系统内存使用情况
        import psutil
        memory = psutil.virtual_memory()
        memory_stats = {
            'total': memory.total,
            'available': memory.available,
            'used': memory.used,
            'percent': memory.percent
        }
        
        # CPU使用情况
        cpu_stats = {
            'percent': psutil.cpu_percent(),
            'count': psutil.cpu_count(),
            'logical_count': psutil.cpu_count(logical=True)
        }
        
        # 返回汇总状态
        status = {
            'thread_pool': {
                'stats': thread_pool_stats,
                'health': thread_pool_health
            },
            'task_queue': queue_stats,
            'database': db_stats,
            'memory': memory_stats,
            'cpu': cpu_stats,
            'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        return jsonify(status)
        
    except Exception as e:
        logger.error(f"获取系统状态失败: {str(e)}")
        return jsonify({
            'error': f'获取系统状态失败: {str(e)}'
        }), 500


@main.route('/system/reset_thread_pool', methods=['POST'])
@login_required
def reset_thread_pool():
    """重置线程池"""
    if not current_user.is_administrator():
        return jsonify({'success': False, 'message': '没有权限执行此操作'}), 403
    
    try:
        # 记录操作日志
        logger.warning(f"管理员 {current_user.username} 正在重置线程池")
        
        # 获取线程池配置
        stats_before = thread_pool.get_stats()
        
        # 重新配置线程池
        thread_pool.configure()
        
        # 获取重置后的状态
        stats_after = thread_pool.get_stats()
        
        return jsonify({
            'success': True,
            'message': '线程池已重置',
            'before': stats_before,
            'after': stats_after
        })
        
    except Exception as e:
        logger.error(f"重置线程池失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'重置线程池失败: {str(e)}',
            'error': str(e)
        }), 500


@main.route('/system/reset_task_queue', methods=['POST'])
@login_required
def reset_task_queue():
    """重置任务队列"""
    if not current_user.is_administrator():
        return jsonify({'success': False, 'message': '没有权限执行此操作'}), 403
    
    try:
        # 记录操作日志
        logger.warning(f"管理员 {current_user.username} 正在重置任务队列")
        
        # 获取任务队列状态
        stats_before = translation_queue.get_queue_stats()
        
        # 停止处理器
        translation_queue.stop_processor()
        
        # 重新启动处理器
        translation_queue.start_processor()
        
        # 获取重置后的状态
        stats_after = translation_queue.get_queue_stats()
        
        return jsonify({
            'success': True,
            'message': '任务队列已重置',
            'before': stats_before,
            'after': stats_after
        })
        
    except Exception as e:
        logger.error(f"重置任务队列失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'重置任务队列失败: {str(e)}',
            'error': str(e)
        }), 500


@main.route('/system_monitoring')
@login_required
def system_monitoring():
    """系统监控页面 - 显示线程池、任务队列和数据库连接状态"""
    # 验证用户是否有管理员权限
    if not current_user.is_administrator:
        flash('您没有访问此页面的权限。', 'danger')
        return redirect(url_for('main.index'))
    
    return render_template('main/system_monitoring.html', user=current_user)


@main.route('/pdf_annotate')
@login_required
def pdf_annotate():
    """PDF注释页面"""
    try:
        # 添加详细的日志
        logger.info("访问 pdf_annotate 页面")
        return render_template('main/pdf_annotate.html')
    except Exception as e:
        logger.error(f"渲染 pdf_annotate 页面出错: {str(e)}")
        # 返回一个简单的错误页面，避免模板渲染问题
        return f"PDF注释功能临时不可用: {str(e)}", 500


@main.route('/upload_pdf', methods=['POST'])
@login_required
def upload_pdf():
    try:
        if 'file' not in request.files:
            logger.error("没有文件部分在请求中")
            return jsonify({'error': '没有文件部分'}), 400

        file = request.files['file']
        if file.filename == '':
            logger.error("没有选择文件")
            return jsonify({'error': '没有选择文件'}), 400

        if not allowed_pdf_file(file.filename):
            logger.error(f"不允许的文件类型: {file.filename}")
            return jsonify({'error': '不允许的文件类型'}), 400

        # 生成安全的文件名和唯一的存储文件名
        original_filename = secure_filename(file.filename)
        logger.info(f"安全文件名: {original_filename}")
        stored_filename = f"{uuid.uuid4().hex}.pdf"

        # 确保上传文件夹存在
        upload_folder = current_app.config['UPLOAD_FOLDER']
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
            logger.info(f"创建上传文件夹: {upload_folder}")

        # 创建用户PDF目录
        user_pdf_dir = os.path.join(upload_folder, f"{current_user.username}_pdfs")
        logger.info(f"PDF上传目录路径: {user_pdf_dir}")

        if not os.path.exists(user_pdf_dir):
            os.makedirs(user_pdf_dir)
            logger.info(f"创建PDF上传目录: {user_pdf_dir}")

        # 保存文件
        file_path = os.path.join(user_pdf_dir, stored_filename)
        file_path = os.path.abspath(file_path)  # 转换为绝对路径
        logger.info(f"保存文件的绝对路径: {file_path}")

        file.save(file_path)
        logger.info(f"PDF文件已保存到: {file_path}")

        # 验证文件是否成功保存
        if not os.path.exists(file_path):
            raise Exception(f"文件保存失败，路径: {file_path}")

        # 检查文件权限并尝试修复
        try:
            with open(file_path, 'rb') as f:
                f.read(1)  # 测试读取
        except PermissionError:
            # 尝试修改文件权限
            try:
                import stat
                os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
                logger.info(f"已修改文件权限: {file_path}")
            except Exception as e:
                logger.error(f"无法修改文件权限: {str(e)}")
                raise Exception(f"文件无法访问，权限问题: {str(e)}")
        except Exception as e:
            raise Exception(f"文件读取测试失败: {str(e)}")

        # 生成完整的URL，包含域名和协议，确保使用与当前请求相同的协议
        file_url = url_for('main.get_pdf', filename=stored_filename, _external=True)
        
        # 确保URL使用与当前请求相同的协议(HTTP或HTTPS)
        if request.is_secure and file_url.startswith('http:'):
            file_url = file_url.replace('http:', 'https:', 1)
        
        logger.info(f"生成的PDF URL: {file_url}")

        return jsonify({
            'message': '文件上传成功',
            'filename': original_filename,
            'file_url': file_url,
            'file_path': file_path  # 添加服务器端文件路径
        })

    except Exception as e:
        logger.error(f"PDF上传错误: {str(e)}")
        # 如果文件已经保存，则删除
        if 'file_path' in locals() and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"清理失败的上传: {file_path}")
            except Exception as cleanup_error:
                logger.error(f"无法清理文件: {cleanup_error}")
        return jsonify({'error': f'上传失败: {str(e)}'}), 500


import zipfile
import requests
from werkzeug.utils import secure_filename
from datetime import datetime
import os

@main.route('/translate_pdf', methods=['POST'])
@login_required
def translate_pdf():
    """处理PDF翻译请求"""
    try:
        logger.info("收到PDF翻译请求")
        
        # 初始化自定义翻译词典
        custom_translations = {}
        
        # 检查是否有文件上传
        if 'file' not in request.files:
            logger.error("未找到上传的文件")
            return jsonify({'success': False, 'error': '未找到上传的文件'}), 400
        
        original_file = request.files['file']
        if original_file.filename == '':
            logger.error("文件名为空")
            return jsonify({'success': False, 'error': '文件名为空'}), 400

        # 生成唯一文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        unique_suffix = uuid.uuid4().hex[:8]
        unique_filename = f"{timestamp}_{unique_suffix}_{secure_filename(original_file.filename)}"
        logger.info(f"生成唯一文件名: {unique_filename}")
        
        # 获取选中的词汇表ID
        selected_vocabulary = request.form.get('selected_vocabulary', '')
        vocabulary_ids = []
        if selected_vocabulary:
            try:
                vocabulary_ids = [int(x.strip()) for x in selected_vocabulary.split(',') if x.strip()]
                logger.info(f"接收到词汇表ID: {vocabulary_ids}")
            except ValueError as e:
                logger.error(f"词汇表ID解析失败: {selected_vocabulary}, 错误: {str(e)}")
                vocabulary_ids = []
        
        # 构建自定义翻译词典
        if vocabulary_ids:
            try:
                # 查询词汇表数据（包含权限检查）
                from app.models import Translation
                translations = Translation.query.filter(
                    Translation.id.in_(vocabulary_ids),
                    db.or_(
                        Translation.user_id == current_user.id,  # 用户自己的词汇
                        Translation.is_public == True  # 公共词汇
                    )
                ).all()
                
                # 构建自定义翻译词典
                for translation in translations:
                    # 根据当前语言设置确定使用哪种语言字段作为源语言和目标语言
                    source_lang = request.form.get('source_lang', 'EN')
                    target_lang = request.form.get('target_lang', 'ZH')
                    
                    # 确定源语言和目标语言字段
                    source_field = {'EN': 'english', 'ZH': 'chinese', 'JA': 'japanese'}.get(source_lang, 'english')
                    target_field = {'EN': 'english', 'ZH': 'chinese', 'JA': 'japanese'}.get(target_lang, 'chinese')
                    
                    source_text = getattr(translation, source_field, '')
                    target_text = getattr(translation, target_field, '')
                    
                    if source_text and target_text:
                        custom_translations[source_text] = target_text
                        
                logger.info(f"构建自定义词典完成，共 {len(custom_translations)} 个词汇")
            except Exception as e:
                logger.error(f"构建自定义词典失败: {str(e)}")
                custom_translations = {}

        # 获取上传文件夹路径
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        upload_folder = current_app.config['UPLOAD_FOLDER']
        if not os.path.isabs(upload_folder):
            upload_folder = os.path.join(project_root, upload_folder)
        
        pdf_upload_dir = os.path.join(upload_folder, 'pdf_uploads')
        pdf_output_dir = os.path.join(upload_folder, 'pdf_outputs')
        
        # 确保目录存在
        os.makedirs(pdf_upload_dir, exist_ok=True)
        os.makedirs(pdf_output_dir, exist_ok=True)
        task_work_dir = os.path.join(
            pdf_output_dir,
            f"{os.path.splitext(unique_filename)[0]}_work"
        )
        os.makedirs(task_work_dir, exist_ok=True)
        
        logger.info(f"项目根目录: {project_root}")
        logger.info(f"上传文件夹配置: {current_app.config['UPLOAD_FOLDER']}")
        logger.info(f"实际上传文件夹路径: {upload_folder}")
        logger.info(f"PDF上传目录: {pdf_upload_dir}")
        logger.info(f"PDF输出目录: {pdf_output_dir}")
        
        pdf_path = os.path.join(pdf_upload_dir, unique_filename)
        original_file.save(pdf_path)
        
        logger.info(f"文件已保存到: {pdf_path}")
        
        # 验证文件是否正确保存
        if not os.path.exists(pdf_path):
            logger.error(f"文件保存失败，路径不存在: {pdf_path}")
            return jsonify({'success': False, 'error': '文件保存失败'}), 500
            
        file_size = os.path.getsize(pdf_path)
        logger.info(f"保存的文件大小: {file_size} 字节")
        
        if file_size == 0:
            logger.error("保存的文件为空")
            return jsonify({'success': False, 'error': '上传的文件为空'}), 400
        
        # 首选方案：使用OSS直链处理PDF
        result = None
        try:
            from app.function.image_ocr.oss_pdf_processor import OSSPDFProcessor
            from app.function.image_ocr.ocr_api import MinerUAPI
            
            logger.info("初始化OSS PDF处理器")
            oss_processor = OSSPDFProcessor()
            logger.info("OSS PDF处理器初始化成功")
            
            logger.info("初始化MinerU API")
            mineru_api = MinerUAPI()
            logger.info("MinerU API初始化成功")
            
            # 使用OSS直链处理PDF
            logger.info(f"开始使用OSS直链处理PDF: {pdf_path}")
            result = oss_processor.process_pdf_with_mineru(pdf_path, mineru_api, bucket="fciai", region="cn-beijing")
            
            # 根据MinerU API规范，使用code字段判断处理结果（0表示成功）
            if result and isinstance(result, dict) and result.get('code') == 0:
                logger.info("OSS直链方案处理成功")
                # 继续执行后续步骤，而不是直接返回结果
                pass
            else:
                logger.warning("OSS直链方案处理失败，尝试使用本地PDF处理器...")
                result = None
        except Exception as e:
            logger.warning(f"OSS直链方案处理失败: {e}")
            result = None
        
        # 如果OSS直链方案失败或返回空结果，使用本地PDF处理器
        if not result:
            logger.info("OSS直链方案处理失败，尝试使用本地PDF处理器...")
            try:
                from app.function.local_pdf_processor import LocalPDFProcessor
                local_processor = LocalPDFProcessor()
                result = local_processor.process_pdf(pdf_path)
                logger.info(f"本地PDF处理结果: {result}")
            except Exception as local_e:
                logger.error(f"本地PDF处理器也失败了: {local_e}")
                return jsonify({'success': False, 'error': 'PDF处理失败，请检查文件格式'}), 500
        
        if not result:
            logger.error("所有PDF处理方法都失败了")
            return jsonify({'success': False, 'error': 'PDF处理失败'}), 500
        
        # 检查结果中的状态码
        if 'code' in result and result['code'] != 0:
            error_msg = result.get('msg', '未知错误')
            logger.error(f"MinerU处理PDF失败: {error_msg}")
            return jsonify({'success': False, 'error': f'PDF处理失败: {error_msg}'}), 500
        
        # 获取任务ID和结果
        if 'data' not in result or 'task_id' not in result['data']:
            logger.error("MinerU返回结果缺少task_id")
            logger.error(f"完整结果: {result}")
            return jsonify({'success': False, 'error': 'PDF处理服务返回数据格式错误'}), 500
            
        task_id = result['data']['task_id']
        logger.info(f"MinerU任务ID: {task_id}")
        
        if 'full_zip_url' not in result['data']:
            logger.error("MinerU返回结果缺少full_zip_url")
            logger.error(f"完整结果: {result}")
            return jsonify({'success': False, 'error': 'PDF处理服务未返回下载地址'}), 500
            
        zip_url = result['data']['full_zip_url']
        logger.info(f"ZIP文件下载地址: {zip_url}")
        
        # 下载结果
        zip_filename = f"mineru_result_{task_id}.zip"
        zip_path = os.path.join(task_work_dir, zip_filename)
        
        # 下载或复制ZIP文件
        try:
            logger.info(f"开始处理ZIP文件: {zip_url}")
            
            # 检查是否是本地文件（file://协议）
            if zip_url.startswith('file://'):
                # 本地文件，直接复制
                source_path = zip_url[7:]  # 移除 'file://' 前缀
                logger.info(f"复制本地文件: {source_path} -> {zip_path}")
                
                if not os.path.exists(source_path):
                    logger.error(f"源文件不存在: {source_path}")
                    return jsonify({'success': False, 'error': '结果文件不存在'}), 500
                
                import shutil
                shutil.copy2(source_path, zip_path)
                logger.info(f"ZIP文件已复制到: {zip_path}")
            else:
                # 远程文件，使用requests下载
                logger.info(f"下载远程ZIP文件: {zip_url}")
                response = requests.get(zip_url, timeout=300)
                logger.info(f"下载响应状态码: {response.status_code}")
                if response.status_code != 200:
                    logger.error(f"下载ZIP文件失败，状态码: {response.status_code}")
                    logger.error(f"响应内容: {response.text}")
                    return jsonify({'success': False, 'error': f'下载结果文件失败，状态码: {response.status_code}'}), 500
                    
                response.raise_for_status()
                with open(zip_path, 'wb') as f:
                    f.write(response.content)
                logger.info(f"ZIP文件已保存到: {zip_path}")
                
        except Exception as e:
            logger.error(f"处理结果文件失败: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            return jsonify({'success': False, 'error': '处理结果文件失败'}), 500
        
        # 解压ZIP文件
        try:
            logger.info(f"开始解压ZIP文件: {zip_path}")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # 列出zip文件中的所有文件
                file_list = zip_ref.namelist()
                logger.info(f"ZIP文件包含以下文件: {file_list}")
                
                # 解压所有文件到任务隔离目录
                zip_ref.extractall(task_work_dir)
                logger.info(f"ZIP文件已解压到: {task_work_dir}")
        except Exception as e:
            logger.error(f"解压文件失败: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            return jsonify({'success': False, 'error': '解压文件失败'}), 500
        
        # 查找markdown文件
        md_file = None
        logger.info(f"在目录 {task_work_dir} 中查找markdown文件")
        
        # 获取解压后的所有文件列表
        extracted_files = []
        for root, dirs, files in os.walk(task_work_dir):
            for file in files:
                full_path = os.path.join(root, file)
                relative_path = os.path.relpath(full_path, task_work_dir)
                extracted_files.append(relative_path)
                logger.info(f"  解压文件: {relative_path}")
                
        logger.info(f"所有解压文件: {extracted_files}")
        
        # 按优先级查找合适的文件
        # 1. 首先查找包含task_id的markdown文件
        for file in extracted_files:
            if file.endswith('.md') and task_id in file:
                md_file = os.path.join(task_work_dir, file)
                logger.info(f"找到匹配task_id的markdown文件: {md_file}")
                break
        
        # 2. 如果没找到，查找任何markdown文件
        if not md_file:
            for file in extracted_files:
                if file.endswith('.md'):
                    md_file = os.path.join(task_work_dir, file)
                    logger.info(f"找到md文件: {md_file}")
                    break
        
        # 2. 如果仍然没找到，查找md文件
        if not md_file:
            for file in extracted_files:
                if file.endswith('.md'):
                    md_file = os.path.join(task_work_dir, file)
                    logger.info(f"找到md文件: {md_file}")
                    break
        
        # 3. 如果仍然没找到，查找txt文件
        if not md_file:
            for file in extracted_files:
                if file.endswith('.txt'):
                    md_file = os.path.join(task_work_dir, file)
                    logger.info(f"找到txt文件: {md_file}")
                    break
        
        # 无论是否找到md文件，都创建docx文件
        docx_filename = f"{os.path.splitext(unique_filename)[0]}.docx"
        docx_path = os.path.join(pdf_output_dir, docx_filename)
        
        if not md_file:
            logger.warning("未找到合适的文本文件，创建包含提示信息的Word文档")
            try:
                from docx import Document
                doc = Document()
                doc.add_heading('PDF处理结果', 1)
                doc.add_paragraph('未能从PDF中提取到文本内容，请检查原始PDF文件是否包含可提取的文本。')
                doc.add_paragraph(f'原始文件名: {original_file.filename}')
                doc.add_paragraph(f'处理时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
                
                # 添加更多诊断信息
                doc.add_paragraph('可能的故障原因:')
                doc.add_paragraph('1. PDF文件可能是扫描的图像，不含可提取文本')
                doc.add_paragraph('2. 文件可能受密码保护')
                doc.add_paragraph('3. 文本可能被PDF格式问题损坏')
                doc.add_paragraph('4. 文件可能为空或损坏')
                
                doc.save(docx_path)
                logger.info(f"创建了包含详细提示信息的文档: {docx_path}")
            except Exception as e:
                logger.error(f"创建提示信息文档失败: {e}")
                import traceback
                logger.error(f"错误详情: {traceback.format_exc()}")
                return jsonify({'success': False, 'error': '处理PDF文件失败'}), 500
        else:
            # 读取提取的文本内容
            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                logger.info(f"成功读取内容文件: {md_file}")
                logger.info(f"读取的内容长度: {len(content)} 字符")
                logger.info(f"读取的内容前200字符: {content[:200]}")
            except Exception as e:
                logger.error(f"读取内容文件失败: {e}")
                return jsonify({'success': False, 'error': '读取提取内容失败'}), 500

            # 检查是否启用图片OCR功能
            enable_image_ocr = request.form.get('enable_image_ocr', 'false').lower() == 'true'
            logger.info(f"图片OCR功能启用状态: {enable_image_ocr}")

            # 如果启用了图片OCR，则处理图片
            if enable_image_ocr:
                try:
                    from app.function.image_ocr.ocr_controller import process_markdown_images_ocr_and_translate
                    logger.info("开始处理Markdown中的图片OCR和翻译")
                    logger.info(f"Markdown目录: {os.path.dirname(md_file)}")
                    
                    # 提取原始Markdown中的图片路径，用于后续匹配
                    original_image_paths = []
                    md_dir = os.path.dirname(md_file)
                    import re
                    image_pattern = r'!\[.*?\]\((.*?)\)'
                    matches = re.findall(image_pattern, content)
                    for match in matches:
                        if match.startswith('images/'):
                            image_path = os.path.join(md_dir, match)
                        elif match.startswith('./images/'):
                            image_path = os.path.join(md_dir, match[2:])
                        elif not os.path.isabs(match):
                            image_path = os.path.join(md_dir, match)
                        else:
                            image_path = match
                        if os.path.exists(image_path):
                            original_image_paths.append((match, image_path))  # (原始路径, 实际文件路径)
                    
                    logger.info(f"找到 {len(original_image_paths)} 个原始图片路径用于匹配")
                    for orig_path, actual_path in original_image_paths:
                        logger.info(f"原始路径: {orig_path} -> 实际路径: {actual_path}")
                    
                    # 调用OCR处理函数
                    ocr_results = process_markdown_images_ocr_and_translate(
                        content, 
                        os.path.dirname(md_file),
                        target_language='zh',
                        source_language='en'
                    )
                    
                    logger.info(f"OCR处理完成，结果数量: {len(ocr_results) if ocr_results else 0}")
                    
                    if ocr_results:
                        # 创建重命名图片到原始图片的映射关系
                        image_name_mapping = {}
                        for i, (orig_path, actual_path) in enumerate(original_image_paths):
                            new_filename = f"image_{i+1:04d}{os.path.splitext(actual_path)[1]}"
                            image_name_mapping[new_filename] = orig_path
                            logger.info(f"映射: {new_filename} -> {orig_path}")
                        
                        # 在内容中插入OCR结果
                        for i, ocr_result in enumerate(ocr_results):
                            if ocr_result.get("success"):
                                image_path = ocr_result.get("image_path", "")
                                ocr_text = ocr_result.get("ocr_text_combined", "")
                                translation_text = ocr_result.get("translation_text_combined", "")
                                
                                logger.info(f"OCR结果 {i+1}: 图片={os.path.basename(image_path)}, "
                                          f"OCR文本长度={len(ocr_text)}, 翻译文本长度={len(translation_text)}")
                                
                                # 使用映射关系找到原始图片路径
                                image_filename = os.path.basename(image_path)
                                if image_filename in image_name_mapping:
                                    original_image_marker = f"![]({image_name_mapping[image_filename]})"
                                    
                                    if ocr_text or translation_text:
                                        # 构造OCR结果插入内容
                                        ocr_insertion = f"\n\n[OCR识别结果]:\n{ocr_text}\n\n[OCR翻译结果]:\n{translation_text}\n"
                                        content = content.replace(original_image_marker, original_image_marker + ocr_insertion)
                                        logger.info(f"已将OCR结果插入到图片 {image_name_mapping[image_filename]} 位置")
                                    else:
                                        logger.info(f"图片 {image_name_mapping[image_filename]} 未识别到文本内容")
                                else:
                                    logger.warning(f"未找到图片 {image_filename} 的原始路径映射")
                            else:
                                image_path = ocr_result.get("image_path", "")
                                logger.warning(f"图片OCR处理失败: {os.path.basename(image_path)}")
                    else:
                        logger.info("未找到需要OCR处理的图片")
                except Exception as ocr_e:
                    logger.error(f"处理图片OCR时出错: {ocr_e}")
                    import traceback
                    logger.error(f"OCR错误详情: {traceback.format_exc()}")
            else:
                logger.info("图片OCR功能未启用，跳过图片处理")

            # 如果配置了翻译API，则进行翻译
            qwen_api_key = os.getenv('QWEN_API_KEY')
            logger.info(f"检查Qwen API密钥: {'已配置' if qwen_api_key else '未配置'}")
            if qwen_api_key:
                try:
                    # 获取目标语言参数
                    target_language = request.form.get('target_language', 'EN')
                    
                    # 根据用户选择设置语言参数
                    # 默认源语言为中文，目标语言根据选择确定
                    lang_map = {
                        'EN': ('Chinese', 'English'),   # 中文翻译为英文
                        'ZH': ('English', 'Chinese'),   # 英文翻译为中文
                        'JA': ('Chinese', 'Japanese')   # 中文翻译为日文
                    }
                    
                    # 根据PDF内容的语言特征，调整源语言和目标语言
                    if target_language in lang_map:
                        source_lang, target_lang = lang_map[target_language]
                    else:
                        source_lang, target_lang = 'Chinese', 'English'
                    
                    logger.info(f"翻译语言设置 - 源语言: {source_lang}, 目标语言: {target_lang}")
                    
                    # 初始化翻译字典
                    translated_dict = {}
                    
                    # 使用PPT模块中的Qwen异步翻译功能
                    from app.function.local_qwen_async import translate_async
                    import asyncio
                    
                    logger.info("开始逐行扫描和翻译")
                    # 逐行扫描处理内容
                    lines = content.split('\n')
                    processed_lines = []
                    i = 0
                    
                    # 将custom_translations转换为vocabulary_prompt格式
                    vocabulary_prompt = ""
                    if custom_translations:
                        vocabulary_items = [f'"{k}": "{v}"' for k, v in custom_translations.items()]
                        vocabulary_prompt = "专业词汇表（请在翻译中优先使用以下术语的对应翻译）:\n" + "\n".join(vocabulary_items)
                    
                    while i < len(lines):
                        line = lines[i].strip()
                        
                        # 如果是空行，直接添加
                        if not line:
                            processed_lines.append("")
                            i += 1
                            continue
                        
                        # 添加原文行
                        processed_lines.append(line)
                        
                        # 检查是否为标题（以#开头）
                        if line.startswith('#'):
                            logger.info(f"检测到标题: {line}")
                            # 翻译标题
                            try:
                                # 创建新的事件循环来运行异步翻译任务
                                import asyncio
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                try:
                                    translated_dict = loop.run_until_complete(
                                        translate_async(line, "通用", [], custom_translations or {}, source_lang, target_lang, vocabulary_prompt=vocabulary_prompt)
                                    )
                                finally:
                                    loop.close()
                                
                                # 使用PDF翻译工具中的文本清理方法
                                from app.function.pdf_translation_utils import PDFTranslationUtils
                                cleaned_line = PDFTranslationUtils._strip_inline_markdown(line)
                                
                                if translated_dict and cleaned_line in translated_dict:
                                    translated_text = translated_dict[cleaned_line]
                                    if translated_text.strip() and not translated_text.startswith('[翻译错误:'):
                                        processed_lines.append("【译文】" + translated_text)
                                        logger.info(f"标题翻译完成: {line} -> {translated_text}")
                                    else:
                                        processed_lines.append("【译文】[翻译失败]")
                                        logger.warning(f"标题翻译失败: {line}")
                                else:
                                    # 增加更智能的匹配逻辑
                                    if translated_dict:
                                        logger.warning(f"标题未找到翻译结果: {line}")
                                        logger.warning(f"翻译字典键列表: {list(translated_dict.keys())}")
                                        
                                        # 尝试多种匹配策略
                                        matched = False
                                        translated_text = ""
                                        
                                        # 策略1: 精确匹配
                                        if cleaned_line in translated_dict:
                                            translated_text = translated_dict[cleaned_line]
                                            matched = True
                                        
                                        # 策略2: 去除空白字符后匹配
                                        if not matched:
                                            line_stripped = cleaned_line.strip()
                                            for key in translated_dict.keys():
                                                if key.strip() == line_stripped:
                                                    translated_text = translated_dict[key]
                                                    matched = True
                                                    logger.info(f"通过去除空白字符匹配成功: {line[:30]}...")
                                                    break
                                        
                                        # 策略3: 如果原始文本包含多个句子，尝试分割后匹配
                                        if not matched:
                                            # 检查是否可以按句号分割
                                            if '. ' in cleaned_line and len(cleaned_line) > 100:  # 长文本且包含句号
                                                sentences = cleaned_line.split('. ')
                                                # 重构句子（添加句号，除了最后一个）
                                                sentences = [s + '.' if i < len(sentences) - 1 else s 
                                                           for i, s in enumerate(sentences)]
                                                
                                                matched_fragments = []
                                                for sentence in sentences:
                                                    sentence_stripped = sentence.strip()
                                                    if sentence_stripped:
                                                        for key in translated_dict.keys():
                                                            # 精确匹配或包含关系
                                                            if (key.strip() == sentence_stripped or 
                                                                sentence_stripped in key.strip() or
                                                                key.strip() in sentence_stripped):
                                                                matched_fragments.append(translated_dict[key])
                                                                break
                                                
                                                # 如果所有片段都匹配成功
                                                if len(matched_fragments) == len([s for s in sentences if s.strip()]):
                                                    translated_text = ''.join(matched_fragments)
                                                    matched = True
                                                    logger.info(f"通过句子分割匹配成功: {line[:30]}...")
                                        
                                        # 策略4: 模糊匹配（包含关系）
                                        if not matched:
                                            for key in translated_dict.keys():
                                                if cleaned_line.strip() in key.strip() or key.strip() in cleaned_line.strip():
                                                    translated_text = translated_dict[key]
                                                    matched = True
                                                    logger.info(f"通过模糊匹配找到翻译结果: {line[:30]}... -> {translated_text[:30]}...")
                                                    break
                                        
                                        # 策略5: 部分匹配（最长公共子串）
                                        if not matched:
                                            def longest_common_substring(s1, s2):
                                                # 简单的最长公共子串计算
                                                # 返回公共子串的长度
                                                m = len(s1)
                                                n = len(s2)
                                                # 创建二维数组来存储长度
                                                LCSuff = [[0 for k in range(n+1)] for l in range(m+1)]
                                                result = 0
                                                
                                                for i in range(m + 1):
                                                    for j in range(n + 1):
                                                        if (i == 0 or j == 0):
                                                            LCSuff[i][j] = 0
                                                        elif (s1[i-1] == s2[j-1]):
                                                            LCSuff[i][j] = LCSuff[i-1][j-1] + 1
                                                            result = max(result, LCSuff[i][j])
                                                        else:
                                                            LCSuff[i][j] = 0
                                                return result
                                            
                                            # 寻找最相似的键
                                            best_match_key = None
                                            best_match_score = 0
                                            line_normalized = cleaned_line.strip().lower()
                                            
                                            for key in translated_dict.keys():
                                                key_normalized = key.strip().lower()
                                                # 计算相似度（公共子串长度/较长字符串长度）
                                                common_len = longest_common_substring(line_normalized, key_normalized)
                                                max_len = max(len(line_normalized), len(key_normalized))
                                                if max_len > 0:
                                                    similarity = common_len / max_len
                                                    if similarity > best_match_score and similarity > 0.8:  # 相似度阈值
                                                        best_match_score = similarity
                                                        best_match_key = key
                                            
                                            if best_match_key:
                                                translated_text = translated_dict[best_match_key]
                                                matched = True
                                                logger.info(f"通过部分匹配找到翻译结果: {line[:30]}... -> {translated_text[:30]}... (相似度: {best_match_score:.2f})")
                                        
                                        # 检查是否是图片标记，如果是则跳过翻译
                                        if line.strip().startswith('![') and '](' in line and line.strip().endswith(')'):
                                            processed_lines.append(line)  # 保留原图片标记
                                            logger.info(f"跳过图片标记的翻译: {line[:50]}...")
                                        elif matched and translated_text.strip() and not translated_text.startswith('[翻译错误:'):
                                            processed_lines.append("【译文】" + translated_text)
                                            logger.info(f"段落翻译完成: {line[:30]}... -> {translated_text[:30]}...")
                                        else:
                                            processed_lines.append("【译文】[翻译失败]")
                                            logger.warning(f"段落翻译失败，无法匹配: {line[:50]}...")
                                    else:
                                        processed_lines.append("【译文】[翻译失败]")
                                        logger.warning(f"翻译结果为空: {line[:50]}...")
                            except Exception as e:
                                logger.error(f"段落翻译出错: {e}")
                                processed_lines.append("【译文】[翻译出错]")
                        
                        i += 1
                    
                    # 重新组合内容
                    content = '\n'.join(processed_lines)
                    logger.info("逐行扫描和翻译处理完成")
                    
                    # 确保translated_dict已定义
                    if 'translated_dict' not in locals():
                        translated_dict = {}
                    
                    # 使用新的双语文档生成器创建Word文档
                    try:
                        from app.utils.document_generator import process_markdown_to_bilingual_doc
                        logger.info("使用新的双语文档生成器创建Word文档")
                        
                        # 确保docx_path目录存在
                        os.makedirs(os.path.dirname(docx_path), exist_ok=True)
                        
                        # 创建双语Word文档
                        success = process_markdown_to_bilingual_doc(content, translated_dict, docx_path)
                        
                        if success:
                            logger.info(f"成功创建双语Word文档: {docx_path}")
                            conversion_success = True
                        else:
                            logger.error("使用新的文档生成器创建Word文档失败")
                    except Exception as e:
                        logger.warning(f"使用新的文档生成器创建Word文档失败: {e}")
                        import traceback
                        logger.warning(f"错误详情: {traceback.format_exc()}")
                    
                except Exception as e:
                    logger.error(f"翻译过程中出错: {e}")
                    import traceback
                    logger.error(f"错误详情: {traceback.format_exc()}")
                    # 即使翻译失败也继续使用原文
            
            # 修复图片路径问题
            # 将相对路径的图片引用改为绝对路径，确保pypandoc能找到图片
            logger.info("开始处理图片路径")
            # 获取markdown文件所在目录
            md_dir = os.path.dirname(md_file)
            logger.info(f"Markdown文件所在目录: {md_dir}")
            
            # 查找所有图片文件
            image_files = []
            for root, dirs, files in os.walk(md_dir):
                for file in files:
                    if file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                        full_path = os.path.join(root, file)
                        relative_path = os.path.relpath(full_path, md_dir)
                        image_files.append((full_path, relative_path))
                        logger.info(f"找到图片文件: {relative_path}")
            
            logger.info(f"总共找到 {len(image_files)} 个图片文件")
            
            # 替换markdown中的图片路径为绝对路径
            for full_path, relative_path in image_files:
                # 构造图片引用格式
                old_ref = f'](images/{os.path.basename(relative_path)})'
                new_ref = f']({full_path})'
                content = content.replace(old_ref, new_ref)
                logger.info(f"替换图片引用: {old_ref} -> {new_ref}")
            
            # 新增：使用逐段翻译并写入Word的流程（原文+译文）
            try:
                from app.utils.document_generator import translate_markdown_to_bilingual_doc
                # 获取用户选择的语言参数
                source_lang = request.form.get('source_lang', 'EN').lower()
                target_lang = request.form.get('target_lang', 'ZH').lower()

                # 将语言代码映射为内部使用的代码
                lang_mapping = {
                    'en': 'en',
                    'zh': 'zh',
                    'ja': 'ja',
                    'english': 'en',
                    'chinese': 'zh',
                    'japanese': 'ja'
                }

                source_language = lang_mapping.get(source_lang, 'en')
                target_language = lang_mapping.get(target_lang, 'zh')

                logger.info(f"使用用户选择的语言参数: 源语言={source_language}, 目标语言={target_language}")

                ok = translate_markdown_to_bilingual_doc(
                    content,
                    docx_path,
                    source_language=source_language,
                    target_language=target_language,
                    image_base_dir=md_dir,
                    custom_translations=custom_translations  # 传递词汇表翻译
                )
                if ok:
                    # 在这里不直接返回，而是设置标志位，继续执行保存数据库记录的代码
                    conversion_success = True
                    logger.info("逐段翻译生成Word成功")
                else:
                    logger.warning('逐段翻译生成Word失败')
                    # 不直接返回错误，继续执行后续流程
            except Exception as e:
                logger.error(f"逐段翻译流程异常: {e}")
                import traceback
                logger.error(f"错误详情: {traceback.format_exc()}")
                # 不直接返回错误，继续执行后续流程
            
            # 转换markdown为Word文档
            # 尝试使用pypandoc转换内容到docx
            if not conversion_success:  # 只有在前面步骤失败时才执行这部分
                conversion_success = False  # 初始化变量
                try:
                    import pypandoc
                    logger.info(f"使用pypandoc转换内容到 {docx_path}")
                    logger.info(f"转换前内容长度: {len(content)} 字符")
                    logger.info(f"转换前内容前200字符: {content[:200]}")
                    pypandoc.convert_text(content, 'docx', format='md', outputfile=docx_path)
                    conversion_success = True
                    logger.info("pypandoc转换成功")
                except Exception as e:
                    logger.warning(f"使用pypandoc转换失败: {e}")
                    import traceback
                    logger.warning(f"错误详情: {traceback.format_exc()}")
            
            # 如果pypandoc不可用或转换失败，使用python-docx手动转换
            if not conversion_success:
                try:
                    from docx import Document
                    from docx.shared import Inches
                    doc = Document()
                except Exception as e:
                    logger.error(f"导入docx模块失败: {e}")
                    import traceback
                    logger.error(f"错误详情: {traceback.format_exc()}")
                    # 在这里可以添加备用处理方案或重新抛出异常
                    raise  # 重新抛出异常
                    
                    logger.info(f"使用python-docx手动转换内容")
                    lines = content.split('\n')
                    
                    # 按段落匹配原文和译文
                    # 创建一个用于匹配的翻译字典副本
                    translation_lookup = translated_dict.copy()
                    
                    # 用于存储最终结果
                    combined_content = []
                    
                    # 用于跟踪未匹配的译文
                    unmatched_translations = []
                    
                    # 逐个处理原始段落
                    for i, paragraph in enumerate(final_paragraphs):
                        paragraph = paragraph.strip()
                        if not paragraph:
                            continue
                            
                        # 添加原文
                        combined_content.append(paragraph)
                        
                        # 查找对应的译文
                        translated_text = None
                        
                        # 精确匹配
                        if paragraph in translation_lookup and translation_lookup[paragraph].strip() and not translation_lookup[paragraph].startswith('[翻译错误:'):
                            translated_text = translation_lookup[paragraph]
                            del translation_lookup[paragraph]
                        
                        # 如果没有找到，尝试前缀匹配
                        if not translated_text:
                            for orig_text, trans_text in list(translation_lookup.items()):
                                # 检查原文和译文是否满足任一匹配条件
                                if trans_text.strip() and not trans_text.startswith('[翻译错误:') and (
                                    orig_text.startswith(paragraph) or 
                                    paragraph.startswith(orig_text) or
                                    len(set(orig_text.split()) & set(paragraph.split())) / max(len(orig_text.split()), 1) > 0.7
                                ):
                                    translated_text = trans_text
                                    del translation_lookup[orig_text]
                                    break
                        
                        # 如果仍然没有找到，尝试模糊匹配
                        if not translated_text and translated_dict:
                            # 取第一个可用的译文作为备选
                            for orig_text, trans_text in list(translated_dict.items()):
                                if trans_text.strip() and not trans_text.startswith('[翻译错误:') and orig_text in translation_lookup:
                                    translated_text = trans_text
                                    del translation_lookup[orig_text]
                                    break
                        
                        # 如果找到对应的译文且不是错误标记，添加到内容中
                        if translated_text and not translated_text.startswith('[翻译错误:'):
                            # 确保译文另起一行显示
                            combined_content.append(paragraph)  # 先添加原文
                            combined_content.append("【译文】" + translated_text)  # 再添加译文，另起一行
                        # 即使翻译失败或没有找到匹配译文，也不添加任何内容（包括占位符）
                        # 这样可以避免在最终结果中显示"翻译失败"或"[未找到匹配译文]"
                        else:
                            # 尝试重新翻译该段落，确保不会有翻译失败的情况
                            retry_translated_text = None
                            try:
                                # 使用默认翻译服务重新翻译
                                from app.function.translate_by_qwen import translate_qwen
                                # 分析段落所属领域
                                field = "通用"
                                stop_words = []  # 可以根据需要添加停止词
                                custom_translations = {}  # 可以根据需要添加自定义翻译
                                
                                # 调用翻译函数
                                retry_result = translate_qwen(paragraph, field, stop_words, custom_translations, 'auto', 'zh')
                                
                                # 从结果字典中获取译文
                                if paragraph in retry_result:
                                    retry_translated_text = retry_result[paragraph]
                                
                                if retry_translated_text and not retry_translated_text.startswith('[翻译错误:]'):
                                    combined_content.append(paragraph)  # 先添加原文
                                    combined_content.append("")  # 添加空行
                                    combined_content.append("【译文】" + retry_translated_text)  # 再添加译文，另起一行
                                    combined_content.append("")  # 添加空行
                                else:
                                    # 即使重试失败也只添加原文
                                    combined_content.append(paragraph)
                                    combined_content.append("")  # 添加空行
                            except Exception as retry_error:
                                logger.warning(f"重试翻译失败: {retry_error}")
                                # 即使重试失败也只添加原文
                                combined_content.append(paragraph)
                                combined_content.append("")  # 添加空行
                    
                    # 重新组合内容，使用换行符连接，确保原文和译文各自独立成行
                    content = '\n'.join(combined_content)
                    logger.info("按段落匹配原文和译文完成")
            
            # 修复图片路径问题
                logger.error(f"翻译过程中出错: {e}")
                import traceback
                logger.error(f"错误详情: {traceback.format_exc()}")
                # 即使翻译失败也继续使用原文
            
            # 修复图片路径问题

            
            # 修复图片路径问题

            
            # 修复图片路径问题

            
            # 修复图片路径问题

            
            # 修复图片路径问题

            
            # 修复图片路径问题

            
            # 修复图片路径问题

            
            # 修复图片路径问题
            # 将相对路径的图片引用改为绝对路径，确保pypandoc能找到图片
            logger.info("开始处理图片路径")
            # 获取markdown文件所在目录
            md_dir = os.path.dirname(md_file)
            logger.info(f"Markdown文件所在目录: {md_dir}")
            
            # 查找所有图片文件
            image_files = []
            for root, dirs, files in os.walk(md_dir):
                for file in files:
                    if file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                        full_path = os.path.join(root, file)
                        relative_path = os.path.relpath(full_path, md_dir)
                        image_files.append((full_path, relative_path))
                        logger.info(f"找到图片文件: {relative_path}")
            
            logger.info(f"总共找到 {len(image_files)} 个图片文件")
            
            # 替换markdown中的图片路径为绝对路径
            for full_path, relative_path in image_files:
                # 构造图片引用格式
                old_ref = f'](images/{os.path.basename(relative_path)})'
                new_ref = f']({full_path})'
                content = content.replace(old_ref, new_ref)
                logger.info(f"替换图片引用: {old_ref} -> {new_ref}")
            
            # 转换markdown为Word文档
            # 尝试使用pypandoc转换内容到docx
            if not conversion_success:  # 只有在前面步骤失败时才执行这部分
                conversion_success = False  # 初始化变量
                try:
                    import pypandoc
                    logger.info(f"使用pypandoc转换内容到 {docx_path}")
                    logger.info(f"转换前内容长度: {len(content)} 字符")
                    logger.info(f"转换前内容前200字符: {content[:200]}")
                    pypandoc.convert_text(content, 'docx', format='md', outputfile=docx_path)
                    conversion_success = True
                    logger.info("pypandoc转换成功")
                except Exception as e:
                    logger.warning(f"使用pypandoc转换失败: {e}")
                    import traceback
                    logger.warning(f"错误详情: {traceback.format_exc()}")
            
            # 如果pypandoc不可用或转换失败，使用python-docx手动转换
            if not conversion_success:
                try:
                    from docx import Document
                    from docx.shared import Inches
                    doc = Document()
                    
                    logger.info(f"使用python-docx手动转换内容")
                    lines = content.split('\n')
                    
                    # 简单处理内容，支持双语对照格式
                    i = 0
                    while i < len(lines):
                        line = lines[i].strip()
                        if line.startswith('#'):
                            # 处理标题 (最多支持6级标题)
                            level = min(line.count('#'), 6)
                            doc.add_heading(line.lstrip('# ').strip(), level=level)
                            
                            # 检查下一行是否为该标题的译文
                            if i + 1 < len(lines) and lines[i + 1].strip().startswith('【译文】'):
                                # 添加译文段落，使用灰色字体以便区分
                                from docx.shared import RGBColor
                                paragraph = doc.add_paragraph()
                                run = paragraph.add_run(lines[i + 1].strip()[5:].strip())  # 去掉"【译文】"前缀
                                run.font.color.rgb = RGBColor(128, 128, 128)  # 灰色字体
                                i += 2  # 跳过标题和译文两行
                            else:
                                i += 1  # 只跳过标题行
                        elif line.startswith('* ') or line.startswith('- '):
                            # 处理无序列表
                            doc.add_paragraph(line[2:].strip(), style='ListBullet')
                            i += 1
                        elif line.startswith('1. '):
                            # 处理有序列表
                            doc.add_paragraph(line[3:].strip(), style='ListNumber')
                            i += 1
                        elif line.startswith('【译文】'):
                            # 处理译文段落，使用灰色字体以便区分
                            from docx.shared import RGBColor
                            paragraph = doc.add_paragraph()
                            run = paragraph.add_run(line[5:].strip())  # 去掉"【译文】"前缀
                            run.font.color.rgb = RGBColor(128, 128, 128)  # 灰色字体
                            i += 1
                        elif line.startswith('![') and '](' in line and line.endswith(')'):
                            # 处理图片
                            try:
                                # 提取图片路径
                                start = line.find('](') + 2
                                end = line.rfind(')')
                                image_path = line[start:end]
                                
                                # 添加图片到文档
                                full_image_path = None
                                if os.path.isabs(image_path):
                                    full_image_path = image_path
                                else:
                                    # 相对于Markdown文件的路径
                                    full_image_path = os.path.join(os.path.dirname(md_file), image_path)
                                
                                if os.path.exists(full_image_path):
                                    doc.add_picture(full_image_path, width=Inches(6))  # 设置图片宽度
                                    logger.info(f"添加图片到文档: {full_image_path}")
                                else:
                                    logger.warning(f"图片文件不存在: {full_image_path}")
                                    # 添加图片路径作为文本占位符
                                    doc.add_paragraph(f"[图片: {os.path.basename(image_path)}]")
                                    
                                # 检查下一行是否为OCR结果
                                if i + 1 < len(lines):
                                    next_line = lines[i + 1].strip()
                                    if next_line.startswith('[OCR识别结果]:'):
                                        # 添加OCR识别结果
                                        doc.add_heading('OCR识别结果', level=3)
                                        ocr_start = i + 2
                                        ocr_end = ocr_start
                                        # 查找OCR翻译结果或下一个图片标记
                                        while ocr_end < len(lines):
                                            if lines[ocr_end].strip().startswith('[OCR翻译结果]:') or \
                                               (ocr_end + 1 < len(lines) and lines[ocr_end + 1].strip().startswith('![') and '](' in lines[ocr_end + 1] and lines[ocr_end + 1].strip().endswith(')')):
                                                break
                                            ocr_end += 1
                                        
                                        # 添加OCR识别文本
                                        ocr_text = '\n'.join(lines[ocr_start:ocr_end]).strip()
                                        if ocr_text:
                                            doc.add_paragraph(ocr_text)
                                        
                                        # 检查是否有OCR翻译结果
                                        if ocr_end < len(lines) and lines[ocr_end].strip().startswith('[OCR翻译结果]:'):
                                            doc.add_heading('OCR翻译结果', level=3)
                                            trans_start = ocr_end + 1
                                            trans_end = trans_start
                                            # 查找下一个图片标记
                                            while trans_end < len(lines):
                                                if trans_end + 1 < len(lines) and lines[trans_end + 1].strip().startswith('![') and '](' in lines[trans_end + 1] and lines[trans_end + 1].strip().endswith(')'):
                                                    break
                                                trans_end += 1
                                            
                                            # 添加OCR翻译文本
                                            trans_text = '\n'.join(lines[trans_start:trans_end]).strip()
                                            if trans_text:
                                                doc.add_paragraph(trans_text)
                                            
                                            i = trans_end  # 更新索引
                                        else:
                                            i = ocr_end  # 更新索引
                                        continue  # 继续下一次循环
                                        
                            except Exception as img_error:
                                logger.error(f"处理图片时出错: {img_error}")
                                # 添加图片路径作为文本占位符
                                if '](' in line:
                                    start = line.find('](') + 2
                                    end = line.rfind(')')
                                    image_path = line[start:end] if end > start else "未知图片"
                                    doc.add_paragraph(f"[图片: {os.path.basename(image_path)}]")
                            i += 1
                        elif line.strip() == '':
                            # 空行跳过，但确保段落分隔
                            i += 1
                    conversion_success = True
                    logger.info("python-docx转换成功")
                except Exception as e2:
                    logger.error(f"使用python-docx转换也失败了: {e2}")
                    import traceback
                    logger.error(f"错误详情: {traceback.format_exc()}")
                    # 即使转换失败，也创建一个包含原始内容的docx文件
                    try:
                        from docx import Document
                        doc = Document()
                        doc.add_heading('PDF内容提取结果', 1)
                        doc.add_paragraph('以下是直接从提取结果中获取的内容:')
                        
                        # 添加内容到文档中，支持双语格式
                        lines = content.split('\n')
                        i = 0
                        while i < len(lines):
                            line = lines[i].strip()
                            if line.startswith('#'):
                                # 处理标题 (最多支持6级标题)
                                level = min(line.count('#'), 6)
                                doc.add_heading(line.lstrip('# ').strip(), level=level)
                                
                                # 检查下一行是否为该标题的译文
                                if i + 1 < len(lines) and lines[i + 1].strip().startswith('【译文】'):
                                    # 添加译文段落，使用灰色字体以便区分
                                    from docx.shared import RGBColor
                                    paragraph = doc.add_paragraph()
                                    run = paragraph.add_run(lines[i + 1].strip()[5:].strip())  # 去掉"【译文】"前缀
                                    run.font.color.rgb = RGBColor(128, 128, 128)  # 灰色字体
                                    i += 2  # 跳过标题和译文两行
                                else:
                                    i += 1  # 只跳过标题行
                            elif line.startswith('【译文】'):
                                # 特殊处理译文段落
                                from docx.shared import RGBColor
                                paragraph = doc.add_paragraph()
                                run = paragraph.add_run(line[5:].strip())  # 去掉"【译文】"前缀
                                run.font.color.rgb = RGBColor(128, 128, 128)  # 灰色字体
                                i += 1
                            elif line:
                                # 添加原文段落
                                doc.add_paragraph(line)
                                
                                # 检查下一行是否为该段落的译文
                                if i + 1 < len(lines) and lines[i + 1].strip().startswith('【译文】'):
                                    # 添加译文段落，使用灰色字体以便区分
                                    from docx.shared import RGBColor
                                    paragraph = doc.add_paragraph()
                                    run = paragraph.add_run(lines[i + 1].strip()[5:].strip())  # 去掉"【译文】"前缀
                                    run.font.color.rgb = RGBColor(128, 128, 128)  # 灰色字体
                                    i += 2  # 跳过原文和译文两行
                                else:
                                    i += 1  # 只跳过原文行
                            else:
                                i += 1
                        
                        doc.save(docx_path)
                        conversion_success = True
                        logger.info("创建了包含内容的文档")
                    except Exception as e3:
                        logger.error(f"创建包含内容的文档也失败了: {e3}")
                        import traceback
                        logger.error(f"错误详情: {traceback.format_exc()}")
                        conversion_success = False
                        
                # 如果所有转换方法都失败了，则返回错误
                if not conversion_success:
                    return jsonify({'success': False, 'error': '转换Word文档失败'}), 500
                
        logger.info("开始执行保存记录到数据库的流程")
        
        # 记录到数据库
        try:
            from app.models.upload_record import UploadRecord
            from app.models.user import User
            
            logger.info(f"开始保存上传记录到数据库: user_id={current_user.id}, filename={original_file.filename}")
            logger.info(f"当前用户ID: {current_user.id}, 用户对象: {current_user}")
            
            # 检查用户是否存在
            user = User.query.get(current_user.id)
            logger.info(f"查询用户结果: {user}")
            if not user:
                logger.error(f"用户ID {current_user.id} 不存在")
                raise ValueError(f"用户ID {current_user.id} 不存在")
            
            logger.info(f"确认用户存在: id={user.id}, username={user.username}")
            
            # 打印数据库连接信息
            logger.info(f"当前数据库连接: {db.engine.url}")
            
            # 检查文件是否存在
            logger.info(f"检查文件是否存在: {docx_path}")
            if not os.path.exists(docx_path):
                logger.error(f"翻译后的文件不存在: {docx_path}")
                raise FileNotFoundError(f"翻译后的文件不存在: {docx_path}")
            
            # 获取文件大小
            file_size = os.path.getsize(docx_path)
            logger.info(f"文件大小: {file_size} 字节")
            
            # 创建记录对象
            logger.info("准备创建UploadRecord对象")
            record = UploadRecord(
                filename=original_file.filename,  # 原始文件名
                stored_filename=docx_filename,
                file_path=pdf_output_dir,
                user_id=current_user.id,
                file_size=file_size,
                status='completed'
            )
            
            logger.info(f"创建UploadRecord对象完成: {record}")
            logger.info(f"UploadRecord属性: filename={record.filename}, stored_filename={record.stored_filename}, file_path={record.file_path}, user_id={record.user_id}, file_size={record.file_size}, status={record.status}")
            logger.info(f"准备添加记录到会话")
            db.session.add(record)
            logger.info(f"记录已添加到会话")
            logger.info(f"准备提交记录: filename={record.filename}, stored_filename={record.stored_filename}, file_path={record.file_path}, user_id={record.user_id}, file_size={record.file_size}, status={record.status}")
            
            # 检查会话状态后再提交
            logger.info(f"检查会话状态: is_active={db.session.is_active}")
            if db.session.is_active:
                logger.info("会话活跃，准备提交")
                db.session.commit()
                logger.info("上传记录已保存到数据库")
                logger.info(f"记录ID: {record.id}")
                
                # 验证记录是否真的保存成功
                logger.info("开始验证记录是否保存成功")
                fresh_record = UploadRecord.query.get(record.id)
                if fresh_record:
                    logger.info(f"验证成功，数据库中存在记录ID: {fresh_record.id}")
                else:
                    logger.error(f"验证失败，数据库中不存在记录ID: {record.id}")
                    raise Exception(f"验证失败，数据库中不存在记录ID: {record.id}")
            else:
                logger.error("会话已失效，回滚事务")
                db.session.rollback()
                raise Exception("数据库会话已失效")
                
        except Exception as e:
            logger.error(f"保存上传记录失败: {e}")
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"错误详情: {error_details}")
            print(f"保存上传记录失败: {e}")  # 强制打印到控制台
            print(f"错误详情: {error_details}")  # 强制打印到控制台
            # 即使数据库记录失败，我们仍然返回成功，因为文件已生成
            db.session.rollback()
            # 修改这里：当数据库记录保存失败时，返回错误而不是继续执行
            return jsonify({'success': False, 'error': f'保存上传记录失败: {str(e)}'}), 500
        
        logger.info(f"PDF翻译完成，生成文件: {docx_path}")
        logger.info("准备返回JSON响应")
        response = jsonify({
            'success': True,
            'message': 'PDF翻译完成',
            'filename': os.path.basename(docx_path),
            'stored_filename': os.path.basename(docx_path),
            'file_path': docx_path,
            'download_url': url_for('main.download_translated_pdf', filename=os.path.basename(docx_path), _external=True)
        })
        logger.info("JSON响应已创建")
        return response
        
    except Exception as e:
        logger.error(f"处理PDF翻译时出错: {e}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'处理PDF翻译时出错: {str(e)}'}), 500


@main.route('/download_translated_pdf/<filename>')
@login_required
def download_translated_pdf(filename):
    """下载翻译后的PDF文件（实际上是Word文档）"""
    try:
        logger.info(f"用户 {current_user.username} 请求下载文件: {filename}")
        
        from werkzeug.utils import secure_filename
        filename = secure_filename(filename)
        logger.info(f"安全文件名: {filename}")
        
        project_root = (os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        upload_folder = current_app.config['UPLOAD_FOLDER']
        if not os.path.isabs(upload_folder):
            upload_folder = os.path.join(project_root, upload_folder)
        
        pdf_output_dir = os.path.join(upload_folder, 'pdf_outputs')
        expected_path = os.path.join(pdf_output_dir, filename)
        absolute_expected_path = os.path.abspath(expected_path)
        
        logger.info(f"项目根目录: {project_root}")
        logger.info(f"上传文件夹配置: {current_app.config['UPLOAD_FOLDER']}")
        logger.info(f"实际上传文件夹路径: {upload_folder}")
        logger.info(f"PDF输出目录: {pdf_output_dir}")
        logger.info(f"期望的文件路径: {expected_path}")
        logger.info(f"文件绝对路径: {absolute_expected_path}")
        
        if not os.path.exists(pdf_output_dir):
            logger.error(f"PDF输出目录不存在: {pdf_output_dir}")
            return jsonify({'success': False, 'error': '文件目录不存在'}), 404
        
        candidate_paths = [absolute_expected_path]
        if not filename.lower().endswith('.docx'):
            candidate_paths.append(os.path.abspath(os.path.join(pdf_output_dir, f"{filename}.docx")))
        
        file_path = next((path for path in candidate_paths if os.path.exists(path)), None)
        if not file_path:
            logger.error(f"下载文件不存在或不匹配: {absolute_expected_path}")
            logger.info(f"候选路径: {candidate_paths}")
            try:
                logger.info(f"目录现有文件: {os.listdir(pdf_output_dir)}")
            except Exception as list_error:
                logger.warning(f"列出目录失败: {list_error}")
            return jsonify({'success': False, 'error': '文件不存在'}), 404
        
        download_name = os.path.basename(file_path)
        
        logger.info(f"准备发送文件给用户: {file_path}")
        logger.info(f"文件大小: {os.path.getsize(file_path)} 字节")
        logger.info(f"文件绝对路径: {os.path.abspath(file_path)}")
        
        return send_file(file_path, as_attachment=True, download_name=download_name)
    except Exception as e:
        logger.error(f"下载文件时出错: {e}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'下载文件时出错: {str(e)}'}), 500

@main.route('/api/pdf_translation/delete', methods=['POST'])
@login_required
def delete_pdf_translation():
    """根据文件名删除PDF历史记录及物理文件（若存在记录）"""
    try:
        data = request.get_json(silent=True) or {}
        filename = data.get('filename')
        if not filename:
            return jsonify({'success': False, 'error': '缺少文件名'}), 400

        from werkzeug.utils import secure_filename
        filename = secure_filename(filename)

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        upload_folder = current_app.config['UPLOAD_FOLDER']
        if not os.path.isabs(upload_folder):
            upload_folder = os.path.join(project_root, upload_folder)
        pdf_output_dir = os.path.join(upload_folder, 'pdf_outputs')
        file_path = os.path.join(pdf_output_dir, filename)

        # 删除物理文件
        file_deleted = False
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                file_deleted = True
            except Exception as e:
                logger.warning(f"删除文件失败: {file_path}, {e}")

        # 删除数据库记录（按 stored_filename 匹配）
        from app.models.upload_record import UploadRecord
        record_deleted = False
        try:
            record = UploadRecord.query.filter_by(user_id=current_user.id, stored_filename=filename).first()
            if record:
                db.session.delete(record)
                db.session.commit()
                record_deleted = True
        except Exception as e:
            logger.warning(f"删除数据库记录失败: {e}")
            db.session.rollback()

        return jsonify({'success': True, 'file_deleted': file_deleted, 'record_deleted': record_deleted})
    except Exception as e:
        logger.error(f"删除PDF历史时出错: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@main.route('/download/<int:record_id>')
@login_required
def download_translated_file(record_id):
    """下载翻译后的文件"""
    try:
        from app.models.upload_record import UploadRecord
        record = UploadRecord.query.get(record_id)
        print(record_id)
        if not record:
            flash('文件记录不存在', 'error')
            return redirect(url_for('main.index'))
        
        # 构造完整文件路径
        file_path = os.path.join(record.file_path, record.stored_filename)
        print("*********************************************************")
        print(file_path)
        print("*********************************************************")

        # 路径兜底处理：
        # 1) 如果记录里是相对路径或文件不存在，按配置的UPLOAD_FOLDER重建绝对路径
        if not os.path.isabs(file_path) or not os.path.exists(file_path):
            try:
                base_upload = current_app.config.get('UPLOAD_FOLDER')
                if base_upload:
                    # 如果配置是相对路径，拼到应用根
                    if not os.path.isabs(base_upload):
                        base_upload = os.path.join(os.path.dirname(current_app.root_path), base_upload)
                    candidate = os.path.join(base_upload, f"user_{record.user_id}", record.stored_filename)
                    if os.path.exists(candidate):
                        file_path = candidate
                # 2) 兼容历史绝对路径中包含 /app/uploads 的情况，替换为 /uploads
                if not os.path.exists(file_path):
                    alt = file_path.replace("/app/uploads/", "/uploads/")
                    if alt != file_path and os.path.exists(alt):
                        file_path = alt
            except Exception:
                pass

        # 最终检查
        if not os.path.exists(file_path):
            flash('文件不存在', 'error')
            return redirect(url_for('main.index'))
        
        # 构造下载文件名
        download_filename = f"translated_{record.filename}"
        
        return send_file(file_path, as_attachment=True, download_name=download_filename)
    except Exception as e:
        logger.error(f"下载文件时出错: {e}")
        flash('下载文件时出错', 'error')
        return redirect(url_for('main.index'))


@main.route('/file_management')
@login_required
def file_management():
    """文件管理页面 - 管理员可查看所有用户上传的文件"""
    if not current_user.is_administrator():
        flash('没有权限访问此页面')
        return redirect(url_for('main.index'))
        
    return render_template('main/file_management.html', user=current_user)


@main.route('/user_management')
@login_required
def user_management():
    """用户管理页面 - 仅管理员可见"""
    if not current_user.is_administrator():
        flash('没有权限访问此页面')
        return redirect(url_for('main.index'))
    return render_template('main/user_management.html', user=current_user)


@main.route('/api/admin/files')
@login_required
def get_admin_files():
    """获取所有用户上传的文件 (仅管理员)"""
    if not current_user.is_administrator():
        return jsonify({'error': '没有权限访问此API'}), 403
        
    try:
        # 查询所有文件记录
        records = UploadRecord.query.order_by(UploadRecord.upload_time.desc()).all()
        
        # 构建文件列表，包含用户信息
        files = []
        for record in records:
            # 查询用户信息
            user = User.query.get(record.user_id)
            username = user.username if user else "未知用户"
            
            # 检查文件是否存在
            file_exists = os.path.exists(os.path.join(record.file_path, record.stored_filename))
            
            # 使用ISO格式返回时间，让前端正确处理时区
            upload_time = datetime_to_isoformat(record.upload_time)
            
            files.append({
                'id': record.id,
                'filename': record.filename,
                'stored_filename': record.stored_filename,
                'file_path': record.file_path,
                'file_size': record.file_size,
                'upload_time': upload_time,
                'status': record.status,
                'error_message': record.error_message,
                'user_id': record.user_id,
                'username': username,
                'file_exists': file_exists
            })
            
        return jsonify({
            'files': files,
            'total': len(files)
        })
        
    except Exception as e:
        logger.error(f"获取管理员文件列表失败: {str(e)}")
        return jsonify({
            'error': f'获取文件列表失败: {str(e)}',
            'files': [],
            'total': 0
        }), 500


@main.route('/api/admin/files/<int:record_id>', methods=['DELETE'])
@login_required
def admin_delete_file(record_id):
    """管理员删除文件"""
    if not current_user.is_administrator():
        return jsonify({'error': '没有权限执行此操作'}), 403
        
    try:
        # 获取上传记录
        record = UploadRecord.query.get_or_404(record_id)
        
        # 删除物理文件
        file_path = os.path.join(record.file_path, record.stored_filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"管理员删除文件: {file_path}")
        
        # 删除数据库记录
        db.session.delete(record)
    except Exception as e:
        db.session.rollback()
        logger.error(f"管理员删除文件失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'删除文件失败: {str(e)}'
        }), 500
        db.session.commit()
    return jsonify({
            'success': True,
            'message': '文件删除成功'
        })


@main.route('/api/translation_history')
@login_required
def translation_history():
    """获取翻译历史记录"""
    try:
        # 获取查询参数
        file_type = request.args.get('type', '')
        
        # 构建查询 - 先按用户筛选，不强制状态=completed，避免写库异常导致历史缺失
        query = UploadRecord.query.filter_by(user_id=current_user.id)
        
        # 按上传时间倒序排列
        records = query.order_by(UploadRecord.upload_time.desc()).all()

        # 格式化记录
        history_records = []
        for record in records:
            # 仅保留PDF翻译生成的记录（目录包含 pdf_outputs）
            try:
                if 'pdf_outputs' not in (record.file_path or ''):
                    continue
            except Exception:
                pass
            # 检查文件是否仍然存在
            file_path = os.path.join(record.file_path, record.stored_filename)
            file_exists = os.path.exists(file_path)
            
            # 如果文件不存在，尝试在pdf_outputs目录中查找
            if not file_exists:
                try:
                    # 构建项目根目录和pdf_outputs路径
                    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    upload_folder = current_app.config['UPLOAD_FOLDER']
                    if not os.path.isabs(upload_folder):
                        upload_folder = os.path.join(project_root, upload_folder)
                    pdf_output_dir = os.path.join(upload_folder, 'pdf_outputs')
                    
                    # 在pdf_outputs目录中查找文件
                    potential_file_path = os.path.join(pdf_output_dir, record.stored_filename)
                    if os.path.exists(potential_file_path):
                        file_exists = True
                        file_path = potential_file_path
                        logger.info(f"在pdf_outputs目录中找到历史文件: {file_path}")
                except Exception as e:
                    logger.warning(f"查找历史文件时出错: {e}")

            # 使用ISO格式返回时间，让前端正确处理时区
            upload_time = datetime_to_isoformat(record.upload_time)
            
            # 直接使用数据库中存储的文件名
            history_records.append({
                'id': record.id,
                'filename': record.filename,  # 使用数据库中存储的文件名
                'stored_filename': getattr(record, 'stored_filename', None),
                'file_size': record.file_size,
                'upload_time': upload_time,
                'status': record.status,
                'file_exists': file_exists
            })

        # 如果指定了文件类型，则在Python层面进行过滤（避免SQL层面的字段不存在错误）
        if file_type:
            filtered_records = []
            for record in history_records:
                # 由于数据库中可能没有file_type字段，我们只能通过文件名后缀等方式大致判断
                # 这里简化处理，如果需要精确过滤，需要在数据库中添加file_type字段
                if file_type == 'pdf_translation':
                    # 简单地通过文件名判断是否为PDF翻译记录
                    if record['filename'].endswith('.docx') or 'translated' in record['filename']:
                        filtered_records.append(record)
                else:
                    # 对于其他类型，暂时不过滤
                    filtered_records.append(record)
            history_records = filtered_records

        return jsonify(history_records)
        
    except Exception as e:
        logger.error(f"获取PDF翻译历史记录失败: {e}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")
        return jsonify({
            'status': 'error',
            'message': '获取历史记录失败'
        }), 500

        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")
        return jsonify({
            'status': 'error',
            'message': '获取历史记录失败'
        }), 500
        template_path = './批量上传词汇(模板).xlsx'

        if not os.path.exists(template_path):
            # 如果模板文件不存在，创建它
            create_template_file(template_path)

        return send_file(
            template_path,
            as_attachment=True,
            download_name='批量上传词汇模板.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        logger.error(f"下载模板文件失败: {str(e)}")
        return jsonify({'error': f'下载模板文件失败: {str(e)}'}), 500


@main.route('/api/pdf_translation_history')
@login_required
def pdf_translation_history():
    """获取PDF翻译历史记录"""
    try:
        logger.info("[PDF History] 开始查询历史记录")
        # 构建查询 - 只返回状态为 completed 的记录
        query = UploadRecord.query.filter_by(user_id=current_user.id, status='completed')
        
        # 按上传时间倒序排列
        records = query.order_by(UploadRecord.upload_time.desc()).all()
        logger.info(f"[PDF History] 查询到用户记录数: {len(records)}")

        # 格式化记录
        history_records = []
        for record in records:
            try:
                logger.info(f"[PDF History] 记录: id={record.id}, filename={record.filename}, stored={record.stored_filename}, path={record.file_path}")
            except Exception:
                pass

            # 通过存储文件的后缀来判断是否为PDF翻译记录（PDF翻译结果是.docx文件）
            stored_file_ext = os.path.splitext(record.stored_filename)[1].lower() if record.stored_filename else ''
            if stored_file_ext != '.docx':
                logger.info(f"[PDF History] 过滤非PDF翻译记录: id={record.id}, stored_filename={record.stored_filename}")
                continue

            # 检查文件是否仍然存在
            file_path = os.path.join(record.file_path, record.stored_filename)
            file_exists = os.path.exists(file_path)
            logger.info(f"[PDF History] 文件存在: {file_exists}, full_path={file_path}")
            
            # 如果文件不存在，尝试在pdf_outputs目录中查找
            if not file_exists:
                try:
                    # 构建项目根目录和pdf_outputs路径
                    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    upload_folder = current_app.config['UPLOAD_FOLDER']
                    if not os.path.isabs(upload_folder):
                        upload_folder = os.path.join(project_root, upload_folder)
                    pdf_output_dir = os.path.join(upload_folder, 'pdf_outputs')
                    
                    # 在pdf_outputs目录中查找文件
                    potential_file_path = os.path.join(pdf_output_dir, record.stored_filename)
                    if os.path.exists(potential_file_path):
                        file_exists = True
                        file_path = potential_file_path
                        logger.info(f"在pdf_outputs目录中找到历史文件: {file_path}")
                except Exception as e:
                    logger.warning(f"查找历史文件时出错: {e}")

            # 使用ISO格式返回时间，让前端正确处理时区
            upload_time = datetime_to_isoformat(record.upload_time)
            
            # 直接使用数据库中存储的文件名
            history_records.append({
                'id': record.id,
                'filename': record.filename,  # 使用数据库中存储的文件名
                'stored_filename': getattr(record, 'stored_filename', None),
                'file_size': record.file_size,
                'upload_time': upload_time,
                'status': record.status,
                'file_exists': file_exists
            })

        logger.info(f"[PDF History] 返回记录数: {len(history_records)}")
        return jsonify(history_records)
        
    except Exception as e:
        logger.error(f"获取PDF翻译历史记录失败: {e}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")
        return jsonify({
            'status': 'error',
            'message': '获取历史记录失败'
        }), 500


@main.route('/api/ppt_translation_history')
@login_required
def ppt_translation_history():
    """获取PPT翻译历史记录"""
    try:
        logger.info("[PPT History] 开始查询历史记录")
        # 构建查询 - 只返回状态为 completed 的记录
        query = UploadRecord.query.filter_by(user_id=current_user.id, status='completed')

        # 按上传时间倒序排列
        records = query.order_by(UploadRecord.upload_time.desc()).all()
        logger.info(f"[PPT History] 查询到用户记录数: {len(records)}")

        # 格式化记录
        history_records = []
        for record in records:
            try:
                logger.info(f"[PPT History] 记录: id={record.id}, filename={record.filename}, stored={record.stored_filename}, path={record.file_path}")
            except Exception:
                pass

            # 通过原始文件的后缀来判断是否为PPT翻译记录
            original_file_ext = os.path.splitext(record.filename)[1].lower() if record.filename else ''
            if original_file_ext not in ['.ppt', '.pptx']:
                logger.info(f"[PPT History] 过滤非PPT翻译记录: id={record.id}, filename={record.filename}")
                continue

            # 检查文件是否仍然存在
            file_path = os.path.join(record.file_path, record.stored_filename)
            file_exists = os.path.exists(file_path)
            logger.info(f"[PPT History] 文件存在: {file_exists}, full_path={file_path}")

            # 如果文件不存在，尝试在ppt_outputs目录中查找
            if not file_exists:
                try:
                    # 构建项目根目录和ppt_outputs路径
                    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    upload_folder = current_app.config['UPLOAD_FOLDER']
                    if not os.path.isabs(upload_folder):
                        upload_folder = os.path.join(project_root, upload_folder)
                    ppt_output_dir = os.path.join(upload_folder, 'ppt_outputs')

                    # 在ppt_outputs目录中查找文件
                    potential_file_path = os.path.join(ppt_output_dir, record.stored_filename)
                    if os.path.exists(potential_file_path):
                        file_exists = True
                        file_path = potential_file_path
                        logger.info(f"在ppt_outputs目录中找到历史文件: {file_path}")
                except Exception as e:
                    logger.warning(f"查找历史文件时出错: {e}")

            # 使用ISO格式返回时间，让前端正确处理时区
            upload_time = datetime_to_isoformat(record.upload_time)

            # 直接使用数据库中存储的文件名
            history_records.append({
                'id': record.id,
                'filename': record.filename,  # 使用数据库中存储的文件名
                'stored_filename': getattr(record, 'stored_filename', None),
                'file_size': record.file_size,
                'upload_time': upload_time,
                'status': record.status,
                'file_exists': file_exists
            })

        logger.info(f"[PPT History] 返回记录数: {len(history_records)}")
        return jsonify(history_records)

    except Exception as e:
        logger.error(f"获取PPT翻译历史记录失败: {e}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")
        return jsonify({
            'status': 'error',
            'message': '获取历史记录失败'
        }), 500


@main.route('/api/delete_pdf_translation/<int:record_id>', methods=['DELETE'])
@login_required
def delete_pdf_translation_by_id(record_id):
    """删除PDF翻译记录和文件"""
    try:
        # 查询记录，确保是PDF翻译记录
        record = UploadRecord.query.filter_by(
            id=record_id, 
            user_id=current_user.id,
            status='completed'
        ).first()
        
        # 再次确认是PDF翻译记录（通过文件扩展名）
        if record:
            stored_file_ext = os.path.splitext(record.stored_filename)[1].lower() if record.stored_filename else ''
            if stored_file_ext != '.docx':
                record = None
        
        if not record:
            return jsonify({'status': 'error', 'message': '记录不存在'}), 404

        # 构建文件路径
        file_path = os.path.join(record.file_path, record.stored_filename)
        
        # 删除文件（如果存在）
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"已删除PDF翻译文件: {file_path}")
        else:
            # 如果在记录的路径中找不到文件，尝试在pdf_outputs目录中查找
            try:
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                upload_folder = current_app.config['UPLOAD_FOLDER']
                if not os.path.isabs(upload_folder):
                    upload_folder = os.path.join(project_root, upload_folder)
                pdf_output_dir = os.path.join(upload_folder, 'pdf_outputs')
                potential_file_path = os.path.join(pdf_output_dir, record.stored_filename)
                
                if os.path.exists(potential_file_path):
                    os.remove(potential_file_path)
                    logger.info(f"在pdf_outputs目录中删除PDF翻译文件: {potential_file_path}")
            except Exception as e:
                logger.warning(f"在pdf_outputs目录中查找或删除文件时出错: {e}")

        # 删除数据库记录
        db.session.delete(record)
        db.session.commit()
        
        return jsonify({'status': 'success', 'message': '删除成功'})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"删除PDF翻译记录失败: {e}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")
        return jsonify({'status': 'error', 'message': '删除失败'}), 500
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num)
        cell.value = header
        cell.font = openpyxl.styles.Font(bold=True)
        cell.fill = openpyxl.styles.PatternFill(start_color="CCCCCC", end_color="CCCCCC", fill_type="solid")

    # 添加示例数据
    sample_data = [
        ['hello', '你好', 'Hallo', '日常；问候', 1],
        ['sorry', '抱歉', 'Pardon', '日常；问候', 0]
    ]

    for row_num, row_data in enumerate(sample_data, 2):
        for col_num, value in enumerate(row_data, 1):
            ws.cell(row=row_num, column=col_num, value=value)

    # 设置列宽度
    column_widths = [20, 20, 20, 30, 10]
    for i, width in enumerate(column_widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = width

    # 保存文件
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    wb.save(file_path)

@main.route('/api/translations/batch_upload', methods=['POST'])
@login_required
def batch_upload_translations():
    """批量上传翻译文件并处理"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': '没有文件'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': '没有选择文件'}), 400

        if not allowed_excel_file(file.filename):
            return jsonify({'error': '只支持 Excel 文件 (.xlsx, .xls)'}), 400

        # 获取文件扩展名并验证
        if '.' not in file.filename:
            return jsonify({'error': '文件名必须包含扩展名'}), 400

        file_ext = file.filename.rsplit('.', 1)[1].lower()
        if file_ext not in EXCEL_ALLOWED_EXTENSIONS:
            return jsonify({'error': f'不支持的文件格式: .{file_ext}。只支持: {", ".join(EXCEL_ALLOWED_EXTENSIONS)}'}), 400

        # 保存上传的文件
        upload_folder = current_app.config['UPLOAD_FOLDER']
        user_upload_dir = os.path.join(upload_folder, f"user_{current_user.id}")
        os.makedirs(user_upload_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = secure_filename(file.filename)
        # 确保文件名包含正确的扩展名
        if not filename.lower().endswith(f'.{file_ext}'):
            filename = f"{filename}.{file_ext}"

        file_path = os.path.join(user_upload_dir, f"batch_upload_{timestamp}_{filename}")
        file_path = os.path.abspath(file_path)  # 转换为绝对路径
        logger.info(f"文件将保存到: {file_path}")
        logger.info(f"文件扩展名: {file_ext}")

        file.save(file_path)
        logger.info("文件保存成功")

        # 验证文件是否为有效的 Excel 文件
        try:
            import zipfile
            if file_ext == 'xlsx':
                # 检查是否为有效的 ZIP 文件（xlsx 实际上是 ZIP 格式）
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    zip_ref.testzip()
                logger.info("文件是有效的 xlsx 格式")
            elif file_ext == 'xls':
                # 对于 xls 文件，检查文件头
                with open(file_path, 'rb') as f:
                    header = f.read(8)
                    # Excel 97-2003 的文件头
                    if not header.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
                        raise ValueError("不是有效的 xls 文件")
                logger.info("文件是有效的 xls 格式")
        except Exception as e:
            logger.error(f"文件格式验证失败: {str(e)}")
            os.remove(file_path)  # 删除无效文件
            return jsonify({'error': f'文件格式无效: {str(e)}'}), 400

        # 解析 Excel 文件
        translations_data, errors = parse_excel_file(file_path)

        if errors:
            # 删除临时文件
            os.remove(file_path)
            return jsonify({
                'error': '文件解析失败',
                'details': errors[:10]  # 只返回前10个错误
            }), 400

        if not translations_data:
            # 删除临时文件
            os.remove(file_path)
            return jsonify({'error': '文件中没有有效的翻译数据'}), 400

        # 批量插入数据库
        success_count, error_count, error_details = batch_insert_translations(translations_data, current_user.id)

        # 删除临时文件
        os.remove(file_path)

        result = {
            'message': f'批量上传完成。成功: {success_count}, 失败: {error_count}',
            'success_count': success_count,
            'error_count': error_count
        }

        if error_details:
            result['errors'] = error_details[:10]  # 只返回前10个错误详情

        return jsonify(result)

    except Exception as e:
        logger.error(f"批量上传翻译失败: {str(e)}")
        logger.error(f"错误类型: {type(e).__name__}")
        import traceback
        logger.error(f"完整错误信息:\n{traceback.format_exc()}")
        return jsonify({
            'error': f'批量上传失败: {str(e)}',
            'error_type': type(e).__name__,
            'file_path': file_path if 'file_path' in locals() else None
        }), 500

def parse_excel_file(file_path):
    """解析 Excel 文件，返回翻译数据和错误信息"""
    translations = []
    errors = []

    try:
        logger.info(f"开始解析 Excel 文件: {file_path}")

        # 检查文件是否存在
        if not os.path.exists(file_path):
            errors.append(f"文件不存在: {file_path}")
            return [], errors

        # 检查文件大小
        file_size = os.path.getsize(file_path)
        logger.info(f"文件大小: {file_size} bytes")

        if file_size == 0:
            errors.append("文件为空")
            return [], errors

        logger.info("尝试加载 Excel 文件...")
        wb = openpyxl.load_workbook(file_path, data_only=True)
        logger.info("Excel 文件加载成功")

        ws = wb.active
        logger.info("获取活动工作表成功")

        logger.info(f"工作表名称: {ws.title}")
        logger.info(f"最大行数: {ws.max_row}, 最大列数: {ws.max_column}")

        # 检查表头
        expected_headers = ['english', 'chinese', 'dutch', 'category', 'is_public']
        actual_headers = []

        for col in range(1, len(expected_headers) + 1):
            cell_value = ws.cell(row=1, column=col).value
            if cell_value:
                actual_headers.append(str(cell_value).strip().lower())
            else:
                actual_headers.append('')

        logger.info(f"期望表头: {expected_headers}")
        logger.info(f"实际表头: {actual_headers}")

        if actual_headers != expected_headers:
            errors.append(f"表头不匹配。期望: {expected_headers}, 实际: {actual_headers}")
            return [], errors

        # 解析数据行
        for row_num in range(2, ws.max_row + 1):
            try:
                row_data = {}
                has_data = False

                for col_num, header in enumerate(expected_headers, 1):
                    cell_value = ws.cell(row=row_num, column=col_num).value
                    if cell_value is not None:
                        if isinstance(cell_value, str):
                            cell_value = cell_value.strip()
                        row_data[header] = cell_value
                        if header in ['english', 'chinese'] and cell_value:
                            has_data = True
                    else:
                        row_data[header] = None

                # 检查必填字段
                if not row_data.get('english') or not row_data.get('chinese'):
                    if has_data:  # 如果有其他数据但必填字段为空
                        errors.append(f"第{row_num}行: 英文和中文为必填字段")
                    continue

                # 处理 is_public 字段
                if row_data.get('is_public') is not None:
                    if isinstance(row_data['is_public'], str):
                        row_data['is_public'] = row_data['is_public'].lower() in ('1', 'true', 'yes', '是')
                    elif isinstance(row_data['is_public'], (int, float)):
                        row_data['is_public'] = bool(row_data['is_public'])
                    else:
                        row_data['is_public'] = False
                else:
                    row_data['is_public'] = False

                # 普通用户不能添加公共翻译
                if row_data['is_public'] and not current_user.is_administrator():
                    row_data['is_public'] = False

                translations.append(row_data)

            except Exception as e:
                errors.append(f"第{row_num}行解析失败: {str(e)}")
                continue

    except Exception as e:
        logger.error(f"Excel 文件解析异常: {str(e)}")
        logger.error(f"异常类型: {type(e).__name__}")
        import traceback
        logger.error(f"完整堆栈跟踪:\n{traceback.format_exc()}")
        errors.append(f"文件解析失败: {str(e)}")

    return translations, errors

def batch_insert_translations(translations_data, user_id):
    """批量插入翻译数据到数据库"""
    success_count = 0
    error_count = 0
    error_details = []

    for item in translations_data:
        try:
            # 检查是否已存在相同的翻译
            existing = None
            if item.get('is_public') and current_user.is_administrator():
                # 管理员检查公共翻译
                existing = Translation.query.filter_by(
                    english=item['english'],
                    is_public=True
                ).first()
            else:
                # 普通用户检查自己的私有翻译
                existing = Translation.query.filter_by(
                    user_id=user_id,
                    english=item['english']
                ).first()

            if existing:
                error_count += 1
                error_details.append(f"英文 '{item['english']}' 已存在")
                continue

            # 创建新的翻译记录
            translation = Translation(
                english=item['english'],
                chinese=item['chinese'],
                dutch=item.get('dutch'),
                category=item.get('category'),
                is_public=item['is_public'],
                user_id=user_id
            )

            db.session.add(translation)
            success_count += 1

        except Exception as e:
            error_count += 1
            error_details.append(f"插入 '{item.get('english', 'N/A')}' 失败: {str(e)}")
            continue

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        error_details.append(f"数据库提交失败: {str(e)}")
        success_count = 0
        error_count = len(translations_data)

    return success_count, error_count, error_details
