import os
import zipfile

import pytest

from app import downloads
from app.config import MUSIC_DIR
from app.retries import classify_error, failed_tracks_text, fallback_providers, retry_plan
from app.state import DownloadState, download_state


class FakeSong:
    def __init__(self, key, name=None, artists=None):
        self.url = f"https://open.spotify.com/track/{key}"
        self.name = name or key.title()
        self.artists = artists or ["Artist"]
        self.artist = self.artists[0]
        self.display_name = f"{self.artist} - {self.name}"


class FakeLoop:
    def is_closed(self):
        return False

    def close(self):
        pass


class FakeDownloader:
    """Succeeds for a song once its provider/attempt is listed in ``succeed_on``."""

    def __init__(self, primary, succeed_on, folder=None, error="AudioProviderError: YT-DLP download error - x"):
        self.settings = {
            "audio_providers": [primary],
            "threads": 4,
            "ytm_data": False,
            "playlist_numbering": False,
            "album_type": None,
            "playlist_retain_track_cover": False,
        }
        self.succeed_on = succeed_on
        self.folder = folder
        self.error = error
        self.errors = []
        self.calls = []
        self.loop = FakeLoop()
        self.progress_handler = None

    def download_multiple_songs(self, songs):
        provider = self.settings["audio_providers"][0]
        attempt = len(self.calls)
        self.calls.append((provider, [song.name for song in songs]))
        results = []
        for song in songs:
            wanted = self.succeed_on.get(song.name.lower())
            if wanted is not None and (wanted == provider or wanted == attempt):
                path = None
                if self.folder:
                    path = os.path.join(self.folder, f"{song.name}.mp3")
                    with open(path, "w") as handle:
                        handle.write("audio")
                results.append((song, path or f"/tmp/{song.name}.mp3"))
            else:
                self.errors.append(f"{song.url} - {self.error}")
                results.append((song, None))
        return results


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    events = []
    monkeypatch.setattr(downloads.socketio, "emit", lambda name, data, namespace=None: events.append((name, data)))
    monkeypatch.setattr(downloads, "use_provider", lambda downloader, name: downloader.settings.update(audio_providers=[name]))
    monkeypatch.setenv("RETRY_DELAY_SECONDS", "0")
    monkeypatch.delenv("AUDIO_PROVIDER_FALLBACKS", raising=False)
    return events


def test_fallbacks_skip_the_primary_and_unknown_names():
    assert fallback_providers("youtube-music", {}) == ["soundcloud", "youtube"]
    assert fallback_providers("soundcloud", {}) == ["youtube-music", "youtube"]
    env = {"AUDIO_PROVIDER_FALLBACKS": "youtube, nope, youtube-music, youtube"}
    assert fallback_providers("youtube-music", env) == ["youtube"]
    assert fallback_providers("youtube-music", {"AUDIO_PROVIDER_FALLBACKS": ""}) == []
    assert retry_plan("youtube-music", {}) == ["youtube-music", "soundcloud", "youtube"]


def test_errors_become_short_reasons():
    assert classify_error("x - LookupError: No results found for song: A - B") == "not_found"
    assert classify_error("x - AudioProviderError: YT-DLP download error - url") == "download_failed"
    assert classify_error("x - FFmpegError: failed") == "conversion_failed"
    assert classify_error("Error occurred while reinitializing song: boom") == "metadata_failed"
    assert classify_error(None) == "download_failed"


def test_a_song_that_works_on_the_second_try_is_not_reported():
    downloader = FakeDownloader("youtube-music", {"a": 0, "b": 1})
    progress = downloads.SpotdlProgress("job")
    succeeded, failures = downloads.download_with_retries(
        downloader, [FakeSong("a"), FakeSong("b")], "youtube-music", progress
    )
    assert [song.name for song, _ in succeeded] == ["A", "B"]
    assert failures == []
    assert downloader.calls == [("youtube-music", ["A", "B"]), ("youtube-music", ["B"])]


def test_a_song_falls_back_to_another_provider():
    downloader = FakeDownloader("youtube-music", {"a": "soundcloud"})
    progress = downloads.SpotdlProgress("job")
    succeeded, failures = downloads.download_with_retries(downloader, [FakeSong("a")], "youtube-music", progress)
    assert len(succeeded) == 1
    assert failures == []
    assert [provider for provider, _ in downloader.calls] == ["youtube-music", "youtube-music", "soundcloud"]


def test_a_song_that_fails_everywhere_keeps_the_reason_from_the_users_provider():
    downloader = FakeDownloader(
        "youtube-music", {}, error="LookupError: No results found for song: Artist - Lost"
    )
    progress = downloads.SpotdlProgress("job")
    succeeded, failures = downloads.download_with_retries(
        downloader, [FakeSong("lost", artists=["Artist", "Guest"])], "youtube-music", progress
    )
    assert succeeded == []
    assert failures == [{
        "title": "Artist, Guest - Lost",
        "reason": "not_found",
        "url": "https://open.spotify.com/track/lost",
    }]
    assert [provider for provider, _ in downloader.calls] == [
        "youtube-music", "youtube-music", "soundcloud", "youtube",
    ]


def test_retries_report_their_own_progress(_quiet):
    downloader = FakeDownloader("youtube-music", {"a": 0})
    progress = downloads.SpotdlProgress("job")
    downloads.download_with_retries(downloader, [FakeSong("a"), FakeSong("b")], "youtube-music", progress)
    retrying = [data for name, data in _quiet if name == "download_progress" and data["message"] == "Retrying"]
    assert retrying
    # The counter covers the whole job: one of two songs saved so far.
    assert retrying[0]["songs_total"] == 2
    assert retrying[0]["songs_done"] in (0, 1)
    download_state.release("job")


def test_failed_tracks_text_lists_every_song():
    text = failed_tracks_text([
        {"title": "A - One", "reason": "not_found", "url": "u1"},
        {"title": "B - Two", "reason": "download_failed", "url": None},
    ])
    assert text.splitlines() == [
        "These 2 songs could not be downloaded:",
        "",
        "A - One (Not found) u1",
        "B - Two (Download failed)",
    ]


def _run(monkeypatch, songs, downloader_factory):
    monkeypatch.setattr(downloads, "ensure_spotify_client", lambda: None)
    monkeypatch.setattr(downloads, "Downloader", downloader_factory)
    monkeypatch.setattr(downloads, "search_songs", lambda downloader, query, on_resolved, is_cancelled=None, on_title=None: (list(songs), []))
    download_state.accept({"unique_id": "retry-job"})
    downloads.run_spotdl("retry-job", "https://open.spotify.com/playlist/x", "youtube-music", None, "mp3")


def test_partly_failed_playlist_lists_the_failures(monkeypatch, client, _quiet):
    folder = os.path.join(MUSIC_DIR, "retry-job")

    def factory(settings):
        return FakeDownloader("youtube-music", {"ok": 0}, folder=folder)

    _run(monkeypatch, [FakeSong("ok"), FakeSong("bad")], factory)

    complete = [data for name, data in _quiet if name == "download_complete"]
    assert complete[-1]["failed_tracks"] == [{
        "title": "Artist - Bad",
        "reason": "download_failed",
        "url": "https://open.spotify.com/track/bad",
    }]
    body = client.get("/api/status/retry-job").get_json()
    assert body["status"] == "completed"
    assert body["failed_tracks"][0]["title"] == "Artist - Bad"

    with zipfile.ZipFile(os.path.join(MUSIC_DIR, "retry-job.zip")) as archive:
        names = sorted(archive.namelist())
        assert names == ["Ok.mp3", "failed-songs.txt"]
        assert "Artist - Bad (Download failed)" in archive.read("failed-songs.txt").decode()
    os.remove(os.path.join(MUSIC_DIR, "retry-job.zip"))


def test_a_playlist_where_every_song_failed_lists_them_all(monkeypatch, client, _quiet):
    _run(monkeypatch, [FakeSong("one"), FakeSong("two")], lambda settings: FakeDownloader("youtube-music", {}))

    failed = [data for name, data in _quiet if name == "download_failed"]
    assert [track["title"] for track in failed[-1]["failed_tracks"]] == ["Artist - One", "Artist - Two"]
    body = client.get("/api/status/retry-job").get_json()
    assert body["status"] == "failed"
    assert len(body["failed_tracks"]) == 2


def test_clean_download_has_no_failed_tracks_field(monkeypatch, client, _quiet):
    folder = os.path.join(MUSIC_DIR, "retry-job")
    _run(monkeypatch, [FakeSong("ok")], lambda settings: FakeDownloader("youtube-music", {"ok": 0}, folder=folder))
    complete = [data for name, data in _quiet if name == "download_complete"]
    assert "failed_tracks" not in complete[-1]
    assert "failed_tracks" not in client.get("/api/status/retry-job").get_json()
    os.remove(os.path.join(MUSIC_DIR, "retry-job.zip"))


def test_failed_tracks_are_forgotten_with_their_job(monkeypatch):
    now = {"t": 1_000.0}
    monkeypatch.setattr("app.state.time.time", lambda: now["t"])
    monkeypatch.setattr("app.state.retention_seconds", lambda: 10)
    state = DownloadState(1, 1)
    state.mark_completed("a", [{"title": "x", "reason": "not_found", "url": None}])
    assert state.failed_tracks("a")[0]["title"] == "x"
    now["t"] = 1_011
    state.expire_stale()
    assert state.failed_tracks("a") is None


def test_only_a_limited_number_of_songs_get_fallback_attempts(monkeypatch):
    monkeypatch.setenv("FALLBACK_SONG_LIMIT", "1")
    downloader = FakeDownloader("youtube-music", {})
    progress = downloads.SpotdlProgress("job")
    _, failures = downloads.download_with_retries(
        downloader, [FakeSong("a"), FakeSong("b")], "youtube-music", progress
    )
    assert downloader.calls == [
        ("youtube-music", ["A", "B"]),
        ("youtube-music", ["A", "B"]),
        ("soundcloud", ["A"]),
        ("youtube", ["A"]),
    ]
    assert sorted(track["title"] for track in failures) == ["Artist - A", "Artist - B"]
    download_state.release("job")
