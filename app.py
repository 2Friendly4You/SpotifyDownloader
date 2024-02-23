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

app = Flask(__name__)
music_directory = "/var/www/html/SpotifyDownloader/"

uri = 'memcached://localhost:11211'  # URI to the storage backend

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri=uri,
)

pending_requests_file = 'pending_requests.txt'

def run_spotdl(unique_id, search_query, audio_format, lyrics_format, output_format):
    with open(pending_requests_file, 'a') as pending_file:
        pending_file.write(unique_id + '\n')

    download_folder = os.path.join(music_directory, unique_id)
    os.makedirs(download_folder, exist_ok=True)

    command = ['spotdl', search_query, '--max-retries', '5', '--audio', audio_format, '--format', output_format, '--output', download_folder]

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
    return render_template('index.html', pending_requests=get_pending_requests())

@app.route('/search', methods=['POST'])
@limiter.limit("1/5seconds;10/minute")
def search():
    # add counter of amount of searches and save to json file
    with open('searches.json', 'r') as f:
        searches = json.load(f)
    searches['total'] += 1
    searches['last'] = request.form['search_query']
    with open('searches.json', 'w') as f:
        json.dump(searches, f)

    search_query = request.form['search_query']
    audio_format = request.form['audio_format']
    lyrics_format = request.form['lyrics_format']
    output_format = request.form['output_format']

    # Check if the search query is empty
    if not search_query:
        return jsonify({'status': 'error', 'message': 'Search query is required'})

    # Generate a new unique ID
    unique_id = str(uuid.uuid4())

    # Run spotdl in a background thread
    thread = threading.Thread(target=run_spotdl, args=(unique_id, search_query, audio_format, lyrics_format, output_format))
    thread.start()

    return jsonify({'status': 'success', 'message': 'Song download started', 'unique_id': unique_id})

@app.route('/download_counter', methods=['GET'])
def download_counter():
    with open('searches.json', 'r') as f:
        searches = json.load(f)
    return str(searches['total'])


@app.route('/status/<unique_id>', methods=['GET'])
def check_request(unique_id):
    pending_requests = get_pending_requests()

    if unique_id in pending_requests:
        return jsonify({'status': 'pending'})
    else:
        return jsonify({'status': 'completed'})

@app.route('/download/<unique_id>', methods=['GET', 'POST'])
def download(unique_id):
    download_file_path = unique_id + ".zip"
    download_url = f"https://sddata.codemagie.xyz/music/{download_file_path}"
    # Check if the file exists
    if os.path.isfile(os.path.join(music_directory, download_file_path)):
        return jsonify({'status': 'success', 'message': 'File ready for download', 'url': download_url})
    else:
        return jsonify({'status': 'error', 'message': 'File not found'})


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
