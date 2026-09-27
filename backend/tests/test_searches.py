import json

from app.searches import (
    get_download_total,
    load_initial_concurrent_limit,
    persist_concurrent_limit,
    read_searches_file,
    record_search,
)


def test_missing_counter_file_reads_as_zero(tmp_path, monkeypatch):
    monkeypatch.setattr("app.searches.SEARCHES_FILE", str(tmp_path / "searches.json"))
    assert read_searches_file() == {"total": 0}
    assert get_download_total() == 0


def test_recorded_searches_increase_the_counter(tmp_path, monkeypatch):
    path = tmp_path / "searches.json"
    monkeypatch.setattr("app.searches.SEARCHES_FILE", str(path))
    record_search()
    record_search()
    assert get_download_total() == 2
    assert json.loads(path.read_text(encoding="utf-8"))["total"] == 2


def test_saving_the_limit_keeps_the_counter(tmp_path, monkeypatch):
    path = tmp_path / "searches.json"
    monkeypatch.setattr("app.searches.SEARCHES_FILE", str(path))
    record_search()
    assert persist_concurrent_limit(4) is True
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == {"total": 1, "concurrent_limit": 4}
    assert load_initial_concurrent_limit() == 4
    assert get_download_total() == 1


def test_unreadable_counter_file_is_left_in_place(tmp_path, monkeypatch):
    path = tmp_path / "searches.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("app.searches.SEARCHES_FILE", str(path))
    assert read_searches_file() is None
    assert persist_concurrent_limit(9) is False
    assert path.read_text(encoding="utf-8") == "{not json"


def test_counter_path_that_is_a_directory_is_not_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr("app.searches.SEARCHES_FILE", str(tmp_path))
    assert read_searches_file() is None
    assert persist_concurrent_limit(2) is False
    assert tmp_path.is_dir()
