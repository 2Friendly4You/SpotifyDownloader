"""Rough time-remaining estimates for running downloads.

The numbers here are meant for a coarse "about 5 minutes" hint in the UI,
not for exact accounting.
"""
import math
import threading
import time

DEFAULT_SECONDS_PER_SONG = 6.0


class EtaEstimator:
    """Estimate the seconds left in one phase from the fraction it has completed.

    Each update computes the naive estimate ``elapsed * (1 - f) / f`` and
    blends it with the previous estimate (counted down by the time that
    passed), using a time-based exponential moving average. That keeps the
    value from jumping around when progress arrives in bursts, for example
    one song at a time.
    """

    def __init__(self, min_elapsed=5.0, min_fraction=0.02, smoothing_seconds=15.0, clock=time.monotonic):
        self._clock = clock
        self._start = clock()
        self._min_elapsed = min_elapsed
        self._min_fraction = min_fraction
        self._smoothing_seconds = smoothing_seconds
        self._smoothed = None
        self._last_update = None

    def update(self, fraction):
        now = self._clock()
        fraction = max(0.0, min(1.0, float(fraction)))
        if fraction >= 1.0:
            self._smoothed = 0.0
            self._last_update = now
            return 0.0
        elapsed = now - self._start
        if elapsed < self._min_elapsed or fraction < self._min_fraction:
            return None
        raw = elapsed * (1.0 - fraction) / fraction
        if self._smoothed is None:
            self._smoothed = raw
        else:
            dt = max(now - self._last_update, 0.0)
            weight = 1.0 - math.exp(-dt / self._smoothing_seconds)
            predicted = max(self._smoothed - dt, 0.0)
            self._smoothed = predicted + weight * (raw - predicted)
        self._last_update = now
        return self._smoothed


class SongRate:
    """Remember how long a song takes to download, smoothed over recent jobs.

    Used as a prior while the song list is still being resolved and no real
    download progress exists yet. It lives in process memory and starts from
    a conservative default after a restart.
    """

    def __init__(self, default=DEFAULT_SECONDS_PER_SONG, alpha=0.3):
        self._lock = threading.Lock()
        self._seconds_per_song = default
        self._alpha = alpha

    def record(self, seconds, songs):
        if songs <= 0 or seconds <= 0:
            return
        sample = seconds / songs
        with self._lock:
            self._seconds_per_song += self._alpha * (sample - self._seconds_per_song)

    def estimate(self, songs):
        with self._lock:
            return max(songs, 0) * self._seconds_per_song


def round_eta(seconds):
    """Seconds as an int for the API, or None when there is no estimate."""
    if seconds is None:
        return None
    return int(max(0.0, seconds) + 0.5)


song_rate = SongRate()
