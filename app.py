import os
import re
import json
import time
import uuid
import redis
import shutil
import secrets
import platform
import threading
import subprocess
import zipfile # Added import
from urllib.parse import urlparse
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash # Added session, redirect, url_for, flash
from flask_socketio import SocketIO, emit
from datetime import datetime # Added datetime
from collections import deque # Added deque

import yt_dlp

# ===============================
# Core Configuration
# ===============================

# Get secret key from environment or generate a secure random one
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY')
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    print("WARNING: Using randomly generated secret key. Set FLASK_SECRET_KEY environment variable for persistence.")

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
if not ADMIN_PASSWORD:
    print("WARNING: ADMIN_PASSWORD environment variable not set. Admin panel will be inaccessible.")
    ADMIN_PASSWORD = secrets.token_hex(32) # Generate a random one if not set to prevent easy access

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
socketio = SocketIO(app, 
    cors_allowed_origins="*",
    async_mode='eventlet',
    logger=True,
    engineio_logger=True,
    ping_timeout=60,
    ping_interval=25
)
redis_client = redis.Redis(host='spotifydownloader-redis', port=6379, db=0)

# Configure paths and constants
MUSIC_DIR = "C:/SpotifyDownloader/music/" if platform.system() == 'Windows' else "/var/www/SpotifyDownloader/"
PENDING_REQUESTS_FILE = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), 'pending_requests.txt')
# MAX_PENDING_REQUESTS is now managed via admin panel, default to 5 if not set in Redis
# MAX_PENDING_REQUESTS = int(os.environ.get('MAX_PENDING_REQUESTS', 5)) 

# Global deque to store last 50 search requests for admin panel
search_request_log = deque(maxlen=50)

# Key for storing concurrent request limit in Redis
CONCURRENT_REQUEST_LIMIT_KEY = "concurrent_request_limit"

def get_max_pending_requests():
    limit = redis_client.get(CONCURRENT_REQUEST_LIMIT_KEY)
    if limit:
        return int(limit)
    return 5 # Default limit

# Valid format options
VALID_AUDIO_PROVIDERS = {'youtube-music', 'youtube',
                         'slider-kz', 'soundcloud', 'bandcamp', 'piped', 'yt-dlp'}
VALID_LYRICS_PROVIDERS = {'musixmatch', 'genius', 'azlyrics', 'synced'}
VALID_OUTPUT_FORMATS = {'mp3', 'm4a', 'wav', 'flac', 'ogg', 'opus'}

# ===============================
# Validation Functions
# ===============================


def is_valid_url(input_url):
    try:
        result = urlparse(input_url)
        return all([result.scheme, result.netloc])
    except:
        return False


def validate_spotify_url(input_url):
    parsed_url = urlparse(input_url)
    return parsed_url.scheme in ['http', 'https'] and parsed_url.netloc == 'open.spotify.com'


def is_youtube_url(url):
    youtube_regex = r'^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\/.+$'
    return bool(re.match(youtube_regex, url))


def validate_song_title(title):
    return bool(re.match(r"^[a-zA-Z0-9\s\-'.,!&?=-]+$", title))


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


def run_spotdl(unique_id, search_query, audio_format, lyrics_format, output_format):
    redis_client.setex(f"pending:{unique_id}", 3600, "1") # Mark as pending for 1 hour
    download_folder = os.path.join(MUSIC_DIR, unique_id)
    os.makedirs(download_folder, exist_ok=True)
    
    retention_seconds = int(os.getenv('CLEANUP_RETENTION_DAYS', 7)) * 86400 # Changed 'RETENTION_DAYS' to 'CLEANUP_RETENTION_DAYS'
    # Construct zip_file_path using the download_folder, not its parent
    zip_file_path = os.path.join(MUSIC_DIR, unique_id + ".zip") 

    try:
        command = [
            'spotdl', search_query,
            '--max-retries', '2',
            '--audio', audio_format,
            '--format', output_format,
            '--output', download_folder, # spotdl downloads into this folder
            '--threads', '4',
            '--bitrate', '320k'
        ]
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')

        if result.returncode == 0:
            # spotdl command reported success, now create the archive from the download_folder contents
            # The archive should be placed in MUSIC_DIR, named unique_id.zip
            # root_dir should be MUSIC_DIR to get flat structure inside zip, or download_folder for nested
            # For consistency, let's archive the contents of download_folder directly.
            shutil.make_archive(os.path.join(MUSIC_DIR, unique_id), 'zip', root_dir=download_folder)

            if not os.path.exists(zip_file_path):
                user_message = "Download failed: Archive file was not created after successful command."
                app.logger.error(f"Zip file {zip_file_path} not found after make_archive for {unique_id} (spotdl).")
                socketio.emit('download_failed', {
                    'unique_id': unique_id, 'search_query': search_query,
                    'message': user_message, 'zip_url': None
                }, namespace='/')
                redis_client.setex(f"failed:{unique_id}", retention_seconds, user_message)
                return # Exit after failure

            try:
                with zipfile.ZipFile(zip_file_path, 'r') as zf:
                    # Filter out directories and count only actual files
                    file_list = [info.filename for info in zf.infolist() if not info.is_dir()]
                
                if not file_list:
                    user_message = "Download failed: The downloaded archive is empty."
                    app.logger.warning(f"Empty zip detected for {unique_id} (spotdl). Path: {zip_file_path}")
                    socketio.emit('download_failed', {
                        'unique_id': unique_id, 'search_query': search_query,
                        'message': user_message, 'zip_url': None
                    }, namespace='/')
                    redis_client.setex(f"failed:{unique_id}", retention_seconds, user_message)
                    if os.path.exists(zip_file_path): os.remove(zip_file_path) # Clean up empty zip
                    return # Exit after failure
            except zipfile.BadZipFile:
                user_message = "Download failed: The downloaded archive is corrupted."
                app.logger.warning(f"Corrupted zip detected for {unique_id} (spotdl). Path: {zip_file_path}")
                socketio.emit('download_failed', {
                    'unique_id': unique_id, 'search_query': search_query,
                    'message': user_message, 'zip_url': None
                }, namespace='/')
                redis_client.setex(f"failed:{unique_id}", retention_seconds, user_message)
                if os.path.exists(zip_file_path): os.remove(zip_file_path) # Clean up corrupted zip
                return # Exit after failure

            # If all checks pass
            notify_client_download_complete(unique_id, f'/music/{unique_id}.zip')
        else:
            # spotdl command failed (result.returncode != 0)
            error_output_stderr = result.stderr if result.stderr else ""
            error_output_stdout = result.stdout if result.stdout else ""
            full_error_output = f"STDERR:\\n{error_output_stderr}\\nSTDOUT:\\n{error_output_stdout}"
            specific_yt_dlp_error = "AudioProviderError: YT-DLP download error" in error_output_stderr
            
            user_message = ""
            if specific_yt_dlp_error:
                yt_match = re.search(r"(https://(?:music\\.)?youtube\\.com/watch\\?v=[\\w-]+)", error_output_stderr)
                yt_link_msg = f" for {yt_match.group(1)}" if yt_match else ""
                user_message = f"Download failed: Could not fetch from YouTube Music{yt_link_msg}. The song might be unavailable or an issue with the provider."
            else:
                first_error_line = error_output_stderr.splitlines()[0] if error_output_stderr.splitlines() else "Unknown spotdl error"
                user_message = f"Download failed: {first_error_line[:150]}" # Truncate

            app.logger.error(f"SpotDL error for {unique_id} (return code {result.returncode}):\\n{full_error_output}")

            # No error.txt for user, no zip file for user on failure. Message is sent via socket.
            socketio.emit('download_failed', {
                'unique_id': unique_id,
                'search_query': search_query,
                'message': user_message,
                'zip_url': None # No zip file for failed downloads
            }, namespace='/')
            redis_client.setex(f"failed:{unique_id}", retention_seconds, user_message)

    except FileNotFoundError:
        user_message = "Download failed: spotdl command not found. Ensure it's installed and accessible in PATH."
        app.logger.error(f"SpotDL FileNotFoundError for {unique_id} processing {search_query}")
        socketio.emit('download_failed', {
            'unique_id': unique_id,
            'search_query': search_query,
            'message': user_message,
            'zip_url': None # No zip file
        }, namespace='/')
        redis_client.setex(f"failed:{unique_id}", retention_seconds, user_message)
    except Exception as e:
        user_message = f"An unexpected error occurred during spotdl processing: {str(e)}"
        app.logger.error(f"Unexpected error in run_spotdl for {unique_id} ({search_query}): {str(e)}", exc_info=True)
        
        socketio.emit('download_failed', {
            'unique_id': unique_id,
            'search_query': search_query,
            'message': user_message,
            'zip_url': None # No zip file
        }, namespace='/')
        redis_client.setex(f"failed:{unique_id}", retention_seconds, user_message)
    finally:
        if os.path.exists(download_folder):
            shutil.rmtree(download_folder)
        redis_client.delete(f"pending:{unique_id}")


def download_from_youtube(unique_id, url, output_format):
    redis_client.setex(f"pending:{unique_id}", 3600, "1")
    download_folder = os.path.join(MUSIC_DIR, unique_id)
    os.makedirs(download_folder, exist_ok=True)
    retention_seconds = int(os.getenv('CLEANUP_RETENTION_DAYS', 7)) * 86400 # Changed 'RETENTION_DAYS' to 'CLEANUP_RETENTION_DAYS'
    zip_file_path = os.path.join(MUSIC_DIR, unique_id + ".zip")

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
        'outtmpl': os.path.join(download_folder, '%(title)s.%(ext)s'), # yt-dlp downloads into this folder
        'writethumbnail': True,
        'embedthumbnail': True,
        'postprocessor_args': [
            '-write_id3v1', '1',
            '-id3v2_version', '3',
        ],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Clean up thumbnails from download_folder before zipping
        for file_in_dir in os.listdir(download_folder):
            if file_in_dir.endswith(('.webp', '.jpg', '.png')):
                os.remove(os.path.join(download_folder, file_in_dir))

        # yt-dlp command reported success, now create and check the archive
        shutil.make_archive(os.path.join(MUSIC_DIR, unique_id), 'zip', root_dir=download_folder)
        
        if not os.path.exists(zip_file_path):
            user_message = "Download failed: Archive file was not created after successful command."
            app.logger.error(f"Zip file {zip_file_path} not found after make_archive for {unique_id} (youtube-dl).")
            socketio.emit('download_failed', {
                'unique_id': unique_id, 'search_query': url,
                'message': user_message, 'zip_url': None
            }, namespace='/')
            redis_client.setex(f"failed:{unique_id}", retention_seconds, user_message)
            return # Exit after failure

        try:
            with zipfile.ZipFile(zip_file_path, 'r') as zf:
                file_list = [info.filename for info in zf.infolist() if not info.is_dir()]
            
            if not file_list:
                user_message = "Download failed: The downloaded archive is empty."
                app.logger.warning(f"Empty zip detected for {unique_id} (youtube-dl). Path: {zip_file_path}")
                socketio.emit('download_failed', {
                    'unique_id': unique_id, 'search_query': url,
                    'message': user_message, 'zip_url': None
                }, namespace='/')
                redis_client.setex(f"failed:{unique_id}", retention_seconds, user_message)
                if os.path.exists(zip_file_path): os.remove(zip_file_path) # Clean up empty zip
                return # Exit after failure
        except zipfile.BadZipFile:
            user_message = "Download failed: The downloaded archive is corrupted."
            app.logger.warning(f"Corrupted zip detected for {unique_id} (youtube-dl). Path: {zip_file_path}")
            socketio.emit('download_failed', {
                'unique_id': unique_id, 'search_query': url,
                'message': user_message, 'zip_url': None
            }, namespace='/')
            redis_client.setex(f"failed:{unique_id}", retention_seconds, user_message)
            if os.path.exists(zip_file_path): os.remove(zip_file_path) # Clean up corrupted zip
            return # Exit after failure
            
        # If all checks pass
        notify_client_download_complete(unique_id, f'/music/{unique_id}.zip')

    except Exception as e: # Catches yt-dlp errors and other exceptions in this block
        user_message = f"YouTube download failed: {str(e)}"
        app.logger.error(f"YouTubeDL error for {unique_id} processing {url}: {str(e)}", exc_info=True)
        socketio.emit('download_failed', {
            'unique_id': unique_id, 'search_query': url,
            'message': user_message, 'zip_url': None
        }, namespace='/')
        redis_client.setex(f"failed:{unique_id}", retention_seconds, user_message)
    finally:
        if os.path.exists(download_folder):
            shutil.rmtree(download_folder)
        redis_client.delete(f"pending:{unique_id}")

# ===============================
# Route Handlers
# ===============================

@app.before_request
def log_request_info():
    # This general request logger is removed as per new requirement
    # to only log specific /search route details.
    pass


@app.after_request
def log_response_info(response):
    # This general response logger is modified to only log /search details
    if request.path == '/search' and request.method == 'POST' and 'search_log_data' in request.environ:
        log_entry = request.environ['search_log_data']
        log_entry['status_code'] = response.status_code # Capture status code of the /search response
        search_request_log.append(log_entry)
        # Clean up from environ to avoid carrying it to other requests if any issue occurs
        del request.environ['search_log_data'] 
    return response


@app.route('/')
def index():
    return render_template('index.html', pending_requests=get_pending_requests()), 200


@app.route('/search', methods=['POST'])
def search():
    # Log search attempt details for admin panel (before validation)
    # We store it in request.environ to add the status code in after_request
    # This is done early to capture the attempt itself.
    if request.method == 'POST': # Ensure we only try to log form data for POST
        request.environ['search_log_data'] = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'ip': request.remote_addr,
            'search_query': request.form.get('search_query', ''), # Use .get for safety
            'audio_format': request.form.get('audio_format'),
            'lyrics_format': request.form.get('lyrics_format'),
            'output_format': request.form.get('output_format'),
            'status_code': None # To be filled by after_request
        }

    # Check pending requests
    if len(get_pending_requests()) >= get_max_pending_requests():
        return jsonify({'status': 'error', 'message': 'Too many requests. Please try again later.'}), 429

    search_query = request.form['search_query']
    audio_format = request.form.get('audio_format')
    lyrics_format = request.form.get('lyrics_format')
    output_format = request.form.get('output_format')

    # Validate inputs
    if not search_query:
        return jsonify({'status': 'error', 'message': 'Search query is required'}), 400

    if is_youtube_url(search_query):
        if not output_format in VALID_OUTPUT_FORMATS:
            return jsonify({'status': 'error', 'message': 'Invalid output format'}), 400
    elif not all([
        validate_input(search_query),
        validate_format_options(audio_format, lyrics_format, output_format)
    ]):
        return jsonify({'status': 'error', 'message': 'Invalid input provided'}), 400

    # Update download counter
    with open('searches.json', 'r+') as f:
        searches = json.load(f)
        searches['total'] += 1
        searches['last'] = search_query
        f.seek(0)
        json.dump(searches, f)
        f.truncate()

    # Start download process
    unique_id = str(uuid.uuid4())
    thread = threading.Thread(
        target=download_from_youtube if is_youtube_url(
            search_query) else run_spotdl,
        args=(unique_id, search_query, output_format) if is_youtube_url(search_query)
        else (unique_id, search_query, audio_format, lyrics_format, output_format)
    )
    thread.start()

    return jsonify({
        'status': 'success',
        'message': 'Download started',
        'unique_id': unique_id
    }, 202)


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    error = None
    if request.method == 'POST':
        if 'password' in request.form:
            if request.form['password'] == ADMIN_PASSWORD:
                session['admin_logged_in'] = True
                return redirect(url_for('admin'))
            else:
                error = 'Invalid password'
        # Handling for other POST requests (like setting limit) will be in separate routes
        # or checked here based on form parameters if preferred.

    if not session.get('admin_logged_in'):
        return render_template('admin.html', error=error)

    # If logged in, display the admin panel
    last_searches = list(search_request_log)
    last_searches.reverse() # Show newest first
    
    running_requests_ids = get_pending_requests()
    current_limit = get_max_pending_requests()

    # Gather useful information
    useful_info = {}
    useful_info['music_dir_path'] = MUSIC_DIR
    try:
        zip_files = [f for f in os.listdir(MUSIC_DIR) if f.lower().endswith('.zip')]
        useful_info['music_dir_zip_count'] = len(zip_files)
        music_dir_size_bytes = sum(os.path.getsize(os.path.join(MUSIC_DIR, f)) for f in os.listdir(MUSIC_DIR) if os.path.isfile(os.path.join(MUSIC_DIR, f)))
        useful_info['music_dir_used_space_mb'] = round(music_dir_size_bytes / (1024 * 1024), 2)
        
        # shutil.disk_usage gives info about the partition MUSIC_DIR is on
        disk_usage = shutil.disk_usage(MUSIC_DIR)
        useful_info['partition_total_space_gb'] = round(disk_usage.total / (1024 * 1024 * 1024), 2)
        useful_info['partition_free_space_gb'] = round(disk_usage.free / (1024 * 1024 * 1024), 2)
    except Exception as e:
        app.logger.error(f"Error gathering storage info: {e}")
        useful_info['storage_info_error'] = str(e)

    useful_info['cleanup_retention_days'] = os.getenv('CLEANUP_RETENTION_DAYS', '14') # Default from compose/app.py
    useful_info['max_pending_requests_effective'] = current_limit
    try:
        useful_info['redis_status'] = "Connected" if redis_client.ping() else "Connection Failed"
    except redis.exceptions.ConnectionError:
        useful_info['redis_status'] = "Connection Error"
    
    useful_info['cleanup_age_interval'] = os.getenv('AGE_CLEANUP_INTERVAL', '86400')
    useful_info['cleanup_max_dir_size_mb'] = os.getenv('MAX_MUSIC_DIR_SIZE_MB', '0')
    useful_info['cleanup_target_percentage'] = os.getenv('CLEANUP_TARGET_PERCENTAGE', '90')
    useful_info['cleanup_size_check_interval'] = os.getenv('SIZE_CHECK_INTERVAL', '3600')

    return render_template('admin.html', 
                           last_requests=last_searches, 
                           running_requests=running_requests_ids,
                           current_limit=current_limit,
                           useful_info=useful_info) # Pass new info

@app.route('/admin/delete_zips', methods=['POST'])
def admin_delete_zips():
    if not session.get('admin_logged_in'):
        flash('You must be logged in to perform this action.', 'error')
        return redirect(url_for('admin'))

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
            flash(f'Successfully deleted {deleted_count} ZIP files. Failed to delete {error_count} files. Check logs for details.', 'warning')
        else:
            flash(f'Successfully deleted {deleted_count} ZIP files from the music directory.', 'success')
    except Exception as e:
        flash(f'An error occurred while trying to delete ZIP files: {e}', 'error')
        app.logger.error(f"Error in admin_delete_zips: {e}")
    
    return redirect(url_for('admin'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin'))

@app.route('/admin/set_limit', methods=['POST'])
def admin_set_limit():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin')) # Or return 403 Forbidden

    new_limit = request.form.get('concurrent_limit')
    limit_message = ''
    if new_limit and new_limit.isdigit() and int(new_limit) > 0:
        redis_client.set(CONCURRENT_REQUEST_LIMIT_KEY, int(new_limit))
        limit_message = f"Concurrent request limit updated to {new_limit}."
        # Optionally, re-render admin page with a success message
        # Or redirect back to admin, which will pick up the new limit
    else:
        limit_message = "Invalid limit value provided."
        # Re-render with error or redirect
    
    # For simplicity, redirect back to admin; the message can be passed via session/flash if needed
    # Or, re-render the admin template directly with the message
    last_searches = list(search_request_log)
    last_searches.reverse()
    running_requests_ids = get_pending_requests()
    current_limit = get_max_pending_requests()
    # Re-gather useful_info for the re-render after setting limit
    useful_info = {}
    useful_info['music_dir_path'] = MUSIC_DIR
    try:
        zip_files = [f for f in os.listdir(MUSIC_DIR) if f.lower().endswith('.zip')]
        useful_info['music_dir_zip_count'] = len(zip_files)
        music_dir_size_bytes = sum(os.path.getsize(os.path.join(MUSIC_DIR, f)) for f in os.listdir(MUSIC_DIR) if os.path.isfile(os.path.join(MUSIC_DIR, f)))
        useful_info['music_dir_used_space_mb'] = round(music_dir_size_bytes / (1024 * 1024), 2)
        disk_usage = shutil.disk_usage(MUSIC_DIR)
        useful_info['partition_total_space_gb'] = round(disk_usage.total / (1024 * 1024 * 1024), 2)
        useful_info['partition_free_space_gb'] = round(disk_usage.free / (1024 * 1024 * 1024), 2)
    except Exception as e:
        app.logger.error(f"Error gathering storage info for set_limit response: {e}")
        useful_info['storage_info_error'] = str(e)

    useful_info['cleanup_retention_days'] = os.getenv('CLEANUP_RETENTION_DAYS', '14')
    useful_info['max_pending_requests_effective'] = current_limit # This is the updated one
    try:
        useful_info['redis_status'] = "Connected" if redis_client.ping() else "Connection Failed"
    except redis.exceptions.ConnectionError:
        useful_info['redis_status'] = "Connection Error"
    
    useful_info['cleanup_age_interval'] = os.getenv('AGE_CLEANUP_INTERVAL', '86400')
    useful_info['cleanup_max_dir_size_mb'] = os.getenv('MAX_MUSIC_DIR_SIZE_MB', '0')
    useful_info['cleanup_target_percentage'] = os.getenv('CLEANUP_TARGET_PERCENTAGE', '90')
    useful_info['cleanup_size_check_interval'] = os.getenv('SIZE_CHECK_INTERVAL', '3600')

    return render_template('admin.html', 
                           last_requests=last_searches, 
                           running_requests=running_requests_ids,
                           current_limit=current_limit,
                           limit_message=limit_message,
                           useful_info=useful_info) # Pass new info


@app.route('/download_counter', methods=['GET'])
def download_counter():
    with open('searches.json', 'r') as f:
        return str(json.load(f)['total'])


@app.route('/status/<unique_id>', methods=['GET'])
def check_request(unique_id):
    app.logger.debug(f"Checking status for {unique_id}")
    
    if platform.system() != 'Windows':
        os.system('sync')

    file_path = os.path.join(MUSIC_DIR, unique_id + ".zip")
    pending_key = f"pending:{unique_id}"
    failed_key = f"failed:{unique_id}"
    completed_key = f"completed:{unique_id}" # This key is set by notify_client_download_complete

    if redis_client.exists(pending_key):
        app.logger.debug(f"{unique_id} is pending")
        return jsonify({'status': 'pending'}), 202

    if redis_client.exists(failed_key):
        error_message = redis_client.get(failed_key).decode('utf-8', 'replace')
        zip_url = f'/music/{unique_id}.zip' if os.path.isfile(file_path) else None
        app.logger.debug(f"{unique_id} is failed: {error_message}")
        return jsonify({'status': 'failed', 'message': error_message, 'url': zip_url}), 200

    if redis_client.exists(completed_key):
        if os.path.isfile(file_path):
            app.logger.debug(f"{unique_id} is completed (Redis key exists, file exists)")
            return jsonify({'status': 'completed', 'url': f'/music/{unique_id}.zip'}), 200
        else:
            app.logger.warning(f"Completed key {completed_key} exists but file {file_path} is missing.")
            # Potentially clean up: redis_client.delete(completed_key)
            return jsonify({'status': 'error', 'message': 'File was marked completed but is now missing.'}), 404
            
    # Fallback: File exists but no explicit Redis state (pending, failed, completed).
    # This could be an old file or Redis data loss.
    if os.path.isfile(file_path):
        app.logger.info(f"File {file_path} exists without explicit Redis completed/failed state. Treating as completed.")
        # To ensure consistency, we can re-trigger the 'completed' state logic
        # This will set the 'completed:<id>' key and emit to sockets if necessary.
        # However, notify_client_download_complete also emits a socket event, which might be redundant if client is just polling.
        # For simplicity here, just return completed status. If full consistency is needed, call:
        # notify_client_download_complete(unique_id, f'/music/{unique_id}.zip')
        # For now, just return the status:
        return jsonify({'status': 'completed', 'url': f'/music/{unique_id}.zip'}), 200
    
    app.logger.debug(f"{unique_id} not found (no pending, failed, completed key, and no file)")
    return jsonify({'status': 'not_found', 'message': 'Request not found or expired.'}), 404

# ===============================
# WebSocket Handlers
# ===============================


@socketio.on('connect')
def handle_connect():
    completed_downloads = []
    pending_downloads = []

    # Get completed downloads
    for key in redis_client.keys("completed:*"):
        unique_id = key.decode('utf-8').split(':')[1]
        data = json.loads(redis_client.get(key))
        completed_downloads.append({
            'unique_id': unique_id,
            'url': data['url']
        })

    # Get pending downloads
    for key in redis_client.keys("pending:*"):
        unique_id = key.decode('utf-8').split(':')[1]
        pending_downloads.append({
            'unique_id': unique_id,
            'status': 'pending'
        })

    if completed_downloads or pending_downloads:
        emit('download_status', {
            'completed': completed_downloads,
            'pending': pending_downloads
        })

# ===============================
# File Management Functions
# ===============================


def get_pending_requests():
    pending_keys = redis_client.keys("pending:*")
    return [key.decode('utf-8').split(':')[1] for key in pending_keys]


def notify_client_download_complete(unique_id, download_url):
    data = {
        'url': download_url,
        'timestamp': time.time(),
        'created_at': time.time()
    }

    retention_seconds = int(os.getenv('CLEANUP_RETENTION_DAYS', 14)) * 86400 # Changed 'RETENTION_DAYS' to 'CLEANUP_RETENTION_DAYS', and default to 14 to match cleanup_service.py
    redis_client.setex(
        f"completed:{unique_id}",
        retention_seconds,
        json.dumps(data)
    )

    socketio.emit('download_complete', {
        'unique_id': unique_id,
        'url': download_url
    }, namespace='/')

# ===============================
# Application Startup
# ===============================


if __name__ == '__main__':
    # Initialize directories and files
    os.makedirs(MUSIC_DIR, exist_ok=True)

    if not os.path.isfile(PENDING_REQUESTS_FILE):
        open(PENDING_REQUESTS_FILE, 'w').close()

    if not os.path.isfile('searches.json'):
        with open('searches.json', 'w') as f:
            json.dump({'total': 0, 'last': ''}, f)

    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
