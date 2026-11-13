import concurrent.futures
import os
import shutil
import threading
import time
import zipfile

import yt_dlp
from spotdl.download.downloader import Downloader
from spotdl.download.progress_handler import ProgressHandler
from spotdl.utils.config import SPOTIFY_OPTIONS
from spotdl.utils.search import get_simple_songs, reinit_song
from spotdl.utils.spotify import SpotifyClient, SpotifyError

from app.config import MUSIC_DIR
from app.extensions import socketio
from app.progress import EtaEstimator, round_eta, song_rate
from app.state import PROGRESS_DETAIL_KEYS, download_state

_spotify_init_lock = threading.Lock()

# The overall bar is split into phases so it never runs backwards:
# 0-1 % while spotDL fetches the song list, 1-5 % while it resolves each
# song's metadata, 5-95 % for the downloads and the rest for packaging.
SEARCH_LIST_PERCENT = 1.0
SEARCH_DONE_PERCENT = 5.0
DOWNLOAD_DONE_PERCENT = 95.0


def _logger():
    from app import app
    return app.logger


def report_progress(unique_id, percent, message, force=False, details=None):
    stored_percent, stored_message, should_emit = download_state.update_progress(
        unique_id, percent, message, details=details
    )
    if not should_emit and not force:
        return
    payload = {
        'unique_id': unique_id,
        'progress': round(stored_percent, 1),
        'message': stored_message,
    }
    for key in PROGRESS_DETAIL_KEYS:
        value = (details or {}).get(key)
        if value is not None:
            payload[key] = value
    socketio.emit('download_progress', payload, namespace='/')


class SpotdlProgress:
    """Turn spotDL's search and download phases into one progress bar with an ETA."""

    def __init__(self, unique_id, clock=time.monotonic):
        self.unique_id = unique_id
        self.total = 0
        self._clock = clock
        self._search_eta = None
        self._download_eta = None
        self._download_started = None

    def searching(self):
        report_progress(self.unique_id, SEARCH_LIST_PERCENT, 'Searching', force=True)

    def resolved(self, done, total):
        """``done`` of ``total`` songs have their metadata."""
        self.total = total
        if self._search_eta is None:
            self._search_eta = EtaEstimator(min_elapsed=2.0, min_fraction=0.0, clock=self._clock)
        fraction = done / total if total else 1.0
        search_left = self._search_eta.update(fraction) if done else None
        eta = song_rate.estimate(total) + (search_left or 0.0)
        percent = SEARCH_LIST_PERCENT + (SEARCH_DONE_PERCENT - SEARCH_LIST_PERCENT) * fraction
        report_progress(self.unique_id, percent, 'Searching', details={
            'songs_done': done,
            'songs_total': total,
            'eta_seconds': round_eta(eta),
        })

    def downloading(self, total):
        self.total = total
        self._download_started = self._clock()
        self._download_eta = EtaEstimator(clock=self._clock)
        report_progress(self.unique_id, SEARCH_DONE_PERCENT, 'Downloading', force=True, details={
            'songs_total': total,
            'eta_seconds': round_eta(song_rate.estimate(total)),
        })

    def download_update(self, fraction, message):
        fraction = max(0.0, min(1.0, fraction))
        left = self._download_eta.update(fraction)
        if left is None:
            left = song_rate.estimate(self.total) * (1.0 - fraction)
        percent = SEARCH_DONE_PERCENT + (DOWNLOAD_DONE_PERCENT - SEARCH_DONE_PERCENT) * fraction
        report_progress(self.unique_id, percent, message or 'Downloading', details={
            'songs_total': self.total,
            'eta_seconds': round_eta(left),
        })

    def downloads_finished(self):
        if self._download_started is not None:
            song_rate.record(self._clock() - self._download_started, self.total)


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


def attach_spotdl_progress(downloader, progress):
    def callback(tracker, message):
        total = tracker.parent.overall_total or 0
        if total:
            fraction = tracker.parent.overall_progress / total
        else:
            fraction = (tracker.progress or 0) / 100
        progress.download_update(fraction, message)

    downloader.progress_handler = ProgressHandler(
        simple_tui=True,
        update_callback=callback,
        web_ui=True,
    )


def search_songs(downloader, search_query, on_resolved):
    """spotDL's parse_query, reporting each song whose metadata is resolved.

    Mirrors spotdl.utils.search.parse_query (spotDL 4.6.0) so the search
    phase can show "x/y songs" instead of a frozen bar.
    """
    settings = downloader.settings
    simple_songs = get_simple_songs(
        [search_query],
        use_ytm_data=settings["ytm_data"],
        playlist_numbering=settings["playlist_numbering"],
        album_type=settings["album_type"],
        playlist_retain_track_cover=settings["playlist_retain_track_cover"],
    )
    total = len(simple_songs)
    if total:
        on_resolved(0, total)

    songs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=settings["threads"]) as executor:
        futures = {executor.submit(reinit_song, song): song for song in simple_songs}
        for done, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            try:
                songs.append(future.result())
            except Exception as exc:
                _logger().error("%s generated an exception: %s", futures[future].display_name, exc)
            on_resolved(done, total)
    return songs


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
    progress = SpotdlProgress(unique_id)
    progress.searching()

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
        songs = search_songs(downloader, search_query, progress.resolved)
        if not songs:
            mark_failed(unique_id, search_query, "Download failed: No songs found for that search.")
            return

        attach_spotdl_progress(downloader, progress)
        progress.downloading(len(songs))
        results = downloader.download_multiple_songs(songs)
        if not any(path for _, path in results):
            detail = downloader.errors[0] if downloader.errors else "No files were downloaded."
            mark_failed(unique_id, search_query, f"Download failed: {detail[:150]}")
            return
        progress.downloads_finished()

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
    eta = EtaEstimator()

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
        'progress_hooks': [lambda data: youtube_progress_hook(unique_id, data, eta)],
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


def youtube_progress_hook(unique_id, data, eta=None):
    status = data.get('status')
    if status == 'downloading':
        percent = youtube_download_percent(data)
        left = eta.update(percent / 90) if eta is not None else None
        details = {'eta_seconds': round_eta(left)} if left is not None else None
        report_progress(unique_id, percent, 'Downloading', details=details)
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
