import os
import shutil
import threading
import zipfile

import yt_dlp
from spotdl.download.downloader import Downloader
from spotdl.download.progress_handler import ProgressHandler
from spotdl.utils.config import SPOTIFY_OPTIONS
from spotdl.utils.search import parse_query
from spotdl.utils.spotify import SpotifyClient, SpotifyError

from app.config import MUSIC_DIR
from app.extensions import socketio
from app.state import download_state

_spotify_init_lock = threading.Lock()


def _logger():
    from app import app
    return app.logger


def report_progress(unique_id, percent, message, force=False):
    stored_percent, stored_message, should_emit = download_state.update_progress(
        unique_id, percent, message
    )
    if not should_emit and not force:
        return
    socketio.emit('download_progress', {
        'unique_id': unique_id,
        'progress': round(stored_percent, 1),
        'message': stored_message,
    }, namespace='/')


def youtube_download_percent(data):
    info = data.get('info_dict') or {}
    total = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
    downloaded = data.get('downloaded_bytes') or 0
    fraction = (downloaded / total) if total else 0
    index = data.get('playlist_index') or info.get('playlist_index') or 1
    count = data.get('playlist_count') or info.get('playlist_count') or info.get('n_entries') or 1
    try:
        index = max(int(index), 1)
        count = max(int(count), 1)
    except (TypeError, ValueError):
        index, count = 1, 1
    if index > count:
        count = index
    return ((index - 1) + fraction) / count * 90


def attach_spotdl_progress(downloader, unique_id):
    def callback(tracker, message):
        total = tracker.parent.overall_total or 0
        if total:
            percent = tracker.parent.overall_progress / total * 100
        else:
            percent = tracker.progress or 0
        report_progress(unique_id, percent, message or 'Downloading')

    downloader.progress_handler = ProgressHandler(
        simple_tui=True,
        update_callback=callback,
        web_ui=True,
    )


def mark_failed(unique_id, search_query, message):
    _logger().error(f"Download failed for {unique_id} ({search_query}): {message}")
    socketio.emit('download_failed', {
        'unique_id': unique_id,
        'search_query': search_query,
        'message': message,
        'zip_url': None,
    }, namespace='/')
    download_state.mark_failed(unique_id, message)


def notify_client_download_complete(unique_id, download_url):
    download_state.mark_completed(unique_id)
    socketio.emit('download_complete', {
        'unique_id': unique_id,
        'url': download_url
    }, namespace='/')


def publish_zip(unique_id, search_query, download_folder):
    current = download_state.get_progress(unique_id)
    report_progress(unique_id, max(current['percent'], 95), 'Packaging', force=True)
    zip_path = os.path.join(MUSIC_DIR, unique_id + ".zip")
    shutil.make_archive(os.path.join(MUSIC_DIR, unique_id), 'zip', root_dir=download_folder)

    if not os.path.isfile(zip_path):
        mark_failed(unique_id, search_query, "Download failed: Archive file was not created.")
        return

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            has_files = any(not info.is_dir() for info in zf.infolist())
    except zipfile.BadZipFile:
        mark_failed(unique_id, search_query, "Download failed: The downloaded archive is corrupted.")
        os.remove(zip_path)
        return

    if not has_files:
        mark_failed(unique_id, search_query, "Download failed: The downloaded archive is empty.")
        os.remove(zip_path)
        return

    notify_client_download_complete(unique_id, f'/music/{unique_id}.zip')


def ensure_spotify_client():
    with _spotify_init_lock:
        try:
            SpotifyClient()
        except SpotifyError:
            SpotifyClient.init(
                client_id=SPOTIFY_OPTIONS["client_id"],
                client_secret=SPOTIFY_OPTIONS["client_secret"],
                no_cache=True,
                max_retries=4,
            )


def run_spotdl(unique_id, search_query, audio_format, lyrics_format, output_format):
    download_folder = os.path.join(MUSIC_DIR, unique_id)
    os.makedirs(download_folder, exist_ok=True)
    downloader = None
    report_progress(unique_id, 0, 'Searching', force=True)

    try:
        ensure_spotify_client()
        downloader = Downloader(settings={
            "audio_providers": [audio_format],
            "lyrics_providers": [lyrics_format] if lyrics_format else [],
            "format": output_format,
            "output": os.path.join(download_folder, "{artists} - {title}.{output-ext}"),
            "threads": 4,
            "bitrate": "auto",
            "simple_tui": True,
        })
        songs = parse_query(
            query=[search_query],
            threads=downloader.settings["threads"],
            use_ytm_data=downloader.settings["ytm_data"],
            playlist_numbering=downloader.settings["playlist_numbering"],
            album_type=downloader.settings["album_type"],
            playlist_retain_track_cover=downloader.settings["playlist_retain_track_cover"],
        )
        if not songs:
            mark_failed(unique_id, search_query, "Download failed: No songs found for that search.")
            return

        attach_spotdl_progress(downloader, unique_id)
        report_progress(unique_id, 0, 'Downloading', force=True)
        results = downloader.download_multiple_songs(songs)
        if not any(path for _, path in results):
            detail = downloader.errors[0] if downloader.errors else "No files were downloaded."
            mark_failed(unique_id, search_query, f"Download failed: {detail[:150]}")
            return

        if downloader.errors:
            _logger().warning("Some tracks failed for %s: %s", unique_id, downloader.errors)

        publish_zip(unique_id, search_query, download_folder)
    except Exception as e:
        _logger().error(f"Unexpected error in run_spotdl for {unique_id} ({search_query}): {e}", exc_info=True)
        mark_failed(unique_id, search_query, f"An unexpected error occurred during spotdl processing: {e}")
    finally:
        try:
            if downloader is not None and not downloader.loop.is_closed():
                downloader.loop.close()
            if os.path.exists(download_folder):
                shutil.rmtree(download_folder)
        finally:
            start_promoted_jobs(download_state.release(unique_id))


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
        'postprocessor_args': [
            '-id3v2_version', '3',
        ],
        'progress_hooks': [lambda data: youtube_progress_hook(unique_id, data)],
        'postprocessor_hooks': [lambda data: youtube_postprocessor_hook(unique_id, data)],
    }

    report_progress(unique_id, 0, 'Downloading', force=True)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        for file_in_dir in os.listdir(download_folder):
            if file_in_dir.endswith(('.webp', '.jpg', '.png')):
                os.remove(os.path.join(download_folder, file_in_dir))

        publish_zip(unique_id, url, download_folder)

    except Exception as e:
        _logger().error(f"YouTubeDL error for {unique_id} processing {url}: {e}", exc_info=True)
        mark_failed(unique_id, url, f"YouTube download failed: {e}")
    finally:
        try:
            if os.path.exists(download_folder):
                shutil.rmtree(download_folder)
        finally:
            start_promoted_jobs(download_state.release(unique_id))


def youtube_progress_hook(unique_id, data):
    status = data.get('status')
    if status == 'downloading':
        report_progress(unique_id, youtube_download_percent(data), 'Downloading')
    elif status == 'finished':
        report_progress(unique_id, None, 'Converting')


def youtube_postprocessor_hook(unique_id, data):
    if data.get('status') != 'started':
        return
    name = data.get('postprocessor') or ''
    if 'FFmpegExtractAudio' in name:
        report_progress(unique_id, None, 'Converting')
    elif 'FFmpegMetadata' in name:
        report_progress(unique_id, None, 'Embedding metadata')


def emit_queue_update():
    socketio.emit('queue_update', {
        'queue': download_state.queue_snapshot(),
    }, namespace='/')


def start_download_job(job, from_queue=False):
    unique_id = job['unique_id']
    if from_queue:
        socketio.emit('download_started', {
            'unique_id': unique_id,
        }, namespace='/')
    if job.get('is_youtube'):
        socketio.start_background_task(
            download_from_youtube, unique_id, job['search_query'], job['output_format']
        )
        return
    socketio.start_background_task(
        run_spotdl,
        unique_id,
        job['search_query'],
        job['audio_format'],
        job['lyrics_format'],
        job['output_format'],
    )


def start_promoted_jobs(jobs):
    for job in jobs:
        start_download_job(job, from_queue=True)
    if jobs:
        emit_queue_update()


def expire_download_state():
    timed_out, promoted = download_state.expire_stale()
    for unique_id in timed_out:
        _logger().error("Download %s timed out and released its concurrency slot", unique_id)
        socketio.emit('download_failed', {
            'unique_id': unique_id,
            'message': 'Download timed out.',
            'zip_url': None,
        }, namespace='/')
    start_promoted_jobs(promoted)
