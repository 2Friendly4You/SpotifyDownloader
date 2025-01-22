import os
import re
import json
import time
import uuid
import redis
import shutil
import platform
import threading
import subprocess
from urllib.parse import urlparse

import yt_dlp
from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# ===============================
# Core Configuration
# ===============================

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, 
    cors_allowed_origins="*",
    async_mode='eventlet',
    logger=True,
    engineio_logger=True,
    ping_timeout=60,
    ping_interval=25
)
redis_client = redis.Redis(host='spotifydownloader-redis', port=6379, db=0)

# Configure rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri="memory:///rate_limits.db",
    default_limits=["200 per day", "50 per hour"]
)

# Configure paths and constants
MUSIC_DIR = "C:/SpotifyDownloader/music/" if platform.system() == 'Windows' else "/var/www/SpotifyDownloader/"
PENDING_REQUESTS_FILE = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), 'pending_requests.txt')

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
    redis_client.setex(f"pending:{unique_id}", 3600, "1")
    download_folder = os.path.join(MUSIC_DIR, unique_id)
    os.makedirs(download_folder, exist_ok=True)

    try:
        command = [
            'spotdl', search_query,
            '--max-retries', '2',
            '--audio', audio_format,
            '--format', output_format,
            '--output', download_folder,
            '--threads', '4'
        ]
        result = subprocess.run(command, check=True, text=True)

        if result.returncode == 0:
            shutil.make_archive(download_folder, 'zip', download_folder)
            notify_client_download_complete(
                unique_id, f'/music/{unique_id}.zip')
        else:
            raise subprocess.CalledProcessError(result.returncode, command)

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        with open(os.path.join(download_folder, 'error.txt'), 'w') as f:
            f.write(f"Error downloading: {str(e)}")
        shutil.make_archive(download_folder, 'zip', download_folder)

    finally:
        shutil.rmtree(download_folder)
        redis_client.delete(f"pending:{unique_id}")


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
        'embedthumbnail': True,
        'postprocessor_args': [
            '-write_id3v1', '1',
            '-id3v2_version', '3',
        ],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Clean up thumbnails
        for file in os.listdir(download_folder):
            if file.endswith(('.webp', '.jpg', '.png')):
                os.remove(os.path.join(download_folder, file))

        shutil.make_archive(download_folder, 'zip', download_folder)
        notify_client_download_complete(unique_id, f'/music/{unique_id}.zip')

    except Exception as e:
        with open(os.path.join(download_folder, 'error.txt'), 'w') as f:
            f.write(f"Error downloading: {str(e)}")
        shutil.make_archive(download_folder, 'zip', download_folder)

    finally:
        shutil.rmtree(download_folder)

# ===============================
# Route Handlers
# ===============================


@app.route('/')
def index():
    return render_template('index.html', pending_requests=get_pending_requests()), 200


@app.route('/search', methods=['POST'])
@limiter.limit("1/5seconds;10/minute")
def search():
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
    }), 202


@app.route('/download_counter', methods=['GET'])
def download_counter():
    with open('searches.json', 'r') as f:
        return str(json.load(f)['total'])


@app.route('/status/<unique_id>', methods=['GET'])
def check_request(unique_id):
    if unique_id in get_pending_requests():
        return jsonify({'status': 'pending'}), 202

    if os.path.isfile(os.path.join(MUSIC_DIR, unique_id + ".zip")):
        return jsonify({'status': 'completed', 'url': f'/music/{unique_id}.zip'}), 200

    return jsonify({'status': 'error', 'message': 'File not found'}), 404

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

    retention_seconds = int(os.getenv('RETENTION_DAYS', 14)) * 86400
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
