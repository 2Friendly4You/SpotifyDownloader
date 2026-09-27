import threading
import time
from collections import deque

from app.config import PENDING_TTL_SECONDS, load_queue_limit, retention_seconds
from app.searches import load_initial_concurrent_limit


class DownloadState:
    def __init__(self, concurrent_limit, queue_limit):
        self._lock = threading.Lock()
        self._pending = {}
        self._queue = deque()
        self._failed = {}
        self._completed = {}
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

    def _promote_locked(self):
        promoted = []
        while self._queue and len(self._pending) < self._concurrent_limit:
            job = self._queue.popleft()
            self._pending[job['unique_id']] = time.time()
            promoted.append(job)
        return promoted

    def update_progress(self, unique_id, percent, message, min_interval=0.4):
        now = time.monotonic()
        with self._lock:
            current = self._progress.get(unique_id, {'percent': 0.0, 'message': ''})
            if percent is None:
                percent = current['percent']
            percent = max(0.0, min(100.0, float(percent)))
            self._progress[unique_id] = {'percent': percent, 'message': message}
            last_time, last_percent, last_message = self._progress_emit.get(
                unique_id, (0.0, -1.0, None)
            )
            message_changed = message != last_message
            percent_moved = abs(percent - last_percent) >= 1
            elapsed = now - last_time
            should_emit = (
                message_changed
                or percent >= 100
                or (percent_moved and elapsed >= min_interval)
            )
            if should_emit:
                self._progress_emit[unique_id] = (now, percent, message)
            return percent, message, should_emit

    def get_progress(self, unique_id):
        with self._lock:
            stored = self._progress.get(unique_id)
            if stored is None:
                return {'percent': 0.0, 'message': 'Searching'}
            return dict(stored)

    def mark_failed(self, unique_id, message):
        with self._lock:
            self._failed[unique_id] = (message, time.time() + retention_seconds())

    def mark_completed(self, unique_id):
        with self._lock:
            self._failed.pop(unique_id, None)
            self._completed[unique_id] = time.time() + retention_seconds()

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
            return timed_out, self._promote_locked()


download_state = DownloadState(load_initial_concurrent_limit(), load_queue_limit())
