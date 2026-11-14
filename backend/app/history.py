"""Lifecycle record of every download job, for the admin page.

The download state only keeps what users need while a job runs or its file
is available. Admins also want to look back: what was downloaded, how long
it took, how big it got, which songs failed. Each job gets one small entry,
written on lifecycle changes only (never on progress), and the newest
``MAX_ENTRIES`` survive restarts in a JSON file next to ``searches.json``.
"""
import json
import logging
import os
import threading
import time
import zipfile

from app.config import MUSIC_DIR, SEARCHES_FILE
from app.titles import is_job_id, read_zip_title

logger = logging.getLogger(__name__)

MAX_ENTRIES = 500
FINISHED = {'completed', 'failed', 'cancelled'}

_lock = threading.Lock()
_entries = {}
_loaded = False


def history_file():
    default = os.path.join(os.path.dirname(os.path.abspath(SEARCHES_FILE)), 'jobs.json')
    return os.environ.get('JOB_HISTORY_FILE', default)


def _load_locked():
    global _loaded
    if _loaded:
        return
    _loaded = True
    path = history_file()
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except FileNotFoundError:
        data = []
    except Exception as e:  # a broken file must not break downloads
        logger.error("Could not read job history %s, keeping it as .broken: %s", path, e)
        try:
            os.replace(path, f'{path}.broken')
        except OSError:
            pass
        data = []
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and isinstance(entry.get('id'), str):
                _entries[entry['id']] = entry
    if _import_existing_zips_locked():
        _save_locked()


def _import_existing_zips_locked():
    """Add finished zips from before the history existed (or from a lost file).

    Only what the zip tells: name from its comment, size, songs, and its
    time as the finish time. There is no start time, so no duration.
    """
    try:
        names = os.listdir(MUSIC_DIR)
    except OSError:
        return False
    added = False
    for name in names:
        unique_id = name[:-4]
        if not name.endswith('.zip') or not is_job_id(unique_id) or unique_id in _entries:
            continue
        path = os.path.join(MUSIC_DIR, name)
        try:
            stat = os.stat(path)
            with zipfile.ZipFile(path) as archive:
                songs = sum(1 for info in archive.infolist() if not info.is_dir() and not info.filename.endswith('.txt'))
        except (OSError, zipfile.BadZipFile):
            continue
        _entries[unique_id] = {
            'id': unique_id, 'status': 'completed', 'imported': True,
            'created_at': stat.st_mtime, 'finished_at': stat.st_mtime,
            'title': read_zip_title(path), 'size_bytes': stat.st_size, 'songs_saved': songs,
            'failed_tracks': [],
        }
        added = True
    return added


def _save_locked():
    entries = sorted(_entries.values(), key=lambda e: e.get('created_at') or 0)
    for old in entries[:-MAX_ENTRIES]:
        _entries.pop(old['id'], None)
    path = history_file()
    tmp = f'{path}.tmp'
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as handle:
            json.dump(entries[-MAX_ENTRIES:], handle, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        logger.error("Could not save job history %s: %s", path, e)


def _update(unique_id, create=False, **fields):
    with _lock:
        _load_locked()
        entry = _entries.get(unique_id)
        if entry is None:
            if not create:
                return
            entry = _entries[unique_id] = {'id': unique_id, 'created_at': time.time()}
        entry.update({key: value for key, value in fields.items() if value is not None})
        _save_locked()


def created(job, queued):
    _update(
        job['unique_id'], create=True,
        query=job.get('search_query'),
        format=job.get('output_format'),
        provider=None if job.get('is_youtube') else job.get('audio_format'),
        source='youtube' if job.get('is_youtube') else 'spotify',
        status='queued' if queued else 'running',
    )


def started(unique_id):
    _update(unique_id, status='running', started_at=time.time())


def set_title(unique_id, title):
    if title:
        _update(unique_id, title=title)


def set_songs(unique_id, total):
    _update(unique_id, songs_total=int(total))


def finished(unique_id, status, message=None, size_bytes=None, songs_saved=None, failed_tracks=None):
    assert status in FINISHED
    with _lock:
        _load_locked()
        entry = _entries.get(unique_id)
        if entry is None:
            return
        entry['status'] = status
        entry['finished_at'] = time.time()
        entry.setdefault('started_at', entry['created_at'])
        if message:
            entry['message'] = str(message)[:300]
        if size_bytes is not None:
            entry['size_bytes'] = int(size_bytes)
        if songs_saved is not None:
            entry['songs_saved'] = int(songs_saved)
        entry['failed_tracks'] = list(failed_tracks or [])[:200]
        _save_locked()


def file_deleted(unique_id):
    _update(unique_id, file_deleted_at=time.time())


def entries():
    """All entries, newest first, as copies."""
    with _lock:
        _load_locked()
        items = [dict(entry) for entry in _entries.values()]
    items.sort(key=lambda e: e.get('created_at') or 0, reverse=True)
    return items


def reset_for_tests():
    global _loaded
    with _lock:
        _entries.clear()
        _loaded = True
