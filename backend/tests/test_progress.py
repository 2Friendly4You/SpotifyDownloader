import pytest

from app import downloads
from app.progress import EtaEstimator, SongProgress, ThroughputEta, round_eta
from app.state import DownloadState, download_state


class FakeClock:
    def __init__(self, start=100.0):
        self.now = start

    def __call__(self):
        return self.now


def test_eta_stays_hidden_until_there_is_enough_data():
    clock = FakeClock()
    eta = EtaEstimator(min_elapsed=5, min_fraction=0.02, clock=clock)
    clock.now += 2
    assert eta.update(0.5) is None
    clock.now += 10
    assert eta.update(0.01) is None
    assert eta.update(0.2) == pytest.approx(48.0)


def test_eta_follows_steady_progress():
    clock = FakeClock()
    eta = EtaEstimator(clock=clock)
    # 1 % per second: 100 seconds in total.
    for second in range(10, 60, 5):
        clock.now = 100 + second
        left = eta.update(second / 100)
    assert left == pytest.approx(45.0, abs=1)


def test_eta_smooths_a_burst_of_progress():
    clock = FakeClock()
    eta = EtaEstimator(smoothing_seconds=15, clock=clock)
    clock.now += 10
    assert eta.update(0.1) == pytest.approx(90.0)
    clock.now += 1
    # A song finishing at once would make the naive estimate drop to ~13 s.
    left = eta.update(0.45)
    assert 13 < left < 89


def test_eta_is_zero_when_the_phase_is_done():
    clock = FakeClock()
    eta = EtaEstimator(clock=clock)
    assert eta.update(1.0) == 0.0


def test_throughput_eta_waits_for_real_data():
    clock = FakeClock()
    eta = ThroughputEta(20, workers=4, min_elapsed=20, clock=clock)
    clock.now += 5
    # Four songs are 40 % in after 5 s: far too early to promise anything.
    assert eta.update(0, 1.6) is None
    clock.now += 10
    assert eta.update(0, 2.0) is None
    clock.now += 10
    # 25 s without a finished song is enough to start estimating.
    assert eta.update(0, 2.4) == pytest.approx((20 - 2.4) / (2.4 / 25))


def test_throughput_eta_uses_parallel_throughput_and_counts_down():
    clock = FakeClock()
    eta = ThroughputEta(40, workers=4, clock=clock)
    # Every song takes 20 s and four run at once: 0.2 songs per second.
    clock.now += 20
    first = eta.update(4, 4.0)
    assert first == pytest.approx(36 / 0.2)
    estimates = [first]
    for step in range(2, 9):
        clock.now += 20
        estimates.append(eta.update(4 * step, 4.0 * step))
    actual = [(40 - 4 * step) / 0.2 for step in range(1, 9)]
    assert estimates == pytest.approx(actual, abs=1)


def test_throughput_eta_is_steady_when_songs_finish_in_bursts():
    clock = FakeClock()
    eta = ThroughputEta(40, workers=4, clock=clock)
    clock.now += 20
    eta.update(4, 4.0)
    clock.now += 20
    before = eta.update(8, 8.0)
    assert before == pytest.approx(32 / 0.2, abs=1)
    # Four more songs land one second later, a misleadingly high rate.
    clock.now += 1
    after = eta.update(12, 12.0)
    assert before * 0.9 < after < before


def test_first_estimate_settles_over_the_whole_first_burst():
    clock = FakeClock()
    eta = ThroughputEta(10, workers=4, clock=clock)
    clock.now += 30
    assert eta.update(1, 1.0) == pytest.approx(9 * 30)
    for done in (2, 3, 4):
        clock.now += 0.01
        last = eta.update(done, float(done))
    assert last == pytest.approx(6 * 30 / 4, rel=0.01)

def test_throughput_eta_for_the_last_songs_is_one_song_duration():
    clock = FakeClock()
    eta = ThroughputEta(6, workers=4, clock=clock)
    clock.now += 20
    eta.update(4, 4.0)  # 0.2 songs/s, so one song takes 20 s with four workers
    clock.now += 0.001
    # Two songs left, both just started: about 20 s, not remaining / rate = 10 s.
    assert eta.update(4, 4.0) == pytest.approx(20, abs=0.5)
    assert eta.update(6, 6.0) == 0.0


def test_round_eta():
    assert round_eta(None) is None
    assert round_eta(-3) == 0
    assert round_eta(61.6) == 62


def test_progress_details_are_stored_and_cleared():
    state = DownloadState(1, 1)
    state.update_progress("a", 2, "Searching", details={"songs_done": 1, "songs_total": 4, "eta_seconds": 30})
    assert state.get_progress("a") == {
        "percent": 2.0,
        "message": "Searching",
        "songs_done": 1,
        "songs_total": 4,
        "eta_seconds": 30,
    }
    state.update_progress("a", 96, "Packaging")
    assert state.get_progress("a") == {"percent": 96.0, "message": "Packaging"}


def test_song_counts_and_large_eta_changes_are_emitted():
    state = DownloadState(1, 1)
    state.update_progress("a", 1, "Searching", min_interval=0, details={"songs_done": 0, "songs_total": 50})
    _, _, should_emit = state.update_progress(
        "a", 1.1, "Searching", min_interval=0, details={"songs_done": 1, "songs_total": 50}
    )
    assert should_emit is True

    details = {"songs_done": 1, "songs_total": 50, "eta_seconds": 300}
    _, _, should_emit = state.update_progress("a", 1.1, "Searching", min_interval=0, details=details)
    assert should_emit is True
    _, _, should_emit = state.update_progress("a", 1.1, "Searching", min_interval=0, details={**details, "eta_seconds": 295})
    assert should_emit is False
    _, _, should_emit = state.update_progress("a", 1.1, "Searching", min_interval=0, details={**details, "eta_seconds": 240})
    assert should_emit is True


def test_status_reports_search_counts_and_eta(client):
    started = client.post("/api/search", json={
        "search_query": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
        "audio_format": "youtube-music",
        "lyrics_format": "genius",
        "output_format": "mp3",
    })
    unique_id = started.get_json()["unique_id"]
    download_state.update_progress(unique_id, 3, "Searching", details={
        "songs_done": 25, "songs_total": 50, "eta_seconds": 320,
    })

    body = client.get(f"/api/status/{unique_id}").get_json()
    assert body == {
        "status": "pending",
        "progress": 3.0,
        "progress_message": "Searching",
        "songs_done": 25,
        "songs_total": 50,
        "eta_seconds": 320,
    }


@pytest.fixture
def emitted(monkeypatch):
    events = []
    monkeypatch.setattr(downloads.socketio, "emit", lambda name, data, namespace=None: events.append((name, data)))
    yield events
    download_state.release("job")


def test_search_reports_each_resolved_song(monkeypatch):
    class Song:
        def __init__(self, name):
            self.display_name = name

    monkeypatch.setattr(downloads, "get_simple_songs", lambda query, **kwargs: [Song("a"), Song("b"), Song("broken")])

    def reinit(song):
        if song.display_name == "broken":
            raise ValueError("no metadata")
        return song.display_name.upper()

    monkeypatch.setattr(downloads, "reinit_song", reinit)
    monkeypatch.setattr(downloads, "_logger", lambda: type("L", (), {"error": staticmethod(lambda *a: None)}))

    class FakeDownloader:
        settings = {
            "threads": 2,
            "ytm_data": False,
            "playlist_numbering": False,
            "album_type": None,
            "playlist_retain_track_cover": False,
        }

    calls = []
    songs, failed = downloads.search_songs(
        FakeDownloader(), "query", lambda done, total: calls.append((done, total))
    )
    assert sorted(songs) == ["A", "B"]
    assert failed == [{"title": "broken", "reason": "metadata_failed", "url": None}]
    assert calls == [(0, 3), (1, 3), (2, 3), (3, 3)]


def test_spotdl_progress_moves_through_the_phases(emitted, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr("app.state.time.monotonic", clock)
    progress = downloads.SpotdlProgress("job", clock=clock, workers=4)

    progress.searching()
    assert emitted[-1][1] == {"unique_id": "job", "progress": 1.0, "message": "Searching"}

    clock.now += 1
    progress.resolved(0, 10)
    assert emitted[-1][1]["songs_total"] == 10
    # No guess while songs are still being looked up.
    assert "eta_seconds" not in emitted[-1][1]

    clock.now += 4
    progress.resolved(10, 10)
    last = emitted[-1][1]
    assert last["progress"] == 5.0
    assert last["songs_done"] == 10

    clock.now += 1
    progress.downloading(10)
    assert emitted[-1][1]["message"] == "Downloading"
    assert "eta_seconds" not in emitted[-1][1]

    clock.now += 5
    progress.song_update(0, 40, "Downloading")
    assert "eta_seconds" not in emitted[-1][1]

    clock.now += 25
    for song in range(4):
        progress.song_update(song, 100, "Done")
    last = emitted[-1][1]
    assert last["progress"] == 41.0
    assert last["songs_done"] == 4
    # 4 songs in 30 s with 4 workers: 6 songs left take about 45 s.
    assert 40 <= last["eta_seconds"] <= 50

def test_youtube_hook_adds_an_eta_once_it_has_data(emitted, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr("app.state.time.monotonic", clock)
    eta = EtaEstimator(clock=clock)
    data = {"status": "downloading", "downloaded_bytes": 10, "total_bytes": 100}
    downloads.youtube_progress_hook("job", data, eta)
    assert "eta_seconds" not in emitted[-1][1]

    clock.now += 10
    downloads.youtube_progress_hook("job", {**data, "downloaded_bytes": 50}, eta)
    assert emitted[-1][1]["eta_seconds"] == 10


def test_song_progress_counts_finished_and_running_songs():
    songs = SongProgress(4)
    assert songs.update("a", 25, "Searching for song") == (0, 1, 0.0625)
    assert songs.update("b", 40, "Getting audio meta") == (0, 2, pytest.approx(0.1625))
    assert songs.update("a", 100, "Done") == (1, 1, pytest.approx(0.35))
    # A failed song is finished too: spotDL will not touch it again.
    assert songs.update("b", 40, "Error") == (2, 0, pytest.approx(0.5))
    # A late, lower update never moves the bar backwards.
    assert songs.update("c", 0, "Searching for song")[2] == pytest.approx(0.5)
    assert songs.update("a", 95, "Embedding metadata") == (2, 1, pytest.approx(0.5))


def test_search_counter_reaches_the_total_in_a_burst(emitted, monkeypatch):
    # spotDL's workers often finish several songs within a few milliseconds.
    # Throttled emits used to drop the last ones, so the card jumped from
    # "75/80" straight to downloading.
    clock = FakeClock()
    monkeypatch.setattr("app.state.time.monotonic", clock)
    progress = downloads.SpotdlProgress("job", clock=clock)
    progress.searching()
    for done in range(0, 81):
        progress.resolved(done, 80)
    counts = [data["songs_done"] for _, data in emitted if data.get("message") == "Searching" and "songs_done" in data]
    assert counts == list(range(0, 81))


def test_download_card_shows_one_calm_step(emitted, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr("app.state.time.monotonic", clock)
    progress = downloads.SpotdlProgress("job", clock=clock)
    progress.downloading(3)
    for key, percent, message in [
        ("a", 25, "Searching for song"),
        ("b", 25, "Searching for song"),
        ("a", 40, "Getting audio meta"),
        ("b", 90, "Converting"),
        ("a", 100, "Done"),
        ("b", 100, "Done"),
        ("c", 100, "Done"),
    ]:
        clock.now += 1
        progress.song_update(key, percent, message)
    messages = {data["message"] for _, data in emitted}
    assert messages == {"Downloading"}
    progress_values = [data["progress"] for _, data in emitted]
    assert progress_values == sorted(progress_values)
    assert emitted[-1][1]["songs_done"] == 3
    assert emitted[-1][1]["progress"] == 95.0


def test_a_batch_that_fits_the_workers_gets_an_early_estimate():
    clock = FakeClock()
    single = ThroughputEta(1, workers=4, clock=clock)
    assert single.update(0, 0.05) is None
    clock.now += 1
    assert single.update(0, 0.3) is None  # too early for any number
    clock.now += 2
    left = single.update(0, 0.5)
    assert left == pytest.approx(3.0)  # half done after 3 s
    clock.now += 1
    assert single.update(0, 0.6) < left  # counts down instead of standing still


def test_a_large_batch_still_waits_for_real_data():
    clock = FakeClock()
    eta = ThroughputEta(20, workers=4, clock=clock)
    clock.now += 5
    assert eta.update(0, 3.5) is None
