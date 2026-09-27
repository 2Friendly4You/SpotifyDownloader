import os
import shutil
from functools import wraps

from flask import Blueprint, current_app, jsonify, request, session

from app.config import ADMIN_PASSWORD, MUSIC_DIR
from app.downloads import start_promoted_jobs
from app.routes.search import search_request_log
from app.searches import persist_concurrent_limit
from app.state import download_state

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
        return view(*args, **kwargs)
    return wrapped


def gather_storage_info():
    useful_info = {
        'music_dir_path': MUSIC_DIR,
    }
    try:
        zip_files = [f for f in os.listdir(MUSIC_DIR) if f.lower().endswith('.zip')]
        useful_info['music_dir_zip_count'] = len(zip_files)
        music_dir_size_bytes = sum(
            os.path.getsize(os.path.join(MUSIC_DIR, f))
            for f in os.listdir(MUSIC_DIR)
            if os.path.isfile(os.path.join(MUSIC_DIR, f))
        )
        useful_info['music_dir_used_space_mb'] = round(music_dir_size_bytes / (1024 * 1024), 2)

        disk_usage = shutil.disk_usage(MUSIC_DIR)
        useful_info['partition_total_space_gb'] = round(disk_usage.total / (1024 * 1024 * 1024), 2)
        useful_info['partition_free_space_gb'] = round(disk_usage.free / (1024 * 1024 * 1024), 2)
    except Exception as e:
        current_app.logger.error(f"Error gathering storage info: {e}")
        useful_info['storage_info_error'] = str(e)

    useful_info['cleanup_retention_days'] = os.getenv('CLEANUP_RETENTION_DAYS', '14')
    useful_info['max_pending_requests_effective'] = download_state.get_limit()
    useful_info['max_queued_requests_effective'] = download_state.get_queue_limit()

    useful_info['cleanup_age_interval'] = os.getenv('AGE_CLEANUP_INTERVAL', '86400')
    useful_info['cleanup_max_dir_size_mb'] = os.getenv('MAX_MUSIC_DIR_SIZE_MB', '0')
    useful_info['cleanup_target_percentage'] = os.getenv('CLEANUP_TARGET_PERCENTAGE', '90')
    useful_info['cleanup_size_check_interval'] = os.getenv('SIZE_CHECK_INTERVAL', '3600')
    return useful_info


def admin_overview_payload():
    last_searches = list(search_request_log)
    last_searches.reverse()
    return {
        'last_requests': last_searches,
        'running_requests': download_state.pending_ids(),
        'queued_requests': download_state.queued_ids(),
        'current_limit': download_state.get_limit(),
        'useful_info': gather_storage_info(),
    }


@admin_bp.route('/login', methods=['POST'])
def admin_login():
    data = request.get_json(silent=True) or {}
    password = data.get('password', '')
    if password == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        return jsonify({'status': 'success', 'logged_in': True})
    return jsonify({'status': 'error', 'message': 'Invalid password', 'logged_in': False}), 401


@admin_bp.route('/logout', methods=['POST'])
def admin_logout():
    session.pop('admin_logged_in', None)
    return jsonify({'status': 'success', 'logged_in': False})


@admin_bp.route('/session', methods=['GET'])
def admin_session():
    return jsonify({'logged_in': bool(session.get('admin_logged_in'))})


@admin_bp.route('/overview', methods=['GET'])
@admin_required
def admin_overview():
    return jsonify(admin_overview_payload())


@admin_bp.route('/delete-zips', methods=['POST'])
@admin_required
def admin_delete_zips():
    deleted_count = 0
    error_count = 0
    try:
        for filename in os.listdir(MUSIC_DIR):
            if filename.lower().endswith('.zip'):
                file_path = os.path.join(MUSIC_DIR, filename)
                try:
                    os.remove(file_path)
                    deleted_count += 1
                    current_app.logger.info(f"Admin deleted ZIP file: {file_path}")
                except Exception as e:
                    error_count += 1
                    current_app.logger.error(f"Error deleting ZIP file {file_path}: {e}")

        if error_count > 0:
            message = f'Successfully deleted {deleted_count} ZIP files. Failed to delete {error_count} files. Check logs for details.'
            status = 'warning'
        else:
            message = f'Successfully deleted {deleted_count} ZIP files from the music directory.'
            status = 'success'
        return jsonify({
            'status': status,
            'message': message,
            'deleted_count': deleted_count,
            'error_count': error_count,
            **admin_overview_payload(),
        })
    except Exception as e:
        current_app.logger.error(f"Error in admin_delete_zips: {e}")
        return jsonify({'status': 'error', 'message': f'An error occurred while trying to delete ZIP files: {e}'}), 500


@admin_bp.route('/limit', methods=['POST'])
@admin_required
def admin_set_limit():
    data = request.get_json(silent=True) or {}
    new_limit = data.get('concurrent_limit')
    try:
        parsed = int(new_limit)
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Invalid limit value provided.'}), 400

    if parsed < 1:
        return jsonify({'status': 'error', 'message': 'Invalid limit value provided.'}), 400

    if not persist_concurrent_limit(parsed):
        return jsonify({
            'status': 'error',
            'message': 'Could not save the limit because searches.json could not be read.',
        }), 500

    start_promoted_jobs(download_state.set_limit(parsed))
    return jsonify({
        'status': 'success',
        'message': f'Concurrent request limit updated to {parsed}.',
        'concurrent_limit': parsed,
        **admin_overview_payload(),
    })
