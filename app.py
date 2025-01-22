from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import subprocess
import threading
import uuid
import shutil
import time
import json
from urllib.parse import urlparse
import re
import yt_dlp
import platform
import redis

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'  # Change this to a secure secret key
socketio = SocketIO(app)

# Redis connection
redis_client = redis.Redis(host='spotifydownloader-redis', port=6379, db=0)

# Set music directory based on OS
if platform.system() == 'Windows':
    music_directory = "C:/SpotifyDownloader/music/"
else:
    music_directory = "/var/www/SpotifyDownloader/"

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri="memory:///rate_limits.db",
    default_limits=["200 per day", "50 per hour"]
)

# Update file path to be absolute
pending_requests_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pending_requests.txt')


def is_valid_url(input_url):
    """Check if the input string is a valid URL."""
    try:
        result = urlparse(input_url)
        return all([result.scheme, result.netloc])
    except:
        return False

def validate_spotify_url(input_url):
    """Validate if the input URL is a valid Spotify link."""
    parsed_url = urlparse(input_url)
    return parsed_url.scheme in ['http', 'https'] and \
           parsed_url.netloc == 'open.spotify.com'

def is_youtube_url(url):
    """Check if the URL is a valid YouTube URL."""
    youtube_regex = r'^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+$'
    return bool(re.match(youtube_regex, url))

def validate_song_title(title):
    """Basic validation for song titles."""
    return bool(re.match(r"^[a-zA-Z0-9\s\-'.,!&?=-]+$", title))

def validate_input(input_string):
    """Determine if input is a Spotify URL or song title, then validate accordingly."""
    if is_valid_url(input_string):
        return validate_spotify_url(input_string) or is_youtube_url(input_string)
    else:
        return validate_song_title(input_string)

# Define valid options for each dropdown
VALID_AUDIO_PROVIDERS = {'youtube-music', 'youtube', 'slider-kz', 'soundcloud', 'bandcamp', 'piped', 'yt-dlp'}
VALID_LYRICS_PROVIDERS = {'musixmatch', 'genius', 'azlyrics', 'synced'}
VALID_OUTPUT_FORMATS = {'mp3', 'm4a', 'wav', 'flac', 'ogg', 'opus'}

def validate_audio_provider(selection):
    return selection in VALID_AUDIO_PROVIDERS

def validate_lyrics_provider(selection):
    return selection in VALID_LYRICS_PROVIDERS

def validate_output_format(selection):
    return selection in VALID_OUTPUT_FORMATS


def run_spotdl(unique_id, search_query, audio_format, lyrics_format, output_format):
    # Add to pending requests with 1 hour expiry
    redis_client.setex(f"pending:{unique_id}", 3600, "1")
    
    download_folder = os.path.join(music_directory, unique_id)
    os.makedirs(download_folder, exist_ok=True)

    command = ['spotdl', search_query, '--max-retries', '2', '--audio', audio_format, '--format', output_format, '--output', download_folder, '--threads', '4']

    try:
        result = subprocess.run(command, check=True, text=True)
    except subprocess.CalledProcessError as e:
        result = e

    if result.returncode == 0:
        try:
            shutil.make_archive(download_folder, 'zip', download_folder)
            notify_client_download_complete(unique_id, f'/music/{unique_id}.zip')
        except FileNotFoundError:
            with open(os.path.join(download_folder, 'error.txt'), 'w') as error_file:
                error_file.write("Error downloading song")
            shutil.make_archive(download_folder, 'zip', download_folder)
    else:
        with open(os.path.join(download_folder, 'error.txt'), 'w') as error_file:
            error_file.write("Error downloading song")
        shutil.make_archive(download_folder, 'zip', download_folder)

    shutil.rmtree(download_folder)

    # Remove from pending requests
    redis_client.delete(f"pending:{unique_id}")

def download_from_youtube(unique_id, url, output_format):
    download_folder = os.path.join(music_directory, unique_id)
    os.makedirs(download_folder, exist_ok=True)
    output_template = os.path.join(download_folder, '%(title)s.%(ext)s')

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': output_format,
            'preferredquality': '320',
        }, {
            'key': 'FFmpegMetadata',
            'add_metadata': True,
        }, {
            'key': 'EmbedThumbnail',  # Add this postprocessor to handle thumbnails
        }],
        'outtmpl': output_template,
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
            
        # Clean up any leftover thumbnail files
        for file in os.listdir(download_folder):
            if file.endswith(('.webp', '.jpg', '.png')):
                os.remove(os.path.join(download_folder, file))
                
        shutil.make_archive(download_folder, 'zip', download_folder)
        notify_client_download_complete(unique_id, f'/music/{unique_id}.zip')
    except Exception as e:
        with open(os.path.join(download_folder, 'error.txt'), 'w') as error_file:
            error_file.write(f"Error downloading: {str(e)}")
        shutil.make_archive(download_folder, 'zip', download_folder)
    finally:
        shutil.rmtree(download_folder)

@app.route('/')
def index():
    return render_template('index.html', pending_requests=get_pending_requests()), 200

@app.route('/search', methods=['POST'])
@limiter.limit("1/5seconds;10/minute")
def search():
    # Load search counter and last search query
    with open('searches.json', 'r') as f:
        searches = json.load(f)
    searches['total'] += 1
    search_query = request.form['search_query']
    searches['last'] = search_query
    with open('searches.json', 'w') as f:
        json.dump(searches, f)

    # Extract form data
    audio_format = request.form.get('audio_format')
    lyrics_format = request.form.get('lyrics_format')
    output_format = request.form.get('output_format')

    if not search_query:
        return jsonify({'status': 'error', 'message': 'Search query is required'}), 400

    # validate search query and form data and send 400 bad request if invalid
    if is_youtube_url(search_query):
        if not output_format or not output_format in VALID_OUTPUT_FORMATS:
            return jsonify({'status': 'error', 'message': 'Invalid output format'}), 400
    else:
        if not validate_input(search_query) or \
           not validate_audio_provider(audio_format) or \
           not validate_lyrics_provider(lyrics_format) or \
           not validate_output_format(output_format):
            return jsonify({'status': 'error', 'message': 'Invalid input provided'}), 400

    unique_id = str(uuid.uuid4())

    if is_youtube_url(search_query):
        thread = threading.Thread(target=download_from_youtube, args=(unique_id, search_query, output_format))
    else:
        thread = threading.Thread(target=run_spotdl, args=(unique_id, search_query, audio_format, lyrics_format, output_format))
    
    thread.start()

    return jsonify({'status': 'success', 'message': 'Download started', 'unique_id': unique_id}), 202

@app.route('/download_counter', methods=['GET'])
def download_counter():
    with open('searches.json', 'r') as f:
        searches = json.load(f)
    return str(searches['total'])


@app.route('/status/<unique_id>', methods=['GET'])
def check_request(unique_id):
    pending_requests = get_pending_requests()

    if unique_id in pending_requests:
        return jsonify({'status': 'pending'}), 202
    else:
        # Check if the file exists
        if os.path.isfile(os.path.join(music_directory, unique_id + ".zip")):
            return jsonify({'status': 'completed', 'url': f'/music/{unique_id}.zip'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'File not found'}), 404


def delete_file(download_file):
    try:
        time.sleep(3600)
        os.remove(download_file)
    except:
        pass

def get_pending_requests():
    pending_keys = redis_client.keys("pending:*")
    return [key.decode('utf-8').split(':')[1] for key in pending_keys]

def notify_client_download_complete(unique_id, download_url):
    # Store completed download in Redis with 24h expiry
    redis_client.setex(f"completed:{unique_id}", 
                      86400,  # 24 hours 
                      json.dumps({
                          'url': download_url,
                          'timestamp': time.time()
                      }))
    
    socketio.emit('download_complete', {
        'unique_id': unique_id,
        'url': download_url
    }, namespace='/')

@socketio.on('connect')
def handle_connect():
    # Check for any completed downloads that happened while client was disconnected
    completed_downloads = []
    pending_downloads = []
    
    # Get all completed downloads from Redis
    for key in redis_client.keys("completed:*"):
        unique_id = key.decode('utf-8').split(':')[1]
        data = json.loads(redis_client.get(key))
        completed_downloads.append({
            'unique_id': unique_id,
            'url': data['url']
        })
    
    # Get all pending downloads from Redis
    for key in redis_client.keys("pending:*"):
        unique_id = key.decode('utf-8').split(':')[1]
        pending_downloads.append({
            'unique_id': unique_id,
            'status': 'pending'
        })
    
    # Send both completed and pending downloads to client
    if completed_downloads or pending_downloads:
        emit('download_status', {
            'completed': completed_downloads,
            'pending': pending_downloads
        })

if __name__ == '__main__':
    os.makedirs(music_directory, exist_ok=True)
    
    # Ensure pending_requests.txt exists and is a file
    if not os.path.isfile(pending_requests_file):
        with open(pending_requests_file, 'w') as f:
            f.write('')
            
    # create json file if it doesn't exist
    if not os.path.isfile('searches.json'):
        with open('searches.json', 'w') as f:
            json.dump({'total': 0, 'last': ''}, f)
    # Remove direct socketio.run call since we're using Gunicorn
    app.run(host='0.0.0.0', port=5000, debug=False)
