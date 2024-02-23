from flask import Flask, request, jsonify, render_template
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

app = Flask(__name__)
music_directory = "/var/www/SpotifyDownloader/"

uri = 'memcached://localhost:11211'  # URI to the storage backend

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri=uri,
)

pending_requests_file = 'pending_requests.txt'


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
           parsed_url.netloc == 'open.spotify.com' and \
           parsed_url.path.split('/')[1] in ['track', 'album', 'playlist']

def validate_song_title(title):
    """Basic validation for song titles."""
    return bool(re.match(r"^[a-zA-Z0-9\s\-'.,!&]+$", title))

def validate_input(input_string):
    """Determine if input is a Spotify URL or song title, then validate accordingly."""
    if is_valid_url(input_string):
        return validate_spotify_url(input_string)
    else:
        return validate_song_title(input_string)

# Define valid options for each dropdown
VALID_AUDIO_PROVIDERS = {'youtube-music', 'youtube', 'slider-kz', 'soundcloud', 'bandcamp', 'piped'}
VALID_LYRICS_PROVIDERS = {'musixmatch', 'genius', 'azlyrics', 'synced'}
VALID_OUTPUT_FORMATS = {'mp3', 'm4a', 'wav', 'flac', 'ogg', 'opus'}

def validate_audio_provider(selection):
    return selection in VALID_AUDIO_PROVIDERS

def validate_lyrics_provider(selection):
    return selection in VALID_LYRICS_PROVIDERS

def validate_output_format(selection):
    return selection in VALID_OUTPUT_FORMATS


def run_spotdl(unique_id, search_query, audio_format, lyrics_format, output_format):
    with open(pending_requests_file, 'a') as pending_file:
        pending_file.write(unique_id + '\n')

    download_folder = os.path.join(music_directory, unique_id)
    os.makedirs(download_folder, exist_ok=True)

    command = ['spotdl', search_query, '--max-retries', '5', '--audio', audio_format, '--format', output_format, '--output', download_folder, '--threads', '8']

    try:
        result = subprocess.run(command, check=True, text=True)
    except subprocess.CalledProcessError as e:
        result = e

    if result.returncode == 0:
        try:
            shutil.make_archive(download_folder, 'zip', download_folder)
        except FileNotFoundError:
            with open(os.path.join(download_folder, 'error.txt'), 'w') as error_file:
                error_file.write("Error downloading song")
            shutil.make_archive(download_folder, 'zip', download_folder)
    else:
        with open(os.path.join(download_folder, 'error.txt'), 'w') as error_file:
            error_file.write("Error downloading song")
        shutil.make_archive(download_folder, 'zip', download_folder)

    shutil.rmtree(download_folder)

    with open(pending_requests_file, 'r') as pending_file:
        lines = pending_file.readlines()
    with open(pending_requests_file, 'w') as pending_file:
        for line in lines:
            if line.strip() != unique_id:
                pending_file.write(line)

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
    if not validate_input(search_query) or \
       not validate_audio_provider(audio_format) or \
       not validate_lyrics_provider(lyrics_format) or \
       not validate_output_format(output_format):
        return jsonify({'status': 'error', 'message': 'Invalid input provided'}), 400

    unique_id = str(uuid.uuid4())
    thread = threading.Thread(target=run_spotdl, args=(unique_id, search_query, audio_format, lyrics_format, output_format))
    thread.start()

    return jsonify({'status': 'success', 'message': 'Song download started', 'unique_id': unique_id}), 202

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
            return jsonify({'status': 'completed', 'url': 'https://sddata.codemagie.xyz/music/' + unique_id + '.zip'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'File not found'}), 404


def delete_file(download_file):
    try:
        time.sleep(3600)
        os.remove(download_file)
    except:
        pass

def get_pending_requests():
    try:
        with open(pending_requests_file, 'r') as pending_file:
            return [line.strip() for line in pending_file.readlines()]
    except FileNotFoundError:
        return []

if __name__ == '__main__':
    os.makedirs(music_directory, exist_ok=True)
    # create json file if it doesn't exist
    if not os.path.isfile('searches.json'):
        with open('searches.json', 'w') as f:
            json.dump({'total': 0, 'last': ''}, f)
    app.run(host='0.0.0.0', port=5000, debug=False)
