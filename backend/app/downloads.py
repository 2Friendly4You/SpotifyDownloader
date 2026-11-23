import asyncio
import collections
import concurrent.futures
import os
import shutil
import threading
import time
import zipfile

import yt_dlp
from spotdl.download.downloader import Downloader
from spotdl.download.progress_handler import ProgressHandler
from spotdl.types.song import Song
from spotdl.utils.config import SPOTIFY_OPTIONS
from spotdl.utils.formatter import create_file_name
from spotdl.utils.search import get_simple_songs, reinit_song
from spotdl.utils.spotify import SpotifyClient, SpotifyError

from app import cancellation, history
from app.cancellation import JobCancelled
from app.config import MUSIC_DIR
from app.extensions import socketio
from app.progress import EtaEstimator, SongProgress, ThroughputEta, round_eta
from app.retries import (
    FAILED_TRACKS_FILE,
    MAX_FAILED_TRACKS,
    describe_exception,
    errors_by_url,
    failed_tracks_text,
    failure_entry,
    fallback_song_limit,
    reasons_by_url,
    retry_delay,
    retry_plan,
    use_provider,
)
from app.state import PROGRESS_DETAIL_KEYS, download_state
from app.titles import clean_title, title_from_songs, write_zip_title

_spotify_init_lock = threading.Lock()

# The overall bar is split into phases so it never runs backwards:
# 0-1 % while spotDL fetches the song list, 1-5 % while it resolves each
# song's metadata, 5-95 % for the downloads and the rest for packaging.
SEARCH_LIST_PERCENT = 1.0
SEARCH_DONE_PERCENT = 5.0
SPOTDL_THREADS = 4
# Song lookups go to Spotify's web player API, which turns away bursts of
# requests (three per song). Two at a time is gentler than the download threads.
METADATA_THREADS = 2
# Lookups that failed are tried again one by one after these pauses (seconds).
METADATA_RETRY_DELAYS = (2.0, 5.0, 10.0)
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
    """Turn spotDL's search and download phases into one progress bar with an ETA.

    While songs are being looked up there is no estimate: the card says the
    time is still being calculated. Each download round (the first one and
    every retry) gets its own throughput-based estimate.

    The song counter is "saved songs of the whole job". Failed songs do not
    count, and a retry round adds to what earlier rounds saved. Counting
    failures as done and restarting the counter per round made it jump
    backwards, from "1/1" to "0/1", whenever a song was retried.
    """

    def __init__(self, unique_id, clock=time.monotonic, workers=4):
        self.unique_id = unique_id
        self.total = 0
        self._clock = clock
        self._workers = workers
        self._retry_total = 0
        self._saved_before = 0
        self._eta = None
        self._songs = SongProgress(0)

    def searching(self):
        report_progress(self.unique_id, SEARCH_LIST_PERCENT, 'Searching', force=True)

    def resolved(self, done, total):
        """``done`` of ``total`` songs have their metadata."""
        self.total = total
        fraction = done / total if total else 1.0
        percent = SEARCH_LIST_PERCENT + (SEARCH_DONE_PERCENT - SEARCH_LIST_PERCENT) * fraction
        report_progress(self.unique_id, percent, 'Searching', details={
            'songs_done': done,
            'songs_total': total,
        })

    def downloading(self, count):
        """``count`` songs start downloading.

        The counter keeps the size of the whole playlist from the search, so
        a song whose lookup failed still shows up as missing ("106/115").
        The estimate only covers the songs that are actually downloaded.
        """
        self.total = max(self.total, count)
        self._eta = ThroughputEta(count, workers=self._workers, clock=self._clock)
        self._songs = SongProgress(count)
        self._saved_before = 0
        history.set_songs(self.unique_id, self.total)
        report_progress(self.unique_id, SEARCH_DONE_PERCENT, 'Downloading', force=True, details={
            'songs_done': 0,
            'songs_total': self.total,
        })

    def song_update(self, key, percent, message):
        """One song changed. The card shows the aggregate, not the song's own step."""
        done, running, fraction = self._songs.update(key, percent, message)
        batch = self._retry_total or self.total
        left = self._eta.update(done, fraction * batch)
        details = {
            'songs_done': self._saved_total(),
            'songs_total': self.total,
            'songs_running': running,
            'eta_seconds': round_eta(left),
        }
        if self._retry_total:
            report_progress(self.unique_id, None, 'Retrying', details=details)
            return
        percent = SEARCH_DONE_PERCENT + (DOWNLOAD_DONE_PERCENT - SEARCH_DONE_PERCENT) * fraction
        report_progress(self.unique_id, percent, 'Downloading', details=details)

    def _saved_total(self):
        return min(self._saved_before + self._songs.saved, self.total)

    def retrying(self, count):
        """A retry round for ``count`` failed songs starts. The bar and the counter stay."""
        self._saved_before = self._saved_total()
        self._retry_total = count
        self._eta = ThroughputEta(count, workers=self._workers, clock=self._clock)
        self._songs = SongProgress(count)
        report_progress(self.unique_id, None, 'Retrying', force=True, details={
            'songs_done': self._saved_before,
            'songs_total': self.total,
        })


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


def attach_spotdl_progress(downloader, progress, error_sink=None):
    """Give the downloader a fresh progress handler that feeds ``progress``.

    With ``error_sink`` (a dict) the real cause of each failed song is kept
    there by song URL. spotDL itself only records a generic text such as
    "YT-DLP download error - <url>".
    """
    def callback(tracker, message):
        # Raising here aborts the yt-dlp download or spotDL step that reported.
        check_cancelled(progress.unique_id)
        progress.song_update(id(tracker), tracker.progress, message)

    handler = ProgressHandler(
        simple_tui=True,
        update_callback=callback,
        web_ui=True,
    )
    if error_sink is not None:
        new_tracker = handler.get_new_tracker

        def get_new_tracker(song):
            tracker = new_tracker(song)
            notify_error = tracker.notify_error

            def record_error(message, traceback, finish=False):
                url = getattr(song, 'url', None)
                if url and isinstance(traceback, BaseException):
                    error_sink[url] = describe_exception(traceback)
                return notify_error(message, traceback, finish)

            tracker.notify_error = record_error
            return tracker

        handler.get_new_tracker = get_new_tracker
    downloader.progress_handler = handler


def publish_title(unique_id, title):
    """Tell the card what this job is called once the name is known."""
    title = clean_title(title)
    if not title or title == download_state.title(unique_id):
        return
    download_state.set_title(unique_id, title)
    history.set_title(unique_id, title)
    socketio.emit('download_title', {'unique_id': unique_id, 'title': title}, namespace='/')


def job_download_url(unique_id):
    """Served by the app so the zip gets a readable file name (the file stays <uuid>.zip)."""
    return f'/api/download/{unique_id}'


def playlist_song(song):
    """A downloadable song from the playlist's own data, or None.

    Used when the full lookup of a song keeps failing. The playlist already
    has the title, artists and length, which is all the search needs. The
    album details spotDL would look up are filled with neutral values so it
    does not try the failing lookup again during the download.
    """
    data = getattr(song, 'json', None)
    if not isinstance(data, dict):
        return None
    artists = data.get('artists') or ([data['artist']] if data.get('artist') else [])
    if not data.get('name') or not artists:
        return None
    data = dict(data)
    data['artists'] = artists
    data['artist'] = data.get('artist') or artists[0]
    defaults = {
        'genres': [],
        'disc_number': 1,
        'track_number': 1,
        'album_name': data['name'],
        'album_artist': data['artist'],
        'album_id': '',
        'publisher': '',
        'explicit': False,
        # mutagen refuses None for these tags, so spotDL would fail to tag the file.
        'date': '',
        'isrc': '',
    }
    for key, value in defaults.items():
        if data.get(key) is None:
            data[key] = value
    if data.get('disc_count') is None:
        data['disc_count'] = data['disc_number']
    if data.get('tracks_count') is None:
        data['tracks_count'] = data['track_number']
    try:
        return Song(**{key: data.get(key) for key in Song.__dataclass_fields__})  # pylint: disable=E1101
    except TypeError:
        return None


def _sleep(seconds, is_cancelled=None):
    """Sleep, but stop early once the job is cancelled."""
    deadline = time.monotonic() + seconds
    while True:
        if is_cancelled is not None and is_cancelled():
            raise JobCancelled()
        left = deadline - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(left, 0.5))


def search_songs(downloader, search_query, on_resolved, is_cancelled=None, on_title=None):
    """spotDL's parse_query, reporting each song whose metadata is resolved.

    Mirrors spotdl.utils.search.parse_query (spotDL 4.6.0) so the search
    phase can show "x/y songs" instead of a frozen bar. Lookups that fail
    are retried one by one after METADATA_RETRY_DELAYS. A song that still
    fails is downloaded with the playlist's own data; only a song without
    even a title and artist is reported as failed. Songs keep the playlist
    order.
    """
    settings = downloader.settings
    simple_songs = get_simple_songs(
        [search_query],
        use_ytm_data=settings["ytm_data"],
        playlist_numbering=settings["playlist_numbering"],
        album_type=settings["album_type"],
        playlist_retain_track_cover=settings["playlist_retain_track_cover"],
    )
    if on_title is not None:
        on_title(title_from_songs(search_query, simple_songs))
    total = len(simple_songs)
    if total:
        on_resolved(0, total)

    def check():
        if is_cancelled is not None and is_cancelled():
            raise JobCancelled()

    resolved = [None] * total
    pending = {}
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=METADATA_THREADS)
    try:
        futures = {executor.submit(reinit_song, song): index for index, song in enumerate(simple_songs)}
        for done, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            check()
            index = futures[future]
            try:
                resolved[index] = future.result()
            except Exception as exc:
                pending[index] = exc
            on_resolved(done, total)
    finally:
        # Do not wait for lookups that are no longer needed after a cancel.
        executor.shutdown(wait=False, cancel_futures=True)

    for attempt, delay in enumerate(METADATA_RETRY_DELAYS, start=1):
        if not pending:
            break
        _logger().info(
            "Retrying the lookup of %d songs (attempt %d) in %.0f s", len(pending), attempt, delay
        )
        _sleep(delay, is_cancelled)
        for index in list(pending):
            check()
            try:
                resolved[index] = reinit_song(simple_songs[index])
                del pending[index]
            except Exception as exc:
                pending[index] = exc

    failed = []
    for index, exc in sorted(pending.items()):
        song = simple_songs[index]
        fallback = playlist_song(song)
        if fallback is not None:
            _logger().warning(
                "Lookup of %s kept failing (%s), using the playlist data", song.display_name, exc
            )
            resolved[index] = fallback
            continue
        _logger().error("%s generated an exception: %s", song.display_name, exc)
        failed.append(failure_entry(song, 'metadata_failed', describe_exception(exc)))
    songs = [song for song in resolved if song is not None]
    return songs, failed


COPY_FOLDER_PREFIX = '.copy-'


def file_key(downloader, song):
    """The file name spotDL will give ``song``, case-folded for case-insensitive file systems."""
    settings = downloader.settings
    try:
        path = create_file_name(
            song=song,
            template=settings['output'],
            file_extension=settings['format'],
            restrict=settings.get('restrict'),
            file_name_length=settings.get('max_filename_length'),
        )
        return str(path).casefold()
    except Exception:
        return str(getattr(song, 'display_name', None) or getattr(song, 'url', '')).casefold()


def copy_slots(downloader, songs):
    """Number songs that would share a file name: the second gets 2, the third 3...

    spotDL skips a song when its file already exists, so two different
    tracks with the same artists and title would end up as one file.
    """
    if not downloader.settings.get('output'):
        return {}
    seen = collections.Counter()
    slots = {}
    for song in songs:
        key = file_key(downloader, song)
        seen[key] += 1
        if seen[key] > 1:
            slots[id(song)] = seen[key]
    return slots


def download_batch(downloader, songs, slots):
    """download_multiple_songs, with each later copy of a file name in its own folder."""
    if not slots:
        return downloader.download_multiple_songs(songs)
    template = downloader.settings['output']
    groups = collections.defaultdict(list)
    for song in songs:
        groups[slots.get(id(song), 1)].append(song)
    results = []
    try:
        for slot in sorted(groups):
            if slot == 1:
                downloader.settings['output'] = template
            else:
                folder, name = os.path.split(template)
                downloader.settings['output'] = os.path.join(folder, f"{COPY_FOLDER_PREFIX}{slot}", name)
            results.extend(downloader.download_multiple_songs(groups[slot]))
    finally:
        downloader.settings['output'] = template
    return results


def collect_copies(download_folder):
    """Move the files of later copies next to the others as "Name (2).mp3"."""
    for entry in sorted(os.listdir(download_folder)):
        folder = os.path.join(download_folder, entry)
        if not (entry.startswith(COPY_FOLDER_PREFIX) and os.path.isdir(folder)):
            continue
        number = entry[len(COPY_FOLDER_PREFIX):]
        for name in sorted(os.listdir(folder)):
            base, ext = os.path.splitext(name)
            suffix = int(number) if number.isdigit() else 2
            target = os.path.join(download_folder, f"{base} ({suffix}){ext}")
            while os.path.exists(target):
                suffix += 1
                target = os.path.join(download_folder, f"{base} ({suffix}){ext}")
            os.replace(os.path.join(folder, name), target)
        shutil.rmtree(folder, ignore_errors=True)


def download_with_retries(downloader, songs, primary, progress, sleep=time.sleep):
    """Download ``songs``, then retry the failures with the retry plan.

    Returns the successful (song, path) pairs and a failure entry for each
    song that failed every attempt. Each song gets one more try with the
    user's provider, and up to FALLBACK_SONG_LIMIT songs then get one try per
    fallback provider. The reason shown is the one from the
    user's own provider, because the fallbacks often just do not have the
    song.
    """
    slots = copy_slots(downloader, songs)
    causes = {}
    attach_spotdl_progress(downloader, progress, causes)
    progress.downloading(len(songs))
    errors_before = len(downloader.errors)
    results = download_batch(downloader, songs, slots)
    check_cancelled(progress.unique_id)

    succeeded = [(song, path) for song, path in results if path]
    failed = [song for song, path in results if not path]
    reasons = reasons_by_url(downloader.errors[errors_before:], failed)
    details = errors_by_url(downloader.errors[errors_before:], failed)
    details.update({url: text for url, text in causes.items() if text})

    delay = retry_delay()
    limit = fallback_song_limit()
    for provider in retry_plan(primary):
        batch, skipped = (failed, []) if provider == primary else (failed[:limit], failed[limit:])
        if not batch:
            break
        check_cancelled(progress.unique_id)
        _logger().info("Retrying %d failed songs with %s", len(batch), provider)
        if delay:
            sleep(delay)
        use_provider(downloader, provider)
        causes = {}
        attach_spotdl_progress(downloader, progress, causes)
        progress.retrying(len(batch))
        errors_before = len(downloader.errors)
        results = download_batch(downloader, batch, slots)
        check_cancelled(progress.unique_id)
        failed = [song for song, path in results if not path] + skipped
        succeeded.extend((song, path) for song, path in results if path)
        if provider == primary:
            reasons.update(reasons_by_url(downloader.errors[errors_before:], failed))
            details.update(errors_by_url(downloader.errors[errors_before:], failed))
            details.update({url: text for url, text in causes.items() if text})

    failures = [
        failure_entry(song, reasons.get(song.url, 'download_failed'), details.get(song.url))
        for song in failed
    ]
    return succeeded, failures


def check_cancelled(unique_id):
    if download_state.is_cancelled(unique_id):
        raise JobCancelled(unique_id)


# Jobs an admin cancelled. Their users get a message instead of a card
# that silently disappears.
_admin_cancelled = set()


def cancel_running_job(unique_id, by_admin=False):
    """Interrupt a running job after DownloadState flagged it as cancelled."""
    if by_admin:
        _admin_cancelled.add(unique_id)
    killed = cancellation.stop(unique_id)
    _logger().info("Cancelling download %s (killed processes: %s)", unique_id, killed or 'none')


def finish_cancelled(unique_id):
    """Remove everything a cancelled job left behind and tell the clients."""
    zip_path = os.path.join(MUSIC_DIR, unique_id + ".zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    download_state.forget(unique_id)
    history.finished(unique_id, 'cancelled')
    payload = {'unique_id': unique_id}
    if unique_id in _admin_cancelled:
        _admin_cancelled.discard(unique_id)
        payload['by_admin'] = True
    socketio.emit('download_cancelled', payload, namespace='/')
    _logger().info("Download %s was cancelled and cleaned up", unique_id)


def mark_failed(unique_id, search_query, message, failed_tracks=None):
    _logger().error(f"Download failed for {unique_id} ({search_query}): {message}")
    failed_tracks = (failed_tracks or [])[:MAX_FAILED_TRACKS] or None
    payload = {
        'unique_id': unique_id,
        'search_query': search_query,
        'message': message,
        'zip_url': None,
    }
    title = download_state.title(unique_id)
    if title:
        payload['title'] = title
    if failed_tracks:
        payload['failed_tracks'] = failed_tracks
    download_state.mark_failed(unique_id, message, failed_tracks)
    history.finished(unique_id, 'failed', message=message, failed_tracks=failed_tracks)
    socketio.emit('download_failed', payload, namespace='/')


def notify_client_download_complete(unique_id, download_url, failed_tracks=None):
    failed_tracks = (failed_tracks or [])[:MAX_FAILED_TRACKS] or None
    download_state.mark_completed(unique_id, failed_tracks)
    payload = {
        'unique_id': unique_id,
        'url': download_url
    }
    title = download_state.title(unique_id)
    if title:
        payload['title'] = title
    if failed_tracks:
        payload['failed_tracks'] = failed_tracks
    socketio.emit('download_complete', payload, namespace='/')


def publish_zip(unique_id, search_query, download_folder, failed_tracks=None):
    current = download_state.get_progress(unique_id)
    report_progress(unique_id, max(current['percent'], 95), 'Packaging', force=True)
    zip_path = os.path.join(MUSIC_DIR, unique_id + ".zip")
    shutil.make_archive(os.path.join(MUSIC_DIR, unique_id), 'zip', root_dir=download_folder)

    if not os.path.isfile(zip_path):
        mark_failed(unique_id, search_query, "Download failed: Archive file was not created.")
        return

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            files = [info for info in zf.infolist() if not info.is_dir()]
            has_files = bool(files)
            songs_saved = sum(1 for info in files if not info.filename.endswith('.txt'))
    except zipfile.BadZipFile:
        mark_failed(unique_id, search_query, "Download failed: The downloaded archive is corrupted.")
        os.remove(zip_path)
        return

    if not has_files:
        mark_failed(unique_id, search_query, "Download failed: The downloaded archive is empty.")
        os.remove(zip_path)
        return

    write_zip_title(zip_path, download_state.title(unique_id))
    history.finished(
        unique_id, 'completed', size_bytes=os.path.getsize(zip_path), songs_saved=songs_saved,
        failed_tracks=failed_tracks,
    )
    notify_client_download_complete(unique_id, job_download_url(unique_id), failed_tracks)


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
    progress = SpotdlProgress(unique_id, workers=SPOTDL_THREADS)
    progress.searching()
    # Free-text searches are named after the query right away; links get
    # their playlist, album or song name once spotDL has looked them up.
    publish_title(unique_id, title_from_songs(search_query, []))

    try:
        ensure_spotify_client()
        downloader = Downloader(settings={
            "audio_providers": [audio_format],
            "lyrics_providers": [lyrics_format] if lyrics_format else [],
            "format": output_format,
            "output": os.path.join(download_folder, "{artists} - {title}.{output-ext}"),
            "threads": SPOTDL_THREADS,
            "bitrate": "auto",
            "simple_tui": True,
        })
        cancellation.register(unique_id, cancellation.loop_stopper(downloader.loop))
        check_cancelled(unique_id)
        songs, failed_tracks = search_songs(
            downloader, search_query, progress.resolved, lambda: download_state.is_cancelled(unique_id),
            on_title=lambda title: publish_title(unique_id, title),
        )
        if not songs:
            mark_failed(
                unique_id, search_query, "Download failed: No songs found for that search.", failed_tracks
            )
            return

        succeeded, download_failures = download_with_retries(downloader, songs, audio_format, progress)
        collect_copies(download_folder)
        failed_tracks += download_failures
        if not succeeded:
            # The card lists each failed song with its reason, so the job
            # message stays short instead of repeating spotDL's raw error.
            if failed_tracks:
                detail = "No song could be downloaded."
            else:
                detail = downloader.errors[0] if downloader.errors else "No files were downloaded."
            mark_failed(unique_id, search_query, f"Download failed: {detail[:150]}", failed_tracks)
            return

        if failed_tracks:
            _logger().warning("%d tracks failed for %s: %s", len(failed_tracks), unique_id, downloader.errors)
            with open(os.path.join(download_folder, FAILED_TRACKS_FILE), 'w', encoding='utf-8') as handle:
                handle.write(failed_tracks_text(failed_tracks))

        check_cancelled(unique_id)
        publish_zip(unique_id, search_query, download_folder, failed_tracks)
    except (JobCancelled, asyncio.CancelledError):
        pass
    except Exception as e:
        if not download_state.is_cancelled(unique_id):
            _logger().error(f"Unexpected error in run_spotdl for {unique_id} ({search_query}): {e}", exc_info=True)
            mark_failed(unique_id, search_query, f"An unexpected error occurred during spotdl processing: {e}")
    finally:
        cancellation.unregister(unique_id)
        try:
            cancelled = download_state.is_cancelled(unique_id)
            if cancelled:
                cancellation.kill_job_processes(unique_id)
            if downloader is not None and not downloader.loop.is_closed():
                downloader.loop.close()
            if os.path.exists(download_folder):
                shutil.rmtree(download_folder, ignore_errors=cancelled)
            if cancelled:
                finish_cancelled(unique_id)
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

        check_cancelled(unique_id)
        publish_zip(unique_id, url, download_folder)

    except JobCancelled:
        pass
    except Exception as e:
        if not download_state.is_cancelled(unique_id):
            _logger().error(f"YouTubeDL error for {unique_id} processing {url}: {e}", exc_info=True)
            mark_failed(unique_id, url, f"YouTube download failed: {e}")
    finally:
        try:
            cancelled = download_state.is_cancelled(unique_id)
            if cancelled:
                cancellation.kill_job_processes(unique_id)
            if os.path.exists(download_folder):
                shutil.rmtree(download_folder, ignore_errors=cancelled)
            if cancelled:
                finish_cancelled(unique_id)
        finally:
            start_promoted_jobs(download_state.release(unique_id))


def youtube_progress_hook(unique_id, data, eta=None):
    check_cancelled(unique_id)
    info = data.get('info_dict') or {}
    publish_title(unique_id, info.get('playlist_title') or info.get('title'))
    status = data.get('status')
    if status == 'downloading':
        percent = youtube_download_percent(data)
        left = eta.update(percent / 90) if eta is not None else None
        details = {'eta_seconds': round_eta(left)} if left is not None else None
        report_progress(unique_id, percent, 'Downloading', details=details)
    elif status == 'finished':
        report_progress(unique_id, None, 'Converting')


def youtube_postprocessor_hook(unique_id, data):
    check_cancelled(unique_id)
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
    history.started(unique_id)
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
        history.finished(unique_id, 'failed', message='Download timed out.')
        socketio.emit('download_failed', {
            'unique_id': unique_id,
            'message': 'Download timed out.',
            'zip_url': None,
        }, namespace='/')
    start_promoted_jobs(promoted)
