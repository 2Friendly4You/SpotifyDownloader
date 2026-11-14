"""Rough time-remaining estimates for running downloads.

The numbers here are meant for a coarse "about 5 minutes" hint in the UI,
not for exact accounting.
"""
import math
import time


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


class ThroughputEta:
    """Seconds left for a batch of songs that several workers download at once.

    No estimate exists until the first song is finished, or until
    ``min_elapsed`` seconds have passed with real progress: before that any
    number is a guess, and the old prior made the card say "under a minute"
    for playlists that took several. The UI shows "calculating" instead.

    A batch that fits into the workers (a single song, a short retry round)
    has no queue, so the songs' own progress already tells the time left.
    Waiting for the first finished song there meant the card said
    "calculating" for the whole job. Such batches get an estimate after
    ``early_elapsed`` seconds once they are ``early_work`` of the way.

    After that it measures throughput as finished songs plus the partial
    progress of the running ones, per second of the phase. That rate already
    includes the parallel workers. The rate is smoothed over time, and so is
    the estimate itself, which counts down between updates and only drifts
    toward a new value, so it does not jump when songs finish in bursts.

    At the end fewer songs than workers are left. They run side by side, so
    the rest takes about one song's duration times the work they have left,
    not ``remaining / rate``.
    """

    def __init__(self, total, workers=4, min_elapsed=20.0, smoothing_seconds=20.0, settle_seconds=3.0,
                 early_elapsed=2.0, early_work=0.15, clock=time.monotonic):
        self.total = max(int(total), 0)
        self.workers = max(int(workers), 1)
        self._clock = clock
        self._start = clock()
        self._min_elapsed = min_elapsed
        self._smoothing_seconds = smoothing_seconds
        self._early_elapsed = early_elapsed
        self._early_work = early_work
        # Songs finish in bursts within milliseconds. The first estimate is
        # only provisional for a moment, so the rest of the burst refines it
        # instead of being smoothed away.
        self._settle_seconds = settle_seconds
        self._first_estimate_at = None
        self._rate = None
        self._eta = None
        self._last_update = None

    def update(self, done, work):
        """``done`` finished songs, ``work`` finished plus partial songs."""
        now = self._clock()
        remaining = self.total - work
        if remaining <= 1e-9:
            self._eta, self._last_update = 0.0, now
            return 0.0
        elapsed = now - self._start
        if work <= 0 or elapsed <= 0:
            return None
        if done < 1 and elapsed < self._min_elapsed:
            fits = self.total <= self.workers
            if not fits or elapsed < self._early_elapsed or work < self._early_work * self.total:
                return None
        sample = work / elapsed
        if self._first_estimate_at is None:
            self._first_estimate_at = now
        settling = now - self._first_estimate_at < self._settle_seconds
        dt = 0.0 if self._last_update is None else max(now - self._last_update, 0.0)
        weight = 1.0 if settling else 1.0 - math.exp(-dt / self._smoothing_seconds)
        self._rate = sample if self._rate is None else self._rate + weight * (sample - self._rate)

        raw = remaining / self._rate
        unfinished = self.total - done
        if 0 < unfinished <= self.workers:
            song_seconds = min(self.workers, self.total) / self._rate
            raw = max(raw, song_seconds * remaining / unfinished)

        if self._eta is None or settling:
            self._eta = raw
        else:
            predicted = max(self._eta - dt, 0.0)
            self._eta = predicted + weight * (raw - predicted)
        self._last_update = now
        return self._eta


def round_eta(seconds):
    """Seconds as an int for the API, or None when there is no estimate."""
    if seconds is None:
        return None
    return int(max(0.0, seconds) + 0.5)



class SongProgress:
    """Overall progress of songs that spotDL downloads in parallel.

    spotDL reports each song separately and the songs interleave, so showing
    the latest per-song step made the text jump around. This keeps one
    number: finished songs plus the partial progress of the running ones,
    and it never goes backwards.
    """

    FINISHED_MESSAGES = {'Done', 'Error', 'Skipped'}

    def __init__(self, total):
        self.total = max(int(total), 0)
        self._partial = {}
        self._finished = set()
        self._errors = set()
        self._fraction = 0.0

    def update(self, key, percent, message):
        if key not in self._finished:
            if message in self.FINISHED_MESSAGES or (percent or 0) >= 100:
                self._finished.add(key)
                self._partial.pop(key, None)
                if message == 'Error':
                    self._errors.add(key)
            else:
                self._partial[key] = max(0.0, min(1.0, (percent or 0) / 100))
        if self.total:
            raw = (len(self._finished) + sum(self._partial.values())) / self.total
            self._fraction = max(self._fraction, min(1.0, raw))
        return self.done, self.running, self._fraction

    @property
    def done(self):
        return min(len(self._finished), self.total)

    @property
    def saved(self):
        """Finished songs that did not fail: the ones the user will get."""
        return min(len(self._finished - self._errors), self.total)

    @property
    def running(self):
        return len(self._partial)
