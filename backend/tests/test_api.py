import os
from pathlib import Path

SONG = {
    "search_query": "Test Song",
    "audio_format": "youtube",
    "lyrics_format": "genius",
    "output_format": "mp3",
}


def login(client):
    response = client.post(
        "/api/admin/login",
        json={"password": os.environ["ADMIN_PASSWORD"]},
    )
    assert response.status_code == 200
    return response


def test_download_counter_returns_the_stored_total(client):
    from app.searches import read_searches_file, write_searches_file

    data = read_searches_file() or {"total": 0}
    previous = int(data.get("total", 0))
    data["total"] = 7
    write_searches_file(data)
    try:
        response = client.get("/api/download_counter")
        assert response.status_code == 200
        assert response.get_json() == {"total": 7}
    finally:
        data["total"] = previous
        write_searches_file(data)


def test_search_requires_a_query(client):
    response = client.post("/api/search", json={})
    assert response.status_code == 400
    assert response.get_json()["message"] == "Search query is required"


def test_search_rejects_a_query_over_2000_characters(client):
    response = client.post("/api/search", json={"search_query": "a" * 2001})
    assert response.status_code == 400
    assert response.get_json()["message"] == "Search query is too long"


def test_search_rejects_unknown_formats(client):
    response = client.post("/api/search", json={
        "search_query": "Test Song",
        "audio_format": "nope",
        "lyrics_format": "nope",
        "output_format": "nope",
    })
    assert response.status_code == 400
    assert response.get_json()["message"] == "Invalid input provided"


def test_search_rejects_a_non_spotify_url(client):
    response = client.post("/api/search", json={
        **SONG,
        "search_query": "https://example.com/track",
    })
    assert response.status_code == 400
    assert response.get_json()["message"] == "Invalid input provided"


def test_youtube_search_rejects_an_unknown_output_format(client):
    response = client.post("/api/search", json={
        "search_query": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "output_format": "aiff",
    })
    assert response.status_code == 400
    assert response.get_json()["message"] == "Invalid output format"


def test_rejected_search_does_not_increase_the_counter(client):
    before = client.get("/api/download_counter").get_json()["total"]
    response = client.post("/api/search", json={})
    assert response.status_code == 400
    assert client.get("/api/download_counter").get_json()["total"] == before


def test_rejected_search_appears_in_the_admin_log(client):
    client.post("/api/search", json={
        "search_query": "$$$",
        "audio_format": "youtube",
        "lyrics_format": "genius",
        "output_format": "mp3",
    })
    login(client)
    last_requests = client.get("/api/admin/overview").get_json()["last_requests"]
    assert last_requests[0]["search_query"] == "$$$"
    assert last_requests[0]["status_code"] == 400


def test_search_starts_a_download_and_reports_it_pending(client):
    before = client.get("/api/download_counter").get_json()["total"]
    started = client.post("/api/search", json=SONG)
    assert started.status_code == 202
    body = started.get_json()
    assert body["status"] == "success"
    assert body["queued"] is False
    assert body["message"] == "Download started"

    pending = client.get(f"/api/status/{body['unique_id']}")
    assert pending.status_code == 202
    assert pending.get_json() == {
        "status": "pending",
        "progress": 0.0,
        "progress_message": "Searching",
    }
    assert client.get("/api/download_counter").get_json()["total"] == before + 1


def test_running_search_cannot_be_cancelled(client):
    started = client.post("/api/search", json=SONG)
    unique_id = started.get_json()["unique_id"]
    response = client.delete(f"/api/search/{unique_id}")
    assert response.status_code == 404
    assert response.get_json()["cancelled"] is False
    assert response.get_json()["message"] == "Request is not queued."


def test_second_search_waits_when_the_concurrency_limit_is_full(client):
    login(client)
    limit = client.post("/api/admin/limit", json={"concurrent_limit": 1})
    assert limit.status_code == 200
    assert limit.get_json()["concurrent_limit"] == 1

    first = client.post("/api/search", json=SONG)
    assert first.get_json()["queued"] is False
    second = client.post("/api/search", json=SONG)
    assert second.status_code == 202
    assert second.get_json()["queued"] is True
    assert second.get_json()["position"] == 1

    queued = client.get(f"/api/status/{second.get_json()['unique_id']}")
    assert queued.status_code == 202
    assert queued.get_json() == {"status": "queued", "position": 1}


def test_queued_search_can_be_cancelled(client):
    login(client)
    client.post("/api/admin/limit", json={"concurrent_limit": 1})
    client.post("/api/search", json=SONG)
    queued = client.post("/api/search", json=SONG)
    unique_id = queued.get_json()["unique_id"]

    cancelled = client.delete(f"/api/search/{unique_id}")
    assert cancelled.status_code == 200
    assert cancelled.get_json() == {"status": "success", "cancelled": True}

    missing = client.delete(f"/api/search/{unique_id}")
    assert missing.status_code == 404


def test_search_is_rejected_when_the_queue_is_full(client):
    login(client)
    client.post("/api/admin/limit", json={"concurrent_limit": 1})
    before = client.get("/api/download_counter").get_json()["total"]
    client.post("/api/search", json=SONG)
    client.post("/api/search", json=SONG)
    rejected = client.post("/api/search", json=SONG)
    assert rejected.status_code == 429
    assert rejected.get_json()["message"] == "Download queue is full. Please try again later."
    assert client.get("/api/download_counter").get_json()["total"] == before + 2


def test_unknown_download_is_not_found(client):
    response = client.get("/api/status/does-not-exist")
    assert response.status_code == 404
    assert response.get_json()["status"] == "not_found"


def test_existing_zip_is_ready_to_download(client):
    music_dir = Path(os.environ["MUSIC_DIR"])
    (music_dir / "ready.zip").write_bytes(b"archive")

    status = client.get("/api/status/ready")
    assert status.status_code == 200
    assert status.get_json() == {"status": "completed", "url": "/music/ready.zip"}

    download = client.get("/music/ready.zip")
    assert download.status_code == 200
    assert download.data == b"archive"


def test_completed_download_without_a_file_is_missing(client):
    from app.state import download_state

    download_state.mark_completed("gone-file")
    response = client.get("/api/status/gone-file")
    assert response.status_code == 404
    assert response.get_json()["message"] == "File was marked completed but is now missing."


def test_admin_overview_requires_login(client):
    response = client.get("/api/admin/overview")
    assert response.status_code == 401
    assert response.get_json()["message"] == "Unauthorized"


def test_admin_can_log_in_and_out(client):
    wrong = client.post("/api/admin/login", json={"password": "wrong"})
    assert wrong.status_code == 401
    assert wrong.get_json()["logged_in"] is False
    assert client.get("/api/admin/session").get_json()["logged_in"] is False

    login(client)
    assert client.get("/api/admin/session").get_json()["logged_in"] is True
    assert client.get("/api/admin/overview").status_code == 200

    logged_out = client.post("/api/admin/logout")
    assert logged_out.get_json()["logged_in"] is False
    assert client.get("/api/admin/overview").status_code == 401


def test_admin_rejects_a_limit_below_one(client):
    login(client)
    response = client.post("/api/admin/limit", json={"concurrent_limit": 0})
    assert response.status_code == 400
    assert response.get_json()["message"] == "Invalid limit value provided."


def test_admin_keeps_the_download_counter_when_saving_the_limit(client):
    before = client.get("/api/download_counter").get_json()["total"]
    client.post("/api/search", json=SONG)
    login(client)
    response = client.post("/api/admin/limit", json={"concurrent_limit": 3})
    assert response.status_code == 200
    assert response.get_json()["concurrent_limit"] == 3
    assert client.get("/api/admin/overview").get_json()["current_limit"] == 3
    assert client.get("/api/download_counter").get_json()["total"] == before + 1


def test_admin_refuses_to_save_a_limit_when_the_counter_file_cannot_be_read(client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.searches.SEARCHES_FILE", str(tmp_path))
    login(client)
    response = client.post("/api/admin/limit", json={"concurrent_limit": 2})
    assert response.status_code == 500
    assert response.get_json()["message"] == "Could not save the limit because searches.json could not be read."


def test_admin_deletes_zip_files_and_leaves_other_files(client):
    music_dir = Path(os.environ["MUSIC_DIR"])
    existing_zips = [path for path in music_dir.iterdir() if path.suffix.lower() == ".zip"]
    (music_dir / "one.zip").write_bytes(b"one")
    (music_dir / "notes.txt").write_bytes(b"keep")
    login(client)

    response = client.post("/api/admin/delete-zips")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["deleted_count"] == len(existing_zips) + 1
    assert body["error_count"] == 0
    assert not (music_dir / "one.zip").exists()
    assert (music_dir / "notes.txt").read_bytes() == b"keep"
