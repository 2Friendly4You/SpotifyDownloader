import os

from flask import Blueprint, jsonify, send_from_directory

from app.config import MUSIC_DIR
from app.searches import get_download_total
from app.state import download_state

status_bp = Blueprint('status', __name__)


@status_bp.route('/music/<path:filename>')
def serve_music(filename):
    return send_from_directory(MUSIC_DIR, filename)


@status_bp.route('/api/download_counter', methods=['GET'])
def download_counter():
    return jsonify({'total': get_download_total()})


@status_bp.route('/api/status/<unique_id>', methods=['GET'])
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
