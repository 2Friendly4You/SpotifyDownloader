import os
import zipfile

import pytest

from app import downloads
from app.config import MUSIC_DIR
from app.retries import (
    classify_error,
    describe_exception,
    failed_tracks_text,
    fallback_providers,
    retry_plan,
    short_error,
)
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

    def __init__(self, primary, succeed_on, folder=None, error="AudioProviderError: YT-DLP download error - x",
                 output=None):
        self.settings = {
            "audio_providers": [primary],
            "threads": 4,
            "ytm_data": False,
            "playlist_numbering": False,
            "album_type": None,
            "playlist_retain_track_cover": False,
        }
        if output:
            self.settings["output"] = output
            self.settings["format"] = "mp3"
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
                folder = os.path.dirname(self.settings["output"]) if "output" in self.settings else self.folder
                if folder:
                    os.makedirs(folder, exist_ok=True)
                    path = os.path.join(folder, f"{song.name}.mp3")
                    # Like spotDL: an existing file counts as saved and is not written again.
                    if not os.path.exists(path):
                        with open(path, "w") as handle:
                            handle.write(f"audio {song.url}")
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
        "error": "LookupError: No results found for song: Artist - Lost",
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
        "error": "AudioProviderError: YT-DLP download error - x",
    }]
    body = client.get("/api/status/retry-job").get_json()
    assert body["status"] == "completed"
    assert body["failed_tracks"][0]["title"] == "Artist - Bad"

    with zipfile.ZipFile(os.path.join(MUSIC_DIR, "retry-job.zip")) as archive:
        names = sorted(archive.namelist())
        assert names == ["Ok.mp3", "failed-songs.txt"]
        text = archive.read("failed-songs.txt").decode()
        assert "Artist - Bad (Download failed)" in text
        assert "    Error: AudioProviderError: YT-DLP download error - x" in text
    os.remove(os.path.join(MUSIC_DIR, "retry-job.zip"))


def test_a_playlist_where_every_song_failed_lists_them_all(monkeypatch, client, _quiet):
    _run(monkeypatch, [FakeSong("one"), FakeSong("two")], lambda settings: FakeDownloader("youtube-music", {}))

    failed = [data for name, data in _quiet if name == "download_failed"]
    assert [track["title"] for track in failed[-1]["failed_tracks"]] == ["Artist - One", "Artist - Two"]
    body = client.get("/api/status/retry-job").get_json()
    assert body["status"] == "failed"
    assert len(body["failed_tracks"]) == 2
    # The songs and reasons are listed on the card; no raw spotDL error.
    assert failed[-1]["message"] == "Download failed: No song could be downloaded."


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


def test_failed_tracks_text_adds_the_error_below_the_song():
    text = failed_tracks_text([
        {"title": "A - One", "reason": "download_failed", "url": "u1", "error": "Sign in to confirm your age."},
    ])
    assert text.splitlines()[2:] == [
        "A - One (Download failed) u1",
        "    Error: Sign in to confirm your age.",
    ]


def test_error_texts_are_short_and_without_secrets():
    age = (
        "ERROR: [youtube] r2Fu8RHv_mI: Sign in to confirm your age. This video may be inappropriate "
        "for some users. Use --cookies-from-browser or --cookies for the authentication. See "
        "https://github.com/yt-dlp/yt-dlp/wiki/FAQ for how to manually pass cookies."
    )
    assert short_error(age) == (
        "[youtube] r2Fu8RHv_mI: Sign in to confirm your age. This video may be inappropriate for some users."
    )
    masked = short_error("GET https://api.example.com/x?access_token=abc123&q=1 failed: Bearer eyJhbGci token=zzz")
    assert "abc123" not in masked and "eyJhbGci" not in masked and "zzz" not in masked
    assert masked.startswith("GET https://api.example.com/x failed")
    assert len(short_error("x" * 1000)) == 180
    assert short_error("   ") is None
    assert short_error(None) is None


def test_the_innermost_cause_is_reported():
    try:
        try:
            raise RuntimeError("ERROR: [youtube] abc: Sign in to confirm your age.")
        except RuntimeError as inner:
            raise ValueError("YT-DLP download error - https://music.youtube.com/watch?v=abc") from inner
    except ValueError as outer:
        assert describe_exception(outer) == "[youtube] abc: Sign in to confirm your age."

    class ApiError(Exception):
        def __init__(self, message, error=None):
            super().__init__(message)
            self.error = error

    assert describe_exception(ApiError("Could not get song info", error="429 Too Many Requests")) == (
        "Could not get song info: 429 Too Many Requests"
    )


def test_the_real_cause_of_a_failed_download_is_kept(monkeypatch):
    from spotdl.download.progress_handler import ProgressHandler
    from spotdl.types.song import Song

    song = Song.from_missing_data(
        name="SMD", artists=["RomancePlanet"], artist="RomancePlanet", url="https://open.spotify.com/track/smd"
    )
    downloader = FakeDownloader("youtube-music", {})
    sink = {}
    progress = downloads.SpotdlProgress("job")
    downloads.attach_spotdl_progress(downloader, progress, sink)
    progress.downloading(1)
    assert isinstance(downloader.progress_handler, ProgressHandler)
    tracker = downloader.progress_handler.get_new_tracker(song)
    try:
        try:
            raise RuntimeError("ERROR: [youtube] r2Fu8RHv_mI: Sign in to confirm your age.")
        except RuntimeError as inner:
            raise ValueError("YT-DLP download error - url") from inner
    except ValueError as outer:
        tracker.notify_error("traceback", outer, True)
    assert sink == {"https://open.spotify.com/track/smd": "[youtube] r2Fu8RHv_mI: Sign in to confirm your age."}
    download_state.release("job")


def test_songs_with_the_same_title_get_their_own_files(monkeypatch, client, _quiet):
    folder = os.path.join(MUSIC_DIR, "retry-job")

    def factory(settings):
        return FakeDownloader(
            "youtube-music", {"same": "youtube-music"}, output=settings["output"]
        )

    _run(monkeypatch, [FakeSong("one", name="Same"), FakeSong("two", name="Same"), FakeSong("three", name="Same")], factory)

    complete = [data for name, data in _quiet if name == "download_complete"]
    assert "failed_tracks" not in complete[-1]
    with zipfile.ZipFile(os.path.join(MUSIC_DIR, "retry-job.zip")) as archive:
        names = sorted(archive.namelist())
        assert names == ["Same (2).mp3", "Same (3).mp3", "Same.mp3"]
        # Each file is a different track, nothing was overwritten.
        assert archive.read("Same.mp3").decode().endswith("/one")
        assert archive.read("Same (2).mp3").decode().endswith("/two")
        assert archive.read("Same (3).mp3").decode().endswith("/three")
    assert not os.path.exists(folder)


def test_copy_folders_survive_spotdl_cleaning_the_output_path():
    # spotDL strips a leading dot from path parts, so the copy folder must not use one.
    from spotdl.types.song import Song
    from spotdl.utils.formatter import create_file_name

    song = Song.from_missing_data(name="Disturbia", artists=["Yoshiko"], artist="Yoshiko")
    template = os.path.join("/music/job", f"{downloads.COPY_FOLDER_PREFIX}2", "{artists} - {title}.{output-ext}")
    path = create_file_name(song=song, template=template, file_extension="mp3")
    assert os.path.basename(os.path.dirname(str(path))) == f"{downloads.COPY_FOLDER_PREFIX}2"
    os.remove(os.path.join(MUSIC_DIR, "retry-job.zip"))
