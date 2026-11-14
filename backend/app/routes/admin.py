import hmac
import os
import platform
import shutil
import threading
import time
from functools import wraps
from importlib import metadata

from flask import Blueprint, current_app, jsonify, request, session

from app import history
from app.config import ADMIN_PASSWORD, MUSIC_DIR, retention_seconds
from app.downloads import cancel_running_job, emit_queue_update, expire_download_state, start_promoted_jobs
from app.routes.search import search_request_log
from app.searches import get_download_total, persist_concurrent_limit
from app.state import download_state
from app.titles import is_job_id

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

PROCESS_STARTED_AT = time.time()
RECENT_JOBS = 100
DAY = 86400


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
        return view(*args, **kwargs)
    return wrapped


def _env(name, default):
    return os.getenv(name, default)


def _zip_path(unique_id):
    return os.path.join(MUSIC_DIR, unique_id + '.zip')


def _tree_size(path):
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            full = os.path.join(dirpath, name)
            if not os.path.islink(full):
                try:
                    total += os.path.getsize(full)
                except OSError:
                    pass
    return total


def _music_entries():
    """Zips and leftover job folders in the music directory.

    A folder belongs to a running job while it downloads. Anything else is a
    leftover from a crash or restart and only takes space.
    """
    active = set(download_state.pending_ids())
    zips, leftovers = [], []
    try:
        names = os.listdir(MUSIC_DIR)
    except OSError:
        return zips, leftovers
    for name in names:
        path = os.path.join(MUSIC_DIR, name)
        try:
            if os.path.isfile(path) and name.lower().endswith('.zip'):
                stat = os.stat(path)
                zips.append({'name': name, 'id': name[:-4], 'bytes': stat.st_size, 'mtime': stat.st_mtime})
            elif os.path.isdir(path) and name not in active:
                leftovers.append({'name': name, 'bytes': _tree_size(path)})
        except OSError:
            continue
    return zips, leftovers


def storage_payload():
    zips, leftovers = _music_entries()
    payload = {
        'zip_count': len(zips),
        'zip_bytes': sum(z['bytes'] for z in zips),
        'oldest_zip_at': min((z['mtime'] for z in zips), default=None),
        'leftover_count': len(leftovers),
        'leftover_bytes': sum(item['bytes'] for item in leftovers),
    }
    payload['music_dir_bytes'] = payload['zip_bytes'] + payload['leftover_bytes'] + sum(
        _tree_size(os.path.join(MUSIC_DIR, job)) for job in download_state.pending_ids()
        if os.path.isdir(os.path.join(MUSIC_DIR, job))
    )
    try:
        usage = shutil.disk_usage(MUSIC_DIR)
        payload.update(disk_total_bytes=usage.total, disk_free_bytes=usage.free, disk_used_bytes=usage.used)
    except OSError as e:
        current_app.logger.error("Could not read disk usage: %s", e)
        payload['error'] = 'disk_usage_unavailable'
    return payload


def _version(package):
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def _memory_bytes():
    try:
        with open('/proc/self/status', encoding='ascii') as handle:
            for line in handle:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return None


def health_payload():
    try:
        load = os.getloadavg()
    except (AttributeError, OSError):
        load = None
    return {
        'started_at': PROCESS_STARTED_AT,
        'uptime_seconds': time.time() - PROCESS_STARTED_AT,
        'load_average': load,
        'cpu_count': os.cpu_count(),
        'memory_bytes': _memory_bytes(),
        'ffmpeg': shutil.which('ffmpeg') is not None,
        'cleanup_running': any(t.name == 'cleanup' and t.is_alive() for t in threading.enumerate()),
        'music_dir_writable': os.access(MUSIC_DIR, os.W_OK),
        'versions': {
            'spotdl': _version('spotdl'),
            'yt_dlp': _version('yt-dlp'),
            'python': platform.python_version(),
        },
    }


def settings_payload():
    max_dir_mb = int(_env('MAX_MUSIC_DIR_SIZE_MB', '0') or 0)
    return {
        'concurrent_limit': download_state.get_limit(),
        'queue_limit': download_state.get_queue_limit(),
        'retention_days': retention_seconds() // DAY,
        'max_music_dir_mb': max_dir_mb,
        'cleanup_target_percent': int(_env('CLEANUP_TARGET_PERCENTAGE', '90') or 90),
        'age_cleanup_interval_seconds': int(_env('AGE_CLEANUP_INTERVAL', '86400') or 86400),
        'size_check_interval_seconds': int(_env('SIZE_CHECK_INTERVAL', '3600') or 3600),
    }


def _job_view(entry, live=None):
    view = {
        key: entry.get(key) for key in (
            'id', 'title', 'query', 'source', 'format', 'provider', 'status', 'created_at', 'started_at',
            'finished_at', 'size_bytes', 'songs_total', 'songs_saved', 'message', 'file_deleted_at',
        )
    }
    view['failed_tracks'] = entry.get('failed_tracks') or []
    path = _zip_path(entry['id'])
    view['file_available'] = os.path.isfile(path)
    if view['file_available']:
        view['size_bytes'] = os.path.getsize(path)
    if live:
        view.update(live)
    return view


def jobs_payload():
    entries = history.entries()
    by_id = {entry['id']: entry for entry in entries}
    running = []
    for unique_id in download_state.pending_ids():
        entry = by_id.get(unique_id) or {'id': unique_id}
        progress = download_state.get_progress(unique_id)
        running.append(_job_view(entry, {
            'status': 'running',
            'title': entry.get('title') or download_state.title(unique_id),
            'progress': progress,
        }))
    queued = []
    for item in download_state.queue_snapshot():
        entry = by_id.get(item['unique_id']) or {'id': item['unique_id']}
        queued.append(_job_view(entry, {'status': 'queued', 'position': item['position']}))
    active = {job['id'] for job in running + queued}
    recent = [_job_view(entry) for entry in entries if entry['id'] not in active][:RECENT_JOBS]
    return {'running': running, 'queued': queued, 'recent': recent}, entries


def stats_payload(entries):
    now = time.time()

    def window(seconds):
        counts = {'completed': 0, 'failed': 0, 'cancelled': 0, 'songs': 0, 'failed_songs': 0, 'bytes': 0}
        durations = []
        for entry in entries:
            finished = entry.get('finished_at')
            if not finished or now - finished > seconds or entry.get('status') not in counts:
                continue
            counts[entry['status']] += 1
            if entry['status'] == 'completed':
                counts['songs'] += entry.get('songs_saved') or 0
                counts['bytes'] += entry.get('size_bytes') or 0
                durations.append(finished - (entry.get('started_at') or entry['created_at']))
            counts['failed_songs'] += len(entry.get('failed_tracks') or [])
        counts['avg_duration_seconds'] = sum(durations) / len(durations) if durations else None
        return counts

    return {
        'total_downloads': get_download_total(),
        'history_since': min((e.get('created_at') or now for e in entries), default=None),
        'day': window(DAY),
        'week': window(7 * DAY),
        'month': window(30 * DAY),
        # Raw finish times for the chart, so the browser can group them by
        # its own calendar days instead of the server's time zone.
        'finishes': [
            [entry['finished_at'], entry['status']] for entry in entries
            if entry.get('finished_at') and now - entry['finished_at'] <= 14 * DAY
        ],
    }


def admin_overview_payload():
    expire_download_state()
    last_searches = list(search_request_log)
    last_searches.reverse()
    jobs, entries = jobs_payload()
    return {
        'last_requests': last_searches,
        'running_requests': download_state.pending_ids(),
        'queued_requests': download_state.queued_ids(),
        'current_limit': download_state.get_limit(),
        'jobs': jobs,
        'stats': stats_payload(entries),
        'storage': storage_payload(),
        'health': health_payload(),
        'settings': settings_payload(),
        'server_time': time.time(),
    }


@admin_bp.route('/login', methods=['POST'])
def admin_login():
    data = request.get_json(silent=True) or {}
    password = str(data.get('password', ''))
    if hmac.compare_digest(password.encode('utf-8'), ADMIN_PASSWORD.encode('utf-8')):
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


@admin_bp.route('/jobs/<unique_id>/cancel', methods=['POST'])
@admin_required
def admin_cancel_job(unique_id):
    if not is_job_id(unique_id):
        return jsonify({'status': 'error', 'message': 'Unknown job.'}), 404
    outcome = download_state.request_cancel(unique_id)
    if outcome == 'queued':
        history.finished(unique_id, 'cancelled')
        emit_queue_update()
    elif outcome == 'running':
        cancel_running_job(unique_id)
    else:
        return jsonify({'status': 'error', 'message': 'The job is not running or queued.'}), 409
    current_app.logger.info("Admin cancelled job %s", unique_id)
    return jsonify({'status': 'success', 'outcome': outcome, **admin_overview_payload()})


@admin_bp.route('/jobs/<unique_id>/delete-file', methods=['POST'])
@admin_required
def admin_delete_job_file(unique_id):
    if not is_job_id(unique_id):
        return jsonify({'status': 'error', 'message': 'Unknown job.'}), 404
    status, _ = download_state.lookup(unique_id)
    if status in ('pending', 'queued'):
        return jsonify({'status': 'error', 'message': 'Cancel the job before deleting its file.'}), 409
    path = _zip_path(unique_id)
    if not os.path.isfile(path):
        return jsonify({'status': 'error', 'message': 'The file is already gone.'}), 404
    freed = os.path.getsize(path)
    os.remove(path)
    download_state.forget(unique_id)
    history.file_deleted(unique_id)
    current_app.logger.info("Admin deleted the file of job %s", unique_id)
    return jsonify({'status': 'success', 'freed_bytes': freed, **admin_overview_payload()})


@admin_bp.route('/cleanup', methods=['POST'])
@admin_required
def admin_cleanup():
    """Delete finished zips older than ``older_than_days`` and/or leftover folders."""
    data = request.get_json(silent=True) or {}
    days = data.get('older_than_days')
    leftovers = bool(data.get('leftovers'))
    if days is not None:
        try:
            days = float(days)
        except (TypeError, ValueError):
            return jsonify({'status': 'error', 'message': 'Invalid age.'}), 400
        if days < 0:
            return jsonify({'status': 'error', 'message': 'Invalid age.'}), 400
    if days is None and not leftovers:
        return jsonify({'status': 'error', 'message': 'Nothing to clean up.'}), 400

    zips, leftover_dirs = _music_entries()
    cutoff = time.time() - (days or 0) * DAY
    deleted = freed = errors = 0
    if days is not None:
        for item in zips:
            if item['mtime'] > cutoff:
                continue
            try:
                os.remove(os.path.join(MUSIC_DIR, item['name']))
            except OSError:
                errors += 1
                continue
            deleted += 1
            freed += item['bytes']
            if is_job_id(item['id']):
                download_state.forget(item['id'])
                history.file_deleted(item['id'])
    folders = 0
    if leftovers:
        active = set(download_state.pending_ids())
        for item in leftover_dirs:
            if item['name'] in active:
                continue
            shutil.rmtree(os.path.join(MUSIC_DIR, item['name']), ignore_errors=True)
            folders += 1
            freed += item['bytes']
    current_app.logger.info("Admin cleanup: %d zips, %d folders, %d bytes", deleted, folders, freed)
    return jsonify({
        'status': 'warning' if errors else 'success',
        'deleted_count': deleted,
        'folder_count': folders,
        'freed_bytes': freed,
        'error_count': errors,
        **admin_overview_payload(),
    })


@admin_bp.route('/delete-zips', methods=['POST'])
@admin_required
def admin_delete_zips():
    deleted_count = 0
    error_count = 0
    freed = 0
    try:
        for filename in os.listdir(MUSIC_DIR):
            if filename.lower().endswith('.zip'):
                file_path = os.path.join(MUSIC_DIR, filename)
                try:
                    size = os.path.getsize(file_path)
                    os.remove(file_path)
                    deleted_count += 1
                    freed += size
                    if is_job_id(filename[:-4]):
                        download_state.forget(filename[:-4])
                        history.file_deleted(filename[:-4])
                except Exception as e:
                    error_count += 1
                    current_app.logger.error(f"Error deleting ZIP file {file_path}: {e}")
        current_app.logger.info("Admin deleted %d ZIP files", deleted_count)
        if error_count > 0:
            message = f'Deleted {deleted_count} ZIP files. Failed to delete {error_count} files. Check logs for details.'
            status = 'warning'
        else:
            message = f'Deleted {deleted_count} ZIP files from the music directory.'
            status = 'success'
        return jsonify({
            'status': status,
            'message': message,
            'deleted_count': deleted_count,
            'error_count': error_count,
            'freed_bytes': freed,
            **admin_overview_payload(),
        })
    except Exception as e:
        current_app.logger.error(f"Error in admin_delete_zips: {e}")
        return jsonify({'status': 'error', 'message': 'Could not delete the ZIP files. Check the logs.'}), 500


@admin_bp.route('/limit', methods=['POST'])
@admin_required
def admin_set_limit():
    data = request.get_json(silent=True) or {}
    new_limit = data.get('concurrent_limit')
    try:
        parsed = int(new_limit)
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Invalid limit value provided.'}), 400

    if parsed < 1 or parsed > 50:
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
