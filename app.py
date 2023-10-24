import os
import subprocess
import threading
from flask import Flask, render_template, request, jsonify, send_file
import uuid
import shutil
import time

app = Flask(__name__)

# A list to store pending request UUIDs
pending_requests = []

def is_request_pending(unique_id):
    return unique_id in pending_requests

import os
import subprocess
import shutil

def run_spotdl(unique_id, search_query, audio_format, lyrics_format, output_format):
    download_folder = os.path.join('templates', 'download', unique_id)
    os.makedirs(download_folder, exist_ok=True)

    # Run spotdl with the provided parameters and unique folder
    if audio_format == 'spotify':
        command = f'spotdl --lyrics {lyrics_format} --format {output_format} --output "{download_folder}" "{search_query}"'
    else:
        command = f'spotdl --audio {audio_format} --lyrics {lyrics_format} --format {output_format} --output "{download_folder}" "{search_query}"'

    result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if result.returncode == 0:
        # Create a zip file with the contents of the folder
        try:
            shutil.make_archive(download_folder, 'zip', download_folder)
        except FileNotFoundError as e:
            time.sleep(1)
            shutil.make_archive(download_folder, 'zip', download_folder)

        # Remove the original folder
        shutil.rmtree(download_folder)

        # Remove the UUID from the list when the download is complete
        pending_requests.remove(unique_id)
    else:
        print(unique_id)
        pending_requests.remove(unique_id)

@app.route('/')
def index():
    return render_template('index.html', pending_requests=pending_requests)

@app.route('/search', methods=['POST'])
def search():
    search_query = request.form['search_query']
    audio_format = request.form['audio_format']
    lyrics_format = request.form['lyrics_format']
    output_format = request.form['output_format']

    # Generate a new unique ID
    while True:
        unique_id = str(uuid.uuid4())
        download_folder = os.path.join('templates', 'download', unique_id)
        if not os.path.exists(download_folder):
            break

    # Add the UUID to the list of pending requests
    pending_requests.append(unique_id)

    # Run spotdl in a background thread
    thread = threading.Thread(target=run_spotdl, args=(unique_id, search_query, audio_format, lyrics_format, output_format))
    thread.start()

    return jsonify({'status': 'success', 'message': 'Song download started', 'unique_id': unique_id})

@app.route('/status/<unique_id>', methods=['GET'])
def check_request(unique_id):
    if is_request_pending(unique_id):
        return jsonify({'status': 'pending'})
    else:
        return jsonify({'status': 'completed'})

@app.route('/download/<unique_id>', methods=['GET', 'POST'])
def download(unique_id):
    download_file = os.path.join('templates', 'download', unique_id + ".zip")
    print(download_file)
    if os.path.isfile(download_file):
        return send_file(download_file, as_attachment=True)
    else:
        return jsonify({'status': 'error', 'message': 'File not found'})
        
if __name__ == '__main__':
    app.run(debug=False)
