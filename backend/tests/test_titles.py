import os
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

from app.state import download_state
from app.titles import (
    content_disposition,
    read_zip_title,
    safe_filename_stem,
    title_from_songs,
    write_zip_title,
    zip_download_name,
)


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def song(**fields):
    base = {"list_name": None, "artist": "Artist", "name": "Song", "album_artist": None}
    base.update(fields)
    return SimpleNamespace(**base)


PLAYLIST = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc"


@pytest.mark.parametrize("query, songs, expected", [
    (PLAYLIST, [song(list_name="Today's Top Hits")], "Today's Top Hits"),
    ("https://open.spotify.com/intl-de/album/1", [song(list_name="Abbey Road", album_artist="The Beatles")],
     "The Beatles - Abbey Road"),
    ("https://open.spotify.com/track/1", [song(artist="Daft Punk", name="One More Time")], "Daft Punk - One More Time"),
    ("https://open.spotify.com/artist/1", [song(list_name="Daft Punk")], "Daft Punk"),
    ("  daft   punk around the world ", [], "daft punk around the world"),
    (PLAYLIST, [], None),
    ("https://spotify.link/abc", [song(list_name="Short Link Mix")], "Short Link Mix"),
])
def test_job_title_is_the_name_a_user_recognises(query, songs, expected):
    assert title_from_songs(query, songs) == expected


@pytest.mark.parametrize("title, expected", [
    ("Chill: Vibes / 2024?", "Chill_ Vibes _ 2024_"),
    ('a<b>c"d|e*f\\g', "a_b_c_d_e_f_g"),
    ("  trailing dots... ", "trailing dots"),
    ("CON", "CON_"),
    ("Sommer 🌞 Hits – Café", "Sommer 🌞 Hits – Café"),
    ("...", None),
    ("", None),
    (None, None),
])
def test_filename_stem_is_safe_everywhere(title, expected):
    assert safe_filename_stem(title) == expected


def test_long_titles_are_cut_on_a_character_boundary():
    stem = safe_filename_stem("🎵" * 100)
    assert len(stem.encode("utf-8")) <= 150
    assert stem == "🎵" * len(stem)


def test_zip_name_falls_back_to_the_job_id():
    assert zip_download_name(None, "abc") == "abc.zip"
    assert zip_download_name("Mix", "abc") == "Mix.zip"


def test_content_disposition_has_an_ascii_name_and_the_full_utf8_name():
    header = content_disposition("Sommer 🌞 Café.zip", "id.zip")
    assert header.startswith('attachment; filename="Sommer Cafe.zip"')
    assert unquote(header.split("filename*=UTF-8''")[1]) == "Sommer 🌞 Café.zip"
    assert content_disposition("Plain Mix.zip", "id.zip") == 'attachment; filename="Plain Mix.zip"'
    only_emoji = content_disposition("🎵🎶.zip", "id.zip")
    assert only_emoji.startswith('attachment; filename="id.zip"')
    trailing_emoji = content_disposition("The Shortest CELTIC Songs 🎻.zip", "id.zip")
    assert trailing_emoji.startswith('attachment; filename="The Shortest CELTIC Songs.zip"')


def test_title_survives_in_the_zip_comment(tmp_path):
    path = tmp_path / "x.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a.mp3", b"x")
    write_zip_title(str(path), "Mix 🌞")
    assert read_zip_title(str(path)) == "Mix 🌞"
    with zipfile.ZipFile(path) as archive:
        assert archive.read("a.mp3") == b"x"


def _make_zip(unique_id, title=None):
    music = Path(os.environ["MUSIC_DIR"])
    music.mkdir(parents=True, exist_ok=True)
    path = music / f"{unique_id}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("song.mp3", b"data")
    if title:
        write_zip_title(str(path), title)
    return path


def test_two_playlists_with_the_same_name_are_stored_and_served_separately(client):
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    _make_zip(first, "Party Mix")
    _make_zip(second, "Party Mix")
    for unique_id in (first, second):
        response = client.get(f"/api/download/{unique_id}")
        assert response.status_code == 200
        assert response.headers["Content-Disposition"] == 'attachment; filename="Party Mix.zip"'
        assert response.mimetype == "application/zip"
        response.close()
    assert (Path(os.environ["MUSIC_DIR"]) / f"{first}.zip").exists()
    assert (Path(os.environ["MUSIC_DIR"]) / f"{second}.zip").exists()


def test_download_prefers_the_live_title_and_falls_back_to_the_id(client):
    named, unnamed = str(uuid.uuid4()), str(uuid.uuid4())
    _make_zip(named, "Old: name")
    _make_zip(unnamed)
    download_state.set_title(named, "Fresh / Name")
    try:
        response = client.get(f"/api/download/{named}")
        assert response.headers["Content-Disposition"] == 'attachment; filename="Fresh _ Name.zip"'
        response.close()
        response = client.get(f"/api/download/{unnamed}")
        assert response.headers["Content-Disposition"] == f'attachment; filename="{unnamed}.zip"'
        response.close()
    finally:
        download_state.set_title(named, None)


def test_download_rejects_anything_but_a_job_id(client):
    assert client.get("/api/download/..%2Fsearches.json").status_code == 404
    assert client.get("/api/download/not-a-uuid").status_code == 404
    assert client.get(f"/api/download/{uuid.uuid4()}").status_code == 404


def test_status_reports_the_title_and_the_named_download_url(client):
    unique_id = str(uuid.uuid4())
    _make_zip(unique_id, "Road Trip 🚗")
    body = client.get(f"/api/status/{unique_id}").get_json()
    assert body["status"] == "completed"
    assert body["url"] == f"/api/download/{unique_id}"
    assert body["title"] == "Road Trip 🚗"


def test_search_names_the_job_after_the_playlist_and_tells_the_client(monkeypatch):
    from app import downloads

    events = []
    monkeypatch.setattr(downloads.socketio, "emit", lambda name, data, namespace=None: events.append((name, data)))
    monkeypatch.setattr(downloads, "get_simple_songs", lambda query, **kwargs: [song(list_name="Night Drive 🌙")] * 2)
    monkeypatch.setattr(downloads, "reinit_song", lambda s: s)

    class FakeDownloader:
        settings = {"threads": 1, "ytm_data": False, "playlist_numbering": False,
                    "album_type": None, "playlist_retain_track_cover": False}

    unique_id = str(uuid.uuid4())
    try:
        downloads.search_songs(FakeDownloader(), PLAYLIST, lambda done, total: None,
                               on_title=lambda title: downloads.publish_title(unique_id, title))
        downloads.publish_title(unique_id, "Night Drive 🌙")  # repeated names are not re-sent
        assert download_state.title(unique_id) == "Night Drive 🌙"
        assert [e for e in events if e[0] == "download_title"] == [
            ("download_title", {"unique_id": unique_id, "title": "Night Drive 🌙"})
        ]
    finally:
        download_state.forget(unique_id)
        assert download_state.title(unique_id) is None
