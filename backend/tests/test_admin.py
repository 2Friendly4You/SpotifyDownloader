import os
import shutil
import time
import uuid
from pathlib import Path

import pytest

from app import downloads, history
from app.state import download_state

SONG = {
    "search_query": "https://open.spotify.com/track/08mG3Y1vljYA6bvDt4Wqkj",
    "audio_format": "youtube",
    "lyrics_format": "genius",
    "output_format": "mp3",
}
MUSIC = Path(os.environ["MUSIC_DIR"])


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    history.reset_for_tests()
    monkeypatch.setattr(downloads.socketio, "emit", lambda *a, **k: None)
    MUSIC.mkdir(parents=True, exist_ok=True)
    for path in MUSIC.iterdir():
        shutil.rmtree(path) if path.is_dir() else path.unlink()
    yield
    history.reset_for_tests()


def login(client):
    assert client.post("/api/admin/login", json={"password": os.environ["ADMIN_PASSWORD"]}).status_code == 200


def finished_job(title="Mix 🌞", age_days=0, size=1234, failed=None):
    unique_id = str(uuid.uuid4())
    history.created({"unique_id": unique_id, "search_query": "q", "output_format": "mp3"}, queued=False)
    history.started(unique_id)
    history.set_title(unique_id, title)
    path = MUSIC / f"{unique_id}.zip"
    path.write_bytes(b"x" * size)
    history.finished(unique_id, "completed", size_bytes=size, songs_saved=3, failed_tracks=failed)
    if age_days:
        old = time.time() - age_days * 86400
        os.utime(path, (old, old))
    return unique_id


@pytest.mark.parametrize("method,path", [
    ("get", "/api/admin/overview"),
    ("post", f"/api/admin/jobs/{uuid.uuid4()}/cancel"),
    ("post", f"/api/admin/jobs/{uuid.uuid4()}/delete-file"),
    ("post", "/api/admin/cleanup"),
    ("post", "/api/admin/delete-zips"),
    ("post", "/api/admin/limit"),
])
def test_every_admin_endpoint_needs_a_login(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_overview_lists_jobs_with_names_sizes_and_failed_songs(client):
    failed = [{"song": "A - B", "reason": "not_found"}]
    unique_id = finished_job(failed=failed)
    login(client)
    body = client.get("/api/admin/overview").get_json()
    job = body["jobs"]["recent"][0]
    assert job["id"] == unique_id
    assert job["title"] == "Mix 🌞"
    assert job["status"] == "completed"
    assert job["file_available"] is True
    assert job["size_bytes"] == 1234
    assert job["songs_saved"] == 3
    assert job["failed_tracks"] == failed
    assert body["stats"]["day"]["completed"] == 1
    assert body["stats"]["day"]["failed_songs"] == 1
    assert body["storage"]["zip_count"] == 1
    assert body["storage"]["zip_bytes"] == 1234
    assert "versions" in body["health"]


def test_overview_never_contains_the_admin_password(client):
    login(client)
    assert os.environ["ADMIN_PASSWORD"] not in client.get("/api/admin/overview").get_data(as_text=True)


def test_a_search_creates_a_history_entry(client, monkeypatch):
    monkeypatch.setattr(downloads.socketio, "start_background_task", lambda *a, **k: None)
    response = client.post("/api/search", json=SONG)
    unique_id = response.get_json()["unique_id"]
    login(client)
    running = client.get("/api/admin/overview").get_json()["jobs"]["running"]
    assert [job["id"] for job in running] == [unique_id]
    assert running[0]["query"] == SONG["search_query"]
    assert running[0]["progress"]["message"] == "Searching"


def test_admin_can_cancel_a_queued_job(client):
    download_state.set_limit(1)
    client.post("/api/search", json=SONG)
    queued_id = client.post("/api/search", json=SONG).get_json()["unique_id"]
    login(client)
    response = client.post(f"/api/admin/jobs/{queued_id}/cancel")
    assert response.status_code == 200
    assert response.get_json()["outcome"] == "queued"
    assert queued_id not in download_state.queued_ids()
    recent = {job["id"]: job for job in response.get_json()["jobs"]["recent"]}
    assert recent[queued_id]["status"] == "cancelled"
    assert client.post(f"/api/admin/jobs/{queued_id}/cancel").status_code == 409


def test_admin_deletes_one_finished_file(client):
    unique_id = finished_job()
    login(client)
    response = client.post(f"/api/admin/jobs/{unique_id}/delete-file")
    assert response.status_code == 200
    assert response.get_json()["freed_bytes"] == 1234
    assert not (MUSIC / f"{unique_id}.zip").exists()
    job = response.get_json()["jobs"]["recent"][0]
    assert job["file_available"] is False and job["file_deleted_at"]
    assert client.post(f"/api/admin/jobs/{unique_id}/delete-file").status_code == 404


def test_admin_cannot_delete_the_file_of_a_running_job(client):
    client.post("/api/search", json=SONG)
    running_id = download_state.pending_ids()[0]
    login(client)
    assert client.post(f"/api/admin/jobs/{running_id}/delete-file").status_code == 409


def test_job_ids_are_validated(client):
    login(client)
    assert client.post("/api/admin/jobs/..%2Fsearches/delete-file").status_code == 404
    assert client.post("/api/admin/jobs/not-a-uuid/cancel").status_code == 404


def test_cleanup_deletes_only_old_zips_and_leftover_folders(client):
    old = finished_job(age_days=10)
    new = finished_job()
    leftover = MUSIC / str(uuid.uuid4())
    leftover.mkdir()
    (leftover / "song.mp3").write_bytes(b"y" * 10)
    login(client)
    response = client.post("/api/admin/cleanup", json={"older_than_days": 7, "leftovers": True})
    body = response.get_json()
    assert response.status_code == 200
    assert (body["deleted_count"], body["folder_count"], body["freed_bytes"]) == (1, 1, 1244)
    assert not (MUSIC / f"{old}.zip").exists()
    assert (MUSIC / f"{new}.zip").exists()
    assert not leftover.exists()


def test_cleanup_keeps_the_folder_of_a_running_job(client):
    client.post("/api/search", json=SONG)
    running_id = download_state.pending_ids()[0]
    (MUSIC / running_id).mkdir()
    login(client)
    body = client.post("/api/admin/cleanup", json={"leftovers": True}).get_json()
    assert body["folder_count"] == 0
    assert (MUSIC / running_id).exists()


def test_cleanup_rejects_bad_input(client):
    login(client)
    assert client.post("/api/admin/cleanup", json={}).status_code == 400
    assert client.post("/api/admin/cleanup", json={"older_than_days": -1}).status_code == 400
    assert client.post("/api/admin/cleanup", json={"older_than_days": "x"}).status_code == 400


def test_history_survives_a_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_HISTORY_FILE", str(tmp_path / "jobs.json"))
    history.reset_for_tests()
    history.created({"unique_id": "a", "search_query": "q"}, queued=True)
    history.finished("a", "failed", message="boom")
    monkeypatch.setattr(history, "_loaded", False)
    history._entries.clear()
    (entry,) = history.entries()
    assert (entry["id"], entry["status"], entry["message"]) == ("a", "failed", "boom")


def test_users_learn_that_the_admin_cancelled_their_job(client, monkeypatch):
    emitted = []
    monkeypatch.setattr(downloads.socketio, "emit", lambda event, data, **k: emitted.append((event, data)))
    from app.routes import admin as admin_routes
    monkeypatch.setattr(admin_routes.socketio, "emit", lambda event, data, **k: emitted.append((event, data)))
    monkeypatch.setattr(downloads.cancellation, "stop", lambda unique_id: None)
    download_state.set_limit(1)
    running_id = client.post("/api/search", json=SONG).get_json()["unique_id"]
    queued_id = client.post("/api/search", json=SONG).get_json()["unique_id"]
    login(client)

    client.post(f"/api/admin/jobs/{queued_id}/cancel")
    assert ("download_cancelled", {"unique_id": queued_id, "by_admin": True}) in emitted

    client.post(f"/api/admin/jobs/{running_id}/cancel")
    downloads.finish_cancelled(running_id)  # what the worker does once it stopped
    assert ("download_cancelled", {"unique_id": running_id, "by_admin": True}) in emitted


def test_a_users_own_cancel_is_not_reported_as_an_admin_cancel(monkeypatch):
    emitted = []
    monkeypatch.setattr(downloads.socketio, "emit", lambda event, data, **k: emitted.append((event, data)))
    unique_id = str(uuid.uuid4())
    downloads.finish_cancelled(unique_id)
    assert emitted == [("download_cancelled", {"unique_id": unique_id})]


def test_zips_from_before_the_history_are_imported(tmp_path, monkeypatch):
    from app.titles import write_zip_title
    unique_id = str(uuid.uuid4())
    path = MUSIC / f"{unique_id}.zip"
    import zipfile
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("A - One.mp3", b"1")
        archive.writestr("B - Two.mp3", b"2")
        archive.writestr("failed_tracks.txt", b"x")
    write_zip_title(str(path), "Old Mix 🎻")
    monkeypatch.setenv("JOB_HISTORY_FILE", str(tmp_path / "jobs.json"))
    history.reset_for_tests()
    monkeypatch.setattr(history, "_loaded", False)
    (entry,) = history.entries()
    assert (entry["id"], entry["title"], entry["songs_saved"], entry["status"]) == (unique_id, "Old Mix 🎻", 2, "completed")
    assert "started_at" not in entry  # no made-up duration
    assert (tmp_path / "jobs.json").exists()


def test_a_broken_history_file_is_kept_aside(tmp_path, monkeypatch):
    broken = tmp_path / "jobs.json"
    broken.write_text("{not json")
    monkeypatch.setenv("JOB_HISTORY_FILE", str(broken))
    history.reset_for_tests()
    monkeypatch.setattr(history, "_loaded", False)
    assert history.entries() == []
    assert (tmp_path / "jobs.json.broken").read_text() == "{not json"
