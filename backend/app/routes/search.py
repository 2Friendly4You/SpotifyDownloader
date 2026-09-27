import uuid
from collections import deque
from datetime import datetime

from flask import Blueprint, jsonify, request

from app.config import VALID_OUTPUT_FORMATS
from app.downloads import emit_queue_update, expire_download_state, start_download_job
from app.searches import record_search
from app.state import download_state
from app.validation import is_youtube_url, validate_format_options, validate_input

search_bp = Blueprint('search', __name__)
search_request_log = deque(maxlen=50)


@search_bp.after_request
def log_response_info(response):
    if request.path == '/api/search' and request.method == 'POST' and 'search_log_data' in request.environ:
        log_entry = request.environ['search_log_data']
        log_entry['status_code'] = response.status_code
        search_request_log.append(log_entry)
        del request.environ['search_log_data']
    return response


@search_bp.route('/api/search', methods=['POST'])
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


@search_bp.route('/api/search/<unique_id>', methods=['DELETE'])
def cancel_queued_search(unique_id):
    if download_state.cancel_queued(unique_id):
        emit_queue_update()
        return jsonify({'status': 'success', 'cancelled': True})
    return jsonify({
        'status': 'error',
        'message': 'Request is not queued.',
        'cancelled': False,
    }), 404
