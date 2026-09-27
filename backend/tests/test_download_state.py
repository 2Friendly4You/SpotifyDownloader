from app.state import DownloadState


def job(unique_id):
    return {"unique_id": unique_id}


def test_job_starts_when_a_slot_is_free():
    state = DownloadState(1, 1)
    assert state.accept(job("a")) == ("started", None)
    assert state.lookup("a") == ("pending", None)


def test_job_queues_when_slots_are_full():
    state = DownloadState(1, 2)
    state.accept(job("a"))
    assert state.accept(job("b")) == ("queued", 1)
    assert state.lookup("b") == ("queued", 1)


def test_queue_rejects_work_when_it_is_full():
    state = DownloadState(1, 1)
    state.accept(job("a"))
    state.accept(job("b"))
    assert state.accept(job("c")) == ("full", None)
    assert state.lookup("c") == ("unknown", None)


def test_finishing_a_job_starts_the_next_queued_job():
    state = DownloadState(1, 2)
    state.accept(job("a"))
    state.accept(job("b"))
    state.accept(job("c"))

    promoted = state.release("a")
    assert [item["unique_id"] for item in promoted] == ["b"]
    assert state.lookup("a") == ("unknown", None)
    assert state.lookup("b") == ("pending", None)
    assert state.lookup("c") == ("queued", 1)


def test_raising_the_limit_starts_queued_jobs():
    state = DownloadState(1, 2)
    state.accept(job("a"))
    state.accept(job("b"))
    state.accept(job("c"))

    promoted = state.set_limit(2)
    assert [item["unique_id"] for item in promoted] == ["b"]
    assert state.get_limit() == 2
    assert state.lookup("c") == ("queued", 1)


def test_cancel_removes_only_a_queued_job():
    state = DownloadState(1, 2)
    state.accept(job("a"))
    state.accept(job("b"))
    state.accept(job("c"))

    assert state.cancel_queued("b") is True
    assert state.cancel_queued("a") is False
    assert state.lookup("b") == ("unknown", None)
    assert state.lookup("c") == ("queued", 1)


def test_timed_out_job_frees_its_slot_for_the_queue(monkeypatch):
    now = {"t": 1_000.0}
    monkeypatch.setattr("app.state.time.time", lambda: now["t"])
    monkeypatch.setattr("app.state.PENDING_TTL_SECONDS", 60)
    monkeypatch.setattr("app.state.retention_seconds", lambda: 100)

    state = DownloadState(1, 1)
    state.accept(job("a"))
    state.accept(job("b"))

    now["t"] = 1_059
    timed_out, promoted = state.expire_stale()
    assert timed_out == []
    assert promoted == []

    now["t"] = 1_060
    timed_out, promoted = state.expire_stale()
    assert timed_out == ["a"]
    assert [item["unique_id"] for item in promoted] == ["b"]
    assert state.lookup("a") == ("failed", "Download timed out.")
    assert state.lookup("b") == ("pending", None)


def test_old_failures_are_forgotten(monkeypatch):
    now = {"t": 1_000.0}
    monkeypatch.setattr("app.state.time.time", lambda: now["t"])
    monkeypatch.setattr("app.state.PENDING_TTL_SECONDS", 10)
    monkeypatch.setattr("app.state.retention_seconds", lambda: 50)

    state = DownloadState(1, 1)
    state.accept(job("a"))
    now["t"] = 1_010
    state.expire_stale()
    assert state.lookup("a")[0] == "failed"

    now["t"] = 1_060
    state.expire_stale()
    assert state.lookup("a") == ("unknown", None)


def test_finished_job_stays_completed_after_its_slot_is_released(monkeypatch):
    now = {"t": 5_000.0}
    monkeypatch.setattr("app.state.time.time", lambda: now["t"])
    monkeypatch.setattr("app.state.retention_seconds", lambda: 30)

    state = DownloadState(1, 1)
    state.accept(job("a"))
    state.mark_completed("a")
    assert state.release("a") == []
    assert state.lookup("a") == ("completed", None)

    now["t"] = 5_030
    state.expire_stale()
    assert state.lookup("a") == ("unknown", None)


def test_progress_updates_skip_tiny_changes():
    state = DownloadState(1, 1)
    percent, message, should_emit = state.update_progress("a", 10, "Downloading", min_interval=0)
    assert (percent, message, should_emit) == (10.0, "Downloading", True)

    _, _, should_emit = state.update_progress("a", 10.4, "Downloading", min_interval=0)
    assert should_emit is False

    percent, message, should_emit = state.update_progress("a", 12, "Downloading", min_interval=0)
    assert (percent, message, should_emit) == (12.0, "Downloading", True)

    _, _, should_emit = state.update_progress("a", 12, "Converting", min_interval=0)
    assert should_emit is True

    _, _, should_emit = state.update_progress("a", 100, "Converting", min_interval=10)
    assert should_emit is True
    assert state.get_progress("a") == {"percent": 100.0, "message": "Converting"}
    assert state.get_progress("missing") == {"percent": 0.0, "message": "Searching"}
