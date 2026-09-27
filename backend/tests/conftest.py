import os
import tempfile
from pathlib import Path

_root = Path(tempfile.mkdtemp(prefix="spotify-downloader-tests-"))
os.environ["FLASK_SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "test-secret")
os.environ["ADMIN_PASSWORD"] = os.environ.get("ADMIN_PASSWORD", "test-admin")
os.environ["MUSIC_DIR"] = str(_root / "music")
os.environ["SEARCHES_FILE"] = str(_root / "searches.json")
os.environ["MAX_PENDING_REQUESTS"] = "2"
os.environ["MAX_QUEUED_REQUESTS"] = "1"

from app import app  # noqa: E402
from app.extensions import socketio  # noqa: E402
from app.state import download_state  # noqa: E402

import pytest  # noqa: E402


def _drain_downloads():
    for unique_id in download_state.queued_ids():
        download_state.cancel_queued(unique_id)
    for unique_id in download_state.pending_ids():
        download_state.release(unique_id)


@pytest.fixture(autouse=True)
def _block_real_downloads(monkeypatch):
    monkeypatch.setattr(socketio, "start_background_task", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def _reset_download_slots():
    _drain_downloads()
    limit = download_state.get_limit()
    yield
    _drain_downloads()
    download_state.set_limit(limit)


@pytest.fixture
def client():
    return app.test_client()
