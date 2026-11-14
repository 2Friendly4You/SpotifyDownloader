import os

from flask import Blueprint, abort, jsonify, send_file, send_from_directory

from app.config import MUSIC_DIR
from app.searches import get_download_total
from app.state import PROGRESS_DETAIL_KEYS, download_state
from app.titles import content_disposition, is_job_id, read_zip_title, zip_download_name

status_bp = Blueprint('status', __name__)


@status_bp.route('/music/<path:filename>')
def serve_music(filename):
    return send_from_directory(MUSIC_DIR, filename)


@status_bp.route('/api/download/<unique_id>', methods=['GET'])
def download_zip(unique_id):
    """The finished zip, saved under the playlist or song name.

    On disk it stays ``<uuid>.zip``. The title comes from memory, or from
    the zip comment after a restart, and falls back to the UUID.
    """
    if not is_job_id(unique_id):
        abort(404)
    path = os.path.join(MUSIC_DIR, unique_id + '.zip')
    if not os.path.isfile(path):
        abort(404)
    title = download_state.title(unique_id) or read_zip_title(path)
    response = send_file(path, mimetype='application/zip', conditional=True, max_age=0)
    response.headers['Content-Disposition'] = content_disposition(
        zip_download_name(title, unique_id), f'{unique_id}.zip'
    )
    return response


def _with_title(body, unique_id):
    title = download_state.title(unique_id)
    if title:
        body['title'] = title
    return body


@status_bp.route('/api/download_counter', methods=['GET'])
def download_counter():
    return jsonify({'total': get_download_total()})


@status_bp.route('/api/status/<unique_id>', methods=['GET'])
def check_request(unique_id):
    file_path = os.path.join(MUSIC_DIR, unique_id + ".zip")
    if download_state.is_cancelled(unique_id):
        # The worker may still be winding down, but for the user the job is gone.
        return jsonify({'status': 'not_found', 'message': 'Request not found or expired.'}), 404
    kind, extra = download_state.lookup(unique_id)

    if kind == 'queued':
        return jsonify(_with_title({
            'status': 'queued',
            'position': extra,
        }, unique_id)), 202

    if kind == 'pending':
        progress = download_state.get_progress(unique_id)
        body = {
            'status': 'pending',
            'progress': round(progress['percent'], 1),
            'progress_message': progress['message'],
        }
        for key in PROGRESS_DETAIL_KEYS:
            if key in progress:
                body[key] = progress[key]
        return jsonify(_with_title(body, unique_id)), 202

    if kind == 'failed':
        error_message = extra or "Download failed"
        zip_url = f'/api/download/{unique_id}' if os.path.isfile(file_path) else None
        body = {'status': 'failed', 'message': error_message, 'url': zip_url}
        failed_tracks = download_state.failed_tracks(unique_id)
        if failed_tracks:
            body['failed_tracks'] = failed_tracks
        return jsonify(_with_title(body, unique_id)), 200

    if kind == 'completed' or os.path.isfile(file_path):
        if os.path.isfile(file_path):
            body = {'status': 'completed', 'url': f'/api/download/{unique_id}'}
            title = download_state.title(unique_id) or read_zip_title(file_path)
            if title:
                body['title'] = title
            failed_tracks = download_state.failed_tracks(unique_id)
            if failed_tracks:
                body['failed_tracks'] = failed_tracks
            return jsonify(body), 200
        return jsonify({'status': 'error', 'message': 'File was marked completed but is now missing.'}), 404

    return jsonify({'status': 'not_found', 'message': 'Request not found or expired.'}), 404
