import pytest

from app import downloads
from app.progress import EtaEstimator, SongRate, round_eta
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


def test_song_rate_learns_from_finished_downloads():
    rate = SongRate(default=10, alpha=0.5)
    assert rate.estimate(3) == 30
    rate.record(seconds=40, songs=10)
    assert rate.estimate(1) == pytest.approx(7.0)
    rate.record(seconds=0, songs=0)
    assert rate.estimate(1) == pytest.approx(7.0)


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
    songs = downloads.search_songs(FakeDownloader(), "query", lambda done, total: calls.append((done, total)))
    assert sorted(songs) == ["A", "B"]
    assert calls == [(0, 3), (1, 3), (2, 3), (3, 3)]


def test_spotdl_progress_moves_through_the_phases(emitted, monkeypatch):
    monkeypatch.setattr(downloads, "song_rate", SongRate(default=5))
    clock = FakeClock()
    monkeypatch.setattr("app.state.time.monotonic", clock)
    progress = downloads.SpotdlProgress("job", clock=clock)

    progress.searching()
    assert emitted[-1][1] == {"unique_id": "job", "progress": 1.0, "message": "Searching"}

    clock.now += 1
    progress.resolved(0, 10)
    assert emitted[-1][1]["songs_total"] == 10
    assert emitted[-1][1]["eta_seconds"] == 50

    clock.now += 4
    progress.resolved(10, 10)
    last = emitted[-1][1]
    assert last["progress"] == 5.0
    assert last["songs_done"] == 10

    clock.now += 1
    progress.downloading(10)
    assert emitted[-1][1]["message"] == "Downloading"
    assert emitted[-1][1]["eta_seconds"] == 50

    clock.now += 30
    progress.download_update(0.5, "Downloading")
    last = emitted[-1][1]
    assert last["progress"] == 50.0
    assert last["eta_seconds"] == 30
    assert "songs_done" not in last


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
