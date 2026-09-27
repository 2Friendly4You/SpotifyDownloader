import os
import re
import json
import time
import uuid
import shutil
import secrets
import platform
import threading
import zipfile
from functools import wraps
from urllib.parse import urlparse
from flask import Flask, request, jsonify, session, send_from_directory
from flask_socketio import SocketIO
from datetime import datetime
from collections import deque

from cleanup_service import start_cleanup_thread

import yt_dlp
from spotdl.download.downloader import Downloader
from spotdl.download.progress_handler import ProgressHandler
from spotdl.utils.config import SPOTIFY_OPTIONS
from spotdl.utils.search import parse_query
from spotdl.utils.spotify import SpotifyClient, SpotifyError

# ===============================
# Core Configuration
# ===============================

SECRET_KEY = os.environ.get('FLASK_SECRET_KEY')
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    print("WARNING: Using randomly generated secret key. Set FLASK_SECRET_KEY environment variable for persistence.")

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
if not ADMIN_PASSWORD:
    print("WARNING: ADMIN_PASSWORD environment variable not set. Admin panel will be inaccessible.")
    ADMIN_PASSWORD = secrets.token_hex(32)

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',
    ping_timeout=60,
    ping_interval=25,
)
MUSIC_DIR = os.environ.get(
    'MUSIC_DIR',
    "C:/SpotifyDownloader/music/" if platform.system() == 'Windows' else "/var/www/SpotifyDownloader/"
)
SEARCHES_FILE = os.environ.get('SEARCHES_FILE', 'searches.json')

search_request_log = deque(maxlen=50)
_searches_file_lock = threading.Lock()


def retention_seconds():
    return int(os.getenv('CLEANUP_RETENTION_DAYS', '14')) * 86400


# Pending downloads used to expire via a one-hour Redis TTL. Keep that limit so a
# hung worker cannot hold a concurrency slot until the process restarts.
PENDING_TTL_SECONDS = int(os.environ.get('PENDING_TTL_SECONDS', 3600))


def load_queue_limit():
    try:
        parsed = int(os.environ.get('MAX_QUEUED_REQUESTS', 20))
    except (TypeError, ValueError):
        return 20
    return max(0, parsed)


class DownloadState:
    def __init__(self, concurrent_limit, queue_limit):
        self._lock = threading.Lock()
        self._pending = {}
        self._queue = deque()
        self._failed = {}
        self._completed = {}
        self._progress = {}
        self._progress_emit = {}
        self._concurrent_limit = concurrent_limit
        self._queue_limit = queue_limit

    def get_limit(self):
        with self._lock:
            return self._concurrent_limit

    def get_queue_limit(self):
        with self._lock:
            return self._queue_limit

    def set_limit(self, limit):
        with self._lock:
            self._concurrent_limit = limit
            return self._promote_locked()

    def accept(self, job):
        with self._lock:
            if len(self._pending) < self._concurrent_limit:
                self._pending[job['unique_id']] = time.time()
                return 'started', None
            if len(self._queue) >= self._queue_limit:
                return 'full', None
            self._queue.append(job)
            return 'queued', len(self._queue)

    def release(self, unique_id):
        with self._lock:
            self._pending.pop(unique_id, None)
            self._progress.pop(unique_id, None)
            self._progress_emit.pop(unique_id, None)
            return self._promote_locked()

    def cancel_queued(self, unique_id):
        with self._lock:
            for index, job in enumerate(self._queue):
                if job['unique_id'] == unique_id:
                    del self._queue[index]
                    return True
            return False

    def _promote_locked(self):
        promoted = []
        while self._queue and len(self._pending) < self._concurrent_limit:
            job = self._queue.popleft()
            self._pending[job['unique_id']] = time.time()
            promoted.append(job)
        return promoted

    def update_progress(self, unique_id, percent, message, min_interval=0.4):
        now = time.monotonic()
        with self._lock:
            current = self._progress.get(unique_id, {'percent': 0.0, 'message': ''})
            if percent is None:
                percent = current['percent']
            percent = max(0.0, min(100.0, float(percent)))
            self._progress[unique_id] = {'percent': percent, 'message': message}
            last_time, last_percent, last_message = self._progress_emit.get(
                unique_id, (0.0, -1.0, None)
            )
            message_changed = message != last_message
            percent_moved = abs(percent - last_percent) >= 1
            elapsed = now - last_time
            should_emit = (
                message_changed
                or percent >= 100
                or (percent_moved and elapsed >= min_interval)
            )
            if should_emit:
                self._progress_emit[unique_id] = (now, percent, message)
            return percent, message, should_emit

    def get_progress(self, unique_id):
        with self._lock:
            stored = self._progress.get(unique_id)
            if stored is None:
                return {'percent': 0.0, 'message': 'Searching'}
            return dict(stored)

    def mark_failed(self, unique_id, message):
        with self._lock:
            self._failed[unique_id] = (message, time.time() + retention_seconds())

    def mark_completed(self, unique_id):
        with self._lock:
            self._failed.pop(unique_id, None)
            self._completed[unique_id] = time.time() + retention_seconds()

    def pending_ids(self):
        with self._lock:
            return list(self._pending)

    def queued_ids(self):
        with self._lock:
            return [job['unique_id'] for job in self._queue]

    def queue_snapshot(self):
        with self._lock:
            return [
                {'unique_id': job['unique_id'], 'position': index + 1}
                for index, job in enumerate(self._queue)
            ]

    def lookup(self, unique_id):
        with self._lock:
            if unique_id in self._pending:
                return 'pending', None
            for index, job in enumerate(self._queue):
                if job['unique_id'] == unique_id:
                    return 'queued', index + 1
            failed = self._failed.get(unique_id)
            if failed is not None:
                return 'failed', failed[0]
            if unique_id in self._completed:
                return 'completed', None
        return 'unknown', None

    def _expire_pending_locked(self, now):
        timed_out = []
        for unique_id, started in list(self._pending.items()):
            if now - started < PENDING_TTL_SECONDS:
                continue
            self._pending.pop(unique_id, None)
            self._progress.pop(unique_id, None)
            self._progress_emit.pop(unique_id, None)
            if unique_id in self._completed:
                continue
            self._failed[unique_id] = ("Download timed out.", now + retention_seconds())
            timed_out.append(unique_id)
        return timed_out

    def expire_stale(self):
        now = time.time()
        with self._lock:
            self._failed = {
                key: value for key, value in self._failed.items() if value[1] > now
            }
            self._completed = {
                key: expires_at for key, expires_at in self._completed.items() if expires_at > now
            }
            timed_out = self._expire_pending_locked(now)
            return timed_out, self._promote_locked()


def read_searches_file():
    """Return the counter document.

    None means the file exists but could not be read. Callers must not replace
    it, or a bad read would wipe a stored concurrent_limit.
    """
    if os.path.isdir(SEARCHES_FILE):
        app.logger.error("searches.json path is a directory: %s", SEARCHES_FILE)
        return None
    if not os.path.isfile(SEARCHES_FILE):
        return {'total': 0}
    try:
        with open(SEARCHES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            app.logger.error("searches.json is not a JSON object")
            return None
        return data
    except Exception as e:
        app.logger.error(f"Error reading searches.json: {e}")
        return None


def write_searches_file(data):
    if os.path.isdir(SEARCHES_FILE):
        raise IsADirectoryError(SEARCHES_FILE)
    directory = os.path.dirname(os.path.abspath(SEARCHES_FILE))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(SEARCHES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def load_initial_concurrent_limit():
    data = read_searches_file()
    if not data:
        return int(os.environ.get('MAX_PENDING_REQUESTS', 5))
    limit = data.get('concurrent_limit')
    if limit is not None:
        try:
            parsed = int(limit)
            if parsed >= 1:
                return parsed
        except (TypeError, ValueError):
            pass
    return int(os.environ.get('MAX_PENDING_REQUESTS', 5))


def persist_concurrent_limit(limit):
    with _searches_file_lock:
        data = read_searches_file()
        if data is None:
            app.logger.error("Refusing to save concurrent_limit because searches.json could not be read")
            return False
        data['concurrent_limit'] = limit
        write_searches_file(data)
        return True


def get_max_pending_requests():
    return download_state.get_limit()


download_state = DownloadState(load_initial_concurrent_limit(), load_queue_limit())


VALID_AUDIO_PROVIDERS = {'youtube-music', 'youtube', 'soundcloud', 'bandcamp', 'piped', 'yt-dlp'}
VALID_LYRICS_PROVIDERS = {'musixmatch', 'genius', 'azlyrics', 'synced'}
VALID_OUTPUT_FORMATS = {'mp3', 'm4a', 'wav', 'flac', 'ogg', 'opus'}

# ===============================
# Validation Functions
# ===============================


def is_valid_url(input_url):
    try:
        result = urlparse(input_url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def validate_spotify_url(input_url):
    parsed_url = urlparse(input_url)
    return parsed_url.scheme in ['http', 'https'] and parsed_url.netloc == 'open.spotify.com'


def is_youtube_url(url):
    youtube_regex = r'^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\/.+$'
    return bool(re.match(youtube_regex, url))


def validate_song_title(title):
    return bool(re.match(r"^[\w\s\-'.,!&?=-]+$", title, re.UNICODE))


def validate_input(input_string):
    if is_valid_url(input_string):
        return validate_spotify_url(input_string) or is_youtube_url(input_string)
    return validate_song_title(input_string)


def validate_format_options(audio_format, lyrics_format, output_format):
    return (
        audio_format in VALID_AUDIO_PROVIDERS and
        lyrics_format in VALID_LYRICS_PROVIDERS and
        output_format in VALID_OUTPUT_FORMATS
    )

# ===============================
# Download Functions
# ===============================


def report_progress(unique_id, percent, message, force=False):
    stored_percent, stored_message, should_emit = download_state.update_progress(
        unique_id, percent, message
    )
    if not should_emit and not force:
        return
    socketio.emit('download_progress', {
        'unique_id': unique_id,
        'progress': round(stored_percent, 1),
        'message': stored_message,
    }, namespace='/')


def youtube_download_percent(data):
    info = data.get('info_dict') or {}
    total = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
    downloaded = data.get('downloaded_bytes') or 0
    fraction = (downloaded / total) if total else 0
    index = data.get('playlist_index') or info.get('playlist_index') or 1
    count = data.get('playlist_count') or info.get('playlist_count') or info.get('n_entries') or 1
    try:
        index = max(int(index), 1)
        count = max(int(count), 1)
    except (TypeError, ValueError):
        index, count = 1, 1
    if index > count:
        count = index
    return ((index - 1) + fraction) / count * 90


def attach_spotdl_progress(downloader, unique_id):
    def callback(tracker, message):
        total = tracker.parent.overall_total or 0
        if total:
            percent = tracker.parent.overall_progress / total * 100
        else:
            percent = tracker.progress or 0
        report_progress(unique_id, percent, message or 'Downloading')

    downloader.progress_handler = ProgressHandler(
        simple_tui=True,
        update_callback=callback,
        web_ui=True,
    )


def mark_failed(unique_id, search_query, message):
    app.logger.error(f"Download failed for {unique_id} ({search_query}): {message}")
    socketio.emit('download_failed', {
        'unique_id': unique_id,
        'search_query': search_query,
        'message': message,
        'zip_url': None,
    }, namespace='/')
    download_state.mark_failed(unique_id, message)


def publish_zip(unique_id, search_query, download_folder):
    current = download_state.get_progress(unique_id)
    report_progress(unique_id, max(current['percent'], 95), 'Packaging', force=True)
    zip_path = os.path.join(MUSIC_DIR, unique_id + ".zip")
    shutil.make_archive(os.path.join(MUSIC_DIR, unique_id), 'zip', root_dir=download_folder)

    if not os.path.isfile(zip_path):
        mark_failed(unique_id, search_query, "Download failed: Archive file was not created.")
        return

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            has_files = any(not info.is_dir() for info in zf.infolist())
    except zipfile.BadZipFile:
        mark_failed(unique_id, search_query, "Download failed: The downloaded archive is corrupted.")
        os.remove(zip_path)
        return

    if not has_files:
        mark_failed(unique_id, search_query, "Download failed: The downloaded archive is empty.")
        os.remove(zip_path)
        return

    notify_client_download_complete(unique_id, f'/music/{unique_id}.zip')


_spotify_init_lock = threading.Lock()


def ensure_spotify_client():
    with _spotify_init_lock:
        try:
            SpotifyClient()
        except SpotifyError:
            SpotifyClient.init(
                client_id=SPOTIFY_OPTIONS["client_id"],
                client_secret=SPOTIFY_OPTIONS["client_secret"],
                no_cache=True,
                max_retries=4,
            )


def run_spotdl(unique_id, search_query, audio_format, lyrics_format, output_format):
    download_folder = os.path.join(MUSIC_DIR, unique_id)
    os.makedirs(download_folder, exist_ok=True)
    downloader = None
    report_progress(unique_id, 0, 'Searching', force=True)

    try:
        ensure_spotify_client()
        downloader = Downloader(settings={
            "audio_providers": [audio_format],
            "lyrics_providers": [lyrics_format] if lyrics_format else [],
            "format": output_format,
            "output": os.path.join(download_folder, "{artists} - {title}.{output-ext}"),
            "threads": 4,
            "bitrate": "auto",
            "simple_tui": True,
        })
        songs = parse_query(
            query=[search_query],
            threads=downloader.settings["threads"],
            use_ytm_data=downloader.settings["ytm_data"],
            playlist_numbering=downloader.settings["playlist_numbering"],
            album_type=downloader.settings["album_type"],
            playlist_retain_track_cover=downloader.settings["playlist_retain_track_cover"],
        )
        if not songs:
            mark_failed(unique_id, search_query, "Download failed: No songs found for that search.")
            return

        attach_spotdl_progress(downloader, unique_id)
        report_progress(unique_id, 0, 'Downloading', force=True)
        results = downloader.download_multiple_songs(songs)
        if not any(path for _, path in results):
            detail = downloader.errors[0] if downloader.errors else "No files were downloaded."
            mark_failed(unique_id, search_query, f"Download failed: {detail[:150]}")
            return

        if downloader.errors:
            app.logger.warning("Some tracks failed for %s: %s", unique_id, downloader.errors)

        publish_zip(unique_id, search_query, download_folder)
    except Exception as e:
        app.logger.error(f"Unexpected error in run_spotdl for {unique_id} ({search_query}): {e}", exc_info=True)
        mark_failed(unique_id, search_query, f"An unexpected error occurred during spotdl processing: {e}")
    finally:
        try:
            if downloader is not None and not downloader.loop.is_closed():
                downloader.loop.close()
            if os.path.exists(download_folder):
                shutil.rmtree(download_folder)
        finally:
            start_promoted_jobs(download_state.release(unique_id))


def download_from_youtube(unique_id, url, output_format):
    download_folder = os.path.join(MUSIC_DIR, unique_id)
    os.makedirs(download_folder, exist_ok=True)

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': output_format,
                'preferredquality': '320',
            },
            {
                'key': 'FFmpegMetadata',
                'add_metadata': True,
            },
            {
                'key': 'EmbedThumbnail',
            }
        ],
        'outtmpl': os.path.join(download_folder, '%(title)s.%(ext)s'),
        'writethumbnail': True,
        'postprocessor_args': [
            '-id3v2_version', '3',
        ],
        'progress_hooks': [lambda data: youtube_progress_hook(unique_id, data)],
        'postprocessor_hooks': [lambda data: youtube_postprocessor_hook(unique_id, data)],
    }

    report_progress(unique_id, 0, 'Downloading', force=True)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        for file_in_dir in os.listdir(download_folder):
            if file_in_dir.endswith(('.webp', '.jpg', '.png')):
                os.remove(os.path.join(download_folder, file_in_dir))

        publish_zip(unique_id, url, download_folder)

    except Exception as e:
        app.logger.error(f"YouTubeDL error for {unique_id} processing {url}: {e}", exc_info=True)
        mark_failed(unique_id, url, f"YouTube download failed: {e}")
    finally:
        try:
            if os.path.exists(download_folder):
                shutil.rmtree(download_folder)
        finally:
            start_promoted_jobs(download_state.release(unique_id))


def youtube_progress_hook(unique_id, data):
    status = data.get('status')
    if status == 'downloading':
        report_progress(unique_id, youtube_download_percent(data), 'Downloading')
    elif status == 'finished':
        report_progress(unique_id, None, 'Converting')


def youtube_postprocessor_hook(unique_id, data):
    if data.get('status') != 'started':
        return
    name = data.get('postprocessor') or ''
    if 'FFmpegExtractAudio' in name:
        report_progress(unique_id, None, 'Converting')
    elif 'FFmpegMetadata' in name:
        report_progress(unique_id, None, 'Embedding metadata')


def emit_queue_update():
    socketio.emit('queue_update', {
        'queue': download_state.queue_snapshot(),
    }, namespace='/')


def start_download_job(job, from_queue=False):
    unique_id = job['unique_id']
    if from_queue:
        socketio.emit('download_started', {
            'unique_id': unique_id,
        }, namespace='/')
    if job.get('is_youtube'):
        socketio.start_background_task(
            download_from_youtube, unique_id, job['search_query'], job['output_format']
        )
        return
    socketio.start_background_task(
        run_spotdl,
        unique_id,
        job['search_query'],
        job['audio_format'],
        job['lyrics_format'],
        job['output_format'],
    )


def start_promoted_jobs(jobs):
    for job in jobs:
        start_download_job(job, from_queue=True)
    if jobs:
        emit_queue_update()

# ===============================
# Admin helpers
# ===============================


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
        app.logger.error(f"Error gathering storage info: {e}")
        useful_info['storage_info_error'] = str(e)

    useful_info['cleanup_retention_days'] = os.getenv('CLEANUP_RETENTION_DAYS', '14')
    useful_info['max_pending_requests_effective'] = get_max_pending_requests()
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
        'running_requests': get_pending_requests(),
        'queued_requests': download_state.queued_ids(),
        'current_limit': get_max_pending_requests(),
        'useful_info': gather_storage_info(),
    }

# ===============================
# Route Handlers
# ===============================


@app.after_request
def log_response_info(response):
    if request.path == '/api/search' and request.method == 'POST' and 'search_log_data' in request.environ:
        log_entry = request.environ['search_log_data']
        log_entry['status_code'] = response.status_code
        search_request_log.append(log_entry)
        del request.environ['search_log_data']
    return response


@app.route('/music/<path:filename>')
def serve_music(filename):
    return send_from_directory(MUSIC_DIR, filename)


def record_search():
    try:
        with _searches_file_lock:
            searches = read_searches_file()
            if searches is None:
                app.logger.error("Skipped download counter update because searches.json could not be read")
                return
            searches['total'] = int(searches.get('total', 0)) + 1
            write_searches_file(searches)
    except Exception as e:
        app.logger.error(f"Failed to update searches.json: {e}")


@app.route('/api/search', methods=['POST'])
def search():
    data = request.get_json(silent=True) or {}
    search_query = (data.get('search_query') or '').strip()
    audio_format = data.get('audio_format')
    lyrics_format = data.get('lyrics_format')
    output_format = data.get('output_format')

    request.environ['search_log_data'] = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'ip': request.remote_addr,
        'search_query': search_query,
        'audio_format': audio_format,
        'lyrics_format': lyrics_format,
        'output_format': output_format,
        'status_code': None
    }

    if not search_query:
        return jsonify({'status': 'error', 'message': 'Search query is required'}), 400

    if len(search_query) > 2000:
        return jsonify({'status': 'error', 'message': 'Search query is too long'}), 400

    if is_youtube_url(search_query):
        if output_format not in VALID_OUTPUT_FORMATS:
            return jsonify({'status': 'error', 'message': 'Invalid output format'}), 400
    elif not all([
        validate_input(search_query),
        validate_format_options(audio_format, lyrics_format, output_format)
    ]):
        return jsonify({'status': 'error', 'message': 'Invalid input provided'}), 400

    expire_download_state()
    unique_id = str(uuid.uuid4())
    job = {
        'unique_id': unique_id,
        'search_query': search_query,
        'audio_format': audio_format,
        'lyrics_format': lyrics_format,
        'output_format': output_format,
        'is_youtube': is_youtube_url(search_query),
    }
    outcome, position = download_state.accept(job)
    if outcome == 'full':
        return jsonify({
            'status': 'error',
            'message': 'Download queue is full. Please try again later.',
        }), 429

    record_search()

    if outcome == 'started':
        start_download_job(job)
        return jsonify({
            'status': 'success',
            'message': 'Download started',
            'unique_id': unique_id,
            'queued': False,
            'position': None,
        }), 202

    emit_queue_update()
    return jsonify({
        'status': 'success',
        'message': 'Download queued',
        'unique_id': unique_id,
        'queued': True,
        'position': position,
    }), 202


@app.route('/api/search/<unique_id>', methods=['DELETE'])
def cancel_queued_search(unique_id):
    if download_state.cancel_queued(unique_id):
        emit_queue_update()
        return jsonify({'status': 'success', 'cancelled': True})
    return jsonify({
        'status': 'error',
        'message': 'Request is not queued.',
        'cancelled': False,
    }), 404


@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json(silent=True) or {}
    password = data.get('password', '')
    if password == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        return jsonify({'status': 'success', 'logged_in': True})
    return jsonify({'status': 'error', 'message': 'Invalid password', 'logged_in': False}), 401


@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('admin_logged_in', None)
    return jsonify({'status': 'success', 'logged_in': False})


@app.route('/api/admin/session', methods=['GET'])
def admin_session():
    return jsonify({'logged_in': bool(session.get('admin_logged_in'))})


@app.route('/api/admin/overview', methods=['GET'])
@admin_required
def admin_overview():
    return jsonify(admin_overview_payload())


@app.route('/api/admin/delete-zips', methods=['POST'])
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
                    app.logger.info(f"Admin deleted ZIP file: {file_path}")
                except Exception as e:
                    error_count += 1
                    app.logger.error(f"Error deleting ZIP file {file_path}: {e}")

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
        app.logger.error(f"Error in admin_delete_zips: {e}")
        return jsonify({'status': 'error', 'message': f'An error occurred while trying to delete ZIP files: {e}'}), 500


@app.route('/api/admin/limit', methods=['POST'])
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


@app.route('/api/download_counter', methods=['GET'])
def download_counter():
    try:
        with _searches_file_lock:
            data = read_searches_file()
        if data is None:
            return jsonify({'total': 0})
        return jsonify({'total': int(data.get('total', 0))})
    except Exception as e:
        app.logger.error(f"Failed to read searches.json in download_counter: {e}")
        return jsonify({'total': 0})


@app.route('/api/status/<unique_id>', methods=['GET'])
def check_request(unique_id):
    file_path = os.path.join(MUSIC_DIR, unique_id + ".zip")
    kind, extra = download_state.lookup(unique_id)

    if kind == 'queued':
        return jsonify({
            'status': 'queued',
            'position': extra,
        }), 202

    if kind == 'pending':
        progress = download_state.get_progress(unique_id)
        return jsonify({
            'status': 'pending',
            'progress': round(progress['percent'], 1),
            'progress_message': progress['message'],
        }), 202

    if kind == 'failed':
        error_message = extra or "Download failed"
        zip_url = f'/music/{unique_id}.zip' if os.path.isfile(file_path) else None
        return jsonify({'status': 'failed', 'message': error_message, 'url': zip_url}), 200

    if kind == 'completed' or os.path.isfile(file_path):
        if os.path.isfile(file_path):
            return jsonify({'status': 'completed', 'url': f'/music/{unique_id}.zip'}), 200
        return jsonify({'status': 'error', 'message': 'File was marked completed but is now missing.'}), 404

    return jsonify({'status': 'not_found', 'message': 'Request not found or expired.'}), 404

# ===============================
# File Management Functions
# ===============================


def get_pending_requests():
    return download_state.pending_ids()


def notify_client_download_complete(unique_id, download_url):
    download_state.mark_completed(unique_id)
    socketio.emit('download_complete', {
        'unique_id': unique_id,
        'url': download_url
    }, namespace='/')

# ===============================
# Application Startup
# ===============================

def expire_download_state():
    timed_out, promoted = download_state.expire_stale()
    for unique_id in timed_out:
        app.logger.error("Download %s timed out and released its concurrency slot", unique_id)
        socketio.emit('download_failed', {
            'unique_id': unique_id,
            'message': 'Download timed out.',
            'zip_url': None,
        }, namespace='/')
    start_promoted_jobs(promoted)


os.makedirs(MUSIC_DIR, exist_ok=True)
if os.path.isdir(SEARCHES_FILE):
    app.logger.error(
        "SEARCHES_FILE %s is a directory. Mount a directory and point SEARCHES_FILE at a file inside it.",
        SEARCHES_FILE,
    )
elif not os.path.isfile(SEARCHES_FILE):
    try:
        write_searches_file({'total': 0})
    except Exception as e:
        app.logger.error(f"Could not create searches.json at startup: {e}")

start_cleanup_thread(MUSIC_DIR, expire_callback=expire_download_state)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
