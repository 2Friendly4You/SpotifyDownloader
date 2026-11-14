import asyncio
import os
import threading

import pytest

from app import cancellation, downloads
from app.cancellation import JobCancelled, kill_job_processes, loop_stopper
from app.config import MUSIC_DIR
from app.state import DownloadState, download_state
from tests.test_retries import FakeDownloader, FakeSong


@pytest.fixture
def events(monkeypatch):
    emitted = []
    monkeypatch.setattr(downloads.socketio, "emit", lambda name, data, namespace=None: emitted.append((name, data)))
    monkeypatch.setattr(downloads, "use_provider", lambda downloader, name: downloader.settings.update(audio_providers=[name]))
    monkeypatch.setattr(downloads, "ensure_spotify_client", lambda: None)
    monkeypatch.setattr(cancellation, "kill_job_processes", lambda unique_id: [])
    monkeypatch.setenv("RETRY_DELAY_SECONDS", "0")
    return emitted


def test_cancel_removes_queued_jobs_and_flags_running_ones():
    state = DownloadState(1, 2)
    state.accept({"unique_id": "running"})
    state.accept({"unique_id": "waiting"})
    assert state.request_cancel("waiting") == "queued"
    assert state.lookup("waiting") == ("unknown", None)
    assert state.request_cancel("running") == "running"
    assert state.is_cancelled("running") is True
    assert state.request_cancel("nope") is None
    # The flag outlives the slot so leftover yt-dlp threads still stop.
    state.release("running")
    assert state.is_cancelled("running") is True


def test_job_processes_are_found_by_their_job_id(tmp_path):
    for pid, cmdline in [(101, b"ffmpeg\0-i\0/tmp/x.webm\0/music/job-1/A - B.mp3"), (102, b"ffmpeg\0/music/job-2/C.mp3")]:
        (tmp_path / str(pid)).mkdir()
        (tmp_path / str(pid) / "cmdline").write_bytes(cmdline)
    (tmp_path / "self").mkdir()
    killed = []
    assert kill_job_processes("job-1", proc_root=str(tmp_path), kill=lambda pid, sig: killed.append(pid)) == [101]
    assert killed == [101]


def test_loop_stopper_cancels_running_tasks():
    loop = asyncio.new_event_loop()
    outcome = {}

    started = threading.Event()

    async def songs():
        started.set()
        await asyncio.gather(asyncio.sleep(30), asyncio.sleep(30))

    def run():
        try:
            loop.run_until_complete(songs())
        except asyncio.CancelledError:
            outcome["cancelled"] = True

    worker = threading.Thread(target=run)
    worker.start()
    assert started.wait(timeout=5)
    loop_stopper(loop)()
    worker.join(timeout=5)
    loop.close()
    assert outcome == {"cancelled": True}


def test_progress_callbacks_raise_once_a_job_is_cancelled(events):
    download_state.accept({"unique_id": "cb-job"})
    downloader = FakeDownloader("youtube-music", {})
    progress = downloads.SpotdlProgress("cb-job")
    progress.downloading(1)
    downloads.attach_spotdl_progress(downloader, progress)
    callback = downloader.progress_handler.update_callback

    class Tracker:
        progress = 50

    callback(Tracker(), "Downloading")
    download_state.request_cancel("cb-job")
    with pytest.raises(JobCancelled):
        callback(Tracker(), "Downloading")
    with pytest.raises(JobCancelled):
        downloads.youtube_progress_hook("cb-job", {"status": "downloading"})
    download_state.release("cb-job")


def test_search_stops_when_cancelled(monkeypatch):
    class Song:
        display_name = "x"

    monkeypatch.setattr(downloads, "get_simple_songs", lambda query, **kwargs: [Song() for _ in range(20)])
    monkeypatch.setattr(downloads, "reinit_song", lambda song: song)
    calls = []
    with pytest.raises(JobCancelled):
        downloads.search_songs(
            FakeDownloader("youtube-music", {}), "q", lambda done, total: calls.append(done),
            is_cancelled=lambda: len(calls) >= 3,
        )
    assert len(calls) < 20


class CancellingDownloader(FakeDownloader):
    """Writes a file for the first song, then the user cancels."""

    def download_multiple_songs(self, songs):
        path = os.path.join(self.folder, "first.mp3")
        with open(path, "w") as handle:
            handle.write("partial")
        download_state.request_cancel("cancel-job")
        return [(songs[0], path)] + [(song, None) for song in songs[1:]]


def test_cancelled_download_cleans_up_and_frees_its_slot(monkeypatch, events, client):
    folder = os.path.join(MUSIC_DIR, "cancel-job")
    monkeypatch.setattr(downloads, "Downloader", lambda settings: CancellingDownloader("youtube-music", {}, folder=folder))
    monkeypatch.setattr(downloads, "search_songs", lambda d, q, r, is_cancelled=None, on_title=None: ([FakeSong("a"), FakeSong("b")], []))

    def job(unique_id):
        return {
            "unique_id": unique_id,
            "search_query": "https://open.spotify.com/track/y",
            "audio_format": "youtube-music",
            "lyrics_format": None,
            "output_format": "mp3",
        }

    download_state.accept(job("cancel-job"))
    download_state.accept(job("other-job"))
    assert download_state.accept(job("next-job"))[0] == "queued"

    downloads.run_spotdl("cancel-job", "https://open.spotify.com/album/x", "youtube-music", None, "mp3")

    names = [name for name, _ in events]
    assert "download_cancelled" in names
    assert "download_complete" not in names
    assert "download_failed" not in names
    assert not os.path.exists(folder)
    assert not os.path.exists(os.path.join(MUSIC_DIR, "cancel-job.zip"))
    assert client.get("/api/status/cancel-job").status_code == 404
    # No retry round started after the cancel.
    assert all(data.get("message") != "Retrying" for name, data in events if name == "download_progress")
    assert download_state.lookup("next-job") == ("pending", None)


def test_a_cancel_that_arrives_after_packaging_still_removes_the_zip(monkeypatch, events, client):
    folder = os.path.join(MUSIC_DIR, "late-job")
    monkeypatch.setattr(downloads, "Downloader", lambda settings: FakeDownloader("youtube-music", {"a": 0}, folder=folder))
    monkeypatch.setattr(downloads, "search_songs", lambda d, q, r, is_cancelled=None, on_title=None: ([FakeSong("a")], []))
    original = downloads.publish_zip

    def publish_then_cancel(unique_id, *args, **kwargs):
        original(unique_id, *args, **kwargs)
        download_state.request_cancel(unique_id)

    monkeypatch.setattr(downloads, "publish_zip", publish_then_cancel)
    download_state.accept({"unique_id": "late-job"})
    downloads.run_spotdl("late-job", "https://open.spotify.com/track/x", "youtube-music", None, "mp3")

    assert not os.path.exists(os.path.join(MUSIC_DIR, "late-job.zip"))
    assert not os.path.exists(folder)
    assert client.get("/api/status/late-job").status_code == 404
    assert events[-1] == ("download_cancelled", {"unique_id": "late-job"})
