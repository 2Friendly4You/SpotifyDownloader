import threading
import time
from collections import deque

from app.config import PENDING_TTL_SECONDS, load_queue_limit, retention_seconds
from app.searches import load_initial_concurrent_limit


PROGRESS_DETAIL_KEYS = ('songs_done', 'songs_total', 'songs_running', 'eta_seconds')


def _eta_moved(previous, current):
    """True when an ETA changed enough to tell the client again."""
    if (previous is None) != (current is None):
        return True
    if previous is None:
        return False
    return abs(current - previous) >= max(10, previous * 0.1)


class DownloadState:
    def __init__(self, concurrent_limit, queue_limit):
        self._lock = threading.Lock()
        self._pending = {}
        self._queue = deque()
        self._failed = {}
        self._completed = {}
        self._failed_tracks = {}
        # Cancelled job ids stay here for a while after the job released its
        # slot, so yt-dlp threads that are still finishing a request stop at
        # their next progress hook instead of downloading to the end.
        self._cancelled = {}
        self._progress = {}
        self._progress_emit = {}
        self._concurrent_limit = concurrent_limit
        self._queue_limit = queue_limit

    def get_limit(self):
        with self._lock:
            return self._concurrent_limit

    def get_queue_limit(self):
        with self._lock:
            return self._queue_limit

    def set_limit(self, limit):
        with self._lock:
            self._concurrent_limit = limit
            return self._promote_locked()

    def accept(self, job):
        with self._lock:
            if len(self._pending) < self._concurrent_limit:
                self._pending[job['unique_id']] = time.time()
                return 'started', None
            if len(self._queue) >= self._queue_limit:
                return 'full', None
            self._queue.append(job)
            return 'queued', len(self._queue)

    def release(self, unique_id):
        with self._lock:
            self._pending.pop(unique_id, None)
            self._progress.pop(unique_id, None)
            self._progress_emit.pop(unique_id, None)
            return self._promote_locked()

    def cancel_queued(self, unique_id):
        with self._lock:
            for index, job in enumerate(self._queue):
                if job['unique_id'] == unique_id:
                    del self._queue[index]
                    return True
            return False

    def request_cancel(self, unique_id):
        """Cancel a job. Returns 'queued', 'running' or None if it is unknown.

        A queued job is simply removed. A running job is flagged; the worker
        stops at its next check and releases its slot as usual.
        """
        with self._lock:
            for index, job in enumerate(self._queue):
                if job['unique_id'] == unique_id:
                    del self._queue[index]
                    return 'queued'
            if unique_id in self._pending:
                self._cancelled[unique_id] = time.time()
                return 'running'
            return None

    def is_cancelled(self, unique_id):
        with self._lock:
            return unique_id in self._cancelled

    def forget(self, unique_id):
        """Drop every trace of a finished job, e.g. after it was cancelled late."""
        with self._lock:
            self._failed.pop(unique_id, None)
            self._completed.pop(unique_id, None)
            self._failed_tracks.pop(unique_id, None)

    def _promote_locked(self):
        promoted = []
        while self._queue and len(self._pending) < self._concurrent_limit:
            job = self._queue.popleft()
            self._pending[job['unique_id']] = time.time()
            promoted.append(job)
        return promoted

    def update_progress(self, unique_id, percent, message, min_interval=0.4, details=None):
        """Store progress and decide whether it is worth a socket.io event.

        ``details`` holds optional extras (``songs_done``, ``songs_total``,
        ``eta_seconds``). They replace the previous extras, so a call without
        them clears an estimate that no longer applies.
        """
        now = time.monotonic()
        with self._lock:
            current = self._progress.get(unique_id, {'percent': 0.0, 'message': ''})
            if percent is None:
                percent = current['percent']
            percent = max(0.0, min(100.0, float(percent)))
            stored = {'percent': percent, 'message': message}
            for key in PROGRESS_DETAIL_KEYS:
                value = (details or {}).get(key)
                if value is not None:
                    stored[key] = value
            self._progress[unique_id] = stored
            last_time, last_percent, last_message, last_counts, last_eta = self._progress_emit.get(
                unique_id, (0.0, -1.0, None, (None, None, None), None)
            )
            counts = (stored.get('songs_done'), stored.get('songs_total'), stored.get('songs_running'))
            eta = stored.get('eta_seconds')
            message_changed = message != last_message
            percent_moved = abs(percent - last_percent) >= 1
            # Song counts change at most a few times per song, so every change
            # is sent. Throttling them dropped the last songs of a burst, and
            # the counter then jumped from "75/80" straight to the next phase.
            counts_changed = counts != last_counts
            elapsed = now - last_time
            should_emit = (
                message_changed
                or counts_changed
                or percent >= 100
                or ((percent_moved or _eta_moved(last_eta, eta)) and elapsed >= min_interval)
            )
            if should_emit:
                self._progress_emit[unique_id] = (now, percent, message, counts, eta)
            return percent, message, should_emit

    def get_progress(self, unique_id):
        with self._lock:
            stored = self._progress.get(unique_id)
            if stored is None:
                return {'percent': 0.0, 'message': 'Searching'}
            return dict(stored)

    def mark_failed(self, unique_id, message, failed_tracks=None):
        with self._lock:
            self._failed[unique_id] = (message, time.time() + retention_seconds())
            self._set_failed_tracks_locked(unique_id, failed_tracks)

    def mark_completed(self, unique_id, failed_tracks=None):
        with self._lock:
            self._failed.pop(unique_id, None)
            self._completed[unique_id] = time.time() + retention_seconds()
            self._set_failed_tracks_locked(unique_id, failed_tracks)

    def _set_failed_tracks_locked(self, unique_id, failed_tracks):
        if failed_tracks:
            self._failed_tracks[unique_id] = list(failed_tracks)
        else:
            self._failed_tracks.pop(unique_id, None)

    def failed_tracks(self, unique_id):
        """Songs of a finished job that could not be downloaded, or None."""
        with self._lock:
            tracks = self._failed_tracks.get(unique_id)
            return list(tracks) if tracks else None

    def pending_ids(self):
        with self._lock:
            return list(self._pending)

    def queued_ids(self):
        with self._lock:
            return [job['unique_id'] for job in self._queue]

    def queue_snapshot(self):
        with self._lock:
            return [
                {'unique_id': job['unique_id'], 'position': index + 1}
                for index, job in enumerate(self._queue)
            ]

    def lookup(self, unique_id):
        with self._lock:
            if unique_id in self._pending:
                return 'pending', None
            for index, job in enumerate(self._queue):
                if job['unique_id'] == unique_id:
                    return 'queued', index + 1
            failed = self._failed.get(unique_id)
            if failed is not None:
                return 'failed', failed[0]
            if unique_id in self._completed:
                return 'completed', None
        return 'unknown', None

    def _expire_pending_locked(self, now):
        timed_out = []
        for unique_id, started in list(self._pending.items()):
            if now - started < PENDING_TTL_SECONDS:
                continue
            self._pending.pop(unique_id, None)
            self._progress.pop(unique_id, None)
            self._progress_emit.pop(unique_id, None)
            if unique_id in self._completed:
                continue
            self._failed[unique_id] = ("Download timed out.", now + retention_seconds())
            timed_out.append(unique_id)
        return timed_out

    def expire_stale(self):
        now = time.time()
        with self._lock:
            self._failed = {
                key: value for key, value in self._failed.items() if value[1] > now
            }
            self._completed = {
                key: expires_at for key, expires_at in self._completed.items() if expires_at > now
            }
            timed_out = self._expire_pending_locked(now)
            self._cancelled = {
                key: when for key, when in self._cancelled.items()
                if key in self._pending or now - when < PENDING_TTL_SECONDS
            }
            self._failed_tracks = {
                key: tracks for key, tracks in self._failed_tracks.items()
                if key in self._failed or key in self._completed
            }
            return timed_out, self._promote_locked()


download_state = DownloadState(load_initial_concurrent_limit(), load_queue_limit())
