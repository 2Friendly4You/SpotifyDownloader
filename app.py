import os
import subprocess
import threading
from flask import Flask, render_template, request, jsonify, send_file
import uuid
import shutil
import time

app = Flask(__name__)

# A file to store pending request UUIDs
pending_requests_file = 'pending_requests.txt'

def run_spotdl(unique_id, search_query, audio_format, lyrics_format, output_format):
    # Mark the request as pending in the shared file
    with open(pending_requests_file, 'a') as pending_file:
        pending_file.write(unique_id + '\n')

    download_folder = os.path.join('templates', 'download', unique_id)
    os.makedirs(download_folder, exist_ok=True)

    # Run spotdl with the provided parameters and unique folder
    if not lyrics_format:
        command = f'spotdl "{search_query}" --audio {audio_format} --format {output_format} --output "{download_folder}"'
    else:
        command = f'spotdl "{search_query}" --audio {audio_format} --lyrics {lyrics_format} --format {output_format} --output "{download_folder}"'
    try:
        result = subprocess.run(command, shell=True, check=True, text=True)
    except subprocess.CalledProcessError as e:
        result = e

    if result.returncode == 0:
        # Create a zip file with the contents of the folder
        try:
            shutil.make_archive(download_folder, 'zip', download_folder)
        except FileNotFoundError as e:
            time.sleep(1)
            shutil.make_archive(download_folder, 'zip', download_folder)
    else:
        # Create an empty zip file
        with open(os.path.join(download_folder, 'error.txt'), 'w') as error_file:
            error_file.write("Error downloading song")
        shutil.make_archive(download_folder, 'zip', download_folder)

    # Remove the original folder
    shutil.rmtree(download_folder)

    # Remove the request from the shared file when completed
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
def search():
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

@app.route('/status/<unique_id>', methods=['GET'])
def check_request(unique_id):
    pending_requests = get_pending_requests()

    if unique_id in pending_requests:
        return jsonify({'status': 'pending'})
    else:
        return jsonify({'status': 'completed'})

@app.route('/download/<unique_id>', methods=['GET', 'POST'])
def download(unique_id):
    download_file = os.path.join('templates', 'download', unique_id + ".zip")
    if os.path.isfile(download_file):
        return send_file(download_file, as_attachment=True)
    else:
        return jsonify({'status': 'error', 'message': 'File not found'})

def get_pending_requests():
    try:
        with open(pending_requests_file, 'r') as pending_file:
            return [line.strip() for line in pending_file.readlines()]
    except FileNotFoundError:
        return []

if __name__ == '__main__':
    os.makedirs('templates/download', exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=False)
